import unittest

from fastapi import HTTPException

from app import _validate_playlist_url_or_id


class UrlAllowlistTests(unittest.TestCase):
    def test_allows_https_spotify(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        self.assertEqual(_validate_playlist_url_or_id(url), url)

    def test_rejects_private_ip(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_playlist_url_or_id("https://127.0.0.1/playlist/abc")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Unsupported URL host", str(ctx.exception.detail))

    def test_rejects_http_scheme(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_playlist_url_or_id("http://open.spotify.com/playlist/abc")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("https", str(ctx.exception.detail))

    def test_allows_raw_id_for_backwards_compat(self):
        raw = "37i9dQZF1DXcBWIGoYBM5M"
        self.assertEqual(_validate_playlist_url_or_id(raw), raw)


if __name__ == "__main__":
    unittest.main()
