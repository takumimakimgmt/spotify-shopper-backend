"""Centralized cache utilities (TTLCache settings & key builders)."""
from __future__ import annotations

import os
from cachetools import TTLCache

# Rekordbox cache settings
REKORDBOX_CACHE_VERSION = int(os.getenv("REKORDBOX_CACHE_VERSION", "1"))
REKORDBOX_CACHE_MAXSIZE = int(os.getenv("REKORDBOX_CACHE_MAXSIZE", "10"))
REKORDBOX_CACHE_TTL_S = int(os.getenv("REKORDBOX_CACHE_TTL_S", "600"))

# Lazy-initialized caches
_rekordbox_cache: TTLCache | None = None


def get_rekordbox_cache() -> TTLCache:
    global _rekordbox_cache
    if _rekordbox_cache is None:
        _rekordbox_cache = TTLCache(maxsize=REKORDBOX_CACHE_MAXSIZE, ttl=REKORDBOX_CACHE_TTL_S)
    return _rekordbox_cache


def build_rekordbox_cache_key(file_hash: str) -> str:
    return f"rb:{REKORDBOX_CACHE_VERSION}:{file_hash}"
