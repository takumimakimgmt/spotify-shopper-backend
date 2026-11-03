from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


class _RequestTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {
            "POST",
            "PUT",
            "PATCH",
        }:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope, receive, send):
        max_mb = self.max_bytes / (1024 * 1024)
        response = JSONResponse(
            status_code=413,
            content={"detail": f"Request body too large (max {max_mb:.0f}MB)"},
        )
        await response(scope, receive, send)


class _RateLimiter:
    def __init__(self):
        self._fallback: OrderedDict[str, tuple[int, int]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._redis = None
        redis_url = (os.getenv("REDIS_URL") or "").strip()
        if redis_url:
            try:
                from redis.asyncio import Redis

                self._redis = Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
            except Exception as exc:
                logger.warning(
                    "Redis rate limiter unavailable (%s)", type(exc).__name__
                )

    async def allow(self, key: str, limit: int) -> tuple[bool, int]:
        now = int(time.time())
        window = now // 60
        retry_after = 60 - (now % 60)

        if self._redis is not None:
            redis_key = f"playlist-shopper:rate:{window}:{key}"
            try:
                count = await self._redis.eval(
                    "local n = redis.call('INCR', KEYS[1]); "
                    "if n == 1 then redis.call('EXPIRE', KEYS[1], 70) end; return n",
                    1,
                    redis_key,
                )
                return count <= limit, retry_after
            except Exception as exc:
                logger.warning("Redis rate limiter failed (%s)", type(exc).__name__)
                if (os.getenv("APP_ENV") or "local") not in {
                    "local",
                    "dev",
                    "development",
                    "test",
                }:
                    raise RuntimeError("Rate limiter unavailable") from None

        async with self._lock:
            stale = [k for k, (bucket, _) in self._fallback.items() if bucket != window]
            for stale_key in stale:
                self._fallback.pop(stale_key, None)

            bucket, count = self._fallback.get(key, (window, 0))
            count = count + 1 if bucket == window else 1
            self._fallback[key] = (window, count)
            self._fallback.move_to_end(key)
            while len(self._fallback) > 10_000:
                self._fallback.popitem(last=False)
            return count <= limit, retry_after


_rate_limiter = _RateLimiter()


def _client_key(request: Request) -> str:
    if (
        _env_bool("TRUST_PROXY_HEADERS")
        and (os.getenv("BACKEND_PROXY_TOKEN") or "").strip()
    ):
        for header in ("x-vercel-forwarded-for", "x-forwarded-for", "x-real-ip"):
            value = request.headers.get(header)
            if value:
                return value.split(",")[-1].strip() or "unknown"
    return request.client.host if request.client else "unknown"


class BackendProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Use the router's ASGI path, never a URL reconstructed from untrusted Host.
        path = request.scope["path"]
        if not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)

        expected_token = (os.getenv("BACKEND_PROXY_TOKEN") or "").strip()
        supplied_token = request.headers.get("x-backend-token", "")
        environment = (os.getenv("APP_ENV") or "local").strip().lower()
        if (
            environment not in {"local", "development", "dev", "test"}
            and not expected_token
        ):
            return JSONResponse(
                status_code=503,
                content={"detail": "Backend protection is not configured"},
            )
        if expected_token and not hmac.compare_digest(expected_token, supplied_token):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        limit = _bounded_env_int("BACKEND_RATE_LIMIT_PER_MINUTE", 60, 1, 10_000)
        key = f"{path}:{_client_key(request)}"
        try:
            allowed, retry_after = await _rate_limiter.allow(key, limit)
        except RuntimeError:
            return JSONResponse(
                status_code=503, content={"detail": "Temporarily unavailable"}
            )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


class WorkloadLimitMiddleware:
    """Reject excess work before bodies are parsed; keep health checks responsive.

    One event-loop-local counter per worker. Deployment uses one worker; for
    multiple replicas each replica has its own bounded memory/CPU budget.
    """

    def __init__(self, app):
        self.app = app
        self.active = 0
        self.limit = _bounded_env_int("BACKEND_MAX_CONCURRENT_REQUESTS", 2, 1, 16)

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope["path"].startswith("/api/")
            or scope["path"] == "/api/health"
        ):
            await self.app(scope, receive, send)
            return
        if self.active >= self.limit:
            response = JSONResponse(
                status_code=503,
                content={"detail": "Server busy. Try again shortly."},
                headers={"Retry-After": "5"},
            )
            await response(scope, receive, send)
            return
        self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active -= 1
