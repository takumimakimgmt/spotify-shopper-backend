"""Playlist access follows provider responses, not an ID prefix guess."""

from unittest.mock import Mock, patch

import pytest
from spotipy.exceptions import SpotifyException

import core
from lib.spotify_errors import spotify_error_details

PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"


def test_editorial_prefix_is_sent_to_provider():
    client = Mock()
    client.playlist.return_value = {
        "id": PLAYLIST_ID,
        "name": "Example",
        "owner": {"id": "spotify"},
    }
    client.playlist_tracks.return_value = {"items": [], "next": None, "total": 0}
    with patch.object(core, "get_spotify_client", return_value=client):
        result = core.fetch_playlist_tracks(PLAYLIST_ID)
    client.playlist.assert_called_once()
    assert result["playlist"]["id"] == PLAYLIST_ID


def test_provider_access_failure_remains_classifiable():
    client = Mock()
    client.playlist.side_effect = SpotifyException(
        403, -1, "private provider diagnostic"
    )
    with (
        patch.object(core, "get_spotify_client", return_value=client),
        pytest.raises(RuntimeError) as failure,
    ):
        core.fetch_playlist_tracks(PLAYLIST_ID)
    assert spotify_error_details(failure.value) == (
        403,
        "SPOTIFY_ACCESS_RESTRICTED",
        {},
    )


def test_exhausted_markets_preserve_provider_error():
    client = Mock()
    client.playlist.return_value = {"id": PLAYLIST_ID, "owner": {"id": "spotify"}}
    client.playlist_tracks.side_effect = SpotifyException(
        404, -1, "private provider diagnostic"
    )
    with (
        patch.object(core, "get_spotify_client", return_value=client),
        pytest.raises(RuntimeError) as failure,
    ):
        core.fetch_playlist_tracks(PLAYLIST_ID)
    assert spotify_error_details(failure.value) == (
        404,
        "SPOTIFY_PLAYLIST_UNAVAILABLE",
        {},
    )
