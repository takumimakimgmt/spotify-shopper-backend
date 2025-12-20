# Dev-only: quick Apple Music scrape test script
import asyncio
import json
import sys

from app import app
from core import fetch_playlist_tracks_generic

DEFAULT_URL = "https://music.apple.com/jp/playlist/%E3%83%88%E3%83%83%E3%83%97100-%E6%97%A5%E6%9C%AC/pl.043a2c9876114d95a4659988497567be"

def _clean_url(s: str) -> str:
    s = (s or "").strip()
    # うっかり <...> を貼っても動くように救済
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    return s

URL = _clean_url(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_URL

async def main():
    print("USING_URL:", URL)

    r = await fetch_playlist_tracks_generic(
        source="apple",
        url_or_id=URL,
        app=app,
        apple_mode="auto",
        enrich_spotify=False,
    )

    print("keys:", list(r.keys()))
    items = r.get("tracks") or r.get("items") or []
    print("count:", len(items))
    meta = r.get("meta", {})
    perf = r.get("perf", {})
    print("meta.apple_final_url:", meta.get("apple_final_url"))
    print("meta.apple_extraction_method:", meta.get("apple_extraction_method"))
    print("perf:", perf)

    if items:
        print("sample0:", json.dumps(items[0], ensure_ascii=False, indent=2)[:1000])

if __name__ == "__main__":
    asyncio.run(main())
