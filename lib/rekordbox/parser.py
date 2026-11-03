"""
Rekordbox XML パーサー。ファイルの読み込みとインデックス構築を担当。
"""

from __future__ import annotations

import os
import hashlib
import time as time_module
from pathlib import Path

from defusedxml import ElementTree as DefusedET

from lib.cache_manager import get_rekordbox_cache, build_rekordbox_cache_key
from lib.rekordbox.models import RekordboxLibrary, RekordboxTrack
from lib.rekordbox.normalizer import (
    normalize_artist,
    normalize_title_base,
    normalize_album,
    generate_title_artist_pairs,
)


def _max_xml_size_bytes() -> int:
    try:
        megabytes = int((os.getenv("REKORDBOX_MAX_XML_MB") or "50").strip())
    except (TypeError, ValueError):
        megabytes = 50
    if not 1 <= megabytes <= 512:
        megabytes = 50
    return megabytes * 1024 * 1024


# XML ファイルサイズ上限（環境変数で設定可能、デフォルト: 50 MB）
MAX_XML_SIZE_BYTES = _max_xml_size_bytes()


def _get_file_hash(path: Path) -> str:
    """Build a stable cache key for identical XML content."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rekordbox_library_xml(
    path: str | Path,
    timeout_sec: float = 30.0,
    content_hash: str | None = None,
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
        OverflowError: File size exceeds configured MB limit

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

    t0 = time_module.monotonic()
    deadline = t0 + timeout_sec

    # Cache lookup
    cache_key = build_rekordbox_cache_key(content_hash or _get_file_hash(path))
    cache = get_rekordbox_cache()
    cache_enabled = os.getenv("REKORDBOX_CACHE_ENABLED", "false").lower() == "true"
    cached = cache.get(cache_key) if cache_enabled else None
    if cached:
        return cached

    by_isrc: dict[str, RekordboxTrack] = {}
    by_title_artist: dict[tuple[str, str], list[RekordboxTrack]] = {}
    by_artist_norm: dict[str, list[RekordboxTrack]] = {}
    by_title_album: dict[tuple[str, str], list[RekordboxTrack]] = {}
    track_count = 0
    t_index_start = time_module.monotonic()
    collection_found = False
    collection_element = None
    event_count = 0
    depth = 0
    collection_depth = None

    for event, track_elem in DefusedET.iterparse(path, events=("start", "end")):
        event_count += 1
        if event == "start":
            depth += 1
            if depth > 64 or event_count > 600_000:
                raise ValueError("XML structure exceeds safe complexity limits")
        else:
            depth -= 1
        if event_count % 256 == 0 and time_module.monotonic() > deadline:
            raise TimeoutError(f"XML parsing exceeded {timeout_sec}s timeout")
        if event == "start" and track_elem.tag == "COLLECTION":
            if collection_found:
                raise ValueError("Invalid Rekordbox XML: multiple COLLECTION elements")
            collection_found = True
            collection_depth = depth
            collection_element = track_elem
            continue
        if event == "end" and track_elem.tag == "COLLECTION":
            collection_element = None
            track_elem.clear()
            continue
        if (
            event != "end"
            or track_elem.tag != "TRACK"
            or collection_element is None
            or depth != collection_depth
        ):
            continue
        if time_module.monotonic() > deadline:
            raise TimeoutError(f"XML parsing exceeded {timeout_sec}s timeout")

        title = (track_elem.get("Name") or "").strip()
        artist = (track_elem.get("Artist") or "").strip()
        album = (track_elem.get("Album") or "").strip()
        isrc = track_elem.get("ISRC")
        track_count += 1
        if track_count > 100_000 or any(
            len(value or "") > 2048 for value in (title, artist, album, isrc)
        ):
            raise ValueError("XML track data exceeds safe complexity limits")

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
            by_isrc[isrc.strip().upper()] = info

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

        track_elem.clear()
        collection_element.remove(track_elem)

    if not collection_found:
        raise ValueError("Invalid Rekordbox XML: COLLECTION not found")

    finished_at = time_module.monotonic()
    parse_ms = int((finished_at - t0) * 1000)
    index_ms = int((finished_at - t_index_start) * 1000)
    xml_mb = xml_bytes / (1024 * 1024)

    library = RekordboxLibrary(
        by_isrc=by_isrc,
        by_title_artist=by_title_artist,
        by_artist_norm=by_artist_norm,
        by_title_album=by_title_album,
    )

    # Cache the parsed library
    if cache_enabled:
        cache[cache_key] = library
    print(
        f"[rekordbox] index tracks={track_count} size_mb={xml_mb:.1f} size_bytes={int(xml_bytes)} "
        f"parse_ms={parse_ms} index_ms={index_ms}"
    )

    return library
