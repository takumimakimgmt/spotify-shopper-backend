"""Regression cases for public API trust boundaries; no outbound requests."""

import json
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as module


class AuditSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "APP_ENV": "test",
                "BACKEND_PROXY_TOKEN": "",
                "BACKEND_RATE_LIMIT_PER_MINUTE": "10000",
                "TRUST_PROXY_HEADERS": "false",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(module.app)

    def test_non_spotify_targets_never_reach_fetch(self):
        targets = [
            ("apple", "http://127.0.0.1/private"),
            ("APPLE", "http://169.254.169.254/latest/meta-data/"),
            (
                "spotify",
                "https://open.spotify.com.evil.test/playlist/0jKqvXbsroCPdccFmORnPz",
            ),
            (
                "spotify",
                "https://open.spotify.com@evil.test/playlist/0jKqvXbsroCPdccFmORnPz",
            ),
            ("spotify", "file:///etc/passwd"),
        ]
        with patch.object(module, "fetch_playlist_tracks_generic") as fetch:
            for source, url in targets:
                with self.subTest(source=source, url=url):
                    response = self.client.post(
                        "/api/playlist-with-rekordbox-upload",
                        data={"source": source, "url": url},
                    )
                    self.assertEqual(response.status_code, 400)
                    response = self.client.get(
                        "/api/playlist", params={"source": source, "url": url}
                    )
                    self.assertEqual(response.status_code, 400)
            fetch.assert_not_called()

    def test_malformed_host_cannot_bypass_backend_auth(self):
        with patch.dict(os.environ, {"BACKEND_PROXY_TOKEN": "test-token"}):
            for host in [
                "testserver/?ignore=",
                "testserver#fragment",
                "testserver/api/health?ignore=",
            ]:
                response = self.client.post(
                    "/api/match-snapshot-with-xml", headers={"host": host}
                )
                self.assertEqual(response.status_code, 401)

    def test_production_without_token_is_closed_and_health_is_available(self):
        with patch.dict(
            os.environ, {"APP_ENV": "production", "BACKEND_PROXY_TOKEN": ""}
        ):
            self.assertEqual(self.client.get("/api/playlist").status_code, 503)
            self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_malformed_snapshots_rejected_before_temp_file_creation(self):
        cases = [
            {"playlist": None, "tracks": []},
            {"tracks": [None]},
            {"tracks": [{"title": "x", "artist": "y", "links": None}]},
            {"tracks": [{"title": [], "artist": "y"}]},
            {"tracks": [{"title": "x" * 2049, "artist": "y"}]},
        ]
        with patch.object(module, "_save_xml_upload") as save:
            for case in cases:
                response = self.client.post(
                    "/api/match-snapshot-with-xml",
                    data={
                        "snapshot": json.dumps(
                            {"schema": "playlist_snapshot", "version": 1, **case}
                        )
                    },
                    files={
                        "file": (
                            "x.xml",
                            b"<DJ_PLAYLISTS><COLLECTION/></DJ_PLAYLISTS>",
                            "text/xml",
                        )
                    },
                )
                self.assertEqual(response.status_code, 400)
            save.assert_not_called()

    def test_playlist_identity_canonicalizes_tracking_parameters(self):
        expected = "https://open.spotify.com/playlist/0jKqvXbsroCPdccFmORnPz"
        for raw in [
            expected + "?si=tracking",
            "0jKqvXbsroCPdccFmORnPz",
            "spotify:playlist:0jKqvXbsroCPdccFmORnPz",
        ]:
            self.assertEqual(module._validate_playlist_input(raw, "spotify"), expected)
