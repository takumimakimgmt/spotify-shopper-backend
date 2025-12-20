"""
プレイリストとREkordboxライブラリのマッチング。
判定の優先順: ISRC → 正規化タイトル+アーティスト → 正規化タイトル+アルバム → Fuzzy タイトル
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import time

from lib.rekordbox.models import (
    RekordboxLibrary,
    RekordboxTrack,
    OwnedDetail,
    MatchMethod,
)
from lib.rekordbox.normalizer import (
    normalize_artist,
    normalize_title_base,
    normalize_album,
)
from lib.rekordbox.parser import load_rekordbox_library_xml


def _similar(a: str, b: str) -> float:
    """0〜1の類似度（同一アーティスト内でのタイトル fuzzy 用）"""
    return SequenceMatcher(None, a, b).ratio()


def mark_owned_tracks(
    playlist_data: dict,
    rekordbox_xml_path: str | Path,
) -> dict:
    """
    playlist_data: playlist_result_to_dict() の戻り（dict）
    RekordboxライブラリXMLと突き合わせて、各 track に owned: bool と owned_detail を付与して返す。

    判定の順番:
    1. ISRC 完全一致 → method = 'isrc'
    2. (title_norm, artist_norm) の組み合わせ一致 → method = 'exact'
       - Rekordbox側は "ARTIST - TITLE" パターンなどを含む複数候補を持つ
    3. (title_norm, album_norm) の組み合わせ一致 → method = 'album'
       - 有名アーティストがカタカナ表記になっていても、タイトル＋アルバムで拾う
    4. 同一 artist_norm 内で title_norm 類似度 >= 0.92 → method = 'fuzzy'

    Args:
        playlist_data: Playlist dict with 'tracks' key
        rekordbox_xml_path: Path to Rekordbox XML file

    Returns:
        Modified playlist_data with 'owned' and 'owned_detail' added to each track
    """
    t0_match = time.time()
    lib = load_rekordbox_library_xml(rekordbox_xml_path)
    fuzzy_count = 0

    for t in playlist_data.get("tracks", []):
        owned = False
        owned_detail: OwnedDetail = {}

        title_norm = normalize_title_base(t["title"])
        artist_norm = normalize_artist(t["artist"])
        album_norm = normalize_album(t.get("album") or "")

        # 1) ISRC 完全一致
        isrc = t.get("isrc")
        if isrc:
            rb_track = lib.by_isrc.get(isrc.upper())
            if rb_track:
                owned = True
                owned_detail = {
                    "method": MatchMethod.ISRC.value,
                    "score": 1.0,
                    "matched_title": rb_track.title,
                    "matched_artist": rb_track.artist,
                    "rb_track": rb_track,
                }

        # 2) タイトル＋アーティスト（正規化）の組み合わせ一致
        if not owned and title_norm and artist_norm:
            key = (title_norm, artist_norm)
            matches = lib.by_title_artist.get(key, [])
            if matches:
                rb_track = matches[0]  # 最初のマッチを使用
                owned = True
                owned_detail = {
                    "method": MatchMethod.EXACT.value,
                    "score": 1.0,
                    "matched_title": rb_track.title,
                    "matched_artist": rb_track.artist,
                    "rb_track": rb_track,
                }

        # 3) タイトル＋アルバム（正規化）の組み合わせ一致
        #    → アーティスト名がカタカナ／別表記でも拾えるようにする
        if not owned and title_norm and album_norm:
            key2 = (title_norm, album_norm)
            matches = lib.by_title_album.get(key2, [])
            if matches:
                rb_track = matches[0]
                owned = True
                owned_detail = {
                    "method": MatchMethod.ALBUM.value,
                    "score": 1.0,
                    "matched_title": rb_track.title,
                    "matched_artist": rb_track.artist,
                    "rb_track": rb_track,
                }

        # 4) 同一アーティスト内でタイトル類似度を見る（かなり閾値高め）
        if not owned and title_norm and artist_norm:
            candidates = lib.by_artist_norm.get(artist_norm, [])
            best_score = 0.0
            best_track = None
            for rb in candidates:
                score = _similar(title_norm, normalize_title_base(rb.title))
                if score > best_score:
                    best_score = score
                    best_track = rb

            if best_score >= 0.92 and best_track:
                owned = True
                owned_detail = {
                    "method": MatchMethod.FUZZY.value,
                    "score": best_score,
                    "matched_title": best_track.title,
                    "matched_artist": best_track.artist,
                    "rb_track": best_track,
                }
                fuzzy_count += 1

        t["owned"] = owned
        t["owned_detail"] = owned_detail
        # 後方互換性: owned_reason フィールドも設定
        t["owned_reason"] = owned_detail.get("method")

    match_ms = int((time.time() - t0_match) * 1000)
    track_total = len(playlist_data.get("tracks", []))
    print(f"[rekordbox] match tracks={track_total} fuzzy={fuzzy_count} match_ms={match_ms}ms")

    playlist_data.setdefault("meta", {})["rekordbox"] = {
        "track_total": track_total,
        "fuzzy_count": fuzzy_count,
        "match_ms": match_ms,
    }

    return playlist_data
