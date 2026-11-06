import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from spotipy.exceptions import SpotifyException
from lib.environment import load_local_environment
from lib.spotify_errors import spotify_error_details, SpotifyConfigurationError


class ConfigurationTests(unittest.TestCase):
    def test_production_ignores_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / ".env.local").write_text(
                "SPOTIFY_CLIENT_ID=local\nUNWANTED_LOCAL_VALUE=yes"  # pragma: allowlist secret -- synthetic dotenv fixture
            )
            with patch.dict(
                os.environ,
                {"APP_ENV": "production", "SPOTIFY_CLIENT_ID": "platform"},
                clear=True,
            ):
                load_local_environment(path)
                self.assertEqual(os.environ["SPOTIFY_CLIENT_ID"], "platform")
                self.assertNotIn("UNWANTED_LOCAL_VALUE", os.environ)

    def test_local_defaults_do_not_override_process_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / ".env").write_text("SPOTIFY_CLIENT_ID=base\nTEST_SETTING=base")
            (path / ".env.local").write_text(
                "SPOTIFY_CLIENT_ID=local\nTEST_SETTING=local"
            )
            with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "platform"}, clear=True):
                load_local_environment(path)
                self.assertEqual(os.environ["SPOTIFY_CLIENT_ID"], "platform")
                self.assertEqual(os.environ["TEST_SETTING"], "local")

    def test_wrapped_provider_errors_are_classified_without_disclosing_messages(self):
        for status, code in [
            (401, "SPOTIFY_AUTH_CONFIG"),
            (400, "SPOTIFY_PLAYLIST_RESTRICTED"),
            (403, "SPOTIFY_ACCESS_RESTRICTED"),
            (404, "SPOTIFY_PLAYLIST_UNAVAILABLE"),
            (429, "SPOTIFY_RATE_LIMITED"),
            (500, "SPOTIFY_UNAVAILABLE"),
        ]:
            try:
                try:
                    raise SpotifyException(
                        status,
                        -1,
                        "private provider detail",
                        headers={"Retry-After": "120"},
                    )
                except SpotifyException:
                    raise RuntimeError("wrapper")
            except RuntimeError as error:
                result = spotify_error_details(error)
                self.assertEqual(result[1], code)
                self.assertNotIn("private provider detail", str(result))
                if status == 429:
                    self.assertEqual(result[2]["Retry-After"], "120")
        self.assertEqual(
            spotify_error_details(SpotifyConfigurationError())[1], "SPOTIFY_AUTH_CONFIG"
        )
        self.assertIsNone(spotify_error_details(ValueError("other")))

    def test_api_preserves_spotify_status_without_provider_details(self):
        import app as app_module
        from fastapi.testclient import TestClient
        from unittest.mock import AsyncMock

        for status, expected in [
            (400, "SPOTIFY_PLAYLIST_RESTRICTED"),
            (403, "SPOTIFY_ACCESS_RESTRICTED"),
            (429, "SPOTIFY_RATE_LIMITED"),
        ]:
            error = RuntimeError("private diagnostic")
            error.__cause__ = SpotifyException(
                status, -1, "private diagnostic", headers={"Retry-After": "120"}
            )
            with (
                patch.dict(os.environ, {"BACKEND_PROXY_TOKEN": ""}),
                patch.object(
                    app_module,
                    "fetch_playlist_tracks_generic",
                    new=AsyncMock(side_effect=error),
                ),
            ):
                response = TestClient(app_module.app).get(
                    "/api/playlist",
                    params={
                        "url": "https://open.spotify.com/playlist/1111111111111111111111",
                        "refresh": "true",
                    },
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["detail"], {"code": expected})
                self.assertNotIn("private diagnostic", response.text)
                if status == 429:
                    self.assertEqual(response.headers["retry-after"], "120")
