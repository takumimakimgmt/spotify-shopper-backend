from __future__ import annotations

import os
import tempfile
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
    Request,
)
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from core import (
    fetch_playlist_tracks_generic,
    playlist_result_to_dict,
    enrich_isrc_for_items,
    normalize_playlist_url,
)
from core import _PLAYLIST_CACHE as PLAYLIST_CACHE  # TTLCache
from core import _TTL_SECONDS as PLAYLIST_CACHE_TTL_S
from core import _CACHE_VERSION as CACHE_VERSION
from rekordbox import mark_owned_tracks
import logging
import json
from playwright_pool import close_browser

# Basic logging configuration to ensure logger outputs appear in the terminal
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)


# =========================
# Pydantic models
# =========================

class StoreLinksModel(BaseModel):
    beatport: Optional[str] = None
    bandcamp: Optional[str] = None
    itunes: Optional[str] = None


class TrackModel(BaseModel):
    title: str
    artist: str
    album: Optional[str] = None
    isrc: Optional[str] = None
    spotify_url: Optional[str] = None
    apple_url: Optional[str] = None
    links: Optional[StoreLinksModel] = None
    owned: Optional[bool] = None
    owned_reason: Optional[str] = None
    track_key_primary: Optional[str] = None  # ISRC-based or fallback (server-determined for state sync)
    track_key_fallback: Optional[str] = None  # normalized(title+artist+album) backup
    track_key_primary_type: str = "norm"  # "isrc" | "norm" (UI hint: isrc=confident, norm=ambiguous)
    track_key_version: str = "v1"  # version for future-proof migrations (normalize rules evolution)


class PlaylistMetaModel(BaseModel):
    model_config = {"extra": "allow"}  # Allow unknown fields to pass through
    
    cache_hit: Optional[bool] = None
    cache_ttl_s: Optional[int] = None
    refresh: Optional[int] = None
    fetch_ms: Optional[float] = None
    enrich_ms: Optional[float] = None
    total_backend_ms: Optional[float] = None
    total_api_ms: Optional[float] = None
    # Apple-specific meta flags
    apple_strategy: Optional[str] = None  # 'html' | 'playwright'
    apple_mode: Optional[str] = None  # 'auto' | 'fast' | 'legacy'
    apple_legacy_used: Optional[bool] = None
    apple_enrich_skipped: Optional[bool] = None
    reason: Optional[str] = None
    seen_catalog_playlist_api: Optional[bool] = None
    apple_api_candidates: Optional[list] = None
    apple_response_candidates: Optional[list] = None
    apple_request_candidates: Optional[list] = None
    apple_xhr_fetch_requests: Optional[list] = None
    json_responses_any_domain: Optional[list] = None
    apple_console_errors: Optional[list] = None
    apple_page_errors: Optional[list] = None
    apple_page_title: Optional[str] = None
    apple_html_snippet: Optional[str] = None
    blocked_hint: Optional[bool] = None


class PlaylistResponse(BaseModel):
    playlist_id: str
    playlist_name: str
    playlist_url: Optional[str] = None
    tracks: List[TrackModel]
    meta: Optional[PlaylistMetaModel] = None


class PlaylistWithRekordboxBody(BaseModel):
    url: str
    rekordbox_xml_path: str
    source: Optional[str] = "spotify"


# =========================
# FastAPI app & CORS
# =========================

app = FastAPI(
    title="Spotify Playlist Shopper",
    version="1.0.0",
)

# Add GZip middleware for response compression (reduces payload size for large JSON)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add request body size limit middleware (protect against extremely large payloads)
from starlette.middleware.base import BaseHTTPMiddleware

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > 25 * 1024 * 1024:  # 25MB ceiling
                logger.warning(f"[RequestSizeLimit] Rejected oversized request: {content_length} bytes from {request.client}")
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large (max 25MB)"}
                )
        return await call_next(request)

app.add_middleware(RequestSizeLimitMiddleware)

@app.on_event("startup")
def _log_startup():
    logger.info("spotify-shopper: startup event triggered")


@app.on_event("startup")
async def _init_playwright_state():
    # Lazy init: create slots and semaphore only; browser starts on first Apple request
    app.state.pw = None
    app.state.browser = None
    app.state.apple_sem = asyncio.Semaphore(2)


@app.on_event("shutdown")
async def _shutdown_playwright_state():
    try:
        await close_browser()
    except Exception:
        pass

# 最大アップロードサイズ（バイト） - デフォルト 20MB（フロントと合わせて）
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 20 * 1024 * 1024))

# デフォルトの許可オリジン
default_origins = [
    "http://localhost:3000",
    "https://spotify-shopper.vercel.app",
    "https://playlist-shopper.vercel.app",
]

