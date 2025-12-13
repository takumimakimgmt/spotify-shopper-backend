from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, List
from difflib import SequenceMatcher
from cachetools import TTLCache

import hashlib
import os


# =========================
# 正規化ヘルパー
# =========================


def normalize_artist(name: str) -> str:
    """
    アーティスト名のゆらぎを減らす:
    - 小文字化（ローマ字側だけ揃える。カタカナはそのまま別キー）
    - カンマ / & / ' and ' で区切って先頭だけ代表にする
    - feat. / ft. / featuring 以降を削る
    - 余分なスペースを詰める
    - 区切り文字 | をエスケープ（track_key_fallback用）
    """
    s = (name or "").lower().strip()

    # 代表アーティストだけ残す
    for sep in [",", "&", " and "]:
        if sep in s:
            s = s.split(sep)[0].strip()

    # feat / ft / featuring 以降を削る
    s = re.split(r"\s+(feat\.|ft\.|featuring)\s+", s)[0]

    s = re.sub(r"\s+", " ", s).strip()
    # Escape pipe delimiter for track_key reconstruction
    s = s.replace("|", "／")
    return s


def normalize_title_base(title: str) -> str:
    """
    タイトルの基本正規化:
    - 小文字化
    - () / [] 内の表記を削る (MIX名やレーベルなど)
    - feat. / ft. / featuring 以降を削る
    - 末尾の " - original mix" 系を削る
    - 余分なスペースを詰める
    - 区切り文字 | をエスケープ（track_key_fallback用）
    """
    s = (title or "").lower().strip()

    # 括弧の中身を全部落とす（位置に関係なく）
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\[[^]]*\]", "", s)

    # タイトル内の feat... を削る
    s = re.sub(r"\s+(feat\.|ft\.|featuring)\s+.*$", "", s)

    # 末尾の " - original mix / extended mix / edit / remix..." を削る
    s = re.sub(
        r"\s*-\s*(original mix|extended mix|radio edit|club mix|dub mix|dub|vip|edit|remix.*|mix)$",
        "",
        s,
    )

    s = re.sub(r"\s+", " ", s).strip()
    # Escape pipe delimiter for track_key reconstruction
    s = s.replace("|", "／")
    return s


def normalize_album(album: str) -> str:
    """
    アルバム名のゆらぎを減らす:
    - 小文字化
    - () / [] 内の注釈（deluxe, extended など）を削る
    - 余分なスペースを詰める
    - 区切り文字 | をエスケープ（track_key_fallback用）
    """
    s = (album or "").lower().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\[[^]]*\]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Escape pipe delimiter for track_key reconstruction
    s = s.replace("|", "／")
    return s


def generate_title_artist_pairs(title: str, artist: str) -> List[Tuple[str, str]]:
    """
    1つのトラックから、(title_norm, artist_norm) の候補ペアを複数生成する。

    - 基本ペア: normalize_title_base(title) × normalize_artist(artist)
    - 追加ペア: title が "X - Y ..." 形式なら
        (normalize_title_base(Y), normalize_artist(X)) を候補として追加
      （例: "OOTORO - The Plot [NIGHTMODE]" → ("the plot", "ootoro")）
    """
    pairs: List[Tuple[str, str]] = []

    base_title_norm = normalize_title_base(title)
    base_artist_norm = normalize_artist(artist)

    if base_title_norm and base_artist_norm:
        pairs.append((base_title_norm, base_artist_norm))

    # "X - Y" パターンを追加候補として扱う
    m = re.match(r"^(?P<left>.+?)\s*-\s*(?P<right>.+)$", title.strip())
    if m:
        left_raw = m.group("left").strip()
        right_raw = m.group("right").strip()

        cand_artist_norm = normalize_artist(left_raw)
        cand_title_norm = normalize_title_base(right_raw)

        if cand_artist_norm and cand_title_norm:
            key = (cand_title_norm, cand_artist_norm)
            if key not in pairs:
                pairs.append(key)

    return pairs


# =========================
# データモデル
# =========================


@dataclass
class RekordboxTrack:
    title: str
    artist: str
    album: str
    isrc: str | None

    title_norm: str
    artist_norm: str
    album_norm: str


