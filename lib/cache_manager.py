"""Centralized cache utilities (TTLCache settings & key builders)."""

from __future__ import annotations

import os
from cachetools import TTLCache


# Rekordbox cache settings
def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


REKORDBOX_CACHE_VERSION = _bounded_env_int("REKORDBOX_CACHE_VERSION", 2, 1, 100)
REKORDBOX_CACHE_MAXSIZE = _bounded_env_int("REKORDBOX_CACHE_MAXSIZE", 2, 1, 20)
REKORDBOX_CACHE_TTL_S = _bounded_env_int("REKORDBOX_CACHE_TTL_S", 600, 1, 86_400)

# Lazy-initialized caches
_rekordbox_cache: TTLCache | None = None


def get_rekordbox_cache() -> TTLCache:
    global _rekordbox_cache
    if _rekordbox_cache is None:
        _rekordbox_cache = TTLCache(
            maxsize=REKORDBOX_CACHE_MAXSIZE, ttl=REKORDBOX_CACHE_TTL_S
        )
    return _rekordbox_cache


def build_rekordbox_cache_key(file_hash: str) -> str:
    return f"rb:{REKORDBOX_CACHE_VERSION}:{file_hash}"
