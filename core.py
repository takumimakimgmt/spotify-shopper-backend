#!/usr/bin/env python3
"""
Spotify プレイリストを取得して、
- プレイリスト基本情報
- 各トラック情報（タイトル / アーティスト / アルバム / ISRC / Spotify URL）
- Beatport / Bandcamp / iTunes 検索リンク

を Python 辞書で返すコアモジュール。
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional
import logging
import asyncio

import requests
import httpx
import html as _html
from bs4 import BeautifulSoup
import json
import time
from cachetools import TTLCache
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

# Global TTL cache for playlist fetch results
_ENV = os.getenv("ENV", "prod").lower()
_TTL_SECONDS = 3600 if _ENV == "dev" else 21600  # dev:1h, prod:6h
_PLAYLIST_CACHE: TTLCache[str, dict] = TTLCache(maxsize=256, ttl=_TTL_SECONDS)
APPLE_HTTP_TIMEOUT_S = float(os.getenv("APPLE_HTTP_TIMEOUT_S", "20"))
APPLE_HTTP_RETRIES = int(os.getenv("APPLE_HTTP_RETRIES", "2"))
APPLE_DEBUG_HTML = os.getenv("APPLE_DEBUG_HTML", "0") == "1"
APPLE_PW_COMMIT_TIMEOUT_MS = int(os.getenv("APPLE_PW_COMMIT_TIMEOUT_MS", "20000"))
APPLE_PW_DOM_TIMEOUT_MS = int(os.getenv("APPLE_PW_DOM_TIMEOUT_MS", "7000"))

def normalize_playlist_url(url: str) -> str:
    """Normalize playlist URL for canonical cache key.
    - Strip tracking query params: si, utm_*, fbclid, gclid
    - Ensure trailing slash consistency
    - For Spotify playlist URLs, canonicalize to open.spotify.com/playlist/<id>
    """
    try:
        s = (url or "").strip()
        if not s:
            return ""
        parsed = urlparse(s)
        q = {k: v for k, v in parse_qsl(parsed.query) if not (k == "si" or k == "fbclid" or k == "gclid" or k.startswith("utm_"))}
        new_query = urlencode(q)
        path = parsed.path or ""
        # Spotify canonicalization
        if "open.spotify.com" in (parsed.netloc or "") and "/playlist/" in path:
            parts = path.split("/")
            # ['', 'playlist', '<id>', ...]
            try:
                idx = parts.index("playlist")
                sp_id = parts[idx + 1]
                path = f"/playlist/{sp_id}"
            except Exception:
                pass
        # Ensure no trailing stuff beyond canonical path and unify trailing slash removal
        if path.endswith("/"):
            path = path[:-1]
        normalized = urlunparse((parsed.scheme or "https", parsed.netloc or "", path, "", new_query, ""))
        return normalized
    except Exception:
        return url

import unicodedata

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException

# Configure logger for this module
logger = logging.getLogger(__name__)


class AppleFetchError(Exception):
    """Custom error to carry Apple-specific meta for diagnostics."""

    def __init__(self, message: str, meta: dict | None = None):
        super().__init__(message)
        self.meta = meta or {}


def _fix_mojibake(s: str) -> str:
    """Robust mojo/encoding fixer.

    Try a set of plausible reparations for strings that look like mojibake
    (UTF-8 bytes interpreted as latin-1 / windows-1252, percent-encoding left
    in place, HTML entities). Score candidates and pick the best.

    Strategies attempted (in order):
    - original (no-op)
    - HTML-unescape
    - percent-unquote
    - latin-1 -> utf-8 decode
    - windows-1252 -> utf-8 decode emulation (via latin1)
    - latin1->utf8 after unquoting/unescaping (composed)

    Scoring: prefer strings with more CJK characters and fewer replacement chars
    (U+FFFD) or leftover typical mojibake markers (like 'Ã', 'Â', 'â').
    """
    if not s or not isinstance(s, str):
        return s

    # quick sanity: if ASCII-only and no typical mojibake markers, skip work
    if re.fullmatch(r"[\x00-\x7f]*", s) and not re.search(r'[ÃÂãâ]', s):
        return s

    def count_cjk(text: str) -> int:
        # basic coverage of common CJK blocks
        return len(re.findall(r'[\u4E00-\u9FFF\u3040-\u30FF\u31F0-\u31FF\u3000-\u303F]', text))

    def count_replacement(text: str) -> int:
        return text.count('\ufffd') + text.count('�')

    def mojibake_marker_score(text: str) -> int:
        # penalize presence of common mojibake glyphs
        return sum(text.count(x) for x in ['Ã', 'Â', 'â', 'ã'])

    def score_candidate(text: str) -> int:
        # higher is better
        cjk = count_cjk(text)
        repl = count_replacement(text)
        marker = mojibake_marker_score(text)
        # weight: CJK heavy positive, replacements and markers negative
        return cjk * 100 - repl * 50 - marker * 10

    candidates = []

    # original
    orig = s
    candidates.append(orig)

    # html unescape
    try:
        candidates.append(_html.unescape(s))
    except Exception:
        pass

    # percent unquote
    try:
        candidates.append(urllib.parse.unquote(s))
    except Exception:
        pass

    # latin1 -> utf-8
    try:
        candidates.append(s.encode('latin1').decode('utf-8'))
    except Exception:
        pass

    # try an additional windows-1252-like route: treat bytes as latin1 then decode utf-8
    try:
        # same as above but keep in candidates for scoring
        candidates.append(s.encode('latin1', errors='replace').decode('utf-8', errors='replace'))
    except Exception:
        pass

    # composed tries: unescape/unquote then latin1->utf8
    tries = set()
    for base in list(candidates):
        try:
            u = urllib.parse.unquote(base)
        except Exception:
            u = base
        try:
            h = _html.unescape(u)
        except Exception:
            h = u
        for cand in (u, h):
            if cand not in tries:
                tries.add(cand)
                candidates.append(cand)
            try:
                repaired = cand.encode('latin1', errors='replace').decode('utf-8', errors='replace')
                if repaired not in tries:
                    tries.add(repaired)
                    candidates.append(repaired)
            except Exception:
                pass

    # Deduplicate preserving order
    seen = set()
    unique = []
    for c in candidates:
        if not isinstance(c, str):
            continue
        if c in seen:
            continue
        seen.add(c)
        unique.append(c)

    # Score them and pick the best
    best = orig
    best_score = score_candidate(orig)
    for c in unique:
        sc = score_candidate(c)
        if sc > best_score:
            best = c
            best_score = sc

    # final normalization
    try:
        best = unicodedata.normalize('NFC', best)
    except Exception:
        pass

    return best


# =========================
# Spotify クライアント
# =========================


def get_spotify_client() -> spotipy.Spotify:
    """
    環境変数から Spotify API のクレデンシャルを読み込み、
    Spotipy クライアントを返す。

    必要な環境変数:
    - SPOTIFY_CLIENT_ID
    - SPOTIFY_CLIENT_SECRET
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "Spotify client credentials are not set. "
            "Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET."
        )

    auth_manager = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


