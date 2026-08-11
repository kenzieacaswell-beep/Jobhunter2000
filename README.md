# Next Move — private job tracker

A localhost-only job discovery and application tracker for early-career product and program roles. Jobs come from real ATS feeds; DeepSeek V4 Flash optionally parses and ranks them against a reviewed, redacted profile.

## Quick start

Prerequisites: macOS, Python 3.10+, Node/pnpm for the initial frontend build.

```bash
./scripts/install.sh
./scripts/job-tracker key
open http://127.0.0.1:8765
```

The installer creates a virtual environment, builds the React UI, initializes SQLite, seeds 27 editable sources in a disabled state, and registers a login service. In Companies, connect or review public job-board tokens, pull one board immediately, and enable the employers you want in scheduled refreshes.

For development:

```bash
.venv/bin/uvicorn app.main:app --reload --port 8765
cd frontend && pnpm dev
```

The Vite UI runs at port 5173 and calls the API at port 8765 when proxied or after a production build. Production serves the built UI directly from FastAPI.

## Privacy and secrets

- The database, resume PDF, extracted text, notes, and contacts remain under `data/` and are gitignored.
- The DeepSeek key is stored through macOS Keychain under `com.local.job-tracker`.
- Only the approved redacted profile, structured profile, preferences, and source job text are sent to DeepSeek.
- The API budget guard defaults to $5/month. Displayed spend is an estimate; DeepSeek billing remains authoritative.

## Gmail digest setup

Create an OAuth desktop client with Gmail Send scope, download it as `data/gmail-client.json`, set `digest_recipient` in Settings, then run `./scripts/job-tracker gmail-auth` once. The resulting OAuth token is stored in macOS Keychain. The daily refresh sends the digest automatically; `./scripts/job-tracker digest you@example.com` sends one manually. Gmail failures are isolated from ingestion.

## Operations

`./scripts/job-tracker` supports `start`, `stop`, `status`, `refresh`, `key`, `backup`, and `logs`. Backups are timestamped SQLite files under `data/`. CSV export is available from Settings.

## Source identifiers

- Greenhouse: the board name in `boards.greenhouse.io/<token>`
- Lever: the site name in `jobs.lever.co/<token>`
- Ashby: the board name in `jobs.ashbyhq.com/<token>`
- Recruitee: the careers-site subdomain in `<token>.recruitee.com`

Greenhouse, Lever, Ashby, and Recruitee listing feeds are public and require no API key. Source APIs and identifiers can change; a failed source is reported in Companies/System state and never produces synthetic jobs.
