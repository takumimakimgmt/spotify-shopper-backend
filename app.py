from __future__ import annotations

import os
import tempfile
from urllib.parse import urlparse
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

from core import fetch_playlist_tracks, playlist_result_to_dict
from rekordbox import mark_owned_tracks


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
    links: Optional[StoreLinksModel] = None
    owned: Optional[bool] = None


class PlaylistResponse(BaseModel):
    playlist_id: str
    playlist_name: str
    playlist_url: Optional[str] = None
    tracks: List[TrackModel]


class PlaylistWithRekordboxBody(BaseModel):
    url: str
    rekordbox_xml_path: str


# =========================
# FastAPI app & CORS
# =========================

app = FastAPI(
    title="Spotify Playlist Shopper",
    version="1.0.0",
)

# デフォルトの許可オリジン
default_origins = [
    "http://localhost:3000",
    "https://spotify-shopper.vercel.app",
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

def _normalize_playlist_id(raw: str) -> str:
    """
    Spotify プレイリスト URL / ID を、純粋な playlist ID に正規化する。

    OK:
      - 0ZzPDztlFcDLdLbBa7hOks
      - https://open.spotify.com/playlist/0ZzPDztlFcDLdLbBa7hOks?si=xxxx
      - https://open.spotify.com/playlist/0ZzPDztlFcDLdLbBa7hOks
    """
    raw = raw.strip()

    # 素の ID だけ来た場合でも、"id?si=..." 形式でも対応
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        parts = parsed.path.strip("/").split("/")
        # /playlist/<id> という形を想定
        if len(parts) >= 2 and parts[0] == "playlist":
            playlist_id = parts[1]
        else:
            # それ以外のパターンは想定外として 400
            raise HTTPException(status_code=400, detail="Unsupported Spotify playlist URL")
    else:
        # URL じゃなければ ID とみなす。?si= 付いてても切り捨て。
        playlist_id = raw.split("?", 1)[0]

    return playlist_id


def _fetch_playlist_data(url: str) -> Dict[str, Any]:
    """Spotify からプレイリストを取得して dict 形式に変換。"""
    playlist_id = _normalize_playlist_id(url)

    try:
        result = fetch_playlist_tracks(playlist_id)
    except Exception as e:
        # Spotify API 認証エラーなど
        raise HTTPException(status_code=400, detail=str(e))

    data = playlist_result_to_dict(result)
    return data



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
    url: str = Query(..., description="Spotify playlist URL or ID"),
):
    """
    プレイリストだけを取得（Rekordbox 突き合わせなし）。
    """
    data = _fetch_playlist_data(url)
    return data


@app.post("/api/playlist-with-rekordbox", response_model=PlaylistResponse)
def playlist_with_rekordbox(body: PlaylistWithRekordboxBody):
    """
    JSON で Rekordbox XML のパスを受け取る版（ローカル用）。
    {
      "url": "...",
      "rekordbox_xml_path": "/Users/xxx/Desktop/rekordbox_collection.xml"
    }
    """
    playlist_data = _fetch_playlist_data(body.url)
    playlist_with_owned = _apply_rekordbox_owned_flags(
        playlist_data,
        body.rekordbox_xml_path,
    )
    return playlist_with_owned


@app.post("/api/playlist-with-rekordbox-upload", response_model=PlaylistResponse)
async def playlist_with_rekordbox_upload(
    url: str = Form(..., description="Spotify playlist URL or ID"),
    file: UploadFile = File(..., description="Rekordbox collection XML"),
):
    """
    フロントからの XML ファイルアップロード版。
    - フロントは multipart/form-data で url と file を送る。
    - アップロードされた XML を一時ファイルに保存し、Rekordbox 突き合わせ。
    """
    if file.content_type not in ("text/xml", "application/xml", "text/plain"):
        # Rekordbox の XML はだいたいこの辺
        raise HTTPException(status_code=400, detail="XML ファイルをアップロードしてください。")

    # プレイリスト取得
    playlist_data = _fetch_playlist_data(url)

    # 一時ファイルに XML を書き出し
    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ファイル読み込みに失敗しました: {e}")

    if not contents:
        raise HTTPException(status_code=400, detail="空のファイルです。")

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
                # ログ出すならここで print / logging
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
