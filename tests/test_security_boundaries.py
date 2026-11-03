import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import app as app_module
from lib.http_middleware import RequestSizeLimitMiddleware


client = TestClient(app_module.app)


class SecurityBoundaryTests(unittest.TestCase):
    def test_backend_proxy_token_rejects_direct_requests(self):
        with patch.dict(os.environ, {"BACKEND_PROXY_TOKEN": "test-token"}):
            response = client.post("/api/match-snapshot-with-xml")
            self.assertEqual(response.status_code, 401)

            authorized = client.post(
                "/api/match-snapshot-with-xml",
                headers={"x-backend-token": "test-token"},
            )
            self.assertEqual(authorized.status_code, 422)

    def test_backend_rate_limit_applies_before_endpoint_work(self):
        env = {
            "BACKEND_PROXY_TOKEN": "rate-test-token",
            "BACKEND_RATE_LIMIT_PER_MINUTE": "1",
            "TRUST_PROXY_HEADERS": "true",
        }
        headers = {"x-real-ip": "203.0.113.77", "x-backend-token": "rate-test-token"}
        with patch.dict(os.environ, env):
            first = client.post("/api/match-snapshot-with-xml", headers=headers)
            second = client.post("/api/match-snapshot-with-xml", headers=headers)

        self.assertEqual(first.status_code, 422)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)

    def test_local_path_api_is_hidden_in_production(self):
        with tempfile.TemporaryDirectory() as directory:
            xml_path = Path(directory) / "library.xml"
            xml_path.write_text("<DJ_PLAYLISTS />", encoding="utf-8")
            env = {
                "ENABLE_LOCAL_PATH_API": "true",
                "REKORDBOX_LOCAL_ROOT": directory,
                "BACKEND_PROXY_TOKEN": "",
            }
            with (
                patch.object(app_module, "_APP_ENV", "production"),
                patch.dict(os.environ, env),
            ):
                response = client.post(
                    "/api/playlist-with-rekordbox",
                    json={
                        "url": "spotify:playlist:588N4Kt4446o660ARpswUD",
                        "rekordbox_xml_path": str(xml_path),
                    },
                    headers={"x-real-ip": "203.0.113.78"},
                )

        self.assertEqual(response.status_code, 404)

    def test_upload_limit_is_checked_before_spotify_fetch(self):
        with (
            patch.object(app_module, "MAX_UPLOAD_SIZE", 8),
            patch.object(app_module, "fetch_playlist_tracks_generic") as fetch_mock,
        ):
            response = client.post(
                "/api/playlist-with-rekordbox-upload",
                data={"url": "spotify:playlist:588N4Kt4446o660ARpswUD"},
                files={"file": ("library.xml", b"<DJ_PLAYLISTS />", "text/xml")},
                headers={"x-real-ip": "203.0.113.79"},
            )

        self.assertEqual(response.status_code, 413)
        fetch_mock.assert_not_called()

    def test_stream_limit_rejects_chunked_body(self):
        small_app = FastAPI()
        small_app.add_middleware(RequestSizeLimitMiddleware, max_bytes=5)

        @small_app.post("/upload")
        async def upload(request: Request):
            return {"size": len(await request.body())}

        def chunks():
            yield b"1234"
            yield b"5678"

        response = TestClient(small_app).post("/upload", content=chunks())
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
