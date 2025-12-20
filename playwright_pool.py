import asyncio
import sys
import os
from typing import Optional

from playwright.async_api import async_playwright, Browser, Playwright, BrowserContext

_lock = asyncio.Lock()
_pw: Optional[Playwright] = None
_browser: Optional[Browser] = None
_persist_ctx: Optional[BrowserContext] = None


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
        headless = os.getenv("APPLE_PLAYWRIGHT_HEADLESS", "1") != "0"
        _browser = await _pw.chromium.launch(headless=headless, args=_launch_args())
        print("[PW_POOL] launch browser", flush=True)
        return _browser


async def new_context():
    global _pw, _persist_ctx
    print("[PW_POOL] new_context() called", flush=True)
    user_data_dir = os.getenv("APPLE_PLAYWRIGHT_USER_DATA_DIR")
    def _reset_browser_globals():
        global _pw, _browser, _persist_ctx
        if _persist_ctx is not None:
            try:
                # fire-and-forget: do not await close, so we don't block request handling; next new_context will re-init
                asyncio.create_task(_persist_ctx.close())
            except Exception:
                pass
            _persist_ctx = None
            print("[PW_POOL] close persistent context (reset)", flush=True)
        if _browser is not None:
            try:
                # fire-and-forget: do not await close, so we don't block request handling; next new_context will re-init
                asyncio.create_task(_browser.close())
            except Exception:
                pass
            _browser = None
            print("[PW_POOL] close browser (reset)", flush=True)
        if _pw is not None:
            try:
                asyncio.create_task(_pw.stop())
            except Exception:
                pass
            _pw = None

    async def _try_create_context():
        if user_data_dir:
            # Persistent profile mode (reused across calls)
            if _persist_ctx is not None:
                print("[PW_POOL] reuse persistent context", flush=True)
                return _persist_ctx
            async with _lock:
                if _persist_ctx is not None:
                    print("[PW_POOL] reuse persistent context", flush=True)
                    return _persist_ctx
                if _pw is None:
                    _pw = await async_playwright().start()
                headless = os.getenv("APPLE_PLAYWRIGHT_HEADLESS", "1") != "0"
                _persist_ctx = await _pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    args=_launch_args(),
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    locale="ja-JP",
                    viewport={"width": 1920, "height": 1080},
                )
                print("[PW_POOL] launch persistent context", flush=True)
                return _persist_ctx
        # Ephemeral context per request
        browser = await get_browser()
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            viewport={"width": 1920, "height": 1080},
        )
        print("[PW_POOL] ephemeral context created", flush=True)
        return ctx

    # Only log once per context creation
    # 1回目トライ
    try:
        return await _try_create_context()
    except Exception as e:
        print(f"[PW_POOL] new_context() failed: {e}", flush=True)
        print("[PW_POOL] new_context failed; resetting browser", flush=True)
        _reset_browser_globals()
    # 2回目トライ
    try:
        return await _try_create_context()
    except Exception as e:
        print(f"[PW_POOL] new_context() failed again: {e}", flush=True)
        raise RuntimeError("[PW_POOL] new_context failed twice; aborting") from e


async def close_browser() -> None:
    global _pw, _browser, _persist_ctx
    async with _lock:
        if _persist_ctx is not None:
            try:
                await _persist_ctx.close()
            finally:
                _persist_ctx = None
                print("[PW_POOL] close persistent context", flush=True)
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
