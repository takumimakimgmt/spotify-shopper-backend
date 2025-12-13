from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import fetch_playlist_tracks_generic, playlist_result_to_dict, enrich_isrc_for_items
from rekordbox import mark_owned_tracks
import logging

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
    track_key_version: str = "v1"  # version for future-proof migrations (normalize rules evolution)


class PlaylistResponse(BaseModel):
    playlist_id: str
    playlist_name: str
    playlist_url: Optional[str] = None
    tracks: List[TrackModel]


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


@app.on_event("startup")
def _log_startup():
    logger.info("spotify-shopper: startup event triggered")

# 最大アップロードサイズ（バイト） - デフォルト 5MB
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 5 * 1024 * 1024))

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
def health() -> Dict[str, str]:
    return {"status": "ok"}


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
def get_playlist(
    url: str = Query(..., description="Playlist URL or ID or URL"),
    source: str = Query("spotify", description="spotify or apple"),
    enrich_isrc: bool = Query(False, description="Fill missing ISRCs via MusicBrainz"),
    isrc_limit: Optional[int] = Query(None, description="Max items to try enriching ISRC"),
):
    """
    プレイリストだけを取得（Rekordbox 突き合わせなし）。
    """
    # Sanitize URL defensively and server-side fallback: if the URL clearly points to Apple Music, prefer apple
    clean_url = _sanitize_url(url)
    src = (source or "spotify").lower()
    if "music.apple.com" in (clean_url or "").lower():
        src = "apple"

    logger.info(f"[api/playlist] raw_url={url} clean_url={clean_url} source_param={source} -> using source={src}")

    # Call core directly so we can attach debug info on failure
    try:
        result = fetch_playlist_tracks_generic(src, clean_url)
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
        return data
    except Exception as e:
        logger.error(f"[api/playlist] error for raw_url={url} clean_url={clean_url} source={src}: {e}")
        # Return structured detail so client can see which source was attempted
        raise HTTPException(status_code=400, detail={"error": str(e), "used_source": src, "url": clean_url})


@app.post("/api/playlist-with-rekordbox", response_model=PlaylistResponse)
def playlist_with_rekordbox(body: PlaylistWithRekordboxBody):
    """
    JSON で Rekordbox XML のパスを受け取る版（ローカル用）。
    {
      "url": "...",
      "rekordbox_xml_path": "/Users/xxx/Desktop/rekordbox_collection.xml"
    }
    """
    try:
        result = fetch_playlist_tracks_generic(getattr(body, "source", "spotify"), body.url)
        playlist_data = playlist_result_to_dict(result)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    
    playlist_with_owned = _apply_rekordbox_owned_flags(
        playlist_data,
        body.rekordbox_xml_path,
    )
    return playlist_with_owned


@app.post("/api/playlist-with-rekordbox-upload", response_model=PlaylistResponse)
async def playlist_with_rekordbox_upload(
    url: str = Form(..., description="Playlist URL or ID or URL"),
    source: str = Form("spotify", description="spotify or apple"),
    file: UploadFile | None = File(None, description="Rekordbox collection XML"),
):
    """
    フロントからの XML ファイルアップロード版。
    - フロントは multipart/form-data で url と file を送る。
    - アップロードされた XML を一時ファイルに保存し、Rekordbox 突き合わせ。
    """
    # file は任意。ある場合は後で content-type とサイズ検証を行う。

    # Sanitize URL defensively and server-side fallback: if the URL clearly points to Apple Music, prefer apple
    clean_url = _sanitize_url(url)
    src = (source or "spotify").lower()
    if "music.apple.com" in (clean_url or "").lower():
        src = "apple"

    logger.info(f"[api/playlist-with-rekordbox-upload] raw_url={url} clean_url={clean_url} source_param={source} -> using source={src}")

    try:
        result = fetch_playlist_tracks_generic(src, clean_url)
        playlist_data = playlist_result_to_dict(result)
    except Exception as e:
        logger.error(f"[api/playlist-with-rekordbox-upload] error for raw_url={url} clean_url={clean_url} source={src}: {e}")
        raise HTTPException(status_code=400, detail={"error": str(e), "used_source": src, "url": clean_url})

    # 一時ファイルに XML を書き出し
    playlist_with_owned = playlist_data

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
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
                tmp.write(contents)
                tmp_path = tmp.name

            playlist_with_owned = _apply_rekordbox_owned_flags(
                playlist_data,
                tmp_path,
            )
        finally:
            # 後始末
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

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
