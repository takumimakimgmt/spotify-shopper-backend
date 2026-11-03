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
    assert track["owned_reason"] == "artist_mismatch"


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


@pytest.mark.parametrize(
    "requested,library",
    [
        ("Song (Intro)", "Song (Outro)"),
        ("Song (Instrumental Intro)", "Song"),
        ("Song (Chapter A)", "Song (Chapter B)"),
    ],
)
def test_meaningful_parentheses_are_not_discarded(tmp_path, requested, library):
    track = match(tmp_path, requested, library)
    assert track["owned"] is None


def test_different_collaborators_are_not_confirmed(tmp_path):
    track = match(tmp_path, "Song", "Song", artist="A & B", library_artist="A & C")
    assert track["owned"] is None
    assert track["owned_reason"] == "artist_mismatch"


def test_reordered_artist_credits_still_match(tmp_path):
    assert (
        match(tmp_path, "Song", "Song", artist="A, B", library_artist="B & A")["owned"]
        is True
    )


def test_reported_counts_include_unavailable_and_local_entries():
    from core import playlist_result_to_dict

    result = playlist_result_to_dict(
        {
            "playlist": {"id": "p"},
            "items": [
                {"track": None},
                {"track": {"is_local": True}},
                {
                    "track": {
                        "name": "Song",
                        "artists": [{"name": "Artist"}],
                        "album": {},
                    }
                },
            ],
        }
    )
    assert result["meta"]["source_track_count"] == 3
    assert result["meta"]["analyzed_track_count"] == 1
    assert result["meta"]["skipped_track_count"] == 2


def test_upload_ceiling_cannot_be_raised_by_legacy_environment():
    from lib.rekordbox.parser import _max_xml_size_bytes

    with patch.dict(os.environ, {"REKORDBOX_MAX_XML_MB": "50"}):
        assert _max_xml_size_bytes() == 3 * 1024 * 1024
    assert module.MAX_UPLOAD_SIZE <= 3 * 1024 * 1024


def test_oversize_xml_is_rejected_before_fetching():
    with (
        patch.dict(
            os.environ,
            {
                "APP_ENV": "test",
                "BACKEND_PROXY_TOKEN": "",
                "BACKEND_RATE_LIMIT_PER_MINUTE": "10000",
            },
        ),
        patch.object(module, "fetch_playlist_tracks_generic") as fetch,
    ):
        response = TestClient(module.app).post(
            "/api/playlist-with-rekordbox-upload",
            data={"url": "0jKqvXbsroCPdccFmORnPz"},
            files={"file": ("large.xml", b"x" * (3 * 1024 * 1024 + 1), "text/xml")},
        )
    assert response.status_code == 413
    fetch.assert_not_called()


def test_slow_spotify_metadata_does_not_start_more_requests():
    from core import fetch_playlist_tracks

    clock = [0.0]

    class Client:
        calls = 0

        def playlist(self, *_args, **_kwargs):
            clock[0] = 21.0
            return {"id": "p", "name": "P"}

        def playlist_tracks(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("Must not continue fetching after deadline")

    client = Client()
    with (
        patch("core.get_spotify_client", return_value=client),
        patch("core.time.monotonic", side_effect=lambda: clock[0]),
    ):
        with pytest.raises(TimeoutError):
            fetch_playlist_tracks("0jKqvXbsroCPdccFmORnPz")
    assert client.calls == 0
