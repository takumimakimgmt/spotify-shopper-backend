import unittest

from fastapi.testclient import TestClient

import app as app_module


client = TestClient(app_module.app)


class HealthRouteTests(unittest.TestCase):
    def test_render_health_route_returns_ok(self):
        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["status"], "ok")

    def test_render_health_head_route_returns_ok(self):
        response = client.head("/health")

        self.assertEqual(response.status_code, 200)

    def test_api_health_route_still_returns_ok(self):
        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_root_route_still_returns_ok(self):
        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
