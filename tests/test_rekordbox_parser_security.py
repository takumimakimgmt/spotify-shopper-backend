import os
import tempfile
import unittest
from pathlib import Path

from defusedxml.common import EntitiesForbidden

from lib.rekordbox.parser import _get_file_hash, load_rekordbox_library_xml


VALID_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS>
  <COLLECTION Entries="1">
    <TRACK Name="Track" Artist="Artist" Album="Album" ISRC="JP0000000001" />
  </COLLECTION>
</DJ_PLAYLISTS>
"""


class RekordboxParserSecurityTests(unittest.TestCase):
    def test_content_hash_does_not_change_with_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.xml"
            path.write_text(VALID_XML, encoding="utf-8")
            first = _get_file_hash(path)
            os.utime(path, (1, 1))
            second = _get_file_hash(path)

        self.assertEqual(first, second)

    def test_entity_expansion_is_rejected(self):
        xml = """<!DOCTYPE lolz [<!ENTITY x "expanded">]>
<DJ_PLAYLISTS><COLLECTION><TRACK Name="&x;" Artist="A" /></COLLECTION></DJ_PLAYLISTS>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entity.xml"
            path.write_text(xml, encoding="utf-8")
            with self.assertRaises(EntitiesForbidden):
                load_rekordbox_library_xml(path)

    def test_excessive_depth_and_metadata_are_rejected(self):
        documents = [
            "<DJ_PLAYLISTS>" + "<N>" * 65 + "</N>" * 65 + "</DJ_PLAYLISTS>",
            '<DJ_PLAYLISTS><COLLECTION><TRACK Name="'
            + "x" * 2049
            + '" Artist="A" /></COLLECTION></DJ_PLAYLISTS>',
        ]
        for xml in documents:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "library.xml"
                path.write_text(xml, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_rekordbox_library_xml(path)

    def test_external_file_entities_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "private.txt"
            secret.write_text("private sentinel", encoding="utf-8")
            path = Path(directory) / "library.xml"
            path.write_text(
                f'<!DOCTYPE x [<!ENTITY secret SYSTEM "{secret.as_uri()}">]><DJ_PLAYLISTS><COLLECTION><TRACK Name="&secret;" Artist="A" /></COLLECTION></DJ_PLAYLISTS>',
                encoding="utf-8",
            )
            with self.assertRaises(EntitiesForbidden):
                load_rekordbox_library_xml(path)

    def test_timeout_is_checked_during_track_iteration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.xml"
            path.write_text(VALID_XML, encoding="utf-8")
            with self.assertRaises(TimeoutError):
                load_rekordbox_library_xml(path, timeout_sec=0)


if __name__ == "__main__":
    unittest.main()
