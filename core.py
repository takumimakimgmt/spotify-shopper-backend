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
from typing import Any, Dict, List

import requests
import html as _html
from bs4 import BeautifulSoup
import json
import time
from cachetools import TTLCache
import unicodedata

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException


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


def extract_playlist_id(url_or_id: str) -> str:
    """
    Spotifyプレイリストの「URL / URI / ID」全部OKで受けて、
    正しい 22文字のID だけ取り出す。

    例：
    - https://open.spotify.com/playlist/0ZzPDztlFcDLdLbBa7hOks?si=... → 0ZzPDztlFcDLdLbBa7hOks
    - spotify:playlist:0ZzPDztlFcDLdLbBa7hOks                     → 0ZzPDztlFcDLdLbBa7hOks
    - 0ZzPDztlFcDLdLbBa7hOks                                      → 0ZzPDztlFcDLdLbBa7hOks
    """
    s = (url_or_id or "").strip()

    # 1) まずは「ふつうのURL」としてパースしてみる
    try:
        parsed = urllib.parse.urlparse(s)
        if parsed.scheme and parsed.netloc:
            # 例: /playlist/0ZzPDztlFcDLdLbBa7hOks
            parts = parsed.path.rstrip("/").split("/")
            if parts:
                cand = parts[-1]
                if re.fullmatch(r"[A-Za-z0-9]{22}", cand):
                    return cand
    except Exception:
        # URLとしてパースできなくても無視
        pass

    # 2) spotify:playlist:xxxxxx や /playlist/xxxxxx 形式から抜く
    m = re.search(r"(?:playlist[/:])([A-Za-z0-9]{22})", s)
    if m:
        return m.group(1)

    # 3) すでにIDだけが渡されているケース
    if re.fullmatch(r"[A-Za-z0-9]{22}", s):
        return s

    # どれにも当てはまらない場合はエラーにする
    raise ValueError(f"Invalid Spotify playlist URL or ID: {url_or_id}")


# =========================
# ストア検索リンク生成
# =========================




def build_store_links(title: str, artist: str, album: str | None = None) -> Dict[str, str]:
    """
    Beatport / Bandcamp / iTunes (Apple Music) の検索リンクを生成。
    Note: album is accepted but not used in search query to avoid reducing results.
    """
    # Build search query from title and artist only (album can reduce results)
    query = f"{title.strip()} {artist.strip()}".strip()
    q = urllib.parse.quote_plus(query)

    beatport = f"https://www.beatport.com/search?q={q}"
    bandcamp = f"https://bandcamp.com/search?q={q}"
    itunes = f"https://music.apple.com/search?term={q}"

    return {
        "beatport": beatport,
        "bandcamp": bandcamp,
        "itunes": itunes,
    }


# =========================
# プレイリスト取得
# =========================


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

        links = build_store_links(title, artist_name, album_name)

        tracks_out.append(
            {
                "title": title,
                "artist": artist_name,
                "album": album_name,
                "isrc": isrc,
                "spotify_url": spotify_url,
                "apple_url": apple_url,
                "links": links,
            }
        )

    return {
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "playlist_url": playlist_url,
        "tracks": tracks_out,
    }