# =========================
# プレイリストID抽出
# =========================


from playwright_pool import new_context


async def _fetch_with_playwright_async(url: str, app: Any) -> str:
    """Fetch page HTML using a shared Playwright browser via playwright_pool."""
    logger.info(f"[APPLE] start url={url}")
    context = await new_context()
    logger.info("[APPLE] got_context")
    page = await context.new_page()
    # Apple is heavier; allow longer timeouts (90s)
    page_timeout_ms = 90000
    page.set_default_navigation_timeout(page_timeout_ms)
    page.set_default_timeout(page_timeout_ms)

    # Block heavy assets to speed up render; allow only document/script/xhr/fetch
    allowed_resources = {"document", "script", "xhr", "fetch"}

    async def _handle_route(route):
        rtype = route.request.resource_type
        if rtype in allowed_resources:
            await route.continue_()
        else:
            await route.abort()

    await page.route("**/*", _handle_route)

    last_error = None
    max_attempts = 3
    try:
        for attempt in range(max_attempts):
            try:
                logger.info(f"[APPLE] goto_start attempt={attempt + 1}")
                await page.goto(url, wait_until="networkidle", timeout=page_timeout_ms)
                logger.info("[APPLE] goto_done")

                await page.wait_for_selector("main", timeout=page_timeout_ms)
                logger.info("[APPLE] main loaded")

                await page.wait_for_selector(
                    'div[role="row"], ol li, .songs-list-row',
                    timeout=page_timeout_ms,
                )
                logger.info("[APPLE] list selector ok")
                html = await page.content()
                logger.info("[APPLE] parse_done")
                return html
            except Exception as e:
                last_error = e
                logger.warning(f"[APPLE] attempt {attempt + 1}/{max_attempts} failed: {e}")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=page_timeout_ms)
                except Exception:
                    pass
                backoff = 1.5 * (attempt + 1)
                await asyncio.sleep(backoff)
        raise RuntimeError(f"Failed to fetch page after retries ({max_attempts}): {last_error}")
    finally:
        try:
            await context.close()
        except Exception:
            pass
def build_store_links(title: str, artist: str, album: str | None = None, isrc: str | None = None) -> Dict[str, str]:
    """
    Beatport / Bandcamp / iTunes (Apple Music) の検索リンクを生成。
    
    優先順位:
    - Beatport: title + artist を最優先（Beatport は ISRC よりテキスト検索が強いため）
      - title が無い場合は artist のみ、どちらも無ければ ISRC を最後の手段として使用
    - iTunes: ISRC があれば ISRC で検索、無ければ title + artist
    - Bandcamp: title + artist（ISRC 非対応のため従来通り）
    """
    title_clean = title.strip()
    artist_clean = artist.strip()
    isrc_clean = isrc.strip().upper() if isrc else None

    # Beatport: prefer human-readable query (title + artist), then title-only, then ISRC.
    beatport_query = f"{title_clean} {artist_clean}".strip() or title_clean or artist_clean or (isrc_clean or "")
    beatport = f"https://www.beatport.com/search?q={urllib.parse.quote_plus(beatport_query)}"

    # Bandcamp: still title + artist (ISRC not supported)
    bandcamp_query = f"{title_clean} {artist_clean}".strip()
    bandcamp = f"https://bandcamp.com/search?q={urllib.parse.quote_plus(bandcamp_query)}"

    # iTunes: ISRC when available, otherwise title + artist
    if isrc_clean:
        itunes_q = urllib.parse.quote_plus(isrc_clean)
    else:
        itunes_q = urllib.parse.quote_plus(f"{title_clean} {artist_clean}".strip())
    itunes = f"https://music.apple.com/search?term={itunes_q}"

    return {
        "beatport": beatport,
        "bandcamp": bandcamp,
        "itunes": itunes,
    }


