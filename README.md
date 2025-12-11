# Spotify Playlist Shopper

A full-stack application to analyze Spotify and Apple Music playlists and match them with your Rekordbox collection.

## 📋 Features

### Core Functionality
- **Dual Source Support**: Spotify and Apple Music playlists
  - **Spotify**: Via Spotipy API with client credentials
  - **Apple Music**: Playwright-based scraping with comprehensive metadata
- **Metadata Preservation**: Apple Music metadata (artist, album) never overwritten by Spotify enrichment
- **ISRC Enrichment**: Read-only ISRC enrichment from Spotify for better matching
- **Rekordbox Integration**: Match playlists against your Rekordbox XML collection
- **3-Tier Ownership Display**:
  - 🟢 **YES**: Confirmed match (ISRC or exact)
  - 🟡 **MAYBE**: Fuzzy match (0.92 threshold)
  - ⚪️ **NO**: Not found in collection
- **Store Links**: ISRC-optimized search links to Beatport, Bandcamp, iTunes

### Error Handling
- **Bilingual Messages** (Japanese/English):
  - Personalized/private playlists (Daily Mix, On Repeat, Blend)
  - Official editorial playlists (37i9)
  - Region-restricted playlists
- **Deployment-Aware Errors**: Helpful Render.com-specific messages

## 🏗️ Architecture

### Backend (Python 3.11 + FastAPI)
```
spotify-shopper/
├── app.py              # FastAPI endpoints
├── core.py             # Playlist fetching, metadata conversion
├── rekordbox.py        # Rekordbox XML parsing, match logic
├── render.yaml         # Render deployment config
└── requirements.txt    # Python dependencies
```

**Key Dependencies:**
- `spotipy` - Spotify API client
- `playwright` - Apple Music scraping (headless browser)
- `beautifulsoup4` - HTML parsing
- `rapidfuzz` - Fuzzy matching (0.92 threshold)
- `cachetools` - TTL caching for API responses

### Frontend (Next.js 15 + React 19 + TypeScript)
```
spotify-shopper-web/
├── app/
│   ├── page.tsx        # Main React component
│   ├── layout.tsx      # Root layout
│   └── globals.css     # Tailwind styles
├── package.json
└── tsconfig.json
```

## 🔧 Setup & Deployment

### Local Development

**Backend:**
```bash
cd spotify-shopper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

export SPOTIFY_CLIENT_ID="your_id"
export SPOTIFY_CLIENT_SECRET="your_secret"
uvicorn app:app --host 127.0.0.1 --port 8000
```

**Frontend:**
```bash
cd spotify-shopper-web
npm install
NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:8000" npm run dev
```

### Render Deployment (Backend)

Configuration in `render.yaml`:
```yaml
buildCommand: |
  set -e
  echo "Installing Python dependencies..."
  pip install -r requirements.txt
  echo "Installing Playwright browsers and dependencies..."
  python -m playwright install --with-deps chromium
  echo "Build complete"
startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT
```

**Environment Variables (Set in Render dashboard):**
- `SPOTIFY_CLIENT_ID` - Spotify app credentials
- `SPOTIFY_CLIENT_SECRET` - Spotify app credentials
- `SPOTIFY_MARKET` - Markets to try for region-restricted playlists (default: JP,US,GB)
- `ALLOWED_ORIGINS` - CORS allowed origins

### Vercel Deployment (Frontend)

**Build Settings:**
```
Build Command: npm run build
Output Directory: .next
```