@dataclass
class RekordboxLibrary:
    by_isrc: Dict[str, RekordboxTrack]
    by_title_artist: Dict[Tuple[str, str], List[RekordboxTrack]]
    by_artist_norm: Dict[str, List[RekordboxTrack]]
    by_title_album: Dict[Tuple[str, str], List[RekordboxTrack]]


# =========================
# XML ロード
# =========================

# In-memory cache for parsed Rekordbox libraries (TTL: 10 minutes)
_rekordbox_cache: TTLCache = TTLCache(maxsize=10, ttl=600)


def _get_file_hash(path: Path) -> str:
    """Use file size and mtime as a cheap cache key"""
    stat = path.stat()
    return f"{stat.st_size}_{stat.st_mtime_ns}"


def load_rekordbox_library_xml(path: str | Path) -> RekordboxLibrary:
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Rekordbox XML not found: {path}")

    # Cache lookup
    cache_key = _get_file_hash(path)
    cached = _rekordbox_cache.get(cache_key)
    if cached:
        return cached

    tree = ET.parse(path)
    root = tree.getroot()

    collection = root.find("COLLECTION")
    if collection is None:
        raise ValueError("Invalid Rekordbox XML: COLLECTION not found")

    by_isrc: Dict[str, RekordboxTrack] = {}
    by_title_artist: Dict[Tuple[str, str], List[RekordboxTrack]] = {}
    by_artist_norm: Dict[str, List[RekordboxTrack]] = {}
    by_title_album: Dict[Tuple[str, str], List[RekordboxTrack]] = {}

    for track in collection.findall("TRACK"):
        title = (track.get("Name") or "").strip()
        artist = (track.get("Artist") or "").strip()
        album = (track.get("Album") or "").strip()
        isrc = track.get("ISRC")

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


# =========================
# プレイリストとの突き合わせ
# =========================


def _similar(a: str, b: str) -> float:
    """0〜1の類似度（同一アーティスト内でのタイトル fuzz 用）"""
    return SequenceMatcher(None, a, b).ratio()


def mark_owned_tracks(playlist_data: dict, rekordbox_xml_path: str | Path) -> dict:
    """
    playlist_data: playlist_result_to_dict() の戻り（dict）
    RekordboxライブラリXMLと突き合わせて、各 track に owned: bool と owned_reason を付与して返す。

    判定の順番:
    1. ISRC 完全一致 → owned_reason = 'isrc'
    2. (title_norm, artist_norm) の組み合わせ一致 → owned_reason = 'exact'
       - Rekordbox側は "ARTIST - TITLE" パターンなどを含む複数候補を持つ
    3. (title_norm, album_norm) の組み合わせ一致 → owned_reason = 'album'
       - 有名アーティストがカタカナ表記になっていても、タイトル＋アルバムで拾う
    4. 同一 artist_norm 内で title_norm 類似度 >= 0.92 → owned_reason = 'fuzzy'
    """
    lib = load_rekordbox_library_xml(rekordbox_xml_path)

    for t in playlist_data.get("tracks", []):
        owned = False
        owned_reason = None

        title_norm = normalize_title_base(t["title"])
        artist_norm = normalize_artist(t["artist"])
        album_norm = normalize_album(t.get("album") or "")

        # 1) ISRC 完全一致
        isrc = t.get("isrc")
        if isrc and lib.by_isrc.get(isrc.upper()):
            owned = True
            owned_reason = "isrc"

        # 2) タイトル＋アーティスト（正規化）の組み合わせ一致
        if not owned and title_norm and artist_norm:
            key = (title_norm, artist_norm)
            if key in lib.by_title_artist:
                owned = True
                owned_reason = "exact"

        # 3) タイトル＋アルバム（正規化）の組み合わせ一致
        #    → アーティスト名がカタカナ／別表記でも拾えるようにする
        if not owned and title_norm and album_norm:
            key2 = (title_norm, album_norm)
            if key2 in lib.by_title_album:
                owned = True
                owned_reason = "album"

        # 4) 同一アーティスト内でタイトル類似度を見る（かなり閾値高め）
        if not owned and title_norm and artist_norm:
            candidates = lib.by_artist_norm.get(artist_norm, [])
            best = 0.0
            for rb in candidates:
                score = _similar(title_norm, normalize_title_base(rb.title))
                if score > best:
                    best = score

            if best >= 0.92:
                owned = True
                owned_reason = "fuzzy"

        t["owned"] = owned
        t["owned_reason"] = owned_reason

    return playlist_data