# =========================
# プレイリスト取得
# =========================


def extract_playlist_id(url_or_id: str) -> str:
    """Extract a Spotify playlist ID from a full URL or a raw ID.

    Supports formats like:
    - https://open.spotify.com/playlist/<id>
    - https://open.spotify.com/user/<user>/playlist/<id>
    - spotify:playlist:<id>
    - raw 22-character ID
    """
    s = (url_or_id or "").strip()
    if not s:
        raise RuntimeError("Empty playlist URL or ID")

    # spotify:playlist:<id>
    m = re.match(r"^spotify:playlist:([a-zA-Z0-9]+)$", s)
    if m:
        return m.group(1)

    # URL forms
    try:
        parsed = urlparse(s)
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        if "open.spotify.com" in host:
            parts = [p for p in path.split("/") if p]
            # possible paths: playlist/<id> or user/<user>/playlist/<id>
            for i, p in enumerate(parts):
                if p == "playlist" and i + 1 < len(parts):
                    return parts[i + 1]
    except Exception:
        pass

    # Raw ID fallback (usually 22 chars base62)
    if re.match(r"^[A-Za-z0-9]{16,}$", s):
        return s

    raise RuntimeError(f"Could not extract Spotify playlist ID from: {s}")


def fetch_playlist_tracks(url_or_id: str) -> Dict[str, Any]:
    """
    Spotifyプレイリストを取得して、
    - playlist: プレイリストメタデータ
    - items: トラック項目（全件）

    の形で返す。

    ここでは Spotipy の生のレスポンスをちょっとだけ整形するレベルに留める。
    実際に使いやすい dict への変換は playlist_result_to_dict() で行う。
    """
    playlist_id = extract_playlist_id(url_or_id)
    
    # Early detection: Check if this is an official editorial playlist (37i9...)
    if re.match(r"^37i9", playlist_id):
        logger.warning(f"[Spotify] Detected official editorial playlist: {playlist_id}")
        raise RuntimeError(
            "このプレイリストはSpotify公式のエディトリアルプレイリスト（ID: 37i9...）です。\n"
            "公式プレイリストは地域制限があり、取得できない場合があります。\n\n"
            "解決方法：\n"
            "1. あなたのアカウントで新しい公開プレイリストを作成\n"
            "2. このプレイリストの全曲をコピー\n"
            "3. 新しいプレイリストのURLを使用してください\n\n"
            "---\n\n"
            "This is an official Spotify editorial playlist (ID starts with 37i9).\n"
            "Official playlists may be region-restricted and unavailable via API.\n\n"
            "Workaround:\n"
            "1. Create a new public playlist in your Spotify account\n"
            "2. Copy all tracks from this playlist\n"
            "3. Use the new playlist URL instead"
        )
    
    sp = get_spotify_client()

    # プレイリストメタ情報
    try:
        playlist = sp.playlist(
            playlist_id,
            fields="id,name,external_urls,owner.id",
        )
    except SpotifyException as e:
        status = getattr(e, "http_status", None)
        msg = getattr(e, "msg", str(e))
        if status in (403, 404):
            # Private/personalized or region-restricted editorial
            editorial_hint = ""
            try:
                if re.match(r"^37i9", playlist_id or ""):
                    editorial_hint = (
                        " It may be an official editorial playlist (ID starts with 37i9) and region-restricted. "
                        "Workaround: Create a new public playlist in your account and copy all tracks, then use that URL."
                    )
            except Exception:
                pass
            raise RuntimeError(
                "Failed to fetch this playlist from Spotify API ({}). "
                "This may be a private or personalized playlist (e.g., Daily Mix / On Repeat / Blend) requiring user authentication, "
                "or region-restricted.{} Original error: {}".format(status, editorial_hint, msg)
            )
        raise RuntimeError(f"Failed to fetch playlist metadata: {msg}")

    # トラック全件（100曲以上にも対応）。市場（market）を指定して可用性差異に対応。
    owner_id = (playlist.get("owner") or {}).get("id") if isinstance(playlist.get("owner"), dict) else None
    is_official_edit = (owner_id == "spotify")
    # 優先順は環境変数 SPOTIFY_MARKET（カンマ区切り可）、なければ JP,US,GB.
    market_env = os.getenv("SPOTIFY_MARKET", "").strip()
    markets: List[str] = [m.strip().upper() for m in market_env.split(",") if m.strip()] or ["JP", "US", "GB"]

    last_error: Exception | None = None
    items: List[Dict[str, Any]] = []
    results = None
    for market in markets:
        try:
            results = sp.playlist_tracks(playlist_id, limit=100, offset=0, market=market)
            items.extend(results.get("items", []))
            # paginate
            while results.get("next"):
                try:
                    results = sp.next(results)
                except SpotifyException as e:
                    status = getattr(e, "http_status", None)
                    msg = getattr(e, "msg", str(e))
                    raise RuntimeError(f"Failed to fetch next page of tracks ({status}) for market {market}: {msg}")
                items.extend(results.get("items", []))
            # success for this market
            break
        except SpotifyException as e:
            last_error = e
            status = getattr(e, "http_status", None)
            msg = getattr(e, "msg", str(e))
            # For 403/404, try next market; otherwise stop immediately
            if status not in (403, 404):
                raise RuntimeError(f"Failed to fetch playlist tracks: {msg}")
            # continue to next market
            continue

    if results is None or (not items and last_error is not None):
        # Exhausted markets
        status = getattr(last_error, "http_status", None) if last_error else None
        msg = getattr(last_error, "msg", str(last_error)) if last_error else "Unknown error"
        prefix = "Failed to fetch playlist tracks from Spotify API. "
        if is_official_edit:
            prefix += "This looks like an official editorial playlist (owner=spotify). "
        hint = (
            "This playlist may be region-locked or personalized/private. "
            f"Tried markets: {','.join(markets)}. Last error ({status}): {msg}. "
            "You can set SPOTIFY_MARKET (e.g., 'JP' or 'US') to control the market. "
            "Workaround: Create a new public playlist in your account and copy all tracks into it, then use that new playlist URL."
        )
        raise RuntimeError(prefix + hint)

    return {
        "playlist": playlist,
        "items": items,
    }


