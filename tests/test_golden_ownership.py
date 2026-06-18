import json
import unittest
from pathlib import Path

from lib.rekordbox.matcher import mark_owned_tracks


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rekordbox"


class GoldenOwnershipTests(unittest.TestCase):
    def test_golden_rekordbox_ownership(self):
        with (FIXTURE_DIR / "golden_playlist.json").open(encoding="utf-8") as file:
            playlist = json.load(file)
        with (FIXTURE_DIR / "golden_expected.json").open(encoding="utf-8") as file:
            expected = json.load(file)

        result = mark_owned_tracks(
            playlist,
            FIXTURE_DIR / "golden_library.xml",
        )
        compact_result = [
            {
                "title": track["title"],
                "artist": track["artist"],
                "owned": track["owned"],
                "owned_reason": track.get("owned_reason"),
            }
            for track in result["tracks"]
        ]

        self.assertEqual(compact_result, expected)

        marseilles = next(
            track
            for track in compact_result
            if track["title"] == "Somewhere Near Marseilles — マルセイユ辺りー"
        )
        self.assertFalse(marseilles["owned"])
        self.assertIsNone(marseilles.get("owned_reason"))


if __name__ == "__main__":
    unittest.main()