# 環境変数 ALLOWED_ORIGINS があればそれを優先（カンマ区切り）
env_origins = os.getenv("ALLOWED_ORIGINS")
if env_origins:
    origins = [o.strip() for o in env_origins.split(",") if o.strip()]
else:
    origins = default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Health check
# =========================

@app.get("/health", tags=["system"])
def health() -> Dict[str, Any]:
    import os
    return {
        "ok": True,
        "status": "ok",
        "build_commit": os.getenv("RENDER_GIT_COMMIT", "local")[:7],
        "has_meta": True,  # This build includes meta field support
    }


@app.get("/", tags=["system"])
def root() -> Dict[str, Any]:
    # Render health-style response to silence platform health checks on /
    return {"ok": True, "status": "ok"}


# =========================
# Core helpers
# =========================

def _sanitize_url(raw: str) -> str:
    """
    Basic server-side URL sanitization: trim whitespace, strip surrounding
    angle brackets and surrounding single/double quotes.
    """
    if not raw:
        return raw
    s = raw.strip()
    if s.startswith('<') and s.endswith('>'):
        s = s[1:-1].strip()
    # strip surrounding quotes
    s = s.strip('\'"')
    return s


def _apply_rekordbox_owned_flags(
    playlist_data: Dict[str, Any],
    library_xml_path: str,
) -> Dict[str, Any]:
    """Rekordbox ライブラリ XML を読み込み、owned フラグを付与。"""
    try:
        # mark_owned_tracks expects a path and will load the XML itself.
        return mark_owned_tracks(playlist_data, library_xml_path)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to apply Rekordbox owned flags: {e}",
        )


# =========================
# Endpoints
# =========================

