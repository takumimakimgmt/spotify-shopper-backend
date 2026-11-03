"""Public transport models, kept separate from HTTP handlers and matching logic."""

from typing import List, Literal, Optional

from pydantic import BaseModel


class StoreLinksModel(BaseModel):
    beatport: Optional[str] = None
    bandcamp: Optional[str] = None
    itunes: Optional[str] = None


class LibraryMatchModel(BaseModel):
    status: Literal["matched", "not_found", "review"]
    reason: str
    matched_title: Optional[str] = None
    matched_artist: Optional[str] = None


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
    library_match: Optional[LibraryMatchModel] = None
    track_key_primary: Optional[str] = (
        None  # ISRC-based or fallback (server-determined for state sync)
    )
    track_key_fallback: Optional[str] = None  # normalized(title+artist+album) backup
    track_key_primary_type: Literal["isrc", "norm"] = (
        "norm"  # "isrc" | "norm" (UI hint: isrc=confident, norm=ambiguous)
    )
    track_key_version: str = (
        "v1"  # version for future-proof migrations (normalize rules evolution)
    )


class PlaylistMetaModel(BaseModel):
    model_config = {"extra": "allow"}  # Allow unknown fields to pass through

    cache_hit: Optional[bool] = None
    cache_ttl_s: Optional[int] = None
    refresh: bool = False
    fetch_ms: Optional[float] = None
    enrich_ms: Optional[float] = None
    total_backend_ms: Optional[float] = None
    total_api_ms: Optional[float] = None
    # Apple-specific meta flags
    apple_strategy: Optional[str] = None  # 'html'
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
