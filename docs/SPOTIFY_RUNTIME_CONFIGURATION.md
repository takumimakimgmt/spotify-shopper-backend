# Spotify runtime configuration

Spotify app: Playlist Shopper (owner-identified). The application reads SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET on Render. No application-name inference or production credential values are stored in this document.

Production (RENDER set or APP_ENV=production/prod/staging) ignores local .env and .env.local files. Set both Spotify variables explicitly in the Render Environment settings before deployment. The repository's render.yaml declares their names but not their values. For local development, process values win over .env.local, which wins over .env defaults. No token or credential is returned by health checks.

App credentials remain a singleton Client Credentials client for the existing public endpoint. Authenticated user playlist reads are handled separately by Vercel and never forwarded into this client's shared cache. See the frontend's docs/SPOTIFY_CONNECTION.md for the optional PKCE connection and deployment prerequisites.

Spotify provider errors are translated to stable public error codes with preserved HTTP semantics: 401/app-token failures and credential configuration become SPOTIFY_AUTH_CONFIG/503; 403 access restriction; 404 missing/inaccessible playlist; 429 rate limit with bounded Retry-After; provider 5xx becomes 502. Codes deliberately avoid claiming that every 403 means a private playlist. Underlying provider messages are not returned for these classified errors.