**Environment Variables:**
- `NEXT_PUBLIC_BACKEND_URL` - Backend API URL (e.g., https://spotify-shopper-backend.onrender.com)

## 📊 Data Flow

### Spotify Playlist
```
Spotify URL/ID
    ↓
fetch_playlist_tracks() [core.py:288]
    ├─ Fetch playlist metadata via Spotipy
    ├─ Fetch all tracks (paginated) with market fallback
    └─ Convert to standard format
    ↓
playlist_result_to_dict() [core.py:390]
    └─ Extract track data with store links
    ↓
mark_owned_tracks() [rekordbox.py:265]
    ├─ Try ISRC match (exact)
    ├─ Try exact title/artist match
    ├─ Try album-based match
    └─ Try fuzzy match (0.92 threshold)
```

### Apple Music Playlist
```
Apple Music URL
    ↓
fetch_apple_playlist_tracks_from_web() [core.py:497]
    ├─ _fetch_with_playwright() [core.py:673]
    │   └─ Launch Playwright, load playlist, extract 100 tracks
    ├─ Parse track data: title, artist, album, URLs
    └─ Return raw playlist
    ↓
_enrich_apple_tracks_with_spotify() [core.py:719]
    ├─ Try to find each track on Spotify by title/artist
    ├─ Add ISRC to track (if found)
    └─ IMPORTANT: Never overwrite artist/album from Apple
    ↓
Same conversion & matching as Spotify
```

## 🔍 Matching Algorithm

**Priority order** (`rekordbox.py:265-300`):
1. **ISRC Match** (most reliable) → `owned_reason: "isrc"`
2. **Exact Match** (title + normalized artist) → `owned_reason: "exact"`
3. **Album Match** (any track from album) → `owned_reason: "album"`
4. **Fuzzy Match** (0.92+ similarity) → `owned_reason: "fuzzy"`
5. **No Match** → `owned: false`

**Normalization:**
- Convert to lowercase
- Remove featured artists (feat./ft./featuring)
- Remove remix/mix suffixes
- Remove parenthetical annotations
- Handle Japanese/CJK characters consistently

## 🌐 API Endpoints

### GET /api/playlist
```
Query params:
  url: string (playlist URL or ID)
  source: string (default: "spotify", or "apple")

Response:
{
  "playlist_id": "str",
  "playlist_name": "str",
  "playlist_url": "str",
  "tracks": [
    {
      "title": "str",
      "artist": "str",
      "album": "str",
      "isrc": "str|null",
      "spotify_url": "str|null",
      "apple_url": "str|null",
      "links": {
        "beatport": "str|null",
        "bandcamp": "str|null",
        "itunes": "str|null"
      },
      "owned": bool,
      "owned_reason": "isrc|exact|album|fuzzy|null"
    }
  ]
}
```

### POST /api/playlist-with-rekordbox-upload
```
Form data:
  url: string
  source: string (default: "spotify")
  file: File (Rekordbox XML)

Response: Same as /api/playlist
```

## ⚠️ Known Limitations

### Spotify API
- **Official Editorial Playlists (37i9)**: Region-locked, returns 404 without authentication
  - Workaround: Create a public playlist copy
- **Personalized Playlists**: Require user authentication (Daily Mix, On Repeat, Blend)
  - Workaround: Manually copy tracks to a public playlist

### Apple Music
- **Slow First Load**: Playwright needs to load full page (~2-5 seconds)
- **100-Track Limit**: Only fetches first 100 tracks from visible page
- **Browser Installation**: Requires `playwright install chromium` during build
  - Render build command includes this automatically

## 🚀 Recent Improvements

### Phase 7: Error Message Enhancement
- ✅ Render deployment fixed: Explicit Playwright browser installation
- ✅ 37i9 detection: Shows proper message for official playlists
- ✅ Bilingual errors: Japanese + English for all error cases
- ✅ Deployment-aware: Helpful hints for cloud platform issues

### Phase 6: Git Push & Deployment
- ✅ All changes committed and pushed to GitHub
- ✅ Render automatically redeploys on push
- ✅ Vercel auto-deploys frontend

### Phase 5-1: 3-Tier Ownership System
- ✅ Icon display: 🟢🟡⚪️ with hover tooltips
- ✅ Match reason tracking: isrc/exact/album/fuzzy
- ✅ ISRC-optimized store links

## 📝 Testing

**Test Spotify Playlist:**
```bash
curl "http://localhost:8000/api/playlist?url=6hqj0pPYIr2qiKb6B6YwLd"
```

**Test Apple Music:**
```bash
curl "http://localhost:8000/api/playlist?url=https://music.apple.com/jp/playlist/トップ100：日本/pl.043a2c9876114d95a4659988497567be&source=apple"
```

**Test 37i9 Error Message:**
```bash
curl "http://localhost:8000/api/playlist?url=37i9dQZF1DX4UtSsGT1Sbe"
```

## 🔗 Live URLs

- **Frontend**: https://spotify-shopper.vercel.app
- **Backend API**: https://spotify-shopper-backend.onrender.com
- **Backend Health**: https://spotify-shopper-backend.onrender.com/health

## 📄 License

MIT
