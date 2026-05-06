import unittest
from pathlib import Path

from lib.rekordbox.matcher import mark_owned_tracks


def _write_xml(tmp_path: Path) -> Path:
    xml = """
<DJ_PLAYLISTS>
  <COLLECTION>
    <TRACK Name="Song A" Artist="Artist A" Album="Album A" ISRC="ISRC123" />
    <TRACK Name="Bright Lights" Artist="Artist B" Album="Album B" />
    <TRACK Name="Goodums_-_Sammy_Virji_Remix" Artist="Sammy Virji" Album="Album C" />
    <TRACK Name="Shapes_(Oh_Will)_-_Oppidan_Remix" Artist="Oppidan" Album="Album D" />
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

    def test_mark_owned_matches_titles_with_underscore_separators(self):
        tmp_dir = Path(self._get_tmp_dir())
        xml_path = _write_xml(tmp_dir)
        playlist = {
            "tracks": [
                {
                    "title": "Goodums - Sammy Virji Remix",
                    "artist": "Sammy Virji",
                    "album": "Album C",
                    "isrc": None,
                },
                {
                    "title": "Shapes (Oh Will) - Oppidan Remix",
                    "artist": "Oppidan",
                    "album": "Album D",
                    "isrc": None,
                },
            ]
        }

        result = mark_owned_tracks(playlist, xml_path)

        self.assertTrue(result["tracks"][0]["owned"])
        self.assertEqual(result["tracks"][0]["owned_reason"], "exact")
        self.assertTrue(result["tracks"][1]["owned"])
        self.assertEqual(result["tracks"][1]["owned_reason"], "exact")

    def _get_tmp_dir(self) -> str:
        # unittest doesn't provide tmp_path fixture; use mkdtemp
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
