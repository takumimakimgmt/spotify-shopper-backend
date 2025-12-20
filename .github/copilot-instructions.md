
# Copilot Instructions for spotify-shopper

## Project Purpose & Architecture
- **Goal:** Analyze Spotify/Apple Music playlists, match to Rekordbox XML, and provide store links for DJs.
- **Backend:** Python 3.11, FastAPI, Spotipy, Playwright, RapidFuzz. Entrypoint: `app.py`. Core logic: `core.py` (playlist fetch, normalization, ISRC enrichment), `rekordbox.py` (XML parsing, matching).
- **Frontend:** Next.js 15, React 19, TypeScript. Entrypoint: `spotify-shopper-web/app/`. State/filters: `lib/ui/selectors.ts`, URL utils: `lib/utils/playlistUrl.ts`.

## Data Flow & Matching
- **Spotify:** Uses Spotipy API, paginated fetch, market fallback for region locks.
- **Apple Music:** Uses Playwright (headless browser) to scrape up to 100 tracks. Handles geo-blocks, consent, and bot detection (see `docs/APPLE_PROBE_GATES.md`).
- **Matching priority:** ISRC > exact > album > fuzzy (see `rekordbox.py`). Never overwrite Apple artist/album with Spotify data.
- **Normalization:** Lowercase, strip featured/remix/parentheticals, CJK handling. See normalization logic in `core.py` and `rekordbox.py`.

## Developer Workflows
- **Backend local run:**
  ```bash
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python -m playwright install chromium
  uvicorn app:app --host 127.0.0.1 --port 8000
  ```
- **Frontend local run:**
  ```bash
  cd spotify-shopper-web
  npm install
  NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:8000" npm run dev
  ```
- **Tests:**
  - Backend: `python -m unittest discover -s tests -p "test_*.py"`
  - Frontend: See QA checklist in `spotify-shopper-web/docs/QA_CHECKLIST.md`
- **Manual API test:**
  ```bash
  curl -sG "http://127.0.0.1:8000/api/playlist" --data-urlencode "url=<playlist_url>" --data-urlencode "source=apple|spotify"
  ```

## Key Conventions & Patterns
- **Error handling:** Bilingual (JP/EN), deployment-aware, playlist-type aware. See error logic in `core.py` and `rekordbox.py`.
- **Caching:** TTL cache via `cachetools` (see `core.py`). Use `refresh=1` to bypass cache.
- **Frontend filters:** All derived track lists/counts via `lib/ui/selectors.ts`. Filters: `categoryFilter`, `searchQuery`, `sortKey`, `onlyUnowned`.
- **CSV export:** Cells starting with =, +, -, @ are prefixed to prevent injection (`lib/utils/csvSanitize.ts`).
- **Project rules:** See `docs/PROJECT_RULES.md` for commit, review, and async safety policies. Never add new markdown docs unless requested.

## Integration & Deployment
- **Backend:** Render.com, see `render.yaml` for build/start (includes Playwright browser install). Env vars set in dashboard.
- **Frontend:** Vercel, standard Next.js build. Env vars: `NEXT_PUBLIC_BACKEND_URL`.
- **Distribution:** Use `git archive` for packaging (see `spotify-shopper-web/docs/DISTRIBUTION.md`).

## Debugging & Performance
- **Performance metrics:** Both frontend and backend log `[PERF]` lines. See `docs/START_HERE.md` and `docs/QUICK_RUN.md` for test flows. Results in `docs/PERF_RESULTS.md`.
- **Apple probe gates:** See `docs/APPLE_PROBE_GATES.md` for handling consent, geo, bot, and DOM issues.
- **Audit:** Full architecture and risk docs in `spotify-shopper-web/docs/audit/`.

## Key Files & References
- Backend: `app.py`, `core.py`, `rekordbox.py`, `playwright_pool.py`, `requirements.txt`, `render.yaml`, `tests/`
- Frontend: `spotify-shopper-web/app/`, `lib/ui/selectors.ts`, `lib/utils/playlistUrl.ts`, `lib/utils/csvSanitize.ts`, `docs/QA_CHECKLIST.md`
- Docs: `docs/START_HERE.md`, `docs/PROJECT_RULES.md`, `docs/APPLE_PROBE_GATES.md`, `docs/P1.1_IMPLEMENTATION_GUIDE.md`

---
For details, see the main README.md and docs/ in each project. If any section is unclear or missing, please provide feedback for improvement.