# =========================
# フロント/CLI向けのフラットな dict に変換
# =========================


def _generate_track_key_primary(isrc: str | None) -> str | None:
    """Generate primary track key based on ISRC (server-determined for state sync)"""
    if isrc and isrc.strip():
        return f"isrc:{isrc.upper()}"
    return None


def _generate_track_key_fallback(title: str, artist: str, album: str | None = None) -> str:
    """Generate fallback track key using normalized fields.
    
    Escapes pipe and backslash characters to prevent delimiter collision.
    Safe to split by '|' for reconstruction.
    """
    from rekordbox import normalize_title_base, normalize_artist, normalize_album
    
    def _sanitize_field(s: str) -> str:
        """Escape delimiter characters for track_key safety"""
        return s.replace("\\", "＼").replace("|", "／")
    
    t_norm = _sanitize_field(normalize_title_base(title))
    a_norm = _sanitize_field(normalize_artist(artist))
    alb_norm = _sanitize_field(normalize_album(album or ""))
    
    # Deterministic key for Buylist state matching (pipe-delimited, fields escaped)
    if alb_norm:
        return f"norm:{t_norm}|{a_norm}|{alb_norm}"
    else:
        return f"norm:{t_norm}|{a_norm}"


def playlist_result_to_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    fetch_playlist_tracks() の結果（raw dict）を、
    フロントエンドや CLI 用に扱いやすい形の dict に変換する。

    戻り値フォーマット:
    {
      "playlist_id": str,
      "playlist_name": str,
      "playlist_url": str,
      "tracks": [
        {
          "title": str,
          "artist": str,
          "album": str,
          "isrc": str | None,
          "spotify_url": str,
          "links": {
            "beatport": str,
            "bandcamp": str,
            "itunes": str,
          }
        },
        ...
      ]
    }
    """
    playlist = raw["playlist"]
    items = raw["items"]

    playlist_id = playlist.get("id") or ""
    playlist_name = playlist.get("name") or ""
    # Spotify API always returns correct UTF-8, just normalize
    try:
        playlist_name = unicodedata.normalize("NFC", playlist_name)
    except Exception:
        pass

    # Prefer Spotify URL; if missing (e.g., Apple playlist), fall back to Apple URL
    playlist_url = (
        playlist.get("external_urls", {}).get("spotify")
        or playlist.get("external_urls", {}).get("apple")
        or ""
    )

    tracks_out: List[Dict[str, Any]] = []

    for item in items:
        track = item.get("track")
        if not track:
            continue

        # ローカルトラックはスキップ
        if track.get("is_local"):
            continue

        # Normalize textual fields (Spotify API always returns correct UTF-8)
        title = track.get("name") or ""
        try:
            title = unicodedata.normalize("NFC", title)
        except Exception:
            pass
        artists = track.get("artists") or []
        album = track.get("album") or {}
        artist_parts = []
        for a in artists:
            an = a.get("name")
            if not an:
                continue
            try:
                an = unicodedata.normalize("NFC", an)
            except Exception:
                pass
            artist_parts.append(an)
        artist_name = ", ".join(artist_parts)

        album_name = album.get("name") or ""
        try:
            album_name = unicodedata.normalize("NFC", album_name)
        except Exception:
            pass
        spotify_url = track.get("external_urls", {}).get("spotify", "")
        apple_url = track.get("external_urls", {}).get("apple", "")
        isrc = (track.get("external_ids") or {}).get("isrc")  # ISRC from Spotify

        links = build_store_links(title, artist_name, album_name, isrc=isrc)
        
        # Generate deterministic track keys for Buylist state management
        track_key_primary = _generate_track_key_primary(isrc)
        track_key_fallback = _generate_track_key_fallback(title, artist_name, album_name)
        
        # Determine primary type: ISRC takes precedence, else fallback
        track_key_primary_type = "isrc" if track_key_primary and track_key_primary.startswith("isrc:") else "norm"
        final_primary = track_key_primary or track_key_fallback

        tracks_out.append(
            {
                "title": title,
                "artist": artist_name,
                "album": album_name,
                "isrc": isrc,
                "spotify_url": spotify_url,
                "apple_url": apple_url,
                "links": links,
                "track_key_primary": final_primary,
                "track_key_fallback": track_key_fallback,
                "track_key_primary_type": track_key_primary_type,  # UI hint: "isrc" → confident, "norm" → ambiguous
                "track_key_version": "v1",  # Allows future migrations of normalization logic
            }
        )

    return {
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "playlist_url": playlist_url,
        "tracks": tracks_out,
    }


async def fetch_apple_playlist_tracks_from_web(url: str, app: Any | None = None) -> Dict[str, Any]:
    """
    Playwright with network interception:
    1. Block heavy resources (images, CSS, fonts, media)
    2. Listen for Apple Music API JSON responses
    3. Fall back to DOM parsing if network JSON unavailable
    4. Detect "blocked/JS-required" variants
    """
    if url:
        url = url.strip()
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1].strip()
        url = url.strip('\'"')

    if "music.apple.com" not in (url or ""):
        raise ValueError("Apple Music playlist URL を指定してください")

    if app is None:
        raise RuntimeError("App instance is required for Apple Music scraping (Playwright state)")

    try:
        cache = fetch_apple_playlist_tracks_from_web._cache
    except AttributeError:
        cache = TTLCache(maxsize=256, ttl=300)
        fetch_apple_playlist_tracks_from_web._cache = cache

    try:
        last = fetch_apple_playlist_tracks_from_web._last_fetch
    except AttributeError:
        last = {}
        fetch_apple_playlist_tracks_from_web._last_fetch = last

    now = time.time()
    last_ts = last.get(url, 0)

    if url in cache:
        return cache[url]

    if now - last_ts < 2:
        await asyncio.sleep(1)

    result: Dict[str, Any] | None = None
    context = None
    page = None
    meta_base: Dict[str, Any] = {"apple_strategy": "playwright"}
    api_response_captured: Dict[str, Any] | None = None

    async def on_response_handler(response):
        """Capture Apple Music API JSON responses."""
        nonlocal api_response_captured
        if api_response_captured:
            return
        try:
            url_str = response.url
            # Match Apple Music API patterns
            if any(
                pattern in url_str
                for pattern in [
                    "/api/v1/catalog/",
                    "/api/v1/playlist",
                ]
            ):
                if (
                    "/playlists" in url_str
                    and response.status == 200
                    and "application/json" in response.headers.get("content-type", "")
                ):
                    try:
                        body = await response.json()
                        # Basic validation: expect data.data or similar structure
                        if isinstance(body, dict) and body:
                            api_response_captured = {
                                "body": body,
                                "url": url_str,
                                "status": response.status,
                            }
                            logger.info(f"[Apple Network] Captured API response from {url_str}")
                    except Exception as e:
                        logger.debug(f"[Apple Network] Failed to parse API response: {e}")
        except Exception as e:
            logger.debug(f"[Apple Network] Error in response handler: {e}")

    try:
        context = await new_context()
        page = await context.new_page()
        page.set_default_navigation_timeout(APPLE_PW_COMMIT_TIMEOUT_MS)
        page.set_default_timeout(APPLE_PW_COMMIT_TIMEOUT_MS)

        # Block heavy resources
        async def route_handler(route):
            req_type = route.request.resource_type
            if req_type in ("image", "stylesheet", "font", "media"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_handler)

        # Listen for API responses
        page.on("response", on_response_handler)

        # Commit-stage fetch
        resp = await page.goto(url, wait_until="commit", timeout=APPLE_PW_COMMIT_TIMEOUT_MS)
        status = resp.status if resp else None
        final_url = resp.url if resp else url
        meta_base.update({
            "apple_http_status": status,
            "apple_final_url": final_url,
        })

        # Wait for API response capture (15s timeout)
        api_wait_timeout = 15000
        api_wait_start = time.time()
        while api_response_captured is None:
            if (time.time() - api_wait_start) * 1000 > api_wait_timeout:
                logger.info("[Apple Network] No API response captured within timeout")
                break
            await asyncio.sleep(0.2)

        # Try to extract tracks from API response
        if api_response_captured:
            try:
                body = api_response_captured["body"]
                # Apple API usually has data.data with attributes/name/artistName
                tracks, playlist_name = _extract_tracks_from_json_tree(body)
                if tracks:
                    result = _build_apple_playlist_result(
                        tracks,
                        playlist_name or "Apple Music Playlist",
                        final_url or url,
                        meta_extra={
                            **meta_base,
                            "apple_playwright_phase": "network_json",
                            "apple_api_url": api_response_captured["url"],
                        },
                    )
                    logger.info(f"[Apple Network] Extracted {len(tracks)} tracks from API response")
            except Exception as e:
                logger.debug(f"[Apple Network] Failed to parse API response: {e}")

        # DOM fallback if API response unavailable
        if result is None:
            try:
                await page.wait_for_timeout(1000)
                try:
                    await page.wait_for_selector(
                        'script[id="__NEXT_DATA__"], script[type="application/json"], script[type="application/ld+json"]',
                        timeout=APPLE_PW_DOM_TIMEOUT_MS,
                    )
                except Exception:
                    pass
                html_dom = await page.content()
            except Exception:
                html_dom = None

            if html_dom:
                parsed_dom = _parse_apple_html_payload(
                    html_dom,
                    final_url or url,
                    strategy_hint="playwright",
                    meta_extra={**meta_base, "apple_playwright_phase": "dom_fallback"},
                )
                if parsed_dom and parsed_dom.get("items"):
                    result = parsed_dom

        # Detect blocked/JS-required variant
        if result is None:
            reason = "no_tracks"
            try:
                page_title = await page.title()
                page_html = await page.content()
                first_kb = page_html[:1024].lower()
                if any(
                    kw in (page_title or "").lower() + first_kb
                    for kw in [
                        "access denied",
                        "denied",
                        "robot",
                        "enable javascript",
                        "javascript required",
                        "js required",
                    ]
                ):
                    reason = "blocked_variant"
                    logger.info(f"[Apple Network] Detected blocked/JS-required variant: {page_title}")
            except Exception:
                pass

            raise AppleFetchError(
                f"Apple page load failed (Playwright, {reason})",
                meta={
                    **meta_base,
                    "apple_playwright_phase": "network_json" if api_response_captured else "dom_fallback",
                    "reason": reason,
                },
            )

        # cache and record timestamp
        cache[url] = result
        last[url] = time.time()
        logger.info(f"[Apple Music] Parsed {len(result.get('items', []))} tracks via Playwright")
        return result
    finally:
        try:
            if context:
                await context.close()
        except Exception:
            pass


def _fetch_with_playwright(url: str) -> str:
    """
    Fetch page HTML using Playwright (headless Chromium). This is a blocking
    helper that uses the sync API; callers may run it in a thread.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("Playwright is not installed or cannot be imported: %s" % e)

    logger.info(f"[Playwright] Starting fetch for: {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            try:
                # Use a realistic desktop UA and Japanese locale to match Apple Music JP
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    locale="ja-JP",
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()
                page.set_default_navigation_timeout(90000)
                page.set_default_timeout(90000)

                # Enhanced retry to handle Apple Music's SPA navigation
                last_error = None
                for attempt in range(3):
                    try:
                        logger.info(f"[Playwright] Attempt {attempt + 1}/3 for {url}")
                        page.goto(url, wait_until="networkidle", timeout=60000)
                        
                        # Wait for main content area; Apple Music pages render under <main>
                        page.wait_for_selector("main", timeout=30000)
                        logger.info(f"[Playwright] Main content loaded")
                        
                        # Wait for track list to render (multiple possible selectors)
                        page.wait_for_selector(
                            'div[role="row"], ol li, .songs-list-row',
                            timeout=30000
                        )
                        logger.info(f"[Playwright] Track list rendered")
                        
                        # Give extra time for all dynamic content to settle
                        page.wait_for_timeout(2000)
                        
                        content = page.content()
                        logger.info(f"[Playwright] Successfully fetched {len(content)} bytes")
                        break
                    except Exception as nav_err:
                        last_error = nav_err
                        logger.warning(f"[Playwright] Attempt {attempt + 1} failed: {nav_err}")
                        if attempt < 2:  # Not the last attempt
                            logger.info(f"[Playwright] Waiting before retry...")
                            page.wait_for_timeout(2000)
                else:
                    raise last_error
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

        return content
    except Exception as e:
        error_msg = str(e)
        
        # Check if Playwright browser is not installed
        if "Executable doesn't exist" in error_msg or "chrome-linux" in error_msg:
            raise RuntimeError(
                "Playwright browser executable not found. "
                "This typically happens on Render.com or other cloud deployment platforms. "
                "The build must include: python -m playwright install --with-deps chromium\n\n"
                f"Original error: {error_msg}"
            )
        elif "PLAYWRIGHT" in error_msg.upper() or "browser" in error_msg.lower():
            raise RuntimeError(
                f"Playwright initialization failed: {error_msg}\n\n"
                "Please ensure Playwright is properly installed with: pip install -r requirements.txt"
            )
        else:
            raise RuntimeError(f"Failed to fetch page with Playwright: {error_msg}")


# --- ISRC enrichment helpers ---
def _mb_search_recording(title: str, artist: str, album: str | None = None) -> dict | None:
    import requests
    from urllib.parse import quote

    query_parts = [f'recording:"{title}"', f'artist:"{artist}"']
    if album:
        query_parts.append(f'release:"{album}"')
    query = " AND ".join(query_parts)
    url = f"https://musicbrainz.org/ws/2/recording?query={quote(query)}&fmt=json&limit=3"
    try:
        res = requests.get(url, headers={"User-Agent": "spotify-shopper/1.0 (ISRC enrichment)"}, timeout=10)
        if res.status_code != 200:
            return None
        data = res.json()
        recordings = data.get("recordings", [])
        for rec in recordings:
            isrcs = rec.get("isrcs", [])
            if isrcs:
                return {"isrc": isrcs[0]}
        return None
    except Exception:
        return None


def enrich_isrc_for_items(items: list, limit: int | None = None) -> int:
    """Fill missing ISRCs in-place for items with track metadata using MusicBrainz.

    Returns number of items updated.
    """
    updated = 0
    count = 0
    for it in items:
        if limit is not None and count >= limit:
            break
        track = it.get("track") or {}
        isrc = track.get("isrc") or track.get("external_ids", {}).get("isrc")
        if isrc:
            continue
        title = track.get("name") or track.get("title")
        album = (track.get("album") or {}).get("name") if isinstance(track.get("album"), dict) else track.get("album")
        artists = track.get("artists") or []
        artist_name = None
        if isinstance(artists, list) and artists:
            a0 = artists[0]
            artist_name = a0.get("name") if isinstance(a0, dict) else a0
        if not title or not artist_name:
            continue
        mb = _mb_search_recording(title, artist_name, album)
        if mb and mb.get("isrc"):
            track.setdefault("external_ids", {})
            track["external_ids"]["isrc"] = mb["isrc"]
            track["isrc"] = mb["isrc"]
            it["track"] = track
            updated += 1
        count += 1
    return updated


def _enrich_apple_tracks_with_spotify(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes an Apple Music playlist result and enriches each track with ISRC
    by searching Spotify for matching tracks.
    
    This preserves Apple's original artist/album/URL metadata completely.
    """
    try:
        sp = get_spotify_client()
    except Exception:
        # If Spotify client unavailable, return as-is (ISRC will remain null)
        return result
    
    items = result.get("items", [])
    enriched_items = []
    
    for item in items:
        track = item.get("track", {})
        title = track.get("name", "").strip()
        artists = track.get("artists", [])
        artist_name = artists[0].get("name", "").strip() if artists else ""
        
        # Skip enrichment if no title or artist (low match accuracy)
        if not title or not artist_name:
            enriched_items.append(item)
            continue
        
        # Search Spotify for ISRC
        try:
            query = f"track:{title} artist:{artist_name}"
            results = sp.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])
            
            if tracks:
                # Extract ISRC only (preserve all Apple metadata)
                sp_track = tracks[0]
                isrc = sp_track.get("external_ids", {}).get("isrc")
                if isrc:
                    if "external_ids" not in track:
                        track["external_ids"] = {}
                    track["external_ids"]["isrc"] = isrc
        except Exception:
            # On search error, keep original track data without ISRC
            pass
        
        enriched_items.append({"track": track})
    
    result["items"] = enriched_items
    return result


def _extract_tracks_from_json_tree(node: Any) -> tuple[list[dict], str | None]:
    """Recursively walk JSON looking for track-like objects with attributes/name/artistName.

    Returns a tuple of (tracks, playlist_name_candidate).
    """
    tracks: list[dict] = []
    playlist_name: str | None = None
    seen: set[tuple[str, str, str]] = set()

    def add_track(title: str | None, artist: str | None, album: str | None, url: str | None) -> None:
        if not title or not artist:
            return
        key = (title.strip().lower(), artist.strip().lower(), (album or "").strip().lower())
        if key in seen:
            return
        seen.add(key)
        tracks.append({
            "title": _fix_mojibake(title.strip()),
            "artist": _fix_mojibake(artist.strip()),
            "album": _fix_mojibake(album.strip()) if album else "",
            "apple_url": url or "",
        })

    def walk(obj: Any):
        nonlocal playlist_name
        if isinstance(obj, dict):
            # Playlist name candidate
            if playlist_name is None:
                name = obj.get("playlistName") or obj.get("name") or (obj.get("attributes") or {}).get("name")
                if isinstance(name, str) and name.strip():
                    playlist_name = _fix_mojibake(name.strip())

            attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else None
            if attrs:
                title = attrs.get("name") or attrs.get("title")
                artist = attrs.get("artistName") or attrs.get("artist")
                album = (
                    attrs.get("albumName")
                    or attrs.get("collectionName")
                    or attrs.get("albumTitle")
                )
                url = attrs.get("url") or attrs.get("shareUrl") or attrs.get("permalink")
                if title and artist:
                    add_track(title, artist, album, url)

            # Direct dict with name/artist keys
            if "name" in obj and "artistName" in obj and isinstance(obj.get("name"), str):
                add_track(obj.get("name"), obj.get("artistName"), obj.get("albumName") or obj.get("collectionName"), obj.get("url"))

            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(node)
    return tracks, playlist_name


def _build_apple_playlist_result(
    tracks: list[dict],
    playlist_name: str,
    url: str,
    meta_extra: dict | None = None,
) -> Dict[str, Any]:
    """Build a playlist result dict from tracks and metadata."""
    items = []
    for t in tracks:
        title = t.get("title") or ""
        artist = t.get("artist") or ""
        album = t.get("album") or ""
        apple_url = t.get("apple_url") or url
        track = {
            "name": title,
            "artists": [{"name": artist}] if artist else [],
            "album": {"name": album},
            "external_urls": {"apple": apple_url},
            "external_ids": {"isrc": None},
        }
        items.append({"track": track})

    playlist = {
        "id": url,
        "name": playlist_name or "Apple Music Playlist",
        "external_urls": {"apple": url},
    }

    meta = {"apple_strategy": "playwright"}
    if meta_extra:
        try:
            meta.update(meta_extra)
        except Exception:
            pass

    return {"playlist": playlist, "items": items, "meta": meta}


def _parse_apple_html_payload(html: str, url: str, strategy_hint: str = "html", meta_extra: dict | None = None) -> Optional[Dict[str, Any]]:
    """Parse Apple Music HTML for embedded JSON and build playlist result."""
    soup = BeautifulSoup(html, "html.parser")

    # Collect candidate scripts (priority: __NEXT_DATA__, ld+json, other application/json)
    candidate_scripts: list[str] = []
    for script in soup.find_all("script"):
        script_id = script.get("id", "")
        script_type = (script.get("type") or "").lower()
        if script_id == "__NEXT_DATA__" or script_type == "application/json" or script_type == "application/ld+json":
            text = script.string or script.get_text() or ""
            if text.strip():
                candidate_scripts.append(text)

    tracks: list[dict] = []
    playlist_name: str | None = None

    def try_parse_payload(payload_text: str) -> bool:
        nonlocal tracks, playlist_name
        try:
            data = json.loads(payload_text)
        except Exception as e:
            logger.debug(f"[Apple HTML] JSON parse failed: {e}")
            return False
        candidate_tracks, pl_name = _extract_tracks_from_json_tree(data)
        if candidate_tracks:
            tracks = candidate_tracks
            playlist_name = playlist_name or pl_name
            return True
        return False

    for text in candidate_scripts:
        if try_parse_payload(text):
            break

    if not tracks:
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        if title:
            playlist_name = playlist_name or _fix_mojibake(title)

    if not tracks:
        if APPLE_DEBUG_HTML:
            try:
                os.makedirs("_debug", exist_ok=True)
                with open("_debug/apple_last.html", "w", encoding="utf-8") as f:
                    f.write(html[:200000])
                logger.info("[Apple HTML] Saved debug HTML to _debug/apple_last.html")
            except Exception as e:
                logger.warning(f"[Apple HTML] Failed to save debug HTML: {e}")
        return None

    return _build_apple_playlist_result(
        tracks,
        playlist_name or "Apple Music Playlist",
        url,
        meta_extra={**{"apple_strategy": strategy_hint}, **(meta_extra or {})},
    )


async def fetch_apple_playlist_http_first(url: str) -> Optional[Dict[str, Any]]:
    """Attempt to fetch Apple Music playlist via static HTML/embedded JSON before Playwright.

    Returns playlist dict on success, or None to signal fallback to Playwright.
    """
    if url:
        url = url.strip().strip('"\'')
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1].strip()

    if "music.apple.com" not in (url or ""):
        raise ValueError("Apple Music playlist URL を指定してください")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    timeout = httpx.Timeout(APPLE_HTTP_TIMEOUT_S)
    last_error: Exception | None = None
    html: str | None = None
    status_code: int | None = None
    final_url: str | None = None
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for attempt in range(APPLE_HTTP_RETRIES + 1):
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text
                status_code = resp.status_code
                final_url = str(resp.url)
                break
            except Exception as e:
                last_error = e
                logger.warning(f"[Apple HTML] attempt {attempt + 1}/{APPLE_HTTP_RETRIES + 1} failed: {e}")
                await asyncio.sleep(1.0 * (attempt + 1))

    if not html:
        logger.warning(f"[Apple HTML] Failed to fetch HTML; fallback to Playwright. last_error={last_error}")
        return None

    parsed = _parse_apple_html_payload(
        html,
        final_url or url,
        strategy_hint="html",
        meta_extra={"apple_http_status": status_code, "apple_final_url": final_url or url},
    )
    if parsed:
        logger.info(f"[Apple HTML] Parsed {len(parsed.get('items', []))} tracks from embedded JSON")
    return parsed


async def fetch_playlist_tracks_generic(
    source: str,
    url_or_id: str,
    app: Any | None = None,
    enrich_spotify: bool | None = None,
) -> Dict[str, Any]:
    """
    Dispatch between spotify/apple sources. Default to spotify for compatibility.
    For Apple Music, enriches tracks with Spotify metadata (artist, album, ISRC).
    Returns dict with 'perf' key containing timing metrics.
    """
    import time
    t0_total = time.time()
    
    src = (source or "spotify").lower()
    perf = {
        'fetch_ms': 0,
        'enrich_ms': 0,
        'total_ms': 0,
        'tracks_count': 0,
    }
    
    if src == "apple":
        t0_fetch = time.time()
        apple_playwright_timeout_s = 95
        apple_strategy = "html"
        result: Dict[str, Any] | None = None

        # HTTP-first attempt
        try:
            result = await asyncio.wait_for(
                fetch_apple_playlist_http_first(url_or_id),
                timeout=APPLE_HTTP_TIMEOUT_S,
            )
        except Exception as e:
            logger.info(f"[Apple] HTML-first failed, will fallback to Playwright: {e}")

        if not result:
            apple_strategy = "playwright"
            try:
                result = await asyncio.wait_for(
                    fetch_apple_playlist_tracks_from_web(url_or_id, app=app),
                    timeout=apple_playwright_timeout_s,
                )
            except asyncio.TimeoutError:
                raise RuntimeError(f"Apple Music fetch timed out ({apple_playwright_timeout_s}s)")
        t1_fetch = time.time()
        perf['fetch_ms'] = (t1_fetch - t0_fetch) * 1000

        # Determine enrichment default: if not specified, default False for Apple
        do_enrich = bool(enrich_spotify) if enrich_spotify is not None else False

        meta = result.get("meta") or {}
        meta["apple_strategy"] = apple_strategy
        if do_enrich:
            t0_enrich = time.time()
            result = _enrich_apple_tracks_with_spotify(result)
            t1_enrich = time.time()
            perf['enrich_ms'] = (t1_enrich - t0_enrich) * 1000
        else:
            # Skip Spotify enrichment deliberately
            meta["apple_enrich_skipped"] = True
            perf['enrich_ms'] = 0.0
        result["meta"] = meta

        result['perf'] = perf
        t1_total = time.time()
        perf['total_ms'] = (t1_total - t0_total) * 1000
        perf['tracks_count'] = len(result.get('items', []))
        return result
    else:
        t0_fetch = time.time()
        result = await asyncio.to_thread(fetch_playlist_tracks, url_or_id)
        t1_fetch = time.time()
        perf['fetch_ms'] = (t1_fetch - t0_fetch) * 1000
        
        result['perf'] = perf
        t1_total = time.time()
        perf['total_ms'] = (t1_total - t0_fetch) * 1000
        perf['tracks_count'] = len(result.get('items', []))
        return result