@app.get("/api/playlist", response_model=PlaylistResponse)
async def get_playlist(
    request: Request,
    url: str = Query(..., description="Playlist URL or ID or URL"),
    source: str = Query("spotify", description="spotify or apple"),
    apple_mode: str = Query("auto", description="auto|fast|legacy (Apple only)"),
    enrich_isrc: bool = Query(False, description="Fill missing ISRCs via MusicBrainz"),
    isrc_limit: Optional[int] = Query(None, description="Max items to try enriching ISRC"),
    enrich_spotify: Optional[int] = Query(None, description="For Apple: 1 to enrich via Spotify, 0 to skip (default 0 for apple)"),
    refresh: Optional[int] = Query(None, description="Bypass cache when set to 1"),
):
    """
    プレイリストだけを取得（Rekordbox 突き合わせなし）。
    """
    import time
    t0_total = time.time()
    
    # Sanitize URL defensively and server-side fallback: if the URL clearly points to Apple Music, prefer apple
    clean_url = _sanitize_url(url)
    normalized_url = normalize_playlist_url(clean_url)
    src = (source or "spotify").lower()
    if "music.apple.com" in (clean_url or "").lower():
        src = "apple"
    # Normalize apple_mode
    mode = (apple_mode or "auto").lower()
    if src != "apple":
        mode = "auto"  # Only meaningful for Apple

    logger.info(f"[api/playlist] raw_url={url} clean_url={clean_url} normalized_url={normalized_url} source_param={source} apple_mode={mode} -> using source={src}")

    # Call core directly so we can attach debug info on failure
    try:
        # Cache lookup (allow bypass via refresh=1)
        # Determine effective enrich flag for Apple defaulting to 0 unless explicitly set
        effective_enrich_spotify = None
        if src == "apple":
            # Default 0 for Apple if not specified; coerce to 0/1
            if enrich_spotify is None:
                effective_enrich_spotify = 0
            else:
                effective_enrich_spotify = 1 if int(enrich_spotify) == 1 else 0
        # Include enrich flag and mode in cache key for Apple to avoid mixing
        cache_key = f"{CACHE_VERSION}:{src}:{normalized_url}"
        if src == "apple":
            cache_key = f"{cache_key}:enrich={effective_enrich_spotify}:mode={mode}"
        bypass = (refresh == 1)
        cached = None if bypass else PLAYLIST_CACHE.get(cache_key)
        cache_hit = (cached is not None)
        if cached is not None:
            result = cached
        else:
            result = await fetch_playlist_tracks_generic(
                src,
                clean_url,
                app=request.app,
                apple_mode=mode if src == "apple" else None,
                enrich_spotify=(bool(effective_enrich_spotify) if effective_enrich_spotify is not None else None),
            )
        
        # Optional ISRC enrichment (best-effort)
        if enrich_isrc and isinstance(result, dict):
            try:
                items = result.get("items", [])
                updated = enrich_isrc_for_items(items, limit=isrc_limit)
                result["items"] = items
                result.setdefault("meta", {})
                result["meta"]["isrc_enriched"] = updated
            except Exception as _:
                # ignore enrichment errors
                pass
        
        data = playlist_result_to_dict(result)
        perf = result.get("perf", {}) if isinstance(result, dict) else {}
        
        # Log performance metrics
        t1_total = time.time()
        total_ms = (t1_total - t0_total) * 1000
        tracks_count = len(data.get('tracks', []))
        # Cache store (only successful non-empty)
        try:
            if not bypass and not cache_hit and not result.get("error") and len(data.get("tracks", [])) > 0:
                PLAYLIST_CACHE[cache_key] = result
        except Exception:
            pass

        logger.info(
            f"[PERF] source={src} url_len={len(clean_url)} normalized_url_len={len(normalized_url)} "
            f"cache_hit={'true' if cache_hit else 'false'} cache_ttl_s={PLAYLIST_CACHE_TTL_S} cache_size={len(PLAYLIST_CACHE)} refresh={'1' if bypass else '0'} "
            f"fetch_ms={perf.get('fetch_ms', 0):.1f} enrich_ms={perf.get('enrich_ms', 0):.1f} "
            f"total_backend_ms={perf.get('total_ms', 0):.1f} total_api_ms={total_ms:.1f} tracks={tracks_count}"
        )

        # Merge core-provided meta (e.g., apple_strategy, apple_enrich_skipped)
        core_meta = result.get("meta") or {}
        meta = {
            "cache_hit": cache_hit,
            "cache_ttl_s": PLAYLIST_CACHE_TTL_S,
            "refresh": 1 if bypass else 0,
            "fetch_ms": float(perf.get("fetch_ms", 0) or 0),
            "enrich_ms": float(perf.get("enrich_ms", 0) or 0),
            "total_backend_ms": float(perf.get("total_ms", 0) or 0),
            "total_api_ms": float(total_ms),
        }
        try:
            if isinstance(core_meta, dict):
                meta.update(core_meta)
        except Exception:
            pass

        data = {**data, "meta": meta}

        return data
    except Exception as e:
        # Include Apple-specific meta in error detail for faster diagnosis
        error_meta = getattr(e, "meta", {}) if hasattr(e, "meta") else {}
        if src == "apple" and not error_meta:
            try:
                error_meta = {
                    "apple_strategy": "playwright",
                    "apple_enrich_skipped": True if (effective_enrich_spotify is None or int(effective_enrich_spotify) == 0) else False,
                }
            except Exception:
                pass
        logger.error(f"[api/playlist] error for raw_url={url} clean_url={clean_url} source={src}: {e} meta={error_meta}")
        # Return structured detail including meta to aid client-side separation
        raise HTTPException(status_code=400, detail={
            "error": str(e),
            "used_source": src,
            "url": clean_url,
            "meta": error_meta,
        })


