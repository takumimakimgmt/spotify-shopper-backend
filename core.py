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
    """
    # Build search query from title, artist, album
    parts = [title.strip(), artist.strip()]
    if album:
        parts.append(album.strip())
    query = " ".join(p for p in parts if p)
    
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
    playlist = sp.playlist(
        playlist_id,
        fields="id,name,external_urls",
    )

    # トラック全件（100曲以上にも対応）
    items: List[Dict[str, Any]] = []
    results = sp.playlist_tracks(playlist_id, limit=100, offset=0)
    items.extend(results.get("items", []))

    while results.get("next"):
        results = sp.next(results)
        items.extend(results.get("items", []))

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
    # attempt to fix mojibake in playlist name as well
    try:
        playlist_name = _fix_mojibake(playlist_name)
    except Exception:
        pass
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

        # Normalize textual fields and attempt to fix mojibake
        title = track.get("name") or ""
        title = _fix_mojibake(title)
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
            an = _fix_mojibake(an)
            try:
                an = unicodedata.normalize("NFC", an)
            except Exception:
                pass
            artist_parts.append(an)
        artist_name = ", ".join(artist_parts)

        album_name = album.get("name") or ""
        album_name = _fix_mojibake(album_name)
        try:
            album_name = unicodedata.normalize("NFC", album_name)
        except Exception:
            pass
        spotify_url = track.get("external_urls", {}).get("spotify", "")
        apple_url = track.get("external_urls", {}).get("apple", "")
        bpm = track.get("tempo")  # BPM from Spotify
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
    if now - last_ts < 2:
        # If cached, return cached; otherwise wait briefly to avoid hammering
        if url in cache:
            return cache[url]
        time.sleep(1)

    # Return cached result if available
    if url in cache:
        return cache[url]

    # Try static HTML parsing first
    resp = requests.get(url, timeout=10, headers={"User-Agent": "spotify-shopper/1.0 (+https://github.com)"})
    resp.raise_for_status()
    # Decode bytes explicitly using detected encoding or utf-8 as fallback to avoid
    # mojibake when servers mis-report charset. Use errors='replace' to avoid exceptions.
    encoding = resp.encoding or resp.apparent_encoding or "utf-8"
    try:
        html = resp.content.decode(encoding, errors="replace")
    except Exception:
        html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Playlist name: try JSON-LD -> h1 -> title
    playlist_name = "Apple Music Playlist"
    # JSON-LD structured data
    ld = None
    jtag = soup.find("script", type="application/ld+json")
    if jtag:
        try:
            ld = json.loads(jtag.string or "{}")
        except Exception:
            ld = None

    if ld:
        # structured data may contain name and track list
        if isinstance(ld, dict) and ld.get("name"):
            playlist_name = ld.get("name")
    else:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            playlist_name = h1.get_text(strip=True)
        elif soup.title and soup.title.string:
            playlist_name = soup.title.string.strip()

    items = []

    # If JSON-LD contains track information, use it but mark as incomplete if missing artist/album
    ld_items_has_artist_album = False
    if ld and isinstance(ld, dict) and ld.get("track"):
        tracks_ld = ld.get("track") or []
        for t in tracks_ld:
            title = t.get("name") or ""
            artist = ""
            if isinstance(t.get("byArtist"), dict):
                artist = t.get("byArtist", {}).get("name", "")
            elif isinstance(t.get("byArtist"), list) and t.get("byArtist"):
                artist = t.get("byArtist")[0].get("name", "")
            album = (t.get("inAlbum") or {}).get("name") if isinstance(t.get("inAlbum"), dict) else ""
            apple_track_url = t.get("url") or ""
            isrc = None
            if isinstance(t.get("identifier"), dict):
                isrc = t.get("identifier", {}).get("@id")

            track = {
                "name": title,
                "artists": [{"name": artist}] if artist else [],
                "album": {"name": album},
                "external_urls": {"apple": apple_track_url},
                "external_ids": {"isrc": isrc},
            }
            items.append({"track": track})
            if artist or album:
                ld_items_has_artist_album = True

    # If JSON-LD not helpful, try to extract embedded JSON blobs from scripts
    def _extract_tracks_from_jsonobj(obj: Any) -> List[dict]:
        """Try to find a list of tracks inside a parsed JSON-like object."""
        found: List[dict] = []
        if not obj:
            return found

        # Common keys that may contain tracks
        candidates = []
        if isinstance(obj, dict):
            for k in ("tracks", "track", "items", "data", "songs", "collection"):
                if k in obj and isinstance(obj[k], (list, dict)):
                    candidates.append(obj[k])
            # also search nested dicts for 'tracks' keys
            for v in obj.values():
                if isinstance(v, dict):
                    for k in ("tracks", "items", "songs"):
                        if k in v and isinstance(v[k], list):
                            candidates.append(v[k])
        elif isinstance(obj, list):
            candidates.append(obj)

        for cand in candidates:
            if isinstance(cand, list):
                for it in cand:
                    # normalize possible shapes into track-like dicts
                    if isinstance(it, dict):
                        # music schema: name, byArtist/inAlbum/url
                        title = it.get("name") or it.get("title") or ""
                        artist = ""
                        if isinstance(it.get("byArtist"), dict):
                            artist = it.get("byArtist", {}).get("name", "")
                        elif isinstance(it.get("byArtist"), list) and it.get("byArtist"):
                            artist = it.get("byArtist")[0].get("name", "")
                        elif it.get("artist"):
                            artist = it.get("artist")
                        album = (it.get("inAlbum") or {}).get("name") if isinstance(it.get("inAlbum"), dict) else it.get("album", "")
                        urlt = it.get("url") or (it.get("external_urls") or {}).get("apple") or ""
                        isrc = None
                        if isinstance(it.get("identifier"), dict):
                            isrc = it.get("identifier", {}).get("@id")

                        track = {
                            "name": title,
                            "artists": [{"name": artist}] if artist else [],
                            "album": {"name": album} if album else {},
                            "external_urls": {"apple": urlt},
                            "external_ids": {"isrc": isrc},
                        }
                        found.append({"track": track})
        return found

    items = []

    # Try to parse <script type="application/json"> or any script containing a top-level JSON
    scripts = soup.find_all("script")
    for s in scripts:
        stype = s.get("type", "") or ""
        txt = None
        try:
            txt = s.string or s.get_text()
        except Exception:
            txt = None
        if not txt or not txt.strip():
            continue

        # If it's application/ld+json we already parsed it above; also try application/json
        if stype and "json" in stype.lower():
            try:
                parsed = json.loads(txt)
            except Exception:
                parsed = None
            if parsed:
                items_ext = _extract_tracks_from_jsonobj(parsed)
                if items_ext:
                    items.extend(items_ext)
                    break

        # For other scripts, try to parse if they start with { or [
        tstr = txt.strip()
        if tstr.startswith("{") or tstr.startswith("["):
            try:
                parsed = json.loads(tstr)
            except Exception:
                parsed = None
            if parsed:
                items_ext = _extract_tracks_from_jsonobj(parsed)
                if items_ext:
                    items.extend(items_ext)
                    break

        # Some pages embed JSON as JS assignment: var X = {...}; or window.__data = {...};
        # Try to heuristically extract a {...} substring
        if "{\"name\"" in tstr or '"@type":"MusicRecording"' in tstr or 'playParams' in tstr:
            m = re.search(r"(\{[\s\S]*\})", tstr)
            if m:
                try:
                    parsed = json.loads(m.group(1))
                except Exception:
                    parsed = None
                if parsed:
                    items_ext = _extract_tracks_from_jsonobj(parsed)
                    if items_ext:
                        items.extend(items_ext)
                        break

    # If JSON-LD produced items earlier, keep them; else continue with DOM heuristics
    if not items:
        # Candidate selectors for track rows. Try a few likely options.
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

            # title
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

            # artist
            artist = ""
            a_el = row.select_one(".songs-list-row__by-line") or row.select_one("[data-test-artist-name]") or row.select_one(".byline")
            if a_el and a_el.get_text(strip=True):
                artist = a_el.get_text(strip=True)
            else:
                # Fallback 1: split by –（em dash）
                parts = text.split("–")
                if len(parts) >= 2:
                    artist = parts[1].strip()
                # Fallback 2: split by - (hyphen) if em dash didn't work
                if not artist:
                    parts = text.split("-")
                    if len(parts) >= 2:
                        artist = parts[1].strip()
                # Fallback 3: split by • (bullet) if hyphen didn't work
                if not artist:
                    parts = text.split("•")
                    if len(parts) >= 2:
                        artist = parts[1].strip()

            # album (optional)
            album = ""
            album_el = row.select_one(".songs-list-row__collection") or row.select_one("[data-test-album-name]")
            if album_el and album_el.get_text(strip=True):
                album = album_el.get_text(strip=True)

            # apple track url
            apple_track_url = ""
            a_tag = row.find("a", href=True)
            if a_tag and "music.apple.com" in a_tag["href"]:
                apple_track_url = a_tag["href"]

            isrc = None

            track = {
                "name": title,
                "artists": [{"name": artist}] if artist else [],
                "album": {"name": album},
                "external_urls": {"apple": apple_track_url},
                "external_ids": {"isrc": isrc},
            }

            items.append({"track": track})

    # If still no items, try Playwright-based rendering as a fallback
    # OR if JSON-LD items don't have artist/album info, try to enrich them with Playwright
    if not items or not ld_items_has_artist_album:
        try:
            html2 = _fetch_with_playwright(url)
            soup2 = BeautifulSoup(html2, "html.parser")
            
            # Try role="row" selector from Apple Music table layout
            rows = soup2.find_all(attrs={'role': 'row'})
            pw_items = []
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
                        a_tag = row.find("a", href=True)
                        if a_tag and "music.apple.com" in a_tag["href"]:
                            apple_track_url = a_tag["href"]
                        
                        isrc = None
                        
                        track = {
                            "name": title,
                            "artists": [{"name": artist}] if artist else [],
                            "album": {"name": album},
                            "external_urls": {"apple": apple_track_url},
                            "external_ids": {"isrc": isrc},
                        }
                        
                        pw_items.append({"track": track})
            
            # If Playwright found items, use them (especially if JSON-LD lacked artist/album)
            if pw_items:
                if not ld_items_has_artist_album:
                    # JSON-LD was incomplete, replace with Playwright items
                    items = pw_items
                else:
                    # JSON-LD was complete, use it as is
                    pass
            elif not items:
                # Fallback: attempt old heuristics on rendered HTML if role=row didn't work
                candidates = []
                candidates.extend(soup2.select("ol li"))
                candidates.extend(soup2.select("ul li"))
                candidates.extend(soup2.select("div[role='listitem']"))
                candidates.extend(soup2.select("div.songs-list-row"))

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
                    a_tag = row.find("a", href=True)
                    if a_tag and "music.apple.com" in a_tag["href"]:
                        apple_track_url = a_tag["href"]

                    isrc = None

                    track = {
                        "name": title,
                        "artists": [{"name": artist}] if artist else [],
                        "album": {"name": album},
                        "external_urls": {"apple": apple_track_url},
                        "external_ids": {"isrc": isrc},
                    }

                    items.append({"track": track})
        except Exception:
            # If playwright is not available or rendering fails, continue with existing items
            pass

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
    Takes an Apple Music playlist result and enriches each track with Spotify data
    (artist, album, ISRC) by searching Spotify for matching tracks.
    
    This allows us to get full metadata for Apple Music playlists.
    """
    try:
        sp = get_spotify_client()
    except Exception as e:
        # If Spotify client unavailable, log and return as-is
        print(f"Warning: Spotify client unavailable for enrichment: {e}")
        return result
    
    items = result.get("items", [])
    enriched_items = []
    
    for item in items:
        track = item.get("track", {})
        title = track.get("name", "").strip()
        artists = track.get("artists", [])
        artist_name = artists[0].get("name", "").strip() if artists else ""
        
        if not title:
            # Can't search without title
            enriched_items.append(item)
            continue
        
        # If artist is missing, still try to search by title alone
        if not artist_name:
            print(f"Debug: Apple track has no artist, searching by title: {title}")
        
        # Search Spotify for this track (with or without artist)
        try:
            if artist_name:
                query = f"track:{title} artist:{artist_name}"
            else:
                query = f"track:{title}"
            print(f"Debug: Searching Spotify for: {query}")
            results = sp.search(q=query, type="track", limit=3)
            tracks = results.get("tracks", {}).get("items", [])
            
            if tracks:
                # Use first match to enrich metadata
                sp_track = tracks[0]
                print(f"Debug: Found match: {sp_track.get('name')} by {[a.get('name') for a in sp_track.get('artists', [])]}")
                
                # Update artist info
                sp_artists = sp_track.get("artists", [])
                if sp_artists:
                    track["artists"] = [{"name": a.get("name", "")} for a in sp_artists]
                
                # Update album info
                album = sp_track.get("album", {})
                if album:
                    track["album"] = {"name": album.get("name", "")}
                
                # Add ISRC if available
                isrc = sp_track.get("external_ids", {}).get("isrc")
                if isrc:
                    if "external_ids" not in track:
                        track["external_ids"] = {}
                    track["external_ids"]["isrc"] = isrc
                
                # Preserve Apple URL, add Spotify URL
                sp_url = sp_track.get("external_urls", {}).get("spotify")
                if sp_url:
                    track["external_urls"] = {
                        "spotify": sp_url,
                        "apple": track.get("external_urls", {}).get("apple", "")
                    }
            else:
                print(f"Debug: No Spotify match for: {query}")
        except Exception as e:
            # On search error, keep original track data
            print(f"Warning: Failed to enrich track '{title}' with Spotify data: {e}")
        
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
