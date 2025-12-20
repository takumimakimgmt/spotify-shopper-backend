"""
Rekordbox ライブラリのデータモデル。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple, TypedDict


class MatchMethod(str, Enum):
    """
    マッチング方法の列挙型。
    優先順位: ISRC > EXACT > ALBUM > FUZZY
    """
    ISRC = "isrc"       # ISRC 完全一致
    EXACT = "exact"     # タイトル + アーティスト（正規化）完全一致
    ALBUM = "album"     # タイトル + アルバム（正規化）完全一致
    FUZZY = "fuzzy"     # 同一アーティスト内でのタイトル類似度 >= 0.92


class OwnedDetail(TypedDict, total=False):
    """
    トラックが所有されている理由の詳細情報。
    
    Fields:
        method: マッチング方法 (MatchMethod 文字列)
        score: 類似度スコア（fuzzyの場合）（0-1）
        matched_title: マッチした Rekordbox 内のタイトル
        matched_artist: マッチした Rekordbox 内のアーティスト
        rb_track: マッチした RekordboxTrack 全体
    """
    method: str
    score: float | None
    matched_title: str | None
    matched_artist: str | None
    rb_track: RekordboxTrack | None


@dataclass
class RekordboxTrack:
    """Rekordbox コレクション内の単一トラック。"""
    title: str
    artist: str
    album: str
    isrc: str | None

    # 正規化済みフィールド（マッチングに使用）
    title_norm: str
    artist_norm: str
    album_norm: str


@dataclass
class RekordboxLibrary:
    """Rekordbox コレクションのインデックス集合。"""
    by_isrc: Dict[str, RekordboxTrack]
    by_title_artist: Dict[Tuple[str, str], List[RekordboxTrack]]
    by_artist_norm: Dict[str, List[RekordboxTrack]]
    by_title_album: Dict[Tuple[str, str], List[RekordboxTrack]]


