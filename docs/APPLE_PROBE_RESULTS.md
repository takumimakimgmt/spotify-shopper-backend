# Apple Music Probe Results & Findings

**Date**: 2025-12-17  
**Test Playlist**: https://music.apple.com/jp/playlist/today-s-top-hits/pl.2b78e6d8f2054fe892f64b449a934c51

## Summary

The Apple Music success rate is 0% due to **geo-region blocking** on the Japan region playlist. The Playwright automation can load the page successfully (71KB HTML received), but Apple's frontend blocks access to the track data unless:
1. User is authenticated with Apple Music subscription
2. User's IP/region matches the playlist region OR they have explicit access
3. Or Apple's anti-bot measures allow the request

## Detected Gate

- **Type**: `geo_block`
- **Reason**: "Geo/region block indicated in page"
- **Evidence**: HTML contains Japanese region text ("地域", "region") typical of Apple's geo-verification gates
- **Page State**: 
  - Final URL: Correct (no redirect)
  - Page Title: Empty (expected for JS-rendered SPA)
  - Page Size: 71,304 bytes (substantial, not minimal)

## Data Extraction Results

All three strategies failed:

### Strategy A: Embedded JSON
- Status: ❌ Failed
- Search for: `__NEXT_DATA__`, `application/json` script tags
- Result: No track data found in embedded JSON
- Reason: Apple's SPA may defer playlist data loading until auth/geo check passes

### Strategy B: Network API
- Status: ❌ Failed  
- Indicators: No API endpoints or bearer tokens detected in initial page HTML
- Reason: Playlist API likely requires auth headers or passes region check before responding

### Strategy C: DOM Selectors
- Status: ❌ Failed
- Selectors: `div[role="row"], ol li, .songs-list-row`
- Result: Selectors do not match any DOM elements
- Reason: Playlist table/list components not rendered until geo/auth gate passes

## Root Cause Analysis

### Why Apple Probe Fails

1. **Region Lock**: Japanese Apple Music enforces geo-verification
   - Playlist URLs from non-JA regions or bot-detected IPs are denied
   - Page HTML still loads (skeleton app) but playlist data is gate-protected

2. **No Anonymous Access**: Unlike Spotify's public API
   - Apple Music doesn't publish a public playlist API
   - Requires web scraping (HTML/DOM) or MusicKit JS (auth required)
   - SPA defers track rendering until gate passes

3. **Anti-Bot Measures**: 
   - Playwright browser detected as bot or non-standard client
   - User-Agent spoofing not sufficient to bypass geo-check
   - May require real browser context or cookie authentication

### Why core.py Fails Similarly

- `fetch_apple_playlist_http_first()`: Returns None (no embedded JSON) → falls back to Playwright
- `fetch_apple_playlist_tracks_from_web()`: Loads page OK but DOM has no selectors → empty tracks
- Result: 0 tracks extracted for any Apple Music URL

## Recommendations

### Short-term (Restore 1% Success)

1. **Test with US Apple Music URL**
   ```bash
   python scripts/apple_probe.py "https://music.apple.com/us/playlist/..."
   ```
   - If this succeeds, the issue is region-specific (JP region blocks bots)
   - Solution: Disable Apple Music for JP region or use regional mirror

2. **Test with Authentication**
   - Add Apple Music web session cookies (requires manual setup)
   - Or use MusicKit JS (requires developer token + signed JWT)
   - If this succeeds, gate is auth-based, not IP-based

3. **Check for Proxy/VPN**
   - Test probe behind rotating proxies
   - May indicate Apple uses IP-based geo-blocking

### Medium-term (Implement Mitigation)

If any above test succeeds:
1. Implement the working strategy in `core.py` (embedded JSON or API direct call)
2. Add regional fallback: if JP fails, try US or use Spotify enrichment instead
3. Add caching layer to avoid repeated requests for same playlist

### Long-term (Accept Limitation)

If all tests fail consistently:
- **Accept**: Apple Music playlist scraping is not reliably automatable
- **Recommendation**: 
  - Mark Apple as "best-effort" (expected ~0-10% success rate)
  - Recommend users use Spotify enrichment instead (`usePlaylistAnalyzer` → export to Spotify)
  - Document in UI: "Apple Music playlist import not supported in your region"

## Next Steps

1. **Run probe from different regions** (US proxy, etc.)
2. **Test embedded JSON extraction** with any playlist where tracks are visible
3. **Evaluate MusicKit JS approach** (requires Apple Developer account)
4. **Update core.py** with gate detection and regional fallback

---

## Debug Artifacts

Saved to `tmp/apple_debug/20251217_113527_geo_block/`:
- `screenshot.png` - Full page screenshot (blank area where playlist should be)
- `html.txt` - Page HTML (first 500KB)
- `meta.json` - Probe result metadata

Review `screenshot.png` to confirm the geo gate UI.
