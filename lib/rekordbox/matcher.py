"""
プレイリストとREkordboxライブラリのマッチング。
判定の優先順: ISRC → 正規化タイトル+アーティスト → 正規化タイトル+アルバム → Fuzzy タイトル
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import time

from lib.rekordbox.models import (
    OwnedDetail,
    MatchMethod,
)
from lib.rekordbox.normalizer import (
    normalize_artist,
    normalize_title_base,
    normalize_album,
    generate_title_artist_pairs,
    title_version_signature,
)
from lib.rekordbox.parser import load_rekordbox_library_xml


def _similar(a: str, b: str) -> float:
    """0〜1の類似度（同一アーティスト内でのタイトル fuzzy 用）"""
    return SequenceMatcher(None, a, b).ratio()


def mark_owned_tracks(
    playlist_data: dict,
    rekordbox_xml_path: str | Path,
    *,
    content_hash: str | None = None,
) -> dict:
    """
    playlist_data: playlist_result_to_dict() の戻り（dict）
    RekordboxライブラリXMLと突き合わせて、各 track に owned: bool | None と owned_detail を付与して返す。

    判定の順番:
    1. ISRC 完全一致 → method = 'isrc'
    2. (title_norm, artist_norm) の組み合わせ一致 → method = 'exact'
       - Rekordbox側は "ARTIST - TITLE" パターンなどを含む複数候補を持つ
    3. (title_norm, album_norm) の組み合わせ一致 → 未確認、method = 'album'
       - 有名アーティストがカタカナ表記になっていても、タイトル＋アルバムで拾う
    4. 同一 artist_norm 内で title_norm 類似度 >= 0.92 → 未確認、method = 'fuzzy'

    Args:
        playlist_data: Playlist dict with 'tracks' key
        rekordbox_xml_path: Path to Rekordbox XML file

    Returns:
        Modified playlist_data with 'owned' and 'owned_detail' added to each track
    """
    t0_match = time.time()
    lib = load_rekordbox_library_xml(
        rekordbox_xml_path,
        content_hash=content_hash,
    )
    fuzzy_count = 0

    deadline = time.monotonic() + 20.0
    tracks = playlist_data.get("tracks", [])
    if len(tracks) > 10_000:
        raise ValueError("Playlist exceeds matching limit (10000 tracks)")
    for t in tracks:
        if time.monotonic() > deadline:
            raise TimeoutError("Library matching exceeded 20s budget")
        owned = False
        owned_detail: OwnedDetail = {}
        review_detail: OwnedDetail = {}

        def can_confirm(candidate):
            nonlocal review_detail
            requested_isrc = (t.get("isrc") or "").strip().upper()
            candidate_isrc = (candidate.isrc or "").strip().upper()
            reason = None
            if requested_isrc and candidate_isrc and requested_isrc != candidate_isrc:
                reason = "isrc_conflict"
            elif title_version_signature(t["title"]) != title_version_signature(
                candidate.title
            ):
                reason = "version_mismatch"
            if reason:
                review_detail = {
                    "method": reason,
                    "matched_title": candidate.title,
                    "matched_artist": candidate.artist,
                }
                return False
            return True

        title_norm = normalize_title_base(t["title"])
        artist_norm = normalize_artist(t["artist"])
        album_norm = normalize_album(t.get("album") or "")

        # 1) ISRC 完全一致
        isrc = t.get("isrc")
        if isrc:
            rb_track = lib.by_isrc.get(isrc.strip().upper())
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
            for key in generate_title_artist_pairs(t["title"], t["artist"]):
                matches = lib.by_title_artist.get(key, [])
                if not matches:
                    continue
                compatible = [
                    candidate for candidate in matches if can_confirm(candidate)
                ]
                if not compatible:
                    continue
                rb_track = compatible[0]
                owned = True
                owned_detail = {
                    "method": MatchMethod.EXACT.value,
                    "score": 1.0,
                    "matched_title": rb_track.title,
                    "matched_artist": rb_track.artist,
                    "rb_track": rb_track,
                }
                break

        # 3) タイトル＋アルバム（正規化）の組み合わせ一致
        #    → アーティスト名がカタカナ／別表記でも拾えるようにする
        if not owned and title_norm and album_norm:
            key2 = (title_norm, album_norm)
            matches = lib.by_title_album.get(key2, [])
            if matches:
                for rb_track in matches:
                    if can_confirm(rb_track):
                        review_detail = {
                            "method": MatchMethod.ALBUM.value,
                            "score": 1.0,
                            "matched_title": rb_track.title,
                            "matched_artist": rb_track.artist,
                        }
                        break

        # 4) 同一アーティスト内でタイトル類似度を見る（かなり閾値高め）
        if not owned and title_norm and artist_norm:
            candidates = lib.by_artist_norm.get(artist_norm, [])
            best_score = 0.0
            best_track = None
            for candidate_index, rb in enumerate(candidates):
                if candidate_index % 32 == 0 and time.monotonic() > deadline:
                    raise TimeoutError("Library matching exceeded 20s budget")
                score = _similar(title_norm, normalize_title_base(rb.title))
                if score >= 0.92 and not can_confirm(rb):
                    continue
                if score > best_score:
                    best_score = score
                    best_track = rb

            if best_score >= 0.92 and best_track:
                review_detail = {
                    "method": MatchMethod.FUZZY.value,
                    "score": best_score,
                    "matched_title": best_track.title,
                    "matched_artist": best_track.artist,
                    "rb_track": best_track,
                }
                fuzzy_count += 1

        if not owned and review_detail:
            owned = None
            owned_detail = review_detail
        t["owned"] = owned
        t["owned_detail"] = owned_detail
        # 後方互換性: owned_reason フィールドも設定
        t["owned_reason"] = owned_detail.get("method")

    match_ms = int((time.time() - t0_match) * 1000)
    track_total = len(playlist_data.get("tracks", []))
    print(
        f"[rekordbox] match tracks={track_total} fuzzy={fuzzy_count} match_ms={match_ms}ms"
    )

    playlist_data.setdefault("meta", {})["rekordbox"] = {
        "track_total": track_total,
        "fuzzy_count": fuzzy_count,
        "match_ms": match_ms,
    }

    return playlist_data
