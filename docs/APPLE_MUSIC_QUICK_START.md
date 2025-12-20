# Apple Music Diagnostic Quick Start

## TL;DR

Apple Music integration is **blocked by anti-bot gates** (requires authentication). A minimal reproduction probe has been created to diagnose the issue.

---

## Quick Start

### Run the Probe

```bash
cd spotify-shopper
python scripts/apple_probe.py "https://music.apple.com/jp/playlist/..."
```

### Interpretation

- ✅ **detected_gate: "success"** → Data extraction worked (commit this strategy)
- ⚠️ **detected_gate: "geo_block"** → Region/auth gate blocking access (expected)
- ⚠️ **detected_gate: "bot_detection"** → Anti-bot CAPTCHA or rate-limit hit
- ⚠️ **detected_gate: "consent"** → Cookie dialog present
- ⚠️ **detected_gate: "empty"** → Page didn't load or timed out

### Debug Artifacts

Failed probes save to `tmp/apple_debug/{TIMESTAMP}_{GATE_TYPE}/`:
- `screenshot.png` — Full page screenshot
- `html.txt` — Page HTML (first 500KB)
- `meta.json` — Probe metadata

---

## Status: Known Issue

As of 2025-12-17:
- **Root Cause**: Apple blocks non-authenticated Playwright requests (anti-bot)
- **Impact**: 0% success rate on all playlists (JP, US, etc.)
- **Solution**: Not recoverable without Apple SDK integration or authentication

See **[APPLE_MUSIC_RECOVERY_REPORT.md](APPLE_MUSIC_RECOVERY_REPORT.md)** for full analysis and recommendations.

---

## Test Cases

**Test 1: Japan Region**
```bash
python scripts/apple_probe.py "https://music.apple.com/jp/playlist/today-s-top-hits/pl.2b78e6d8f2054fe892f64b449a934c51"
# Expected: detected_gate: geo_block
```

**Test 2: US Region**
```bash
python scripts/apple_probe.py "https://music.apple.com/us/playlist/todays-top-hits/pl.2b78e6d8f2054fe892f64b449a934c50"
# Expected: detected_gate: geo_block (same issue, not region-specific)
```

**Test 3: Custom URL**
```bash
python scripts/apple_probe.py "https://music.apple.com/us/playlist/{YOUR_PLAYLIST_ID}"
```

---

## What the Probe Does

1. **Opens page** with Playwright (headless Chrome)
2. **Tries to extract tracks** using three strategies (in order):
   - Embedded JSON (`__NEXT_DATA__`, `application/json` scripts)
   - Network API hints (Bearer tokens, endpoints)
   - DOM selectors (`div[role="row"]`, `.songs-list-row`)
3. **Detects blocking gates** if extraction fails
4. **Saves debug artifacts** for manual inspection

---

## Next Steps

### For Users
→ Use Spotify playlists. Apple Music import is not supported.

### For Engineers
→ See [APPLE_MUSIC_RECOVERY_REPORT.md](APPLE_MUSIC_RECOVERY_REPORT.md) for implementation options (MusicKit JS, etc.)

### For QA
→ Run probe on new Apple Music URLs to confirm gate type is consistent.

---

## References

- 📋 [Full Recovery Report](APPLE_MUSIC_RECOVERY_REPORT.md)
- 🔧 [Gate Classification Guide](APPLE_PROBE_GATES.md)
- 🧪 [Test Results & Findings](APPLE_PROBE_RESULTS.md)
- 🐍 [Probe Script](../scripts/apple_probe.py)
