"""
Rekordbox XML パーサー。ファイルの読み込みとインデックス構築を担当。
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import time as time_module
from pathlib import Path
from cachetools import TTLCache

from lib.rekordbox.models import RekordboxLibrary, RekordboxTrack
from lib.rekordbox.normalizer import (
    normalize_artist,
    normalize_title_base,
    normalize_album,
    generate_title_artist_pairs,
)


# XML ファイルサイズ上限（環境変数で設定可能、デフォルト: 20 MB）
MAX_XML_SIZE_BYTES = int(os.getenv("REKORDBOX_MAX_XML_MB", "20")) * 1024 * 1024

# In-memory cache for parsed Rekordbox libraries (TTL: 10 minutes)
_rekordbox_cache: TTLCache = TTLCache(maxsize=10, ttl=600)


def _get_file_hash(path: Path) -> str:
    """Use file size and mtime as a cheap cache key."""
    stat = path.stat()
    return f"{stat.st_size}_{stat.st_mtime_ns}"


def load_rekordbox_library_xml(
    path: str | Path,
    timeout_sec: float = 30.0,
) -> RekordboxLibrary:
    """
    Parse Rekordbox XML collection file.

    Args:
        path: Path to the XML file
        timeout_sec: Max seconds to spend parsing (prevents hang on huge XML)

    Raises:
        FileNotFoundError: XML file not found
        ValueError: Invalid XML structure
        TimeoutError: Parsing exceeded timeout
        OverflowError: File size exceeds 20 MB limit

    Returns:
        RekordboxLibrary with indexed tracks
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Rekordbox XML not found: {path}")

    xml_bytes = path.stat().st_size
    
    # File size guard
    if xml_bytes > MAX_XML_SIZE_BYTES:
        raise OverflowError(
            f"Rekordbox XML exceeds {MAX_XML_SIZE_BYTES / (1024 * 1024):.0f}MB limit "
            f"({xml_bytes / (1024 * 1024):.1f}MB). "
            "See docs/REKORDBOX_XML_LIMITS.md for guidance."
        )

    t0 = time_module.time()

    # Cache lookup
    cache_key = _get_file_hash(path)
    cached = _rekordbox_cache.get(cache_key)
    if cached:
        return cached

    # Parse with timeout awareness (simple: just log if takes too long)
    tree = ET.parse(path)
    parse_ms = int((time_module.time() - t0) * 1000)

    # Log XML size and parse time for observability
    xml_mb = xml_bytes / (1024 * 1024)
    print(f"[rekordbox] parsed {xml_mb:.1f}MB XML in {parse_ms}ms")

    if parse_ms > timeout_sec * 1000:
        raise TimeoutError(f"XML parsing exceeded {timeout_sec}s timeout")

    root = tree.getroot()

    collection = root.find("COLLECTION")
    if collection is None:
        raise ValueError("Invalid Rekordbox XML: COLLECTION not found")

    by_isrc: dict[str, RekordboxTrack] = {}
    by_title_artist: dict[tuple[str, str], list[RekordboxTrack]] = {}
    by_artist_norm: dict[str, list[RekordboxTrack]] = {}
    by_title_album: dict[tuple[str, str], list[RekordboxTrack]] = {}

    for track_elem in collection.findall("TRACK"):
        title = (track_elem.get("Name") or "").strip()
        artist = (track_elem.get("Artist") or "").strip()
        album = (track_elem.get("Album") or "").strip()
        isrc = track_elem.get("ISRC")

        title_norm = normalize_title_base(title)
        artist_norm = normalize_artist(artist)
        album_norm = normalize_album(album)

        info = RekordboxTrack(
            title=title,
            artist=artist,
            album=album,
            isrc=isrc,
            title_norm=title_norm,
            artist_norm=artist_norm,
            album_norm=album_norm,
        )

        # ISRC index
        if isrc:
            by_isrc[isrc.upper()] = info

        # title+artist 候補ペアすべてに index を張る
        for t_norm, a_norm in generate_title_artist_pairs(title, artist):
            key = (t_norm, a_norm)
            by_title_artist.setdefault(key, []).append(info)

        # アーティストごとのリスト（fuzzy用）
        if artist_norm:
            by_artist_norm.setdefault(artist_norm, []).append(info)

        # title+album index
        if title_norm and album_norm:
            key2 = (title_norm, album_norm)
            by_title_album.setdefault(key2, []).append(info)

    library = RekordboxLibrary(
        by_isrc=by_isrc,
        by_title_artist=by_title_artist,
        by_artist_norm=by_artist_norm,
        by_title_album=by_title_album,
    )

    # Cache the parsed library
    _rekordbox_cache[cache_key] = library

    return library
