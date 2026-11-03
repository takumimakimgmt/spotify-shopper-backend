import asyncio
import copy
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from lib.http_middleware import WorkloadLimitMiddleware
from lib.rekordbox.matcher import mark_owned_tracks
from lib.cache_manager import get_rekordbox_cache


@pytest.mark.anyio
async def test_workload_cap_rejects_excess_but_allows_health_and_recovers():
    entered, release = asyncio.Event(), asyncio.Event()

    async def downstream(scope, receive, send):
        if scope["path"] != "/api/health":
            entered.set()
            await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    with patch.dict(os.environ, {"BACKEND_MAX_CONCURRENT_REQUESTS": "1"}):
        middleware = WorkloadLimitMiddleware(downstream)

    async def request(path):
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await middleware({"type": "http", "path": path}, receive, send)
        return messages[0]["status"]

    first = asyncio.create_task(request("/api/playlist"))
    await entered.wait()
    assert await request("/api/playlist") == 503
    assert await request("/api/health") == 200
    release.set()
    assert await first == 200
    assert middleware.active == 0
    assert await request("/api/playlist") == 200


def test_users_xml_results_do_not_cross_contaminate():
    base = {"tracks": [{"title": "Track", "artist": "Artist", "album": ""}]}
    cache = get_rekordbox_cache()
    cache.clear()
    with (
        patch.dict(os.environ, {"REKORDBOX_CACHE_ENABLED": "false"}),
        tempfile.TemporaryDirectory() as tmp,
    ):
        owned_xml, empty_xml = Path(tmp) / "owned.xml", Path(tmp) / "empty.xml"
        owned_xml.write_text(
            '<DJ_PLAYLISTS><COLLECTION><TRACK Name="Track" Artist="Artist"/></COLLECTION></DJ_PLAYLISTS>'
        )
        empty_xml.write_text("<DJ_PLAYLISTS><COLLECTION/></DJ_PLAYLISTS>")
        first = mark_owned_tracks(copy.deepcopy(base), owned_xml)
        second = mark_owned_tracks(copy.deepcopy(base), empty_xml)
        assert first["tracks"][0]["owned"] is True
        assert second["tracks"][0]["owned"] is False
        assert "owned" not in base["tracks"][0]
        assert len(cache) == 0


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_public_playlist_cache_is_not_mutated_by_xml_matching():
    from fastapi.testclient import TestClient
    import app as module

    identity = "https://open.spotify.com/playlist/0jKqvXbsroCPdccFmORnPz"
    key = f"{module.CACHE_VERSION}:spotify:{identity}"
    base = {
        "playlist_id": "p",
        "playlist_name": "P",
        "tracks": [{"title": "Track", "artist": "Artist"}],
    }

    def apply(data, *_args, **_kwargs):
        data["tracks"][0]["owned"] = True
        return data

    with patch.dict(
        os.environ,
        {
            "APP_ENV": "test",
            "BACKEND_PROXY_TOKEN": "",
            "BACKEND_RATE_LIMIT_PER_MINUTE": "10000",
        },
    ):
        module.PLAYLIST_CACHE[key] = copy.deepcopy(base)
        try:
            with (
                patch.object(
                    module, "playlist_result_to_dict", side_effect=lambda raw: raw
                ),
                patch.object(module, "_apply_rekordbox_owned_flags", side_effect=apply),
            ):
                response = TestClient(module.app).post(
                    "/api/playlist-with-rekordbox-upload",
                    data={"url": identity},
                    files={
                        "file": (
                            "x.xml",
                            b"<DJ_PLAYLISTS><COLLECTION/></DJ_PLAYLISTS>",
                            "text/xml",
                        )
                    },
                )
            assert response.status_code == 200
            assert response.json()["tracks"][0]["owned"] is True
            assert "owned" not in module.PLAYLIST_CACHE[key]["tracks"][0]
        finally:
            module.PLAYLIST_CACHE.pop(key, None)
