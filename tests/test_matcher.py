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
    <TRACK Name="WHO 160-145" Artist="Port London" Album="WHO" />
    <TRACK Name="Takumi Maki Civic Master" Artist="" Album="" />
    <TRACK Name="CORRUPT us - Posij &amp; ZEP Remix 169.98" Artist="ZEP, Posij" Album="CORRUPT us (Posij &amp; ZEP Remix)" />
    <TRACK Name="Outer Space (JAMPAGNE Remix)" Artist="Habstrakt, Roderick Porter, JAMPAGNE" Album="Heritage - Remixes" />
    <TRACK Name="Before Love (Extended)" Artist="The Good Son" Album="Before Love" />
    <TRACK Name="Somewhere Near Marseilles (Sci-Fi Edit)" Artist="Hikaru Utada" Album="SCIENCE FICTION" />
    <TRACK Name="Thierry Henry (Modeā Extended Remix)" Artist="Ev, Modeā" Album="Thierry Henry (Modeā Extended Remix)" />
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

    def test_mark_owned_matches_known_false_negative_variants(self):
        tmp_dir = Path(self._get_tmp_dir())
        xml_path = _write_xml(tmp_dir)
        playlist = {
            "tracks": [
                {
                    "title": "WHO",
                    "artist": "Port London",
                    "album": "WHO",
                    "isrc": None,
                },
                {
                    "title": "Civic",
                    "artist": "Takumi Maki",
                    "album": "Civic",
                    "isrc": None,
                },
                {
                    "title": "CORRUPT us - Posij & ZEP Remix",
                    "artist": "ZEP, Posij",
                    "album": "CORRUPT us (Posij & ZEP Remix)",
                    "isrc": None,
                },
                {
                    "title": "Outer Space - JAMPAGNE Remix",
                    "artist": "Habstrakt, Roderick Porter, JAMPAGNE",
                    "album": "Heritage (Remixes)",
                    "isrc": None,
                },
                {
                    "title": "Before Love - Extended",
                    "artist": "The Good Son",
                    "album": "Before Love",
                    "isrc": None,
                },
                {
                    "title": "Somewhere Near Marseilles — マルセイユ辺りー",
                    "artist": "Hikaru Utada",
                    "album": "BADモード",
                    "isrc": None,
                },
                {
                    "title": "Thierry Henry - Modeā Remix",
                    "artist": "EV, Modeā",
                    "album": "Sunrise Behind The Tower Blocks",
                    "isrc": None,
                },
            ]
        }

        result = mark_owned_tracks(playlist, xml_path)

        expected_owned = {
            "WHO",
            "Civic",
            "CORRUPT us - Posij & ZEP Remix",
            "Outer Space - JAMPAGNE Remix",
            "Before Love - Extended",
            "Thierry Henry - Modeā Remix",
        }

        for track in result["tracks"]:
            if track["title"] == "Somewhere Near Marseilles — マルセイユ辺りー":
                self.assertFalse(
                    track["owned"],
                    msg="Localized Marseilles title should not match the Sci-Fi Edit",
                )
                self.assertIsNone(track["owned_reason"])
                continue

            self.assertIn(track["title"], expected_owned)
            self.assertTrue(
                track["owned"],
                msg=f"Expected owned match for {track['artist']} - {track['title']}",
            )
            self.assertIn(
                track["owned_reason"],
                {"exact", "album", "fuzzy"},
                msg=f"Unexpected ownership reason for {track['artist']} - {track['title']}",
            )

    def _get_tmp_dir(self) -> str:
        # unittest doesn't provide tmp_path fixture; use mkdtemp
        import tempfile

        return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
