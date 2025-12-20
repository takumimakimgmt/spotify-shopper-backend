#!/usr/bin/env python3
"""
Apple Music Playlist Probe.

Minimal reproduction script to diagnose Apple Music success rate.
Opens a playlist URL and detects blocking gates, captures page state, and attempts data extraction.

Usage:
    python scripts/apple_probe.py "https://music.apple.com/jp/playlist/..."
    
Output:
    - Logs: final_url, page_title, detected_gate, strategy_used, track_count, sample_titles
    - Debug artifacts: tmp/apple_debug/{timestamp}_{gate_type}/screenshot.png + html.txt
"""

import os
import sys
import json
import asyncio
import tempfile
import logging
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Error: playwright not installed. Install with: pip install playwright")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class AppleGateDetector:
    """Detects blocking gates (consent, age, geo, bot, DOM broken, empty)."""
    
    @staticmethod
    def find_tracks_in_html(html: str):
        """Extract track list from embedded JSON (synchronous)."""
        
        # Try __NEXT_DATA__ first
        match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>([^<]+)</script>', html)
        if match:
            try:
                data = json.loads(match.group(1))
                result = AppleGateDetector._traverse_for_tracks(data)
                if result:
                    logger.debug(f"Found tracks in __NEXT_DATA__: {len(result)} items")
                    return result
            except Exception as e:
                logger.debug(f"__NEXT_DATA__ parse failed: {e}")

        # Try application/json script tags
        for match in re.finditer(r'<script[^>]*type="application/json"[^>]*>([^<]+)</script>', html):
            try:
                data = json.loads(match.group(1))
                tracks = AppleGateDetector._traverse_for_tracks(data)
                if tracks:
                    logger.debug(f"Found tracks in application/json script: {len(tracks)} items")
                    return tracks
            except Exception:
                pass

        return None

    @staticmethod
    def _traverse_for_tracks(data, depth=0, max_depth=10):
        """Recursively traverse JSON looking for track arrays."""
        if depth > max_depth:
            return None

        if isinstance(data, dict):
            # Look for common playlist/track array keys
            for key in ["tracks", "data", "songs", "items", "catalog"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list) and len(val) > 0:
                        if isinstance(val[0], dict) and any(k in val[0] for k in ["title", "name", "trackName"]):
                            return val
                    result = AppleGateDetector._traverse_for_tracks(val, depth + 1, max_depth)
                    if result:
                        return result
            # Continue traversal
            for v in data.values():
                result = AppleGateDetector._traverse_for_tracks(v, depth + 1, max_depth)
                if result:
                    return result
        elif isinstance(data, list):
            for item in data[:10]:  # Limit traversal
                result = AppleGateDetector._traverse_for_tracks(item, depth + 1, max_depth)
                if result:
                    return result

        return None

    @staticmethod
    async def detect(page, html: str) -> dict:
        """
        Detect which gate is blocking the playlist.
        
        Returns:
            {
                "gate": "success" | "consent" | "age_verification" | "geo_block" | 
                        "bot_detection" | "dom_broken" | "empty",
                "reason": "human-readable reason",
            }
        """
        # Check for consent dialogs
        if any(s in html for s in ["cookie", "Accept", "同意", "利用規約"]):
            if await page.query_selector('[role="dialog"]'):
                return {"gate": "consent", "reason": "Cookie/consent dialog detected"}

        # Check for age verification
        if any(s in html for s in ["age", "年齢", "verification", "confirm your age", "18+"]):
            if await page.query_selector('input[type="number"], input[type="text"][aria-label*="age"]'):
                return {"gate": "age_verification", "reason": "Age verification gate detected"}

        # Check for geo/region block
        if any(s in html for s in ["region", "地域", "not available", "利用できません", "not supported"]):
            return {"gate": "geo_block", "reason": "Geo/region block indicated in page"}

        # Check for bot detection
        if any(s in html for s in ["recaptcha", "reCAPTCHA", "bot", "unusual activity", "異常な活動"]):
            return {"gate": "bot_detection", "reason": "Bot detection/captcha indicated"}

        # Check for DOM but no tracks
        if await page.query_selector('div[role="row"], ol li, .songs-list-row'):
            return {"gate": "dom_broken", "reason": "DOM selector exists but no data extracted"}

        # Empty/unknown state
        if len(html) < 10000:
            return {"gate": "empty", "reason": "Page too minimal (< 10KB)"}

        return {"gate": "unknown", "reason": "Unable to classify gate"}


