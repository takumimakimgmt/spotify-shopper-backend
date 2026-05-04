import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module


client = TestClient(app_module.app)


async def _fake_fetch_playlist_tracks_generic(source, url, **kwargs):
    return {"source": source, "url": url}


def _fake_playlist_result_to_dict(_result):
    return {
        "playlist_id": "playlist-1",
        "playlist_name": "Test Playlist",
        "playlist_url": "https://example.com/playlist/1",
        "tracks": [
            {
                "title": "Track A",
                "artist": "Artist A",
                "album": "Album A",
                "isrc": "ISRC123",
            },
            {
                "title": "Track B",
                "artist": "Artist B",
                "album": "Album B",
                "isrc": None,
            },
        ],
    }


def _fake_apply_rekordbox_owned_flags(playlist_data, _library_xml_path):
    playlist_data["tracks"][0]["owned"] = True
    playlist_data["tracks"][0]["owned_reason"] = "isrc"
    playlist_data["tracks"][1]["owned"] = False
    playlist_data["tracks"][1]["owned_reason"] = None
    return playlist_data


class UploadContractTests(unittest.TestCase):
    @patch.object(
        app_module,
        "_apply_rekordbox_owned_flags",
        side_effect=_fake_apply_rekordbox_owned_flags,
    )
    @patch.object(
        app_module,
        "playlist_result_to_dict",
        side_effect=_fake_playlist_result_to_dict,
    )
    @patch.object(
        app_module,
        "fetch_playlist_tracks_generic",
        side_effect=_fake_fetch_playlist_tracks_generic,
    )
    def test_playlist_with_rekordbox_upload_uses_json_boolean_and_null_types(
        self,
        _mock_fetch,
        _mock_playlist_to_dict,
        _mock_apply_flags,
    ):
        response = client.post(
            "/api/playlist-with-rekordbox-upload",
            data={"url": "https://open.spotify.com/playlist/abc", "source": "spotify"},
            files={"file": ("library.xml", b"<DJ_PLAYLISTS />", "text/xml")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIs(payload["tracks"][0]["owned"], True)
        self.assertEqual(payload["tracks"][0]["owned_reason"], "isrc")
        self.assertIs(payload["tracks"][1]["owned"], False)
        self.assertIsNone(payload["tracks"][1]["owned_reason"])


if __name__ == "__main__":
    unittest.main()
