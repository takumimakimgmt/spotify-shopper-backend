import unittest
from lib.rekordbox.normalizer import (
    normalize_artist,
    normalize_title_base,
    normalize_album,
    generate_title_artist_pairs,
)


class NormalizeTests(unittest.TestCase):
    def test_normalize_artist_strips_feat_and_delimiters(self):
        self.assertEqual(normalize_artist("Artist A feat. Guest, Another"), "artist a")
        self.assertEqual(normalize_artist("Artist A & B"), "artist a")

    def test_normalize_title_base_removes_parens_and_mix(self):
        self.assertEqual(normalize_title_base("My Song (Original Mix)"), "my song")
        self.assertEqual(normalize_title_base("Track [Deluxe] - Radio Edit"), "track")
        self.assertEqual(
            normalize_title_base("Goodums_-_Sammy_Virji_Remix"),
            "goodums",
        )
        self.assertEqual(
            normalize_title_base("Shapes_(Oh_Will)_-_Oppidan_Remix"),
            "shapes",
        )
        self.assertEqual(normalize_title_base("WHO 160-145"), "who")
        self.assertEqual(
            normalize_title_base("CORRUPT us - Posij & ZEP Remix 169.98"),
            "corrupt us",
        )
        self.assertEqual(
            normalize_title_base("Before Love - Extended"),
            "before love",
        )
        self.assertEqual(
            normalize_title_base("Takumi Maki Civic Master"),
            "takumi maki civic",
        )
        self.assertEqual(
            normalize_title_base("Somewhere Near Marseilles — マルセイユ辺りー"),
            "somewhere near marseilles - マルセイユ辺りー",
        )

    def test_generate_title_artist_pairs_derives_artist_when_artist_field_empty(self):
        pairs = generate_title_artist_pairs("Takumi Maki Civic Master", "")
        self.assertIn(("civic", "takumi maki"), pairs)

    def test_normalize_album_simplifies_spacing(self):
        self.assertEqual(normalize_album("Album Name (Deluxe Edition)"), "album name")
        self.assertEqual(normalize_album("Album  Name  [Special]"), "album name")


if __name__ == "__main__":
    unittest.main()
