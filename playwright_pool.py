import asyncio
import sys
from typing import Optional

from playwright.async_api import async_playwright, Browser, Playwright

_lock = asyncio.Lock()
_pw: Optional[Playwright] = None
_browser: Optional[Browser] = None


def _launch_args() -> list[str]:
    args: list[str] = []
    # Render/Linux 対策: sandbox/DEV SHM を無効化
    if sys.platform.startswith("linux"):
        args += ["--no-sandbox", "--disable-dev-shm-usage"]
    return args


async def get_browser() -> Browser:
    global _pw, _browser
    if _browser is not None:
        print("[PW_POOL] reuse browser", flush=True)
        return _browser

    async with _lock:
        if _browser is not None:
            print("[PW_POOL] reuse browser", flush=True)
            return _browser
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(headless=True, args=_launch_args())
        print("[PW_POOL] launch browser", flush=True)
        return _browser


async def new_context():
    browser = await get_browser()
    # リクエスト毎に context を作成し、使い終わったら破棄する
    return await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        locale="ja-JP",
        viewport={"width": 1920, "height": 1080},
    )


async def close_browser() -> None:
    global _pw, _browser
    async with _lock:
        if _browser is not None:
            try:
                await _browser.close()
            finally:
                _browser = None
                print("[PW_POOL] close browser", flush=True)
        if _pw is not None:
            try:
                await _pw.stop()
            finally:
                _pw = None