@app.post("/api/playlist-with-rekordbox", response_model=PlaylistResponse)
async def playlist_with_rekordbox(body: PlaylistWithRekordboxBody, request: Request):
    """
    JSON で Rekordbox XML のパスを受け取る版（ローカル用）。
    {
      "url": "...",
      "rekordbox_xml_path": "/Users/xxx/Desktop/rekordbox_collection.xml"
    }
    """
    try:
        result = await fetch_playlist_tracks_generic(getattr(body, "source", "spotify"), body.url, app=request.app)
        playlist_data = playlist_result_to_dict(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    
    playlist_with_owned = _apply_rekordbox_owned_flags(
        playlist_data,
        body.rekordbox_xml_path,
    )
    return playlist_with_owned


@app.post("/api/match-snapshot-with-xml")
async def match_snapshot_with_xml(
    snapshot: str = Form(..., description="PlaylistSnapshotV1 JSON string"),
    file: UploadFile | None = File(..., description="Rekordbox collection XML"),
):
    """
    与えられた PlaylistSnapshotV1（JSON）に対して、Rekordbox XML を用いて owned/owned_reason を付与して返す。
    URL の再入力は不要。

    制限：
    - snapshot: 最大 1MB
    - XML: MAX_UPLOAD_SIZE（環境変数、デフォルト 5MB）
    """
    # サイズチェック（snapshot 文字列長）
    if snapshot is None:
        raise HTTPException(status_code=400, detail="snapshot は必須です")
    if len(snapshot.encode("utf-8")) > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="snapshot のサイズが上限(1MB)を超えています")

    # JSON パース
    try:
        snap = json.loads(snapshot)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"snapshot JSON のパースに失敗: {e}")

    # 簡易スキーマ検証
    if not isinstance(snap, dict):
        raise HTTPException(status_code=400, detail="snapshot は JSON オブジェクトである必要があります")
    if snap.get("schema") != "playlist_snapshot":
        raise HTTPException(status_code=400, detail="snapshot.schema は 'playlist_snapshot' である必要があります")
    if snap.get("version") != 1:
        raise HTTPException(status_code=400, detail="snapshot.version は 1 である必要があります")
    if "tracks" not in snap or not isinstance(snap["tracks"], list):
        raise HTTPException(status_code=400, detail="snapshot.tracks は配列である必要があります")

    # XML ファイル必須＆検証
    if file is None:
        raise HTTPException(status_code=400, detail="XML ファイルを 'file' フィールドで送信してください")
    if file.content_type not in ("text/xml", "application/xml", "text/plain"):
        raise HTTPException(status_code=400, detail="XML ファイルをアップロードしてください")

    try:
        xml_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"XML 読み込みに失敗しました: {e}")

    if not xml_bytes:
        raise HTTPException(status_code=400, detail="空の XML ファイルです")
    if len(xml_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"XML が大きすぎます（上限 {MAX_UPLOAD_SIZE} バイト）")

    # 既存の mark_owned_tracks は playlist 型（/api/playlist の返却）を期待するため、
    # snapshot から近い構造に組み替えて owned 判定を実行し、結果を snapshot に反映する。
    # playlist_result_to_dict の形に合わせる：
    playlist_like: Dict[str, Any] = {
        "playlist_id": snap.get("playlist", {}).get("id") or "snapshot",
        "playlist_name": snap.get("playlist", {}).get("name") or "Snapshot",
        "playlist_url": snap.get("playlist", {}).get("url"),
        "tracks": [
            {
                "title": t.get("title"),
                "artist": t.get("artist"),
                "album": t.get("album"),
                "isrc": t.get("isrc"),
                # URL フィールド名差異を吸収（あれば）
                "spotify_url": t.get("links", {}).get("spotify"),
                "apple_url": t.get("links", {}).get("apple"),
                # 既存キーもそのまま運ぶ
                "track_key_primary": t.get("track_key_primary"),
                "track_key_fallback": t.get("track_key_fallback"),
                "track_key_primary_type": t.get("track_key_primary_type", "norm"),
                "track_key_version": t.get("track_key_version", "v1"),
            }
            for t in snap.get("tracks", [])
        ],
    }

    # XML を一時ファイルへ書き出して照合
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
            tmp.write(xml_bytes)
            tmp_path = tmp.name

        matched = _apply_rekordbox_owned_flags(playlist_like, tmp_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # matched.tracks には owned/owned_reason が入っている想定。
    matched_tracks: List[Dict[str, Any]] = matched.get("tracks", [])
    # track_key_primary を使って対応付けし、snap.tracks を更新
    index_by_key: Dict[str, Dict[str, Any]] = {}
    for mt in matched_tracks:
        key = mt.get("track_key_primary") or mt.get("track_key_fallback")
        if key:
            index_by_key[key] = mt

    updated_tracks: List[Dict[str, Any]] = []
    for t in snap.get("tracks", []):
        key = t.get("track_key_primary") or t.get("track_key_fallback")
        mt = index_by_key.get(key)
        if mt:
            t["owned"] = mt.get("owned")
            t["owned_reason"] = mt.get("owned_reason")
        updated_tracks.append(t)

    snap["tracks"] = updated_tracks
    # 返却：PlaylistSnapshotV1（入力を更新したもの）
    return snap

@app.post("/api/playlist-with-rekordbox-upload", response_model=PlaylistResponse)
async def playlist_with_rekordbox_upload(
    request: Request,
    url: str = Form(..., description="Playlist URL or ID or URL"),
    source: str = Form("spotify", description="spotify or apple"),
    apple_mode: str = Form("auto", description="auto|fast|legacy (Apple only)"),
    file: UploadFile | None = File(None, description="Rekordbox collection XML"),
    enrich_spotify: Optional[int] = Form(None, description="For Apple: 1 to enrich via Spotify, 0 to skip (default 0 for apple)"),
    refresh: Optional[int] = Form(None, description="Bypass cache when set to 1"),
):
    """
    フロントからの XML ファイルアップロード版。
    - フロントは multipart/form-data で url と file を送る。
    - アップロードされた XML を一時ファイルに保存し、Rekordbox 突き合わせ。
    """
    import time
    t0_total = time.time()
    
    # file は任意。ある場合は後で content-type とサイズ検証を行う。

    # Sanitize URL defensively and server-side fallback: if the URL clearly points to Apple Music, prefer apple
    clean_url = _sanitize_url(url)
    normalized_url = normalize_playlist_url(clean_url)
    src = (source or "spotify").lower()
    if "music.apple.com" in (clean_url or "").lower():
        src = "apple"
    # Normalize apple_mode
    mode = (apple_mode or "auto").lower()
    if src != "apple":
        mode = "auto"  # Only meaningful for Apple

    logger.info(f"[api/playlist-with-rekordbox-upload] raw_url={url} clean_url={clean_url} normalized_url={normalized_url} source_param={source} apple_mode={mode} -> using source={src}")

    try:
        t0_fetch = time.time()
        # Determine effective enrich flag for Apple defaulting to 0 unless explicitly set
        effective_enrich_spotify = None
        if src == "apple":
            if enrich_spotify is None:
                effective_enrich_spotify = 0
            else:
                effective_enrich_spotify = 1 if int(enrich_spotify) == 1 else 0
        cache_key = f"{CACHE_VERSION}:{src}:{normalized_url}"
        if src == "apple":
            cache_key = f"{cache_key}:enrich={effective_enrich_spotify}:mode={mode}"
        bypass = (refresh == 1)
        cached = None if bypass else PLAYLIST_CACHE.get(cache_key)
        cache_hit = cached is not None
        if cached is not None:
            result = cached
        else:
            result = await fetch_playlist_tracks_generic(
                src,
                clean_url,
                app=request.app,
                apple_mode=mode if src == "apple" else None,
                enrich_spotify=(bool(effective_enrich_spotify) if effective_enrich_spotify is not None else None),
            )
        t1_fetch = time.time()
        fetch_ms = (t1_fetch - t0_fetch) * 1000
        
        playlist_data = playlist_result_to_dict(result)

        # Store base playlist in cache (no XML-specific flags)
        try:
            if not bypass and not cache_hit and not result.get("error") and len(playlist_data.get("tracks", [])) > 0:
                PLAYLIST_CACHE[cache_key] = result
        except Exception:
            pass
    except Exception as e:
        error_meta = getattr(e, "meta", {}) if hasattr(e, "meta") else {}
        if src == "apple" and not error_meta:
            try:
                error_meta = {
                    "apple_strategy": "playwright",
                    "apple_enrich_skipped": True if (effective_enrich_spotify is None or int(effective_enrich_spotify) == 0) else False,
                }
            except Exception:
                pass
        logger.error(f"[api/playlist-with-rekordbox-upload] error for raw_url={url} clean_url={clean_url} source={src}: {e} meta={error_meta}")
        raise HTTPException(status_code=400, detail={
            "error": str(e),
            "used_source": src,
            "url": clean_url,
            "meta": error_meta,
        })

    # 一時ファイルに XML を書き出し
    playlist_with_owned = playlist_data
    xml_ms = 0
    total_ms = 0

    # file がある場合だけ Rekordbox 照合を行う
    if file is not None:
        if file.content_type not in ("text/xml", "application/xml", "text/plain"):
            raise HTTPException(status_code=400, detail="XML ファイルをアップロードしてください。")

        try:
            contents = await file.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"ファイル読み込みに失敗しました: {e}")

        if not contents:
            raise HTTPException(status_code=400, detail="空のファイルです。")

        if len(contents) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"ファイルが大きすぎます（上限 {MAX_UPLOAD_SIZE} バイト）。")

        tmp_path = None
        try:
            t0_xml = time.time()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
                tmp.write(contents)
                tmp_path = tmp.name

            playlist_with_owned = _apply_rekordbox_owned_flags(
                playlist_data,
                tmp_path,
            )
            t1_xml = time.time()
            xml_ms = (t1_xml - t0_xml) * 1000
        finally:
            # 後始末
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    t1_total = time.time()
    total_ms = (t1_total - t0_total) * 1000
    tracks_count = len(playlist_with_owned.get('tracks', []))
    logger.info(
        f"[PERF] source={src} url_len={len(clean_url)} normalized_url_len={len(normalized_url)} "
        f"cache_hit={'true' if 'cache_hit' in locals() and cache_hit else 'false'} cache_ttl_s={PLAYLIST_CACHE_TTL_S} cache_size={len(PLAYLIST_CACHE)} refresh={'1' if (refresh == 1) else '0'} "
        f"fetch_ms={fetch_ms:.1f} xml_ms={xml_ms:.1f} total_ms={total_ms:.1f} tracks={tracks_count}"
    )
    
    return playlist_with_owned


# =========================
# Local dev entrypoint
# =========================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
