# Security audit — 2026-11-03

Scope: local backend XML and API trust boundaries. This is not an assessment of live deployment configuration or evidence of compromise. Existing uncommitted work was retained.

## Findings addressed

- High: BackendProtectionMiddleware used request.url.path. Malformed Host headers can make this differ from the router path on the pinned Starlette release, bypassing authentication and rate limiting. Use scope['path'] for both decisions. Regression cases cover malformed Host headers. Reference: https://github.com/Kludex/starlette/security/advisories/GHSA-86qp-5c8j-p5mr
- High: Upload/local-path playlist APIs could dispatch source=apple to an arbitrary HTTP target; only GET had an Apple block. Validate source and exact Spotify playlist identity before network calls or upload persistence. Regression cases cover loopback, link-local, host suffixes, userinfo and file URLs without making actual outbound requests.
- High, configuration-dependent: production API protection silently disabled when BACKEND_PROXY_TOKEN was absent. Non-development environments now reject protected API requests with 503 until configured. Health remains available.
- Medium: forwarded client identities were trusted even without proxy authentication. They are now used only when the proxy token is configured and authenticated.
- Medium: malformed snapshot structures were processed after XML temporary files were created and could raise outside cleanup. Validate nested shapes, string sizes and track count before writing files.
- Medium: XML size alone did not limit structural complexity. Added depth, event count, track count and metadata-length limits. Existing defusedxml entity protection retained; external file entity rejection explicitly tested.
- Deployment template trusted all vercel.app previews. Restricted template to the intended production origin and disabled credentialed CORS. This does not change deployed environment values and CORS is not authentication.

## Validation

- pytest: 34 tests passed, 5 subtests passed.
- Ruff on changed Python files and git diff --check passed.
- Supplied real XML parsed 2,302 library tracks; prior playlist still matches 11 owned / 9 unowned out of 20.
- Tests exercise local ASGI requests and mocked network boundaries. No production exploit attempts performed.

## Follow-up remediation

- Updated compatible FastAPI/Starlette, multipart parser, HTTP and other vulnerable dependencies; regenerated requirements.txt. pip-audit reports no known vulnerabilities for the pinned production requirements on 2026-11-03. This is a database check, not proof of absence of vulnerabilities.
- Added dependency auditing to CI and pinned pip-audit as a development dependency.
- Heavy XML matching and optional enrichment now run outside the event loop. An ASGI gate admits at most two active API requests per worker (health exempt), rejects excess work before body parsing, and releases capacity after completion. Deployment explicitly uses one worker with an additional connection cap.
- Matching checks a 20-second cooperative deadline during track and fuzzy-candidate iteration; rejects more than 10,000 tracks rather than returning incomplete results. This is not hard process isolation or a hard deadline for a single expensive operation.
- XML parsed-library caching is disabled by default to avoid retaining shared user library metadata. Public playlist caching uses defensive copies and a 16 MiB serialized-payload budget. Python object overhead can exceed this budget.
- Redis rate checks use an atomic increment/expiry operation, bounded connection timeouts, and reject requests on Redis failure in production rather than silently weakening limits.
- Production errors no longer return raw upstream exception messages; Redis errors no longer log connection URLs.

Validation: 37 pytest tests passed (plus 5 subtests), Ruff and pip check passed. New regressions cover workload rejection/recovery, responsive health checks, distinct XML ownership outcomes and cached public-playlist immutability.

## Deployment and remaining limits

- Changes are local, not deployed. No Render/Vercel deployment credentials or CLI sessions were available. Actual production environment and access logs remain uninspected.
- Set the same server-only BACKEND_PROXY_TOKEN on frontend/backend and APP_ENV=production on backend before deploying. The frontend must be deployed with its proxy support before making the backend require this token.
- Render template changes do not automatically erase previously configured environment variables. Remove any old ALLOWED_ORIGIN_REGEX value and review actual ALLOWED_ORIGINS.
- Redis is needed for a rate limit shared across replicas. Connection/concurrency caps protect per-process resources; they are not a substitute for upstream distributed abuse protection.
- Further audit of matching accuracy, playlist completeness and cancellation remains separate from these security fixes. No claim of complete security or evidence of compromise is made.
