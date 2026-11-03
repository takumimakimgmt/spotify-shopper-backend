import json
import os
from xml.sax.saxutils import quoteattr
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
import app as module
from lib.rekordbox.matcher import mark_owned_tracks


def match(
    tmp_path,
    requested,
    library,
    artist="Artist",
    library_artist="Artist",
    isrc=None,
    library_isrc=None,
):
    path = tmp_path / "library.xml"
    path.write_text(
        f'<DJ_PLAYLISTS><COLLECTION><TRACK Name={quoteattr(library)} Artist={quoteattr(library_artist)} Album="Album" ISRC={quoteattr(library_isrc or "")}/></COLLECTION></DJ_PLAYLISTS>'
    )
    return mark_owned_tracks(
        {
            "tracks": [
                {"title": requested, "artist": artist, "album": "Album", "isrc": isrc}
            ]
        },
        path,
    )["tracks"][0]


@pytest.mark.parametrize(
    "requested,library",
    [
        ("Song - Alice Remix", "Song - Bob Remix"),
        ("Song", "Song (Alice Remix)"),
        ("Song - Extended", "Song - Radio Edit"),
        ("Song - Extended", "Song"),
        ("Song - VIP", "Song - Dub Mix"),
        ("Song (Live)", "Song"),
        ("Song (Part I)", "Song (Part II)"),
        ("Song (Clean Version)", "Song (Explicit Version)"),
    ],
)
def test_versions_are_not_confirmed_as_owned(tmp_path, requested, library):
    track = match(tmp_path, requested, library)
    assert track["owned"] is None
    assert track["owned_reason"] == "version_mismatch"


@pytest.mark.parametrize(
    "requested,library",
    [
        ("Song - Alice Remix", "Song_(Alice_Remix)"),
        ("Song", "Song (Original Mix)"),
        ("Song - Extended", "Song (Extended Mix)"),
    ],
)
def test_equivalent_version_formatting_still_matches(tmp_path, requested, library):
    assert match(tmp_path, requested, library)["owned"] is True


def test_conflicting_isrc_requires_review_even_when_title_matches(tmp_path):
    track = match(tmp_path, "Song", "Song", isrc="AAA", library_isrc="BBB")
    assert track["owned"] is None
    assert track["owned_reason"] == "isrc_conflict"


def test_same_album_and_title_with_different_artist_requires_review(tmp_path):
    track = match(tmp_path, "Song", "Song", artist="Different Artist")
    assert track["owned"] is None
    assert track["owned_reason"] == "album"


def test_snapshot_preserves_each_version_even_with_colliding_keys(tmp_path):
    snapshot = {
        "schema": "playlist_snapshot",
        "version": 1,
        "tracks": [
            {
                "title": "Song - Alice Remix",
                "artist": "Artist",
                "track_key_primary": "same",
            },
            {
                "title": "Song - Bob Remix",
                "artist": "Artist",
                "track_key_primary": "same",
            },
        ],
    }
    xml = b'<DJ_PLAYLISTS><COLLECTION><TRACK Name="Song (Alice Remix)" Artist="Artist"/></COLLECTION></DJ_PLAYLISTS>'
    with patch.dict(
        os.environ,
        {
            "APP_ENV": "test",
            "BACKEND_PROXY_TOKEN": "",
            "BACKEND_RATE_LIMIT_PER_MINUTE": "10000",
        },
    ):
        response = TestClient(module.app).post(
            "/api/match-snapshot-with-xml",
            data={"snapshot": json.dumps(snapshot)},
            files={"file": ("library.xml", xml, "text/xml")},
        )
    assert response.status_code == 200
    assert [t["owned"] for t in response.json()["tracks"]] == [True, None]