def fetch_apple_playlist_tracks_from_web(url: str) -> Dict[str, Any]:
    """
    Best-effort scraper for Apple Music playlist pages.
    Returns a raw dict in the same shape as `fetch_playlist_tracks` so that
    `playlist_result_to_dict` can be reused.

    This implementation uses conservative/selective parsing and attempts to
    extract title/artist/album and per-track Apple URL where possible.
    """
    # Sanitize URL: strip whitespace, surrounding angle brackets and quotes
    if url:
        url = url.strip()
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1].strip()
        url = url.strip('\'"')

    if "music.apple.com" not in (url or ""):
        raise ValueError("Apple Music playlist URL を指定してください")

    # Simple in-memory cache to avoid frequent repeated scraping
    try:
        cache = fetch_apple_playlist_tracks_from_web._cache
    except AttributeError:
        cache = TTLCache(maxsize=256, ttl=300)
        fetch_apple_playlist_tracks_from_web._cache = cache

    # Per-URL last fetch timestamp to throttle accidental repeated hits
    try:
        last = fetch_apple_playlist_tracks_from_web._last_fetch
    except AttributeError:
        last = {}
        fetch_apple_playlist_tracks_from_web._last_fetch = last

    now = time.time()
    last_ts = last.get(url, 0)
    
    # Return cached result if available
    if url in cache:
        return cache[url]
    
    # Throttle repeated requests for same URL
    if now - last_ts < 2:
        time.sleep(1)

    # Apple Music always requires dynamic rendering - use Playwright first
    # This approach is more reliable than static HTML parsing
    playlist_name = "Apple Music Playlist"
    items = []
    
    try:
        html = _fetch_with_playwright(url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract playlist name from rendered page
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            playlist_name = h1.get_text(strip=True)
        elif soup.title and soup.title.string:
            playlist_name = soup.title.string.strip()
        
        # Try role="row" selector from Apple Music table layout
        rows = soup.find_all(attrs={'role': 'row'})
        if rows:
            # Skip header row (first row)
            for row in rows[1:]:
                # Use pipe separator to split into cells, then clean up
                text = row.get_text(separator='|')
                parts = [p.strip() for p in text.split('|') if p.strip()]
                
                if len(parts) >= 5:
                    # Format: [song, artist, rank?, artist_dup, album, preview(?), time]
                    # Pick fields by position
                    title = parts[0] if len(parts) > 0 else ""
                    artist = parts[1] if len(parts) > 1 else ""
                    # Album should be at index 4 or later, but skip preview/time
                    album = ""
                    for idx in range(4, len(parts)):
                        candidate = parts[idx]
                        # Skip "プレビュー", "preview" and time format
                        if candidate and candidate not in ("プレビュー", "preview"):
                            if not (":" in candidate and candidate.count(":") == 1):
                                album = candidate
                                break
                    
                    apple_track_url = ""
                    for a in row.find_all("a", href=True):
                        href = a.get("href", "")
                        if "music.apple.com" in href and "/song/" in href:
                            apple_track_url = href
                            break
                    
                    isrc = None
                    
                    track = {
                        "name": title,
                        "artists": [{"name": artist}] if artist else [],
                        "album": {"name": album},
                        "external_urls": {"apple": apple_track_url},
                        "external_ids": {"isrc": isrc},
                    }
                    
                    items.append({"track": track})
        
        # Fallback: if role=row didn't work, try other selectors
        if not items:
            candidates = []
            candidates.extend(soup.select("ol li"))
            candidates.extend(soup.select("ul li"))
            candidates.extend(soup.select("div[role='listitem']"))
            candidates.extend(soup.select("div.songs-list-row"))

            seen = set()
            for row in candidates:
                text = row.get_text(" ", strip=True)
                if not text or text in seen:
                    continue
                seen.add(text)

                title = ""
                t_el = row.select_one("h3") or row.select_one("[data-test-song-title]") or row.select_one(".songs-list-row__song-title")
                if t_el and t_el.get_text(strip=True):
                    title = t_el.get_text(strip=True)
                else:
                    b = row.select_one("strong") or row.select_one("b")
                    if b and b.get_text(strip=True):
                        title = b.get_text(strip=True)
                    else:
                        title = text.split("—")[0].strip()

                artist = ""
                a_el = row.select_one(".songs-list-row__by-line") or row.select_one("[data-test-artist-name]") or row.select_one(".byline")
                if a_el and a_el.get_text(strip=True):
                    artist = a_el.get_text(strip=True)
                else:
                    parts = text.split("–")
                    if len(parts) >= 2:
                        artist = parts[1].strip()

                album = ""
                album_el = row.select_one(".songs-list-row__collection") or row.select_one("[data-test-album-name]")
                if album_el and album_el.get_text(strip=True):
                    album = album_el.get_text(strip=True)

                apple_track_url = ""
                for a in row.find_all("a", href=True):
                    href = a.get("href", "")
                    if "music.apple.com" in href and "/song/" in href:
                        apple_track_url = href
                        break

                isrc = None

                track = {
                    "name": title,
                    "artists": [{"name": artist}] if artist else [],
                    "album": {"name": album},
                    "external_urls": {"apple": apple_track_url},
                    "external_ids": {"isrc": isrc},
                }

                items.append({"track": track})
    except Exception as e:
        # If Playwright is not available or rendering fails, raise error
        raise RuntimeError(f"Failed to fetch Apple Music playlist with Playwright: {e}")
    
    playlist = {"id": url, "name": playlist_name, "external_urls": {"apple": url}}

    result = {"playlist": playlist, "items": items}

    # cache and record timestamp
    cache[url] = result
    last[url] = time.time()

    return result


def _fetch_with_playwright(url: str) -> str:
    """
    Fetch page HTML using Playwright (headless Chromium). This is a blocking
    helper that uses the sync API; callers may run it in a thread.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("Playwright is not installed or cannot be imported: %s" % e)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            # give extra time for dynamic content
            page.wait_for_timeout(500)
            content = page.content()
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return content


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


def fetch_playlist_tracks_generic(source: str, url_or_id: str) -> Dict[str, Any]:
    """
    Dispatch between spotify/apple sources. Default to spotify for compatibility.
    For Apple Music, enriches tracks with Spotify metadata (artist, album, ISRC).
    """
    src = (source or "spotify").lower()
    if src == "apple":
        result = fetch_apple_playlist_tracks_from_web(url_or_id)
        # Enrich Apple tracks with Spotify metadata
        result = _enrich_apple_tracks_with_spotify(result)
        return result
    else:
        return fetch_playlist_tracks(url_or_id)
