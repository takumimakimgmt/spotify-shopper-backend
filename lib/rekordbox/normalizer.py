"""
正規化ヘルパー: タイトル/アーティスト/アルバム名のゆらぎを減らす。
"""
from __future__ import annotations

import re
from typing import List, Tuple


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
