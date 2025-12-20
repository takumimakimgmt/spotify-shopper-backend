# Apple Music Matrix Test Results

**Date**: 2024-12-17  
**Script**: `tools/apple_matrix.sh`  
**Backend**: DOM-first Apple Music scraper with scroll support  
**Canary URLs**: 10 Japanese playlists  

## Summary

| Metric | Value |
|--------|-------|
| **Total URLs Tested** | 10 |
| **OK** | 10 (100%) |
| **Fail** | 0 |
| **Skip** | 0 |
| **Total Tracks Extracted** | 1,136 |
| **Average Tracks per Playlist** | 113 |

## Key Observations

### ✅ All Playlists Extracted Successfully
- **100% success rate** across all 10 canary URLs
- All playlists used `method=dom_rows` (DOM-first extraction)
- No geo-blocking or consent pages encountered
- No scroll issues detected

### 📊 Extraction Metrics

**Track Count Distribution:**
- Small: 40-76 tracks (3 playlists)
- Medium: 97-130 tracks (5 playlists)
- Large: 300 tracks (1 playlist)

**Performance:**
- Fastest: 219ms (48 tracks)
- Slowest: 1004ms (100 tracks)
- Average: ~635ms per playlist

### 🔍 Scroll Diagnostics

All playlists show stable row counts after scroll:
- `row_prog=[N, N, N]` - 3 consecutive rounds with same row count
- `uniq_prog=[1, 1, 1]` - last track key stable across rounds
- No progressive increase in row count, indicating scroll completed on first load

**Interpretation:**
- These playlists (40-300 tracks) appear to load fully without requiring scroll
- Scroll loop correctly detects stability (3 rounds with no content change)
- `last_track` field confirms same final track across all scroll iterations

## Detailed Results

```
ok idx=1 url=https://music.apple.com/jp/playlist/ampm-thinking-may/pl.024712183de946b7be5ba1267d94e035 tracks=40 method=dom_rows row_prog=[81, 81, 81] uniq_prog=[1, 1, 1] last_track=['Moments Passed (Mike Dean Remix)|||Dermot Kennedy', 'Moments Passed (Mike Dean Remix)|||Dermot Kennedy', 'Moments Passed (Mike Dean Remix)|||Dermot Kennedy'] reason=None elapsed_ms=572

ok idx=2 url=https://music.apple.com/jp/playlist/beatstrumentals/pl.f54198ad42404535be13eabf3835fb22 tracks=300 method=dom_rows row_prog=[601, 601, 601] uniq_prog=[1, 1, 1] last_track=['buttercream|||Pistachio', 'buttercream|||Pistachio', 'buttercream|||Pistachio'] reason=None elapsed_ms=851

ok idx=3 url=https://music.apple.com/jp/playlist/me-and-bae/pl.a13aca4f4f2c45538472de9014057cc0 tracks=130 method=dom_rows row_prog=[261, 261, 261] uniq_prog=[1, 1, 1] last_track=['Catching Feelings|||Annie Tracy', 'Catching Feelings|||Annie Tracy', 'Catching Feelings|||Annie Tracy'] reason=None elapsed_ms=764

ok idx=4 url=https://music.apple.com/jp/playlist/オールインディー/pl.0e91490f3310408eb1186fc9befb3d11 tracks=112 method=dom_rows row_prog=[225, 225, 225] uniq_prog=[1, 1, 1] last_track=['Anticipate|||El Michels Affair', 'Anticipate|||El Michels Affair', 'Anticipate|||El Michels Affair'] reason=None elapsed_ms=508

ok idx=5 url=https://music.apple.com/jp/playlist/ナイトキャップ/pl.abf3cb0e85e64b659f399d2d77745dcb tracks=100 method=dom_rows row_prog=[201, 201, 201] uniq_prog=[1, 1, 1] last_track=['kill the thought|||cehryl', 'kill the thought|||cehryl', 'kill the thought|||cehryl'] reason=None elapsed_ms=993

ok idx=6 url=https://music.apple.com/jp/playlist/勉強がはかどるビート/pl.a4e197979fc74b2a91b3cdf869f12aa5 tracks=100 method=dom_rows row_prog=[201, 201, 201] uniq_prog=[1, 1, 1] last_track=['Tiny Sad Face|||Kilig', 'Tiny Sad Face|||Kilig', 'Tiny Sad Face|||Kilig'] reason=None elapsed_ms=1004

ok idx=7 url=https://music.apple.com/jp/playlist/アフロビーツ-ヒッツ/pl.dc349df19c6f410d874c197db63ecfed tracks=100 method=dom_rows row_prog=[201, 201, 201] uniq_prog=[1, 1, 1] last_track=['If You Leave|||Salle', 'If You Leave|||Salle', 'If You Leave|||Salle'] reason=None elapsed_ms=734

ok idx=8 url=https://music.apple.com/jp/playlist/ピュア-ヨガ/pl.6e7eb6c06bcd40ec982e24d6af0cd59a tracks=130 method=dom_rows row_prog=[261, 261, 261] uniq_prog=[1, 1, 1] last_track=['Apes & Children|||Lane 8', 'Apes & Children|||Lane 8', 'Apes & Children|||Lane 8'] reason=None elapsed_ms=687

ok idx=9 url=https://music.apple.com/jp/playlist/alt-ctrl/pl.0b593f1142b84a50a2c1e7088b3fb683 tracks=76 method=dom_rows row_prog=[153, 153, 153] uniq_prog=[1, 1, 1] last_track=['Eureka|||The Orphan The Poet', 'Eureka|||The Orphan The Poet', 'Eureka|||The Orphan The Poet'] reason=None elapsed_ms=242

ok idx=10 url=https://music.apple.com/jp/playlist/マンドポップ-失恋ソング/pl.13dc58ad0eda4543b2169ae0a4ef13f6 tracks=48 method=dom_rows row_prog=[97, 97, 97] uniq_prog=[1, 1, 1] last_track=['想見你想見你想見你 (電視劇《想見你》片尾曲)|||八三夭', '想見你想見你想見你 (電視劇《想見你》片尾曲)|||八三夭', '想見你想見你想見你 (電視劇《想見你》片尾曲)|||八三夭'] reason=None elapsed_ms=219
```

## Matrix Script Fixes Applied

The following issues were identified and fixed in `tools/apple_matrix.sh`:

1. **PORT parameter**: Added `PORT="${1:-8000}"` to allow specifying port
2. **HTTP code extraction**: Rewrote curl to output `HTTP_CODE:200` format
3. **Body validation**: Added checks for empty body and HTML body before JSON parse
4. **Encoding fix**: Used `LC_ALL=C tr '\n' ' '` to avoid "Illegal byte sequence" on Japanese URL-encoded chars
5. **Stdin piping fix**: Switched from `printf "$body" | python` to temp file approach (`$tmpfile` passed as arg) to avoid heredoc stdin conflicts with large JSON bodies

## Next Steps

### Immediate Actions
- [ ] Remove debug output (`[debug]` lines) from matrix script for production use
- [ ] Test with longer playlists (500-1000 tracks) to verify scroll loop works when content doesn't load fully on first render
- [ ] Add timeout handling for slow playlists (>30s)

### Future Enhancements
- [ ] Add geo-region testing (US, UK, JP, etc.)
- [ ] Expand canary set to 20-30 URLs covering various playlist sizes
- [ ] Add retry logic for transient failures
- [ ] Monitor scroll diagnostics for playlists that require multiple scroll iterations
