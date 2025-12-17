import unittest
from pathlib import Path

from lib.rekordbox.matcher import mark_owned_tracks


def _write_xml(tmp_path: Path) -> Path:
    xml = """
<DJ_PLAYLISTS>
  <COLLECTION>
    <TRACK Name="Song A" Artist="Artist A" Album="Album A" ISRC="ISRC123" />
    <TRACK Name="Bright Lights" Artist="Artist B" Album="Album B" />
  </COLLECTION>
</DJ_PLAYLISTS>
"""
    path = tmp_path / "library.xml"
    path.write_text(xml.strip())
    return path


class MatcherTests(unittest.TestCase):
    def test_mark_owned_priority_isrc_over_others(self):
        tmp_dir = Path(self._get_tmp_dir())
        xml_path = _write_xml(tmp_dir)
        playlist = {
            "tracks": [
                {
                    "title": "Song A (Remix)",
                    "artist": "Artist A",
                    "album": "Album A (Deluxe)",
                    "isrc": "isrc123",
                }
            ]
        }

        result = mark_owned_tracks(playlist, xml_path)
        track = result["tracks"][0]
        self.assertTrue(track["owned"])
        self.assertEqual(track["owned_reason"], "isrc")

    def test_mark_owned_prefers_fuzzy_when_no_exact(self):
        tmp_dir = Path(self._get_tmp_dir())
        xml_path = _write_xml(tmp_dir)
        playlist = {
            "tracks": [
                {
                    "title": "Bright Light",  # missing trailing 's'
                    "artist": "Artist B",
                    "album": "Album B",
                    "isrc": None,
                }
            ]
        }

        result = mark_owned_tracks(playlist, xml_path)
        track = result["tracks"][0]
        self.assertTrue(track["owned"])
        self.assertEqual(track["owned_reason"], "fuzzy")

    def _get_tmp_dir(self) -> str:
        # unittest doesn't provide tmp_path fixture; use mkdtemp
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
