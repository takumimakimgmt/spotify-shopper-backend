import tempfile
import unittest
from pathlib import Path

from lib.rekordbox.parser import load_rekordbox_library_xml


class RekordboxParserTests(unittest.TestCase):
    def test_loads_simple_xml(self):
        xml = """
<DJ_PLAYLISTS>
  <COLLECTION>
    <TRACK Name="Song A" Artist="Artist A" Album="Album A" ISRC="ISRC999" />
  </COLLECTION>
</DJ_PLAYLISTS>
""".strip()

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "library.xml"
            path.write_text(xml)

            library = load_rekordbox_library_xml(path)

        self.assertIn("ISRC999", library.by_isrc)
        self.assertEqual(library.by_isrc["ISRC999"].title, "Song A")


if __name__ == "__main__":
    unittest.main()
