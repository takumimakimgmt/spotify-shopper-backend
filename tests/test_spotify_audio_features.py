import unittest
from unittest.mock import Mock

from core import (
    _enrich_items_with_audio_features,
    format_spotify_key,
    playlist_result_to_dict,
)


class SpotifyAudioFeaturesTests(unittest.TestCase):
    def test_format_spotify_key_major_and_minor(self):
        self.assertEqual(format_spotify_key(0, 1), "C")
        self.assertEqual(format_spotify_key(0, 0), "Cm")
        self.assertEqual(format_spotify_key(1, 1), "C#/Db")
        self.assertEqual(format_spotify_key(1, 0), "C#m/Dbm")

    def test_format_spotify_key_invalid_returns_none(self):
        self.assertIsNone(format_spotify_key(-1, 1))
        self.assertIsNone(format_spotify_key(0, None))
        self.assertIsNone(format_spotify_key(None, 1))
        self.assertIsNone(format_spotify_key(12, 1))
        self.assertIsNone(format_spotify_key(5, 3))

    def test_playlist_result_to_dict_emits_audio_feature_fields(self):
        raw = {
            "playlist": {
                "id": "playlist-1",
                "name": "Test Playlist",
                "external_urls": {
                    "spotify": "https://open.spotify.com/playlist/playlist-1"
                },
            },
            "items": [
                {
                    "track": {
                        "id": "track-1",
                        "name": "Track A",
                        "artists": [{"name": "Artist A"}],
                        "album": {"name": "Album A"},
                        "external_urls": {
                            "spotify": "https://open.spotify.com/track/track-1"
                        },
                        "external_ids": {"isrc": "ISRC123"},
                        "audio_features": {
                            "id": "track-1",
                            "tempo": 127.6,
                            "key": 1,
                            "mode": 0,
                        },
                    }
                },
                {
                    "track": {
                        "id": "track-2",
                        "name": "Track B",
                        "artists": [{"name": "Artist B"}],
                        "album": {"name": "Album B"},
                        "external_urls": {
                            "spotify": "https://open.spotify.com/track/track-2"
                        },
                        "external_ids": {},
                    }
                },
            ],
        }

        result = playlist_result_to_dict(raw)

        self.assertEqual(result["tracks"][0]["tempo"], 127.6)
        self.assertEqual(result["tracks"][0]["bpm"], 128)
        self.assertEqual(result["tracks"][0]["spotifyKey"], 1)
        self.assertEqual(result["tracks"][0]["spotifyMode"], 0)
        self.assertEqual(result["tracks"][0]["key"], "C#m/Dbm")

        self.assertIsNone(result["tracks"][1]["tempo"])
        self.assertIsNone(result["tracks"][1]["bpm"])
        self.assertIsNone(result["tracks"][1]["spotifyKey"])
        self.assertIsNone(result["tracks"][1]["spotifyMode"])
        self.assertIsNone(result["tracks"][1]["key"])

    def test_enrich_items_with_audio_features_is_best_effort(self):
        sp = Mock()
        sp.audio_features.side_effect = RuntimeError("spotify down")
        items = [
            {"track": {"id": "track-1", "name": "Track A"}},
            {"track": {"id": "track-2", "name": "Track B"}},
        ]

        _enrich_items_with_audio_features(sp, items)

        self.assertNotIn("audio_features", items[0]["track"])
        self.assertNotIn("audio_features", items[1]["track"])

    def test_enrich_items_with_audio_features_maps_batches_back_to_tracks(self):
        sp = Mock()
        sp.audio_features.return_value = [
            {"id": "track-1", "tempo": 128.2, "key": 0, "mode": 1},
            None,
        ]
        items = [
            {"track": {"id": "track-1", "name": "Track A"}},
            {"track": {"id": "track-2", "name": "Track B"}},
        ]

        _enrich_items_with_audio_features(sp, items)

        sp.audio_features.assert_called_once_with(["track-1", "track-2"])
        self.assertEqual(items[0]["track"]["audio_features"]["tempo"], 128.2)
        self.assertNotIn("audio_features", items[1]["track"])


if __name__ == "__main__":
    unittest.main()
