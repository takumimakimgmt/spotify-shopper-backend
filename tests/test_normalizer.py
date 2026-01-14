import unittest
from lib.rekordbox.normalizer import (
    normalize_artist,
    normalize_title_base,
    normalize_album,
)


class NormalizeTests(unittest.TestCase):
    def test_normalize_artist_strips_feat_and_delimiters(self):
        self.assertEqual(normalize_artist("Artist A feat. Guest, Another"), "artist a")
        self.assertEqual(normalize_artist("Artist A & B"), "artist a")

    def test_normalize_title_base_removes_parens_and_mix(self):
        self.assertEqual(normalize_title_base("My Song (Original Mix)"), "my song")
        self.assertEqual(normalize_title_base("Track [Deluxe] - Radio Edit"), "track")

    def test_normalize_album_simplifies_spacing(self):
        self.assertEqual(normalize_album("Album Name (Deluxe Edition)"), "album name")
        self.assertEqual(normalize_album("Album  Name  [Special]"), "album name")


if __name__ == "__main__":
    unittest.main()
