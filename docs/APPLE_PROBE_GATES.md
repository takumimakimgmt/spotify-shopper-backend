# Apple Music Probe - Detected Gate Classification

## Gate Types

### 1. `success`
- **Indicator**: Tracks found in embedded JSON or DOM
- **Action**: Data extraction succeeded; no blocker present
- **Next Step**: Commit the working strategy to core.py

### 2. `consent`
- **Indicator**: Cookie/consent dialog, `[role="dialog"]` selector matches
- **Keywords in HTML**: "cookie", "Accept", "同意", "利用規約"
- **Action**: Dismiss dialog (if possible) or wait for auto-dismissal
- **Next Step**: Add dialog-dismiss logic if needed

### 3. `age_verification`
- **Indicator**: Age input fields, "年齢" or "age" text
- **Keywords**: "age", "年齢", "verification", "confirm your age", "18+"
- **DOM Clue**: `input[type="number"]`, `input[aria-label*="age"]`
- **Action**: Cannot proceed without user interaction
- **Note**: Indicates Apple may be blocking based on region/user profile

### 4. `geo_block`
- **Indicator**: Region/country restrictions
- **Keywords**: "region", "地域", "not available", "利用できません", "not supported"
- **Action**: Try different region or VPN
- **Note**: Apple Music API may deny requests from non-supported regions

### 5. `bot_detection`
- **Indicator**: CAPTCHA, bot warnings
- **Keywords**: "recaptcha", "reCAPTCHA", "bot", "unusual activity", "異常な活動"
- **Action**: Playwright rate-limit reduction or user-agent rotation
- **Next Step**: Add delay between requests, rotate user-agents

### 6. `dom_broken`
- **Indicator**: DOM structure exists but no track data extracted
- **DOM Match**: `div[role="row"], ol li, .songs-list-row` found but empty
- **Action**: Selector may have changed; investigate page structure
- **Debug**: Check saved HTML for new selectors

### 7. `empty`
- **Indicator**: Minimal page load (< 10KB)
- **Cause**: Network timeout, page redirect, or incomplete load
- **Action**: Increase load timeout or add retry logic
- **Next Step**: Check final URL for redirects or 404

### 8. `navigation_failed`
- **Indicator**: Could not load page at all
- **Cause**: Network error, DNS failure, blocked by Apple
- **Action**: Retry with different user-agent or IP
- **Next Step**: Check rate-limit headers in response

---

## Recommended Debug Workflow

1. **Run the probe** with a known-good playlist URL:
   ```bash
   python scripts/apple_probe.py "https://music.apple.com/jp/playlist/..."
   ```

2. **Check output**:
   - If `detected_gate: success` → Extract `strategy_used` and commit that approach
   - Otherwise → Check debug artifacts in `tmp/apple_debug/` (screenshot, html, meta.json)

3. **Identify the blocker**:
   - Match gate type to above list
   - Review saved HTML for unexpected redirects or content changes

4. **Document findings**:
   - Update `core.py` with gate-specific handling if needed
   - Note any environment-specific issues (region, IP, user-agent)

---

## Expected Debug Artifacts

For each failed probe run:
- `tmp/apple_debug/{TIMESTAMP}_{GATE_TYPE}/screenshot.png` - Full page screenshot
- `tmp/apple_debug/{TIMESTAMP}_{GATE_TYPE}/html.txt` - Page HTML (first 500KB)
- `tmp/apple_debug/{TIMESTAMP}_{GATE_TYPE}/meta.json` - Probe metadata and result

---

## Strategy Ranking (by success probability)

1. **Embedded JSON** (`__NEXT_DATA__`, `application/json` scripts)
   - Fastest, least fragile, preferred if gate doesn't block page load

2. **Network API** (detect auth headers/bearer tokens from page context)
   - More stable than DOM but requires live network monitoring
   - Good fallback if HTML extraction fails

3. **DOM Selectors** (last resort)
   - Fragile to layout changes
   - Only use if gates allow page to fully render

---

## Common Issues & Fixes

| Gate | Probable Cause | Fix |
|------|---------------|-----|
| consent | Cookie banner | Wait 2-3s for auto-dismiss or add button-click logic |
| age_verification | Regional restriction | Check region; may need to skip Apple enrichment for user |
| geo_block | IP/region mismatch | Verify proxy or try different region |
| bot_detection | Rate-limit hit | Add exponential backoff, rotate user-agents |
| dom_broken | Selector changed | Review screenshot to find new selectors |
| empty | Timeout | Increase `wait_until` timeout, check for 30x redirects |
| navigation_failed | Network blocked | Check Apple's rate-limit headers, add retry |