class AppleProbe:
    """Main probe logic."""
    
    def __init__(self, url: str, debug_dir: str = "tmp/apple_debug"):
        self.url = url
        self.debug_dir = Path(debug_dir)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.result = {
            "url": url,
            "final_url": None,
            "page_title": None,
            "detected_gate": None,
            "strategy_used": None,
            "track_count": 0,
            "sample_titles": [],
            "timestamp": datetime.now().isoformat(),
        }

    async def run(self):
        """Execute the probe."""
        logger.info(f"Starting Apple probe: {self.url}")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                
                try:
                    await self._fetch_and_analyze(page)
                finally:
                    await context.close()
                    await browser.close()
        except Exception as e:
            logger.error(f"Probe failed: {e}", exc_info=True)
            self.result["error"] = str(e)

        return self.result

    async def _fetch_and_analyze(self, page):
        """Fetch page and analyze content."""
        try:
            logger.info(f"Opening URL (timeout: 95s)")
            await page.goto(self.url, wait_until="networkidle", timeout=95000)
        except Exception as e:
            logger.warning(f"goto failed (will try with partial load): {e}")
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e2:
                logger.error(f"Failed to load page: {e2}")
                self.result["detected_gate"] = "navigation_failed"
                return

        self.result["final_url"] = page.url

        # Get page title
        title = await page.title()
        self.result["page_title"] = title
        logger.info(f"Page title: {title}")
        logger.info(f"Final URL: {page.url}")

        # Get HTML for analysis
        html = await page.content()
        logger.info(f"Page size: {len(html)} bytes")

        # Try to extract data FIRST (before gate detection)
        await self._try_extraction(page, html)

        # Detect gate (after extraction, so we know if success)
        if self.result["track_count"] > 0:
            self.result["detected_gate"] = "success"
            logger.info(f"✓ Success: Extracted {self.result['track_count']} tracks via {self.result.get('strategy_used', 'unknown')}")
        else:
            gate_info = await AppleGateDetector.detect(page, html)
            self.result["detected_gate"] = gate_info["gate"]
            logger.info(f"Detected gate: {gate_info['gate']} - {gate_info['reason']}")
            # Save debug artifacts only on failure
            await self._save_debug_artifacts(page, html, gate_info["gate"])

    async def _try_extraction(self, page, html: str):
        """Attempt to extract track data using all three strategies."""
        
        # Strategy A: Embedded JSON
        logger.info("Strategy A: Searching embedded JSON...")
        tracks_a = AppleGateDetector.find_tracks_in_html(html)
        if tracks_a:
            self.result["strategy_used"] = "embedded_json"
            self.result["track_count"] = len(tracks_a)
            self._extract_samples(tracks_a)
            logger.info(f"✓ Found {len(tracks_a)} tracks via embedded JSON")
            return

        # Strategy B: Network API interception (detect Authorization from page context)
        logger.info("Strategy B: Checking for network API clues...")
        # Look for bearer tokens in page source that might be used for Apple API
        if "music.apple.com/api" in html or "bearer" in html.lower():
            logger.info("  Detected potential API endpoints or auth tokens in page")
            self.result["strategy_used"] = "network_api"
            logger.info("  (Full API intercept would require live network monitoring)")
        
        # Strategy C: DOM selectors (fallback)
        logger.info("Strategy C: Attempting DOM selector extraction...")
        try:
            await page.wait_for_selector(
                'div[role="row"], ol li, .songs-list-row',
                timeout=5000
            )
            rows = await page.query_selector_all('div[role="row"], ol li, .songs-list-row')
            if rows:
                self.result["strategy_used"] = "dom_selector"
                self.result["track_count"] = len(rows)
                # Try to extract text from visible rows
                for i, row in enumerate(rows[:3]):
                    text = await row.text_content()
                    if text:
                        self.result["sample_titles"].append(text.strip()[:100])
                logger.info(f"✓ Found {len(rows)} rows via DOM selector")
                return
        except Exception as e:
            logger.debug(f"  DOM selector failed: {e}")

        logger.warning("✗ No tracks extracted via any strategy")

    def _extract_samples(self, tracks: list):
        """Extract sample titles from track list."""
        for track in tracks[:3]:
            if isinstance(track, dict):
                title = track.get("title") or track.get("name") or track.get("trackName", "")
                artist = track.get("artist") or track.get("artistName") or ""
                sample = f"{title} - {artist}" if artist else title
                if sample:
                    self.result["sample_titles"].append(sample[:100])

    async def _save_debug_artifacts(self, page, html: str, gate_type: str):
        """Save screenshot and HTML for debugging."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_subdir = self.debug_dir / f"{timestamp}_{gate_type}"
        debug_subdir.mkdir(parents=True, exist_ok=True)

        try:
            # Save screenshot
            screenshot_path = debug_subdir / "screenshot.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"Saved screenshot: {screenshot_path}")

            # Save HTML (first 500KB)
            html_path = debug_subdir / "html.txt"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html[:500000])
            logger.info(f"Saved HTML: {html_path}")

            # Save metadata
            meta_path = debug_subdir / "meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(self.result, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved metadata: {meta_path}")
        except Exception as e:
            logger.warning(f"Failed to save debug artifacts: {e}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/apple_probe.py <playlist_url>")
        print("Example: python scripts/apple_probe.py 'https://music.apple.com/jp/playlist/...'")
        sys.exit(1)

    url = sys.argv[1].strip().strip('"\'')
    
    if "music.apple.com" not in url:
        print("Error: URL must be an Apple Music playlist URL (music.apple.com)")
        sys.exit(1)

    probe = AppleProbe(url)
    result = await probe.run()

    # Print summary
    print("\n" + "=" * 70)
    print("APPLE MUSIC PROBE RESULT")
    print("=" * 70)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 70)

    # Exit code: 0 if success, 1 otherwise
    sys.exit(0 if result.get("detected_gate") == "success" else 1)


if __name__ == "__main__":
    asyncio.run(main())
