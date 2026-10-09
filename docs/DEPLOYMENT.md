# Deployment

Nirikshan is **reference test data and a forensic-recovery workbench, not a validated tool**: nothing here has been validated on a real device and no vendor is supported above Tier B. A **public instance must only ever hold reference data, never real evidence** (set `NIRIKSHAN_PUBLIC_INSTANCE=1`).

## What goes where

| Part | Needs | Hosts |
|---|---|---|
| Backend (FastAPI) | ffmpeg/ffprobe, ONNX models, a **persistent disk** (database, case data, signing keys), long-running jobs (subprocess workers) | Any Docker-capable host: one VM with Docker (recommended), a container platform with a persistent volume |
| Frontend (static Vite build) | nothing at run time | The nginx image in this repo (serves the app and proxies `/api`), **or** Vercel/any static host |

**Vercel can host the frontend only.** Its functions have no ffmpeg, no persistent disk and short time limits, so the backend cannot run there. With a split deployment the frontend calls the backend across origins (see "Split deployment").

## Single VM with Docker (recommended)

```bash
git clone https://github.com/buildwithshikhar/Nirikshan && cd Nirikshan
cp deploy/prod.env.example deploy/prod.env      # edit it (see the reference below)
NIRIKSHAN_EVIDENCE_DIR=/srv/evidence \
  docker compose -f docker-compose.prod.yml -p nirikshan-prod up -d --build
NIRIKSHAN_SMOKE_USERNAME=admin NIRIKSHAN_SMOKE_PASSWORD=... python scripts/smoke_test.py --base-url http://127.0.0.1:8080
```

- The image build downloads the analytics models and **verifies their SHA-256** (the build fails on a mismatch). ffmpeg comes from the Debian package.
- The backend runs as a non-root user (uid 10001) with a read-only root filesystem, no capabilities, and `no-new-privileges`. Data and keys are separate named volumes (`nirikshan_data`, `nirikshan_keys`). The evidence folder is mounted **read-only**; the only writable evidence location is the `nirikshan_incoming` volume (browser uploads).
- Both containers have healthchecks (`/healthz`). The frontend publishes `127.0.0.1:8080` by default (`NIRIKSHAN_BIND`, `NIRIKSHAN_PORT`).
- **TLS is not terminated by the stack.** Put a TLS reverse proxy (Caddy, nginx, a cloud load balancer) in front of the frontend port. Tokens and passwords cross the network in clear without it.
- SQLite is the default (single host, single writer). A Postgres 16 `DATABASE_URL` is supported.

## First admin

There is no default account. Either:

1. Set `NIRIKSHAN_FIRST_ADMIN_USERNAME` and `NIRIKSHAN_FIRST_ADMIN_PASSWORD_FILE` (a file whose first line is the password; or `NIRIKSHAN_FIRST_ADMIN_PASSWORD`) before the first start. The admin is created once, only while no active admin exists; remove the variables afterwards. The password is never printed or logged.
2. Or run `docker compose -f docker-compose.prod.yml -p nirikshan-prod exec backend python -m app.cli create-admin <username>` (prompts twice, never prints the password).

Then log in and create users under **Admin**. Password policy: at least 12 characters.

**Public demo (reference data only).** Seed the reference case as that admin, then create the read-only viewer:

```bash
NIRIKSHAN_DEMO_SEED_PASSWORD=... python scripts/demo.py --data-only --api-url https://HOST --login <admin> --evidence-dir <a folder inside the backend's evidence roots>
docker compose ... exec backend python -m app.cli create-demo-viewer     # prompts, or NIRIKSHAN_DEMO_VIEWER_PASSWORD_FILE
```

`demo-viewer` is a Read-only account that is a member of the `DEMO-REFERENCE-*` case(s) only. `make demo` and the demo accounts (with their published password) **refuse to run or be created when `NIRIKSHAN_PRODUCTION` is set**.

## Environment variables

Backend (validated at startup; with `NIRIKSHAN_PRODUCTION=1` a bad configuration stops the process and lists every problem):

| Variable | Default | Meaning |
|---|---|---|
| `NIRIKSHAN_PRODUCTION` | off | **The production flag.** Makes the settings below mandatory; refuses `NIRIKSHAN_DEV_HEADER_AUTH`; secure cookie by default; demo accounts cannot be created |
| `NIRIKSHAN_PUBLIC_INSTANCE` | off | Public/internet-facing, reference data only: disables browser uploads and block-device acquisition |
| `DATABASE_URL` | `sqlite:///./nirikshan.db` | Required in production. `postgresql://...` supported |
| `NIRIKSHAN_DATA_DIR` | `./data` | Case workspaces. Required in production (persistent volume) |
| `NIRIKSHAN_KEY_DIR` | `~/.nirikshan/keys` | Signing keys; must be outside the data dir; required in production (persistent volume, back it up) |
| `NIRIKSHAN_EVIDENCE_ROOTS` | none (deny all) | Folders sources may be read from, `:`-separated. Required in production |
| `NIRIKSHAN_INCOMING_DIR` | `<first root>/incoming` | Upload folder (0700); must be inside an evidence root |
| `NIRIKSHAN_MAX_UPLOAD_BYTES` | 2147483648 | Browser upload limit (the bundled nginx also caps the upload route at 2 GiB) |
| `NIRIKSHAN_ALLOW_BLOCK_DEVICES` | off | Block-device acquisition (never on a public instance; never verified on real disks) |
| `CORS_ORIGINS` | `http://localhost:5173` (dev) / none (production) | Allowed frontend origin(s), comma separated. Required in production; no `*`, no localhost |
| `NIRIKSHAN_ALLOWED_HOSTS` | unset | Optional Host-header allow-list |
| `NIRIKSHAN_COOKIE_SECURE` | on in production | `Secure` flag of the session cookie |
| `NIRIKSHAN_COOKIE_SAMESITE` | `strict` | `strict`, `lax` or `none` (`none` needs a secure cookie and enables CORS credentials) |
| `NIRIKSHAN_DEV_HEADER_AUTH` | off | Unauthenticated attestation for tests/dev. **Startup refuses it when `NIRIKSHAN_PRODUCTION` is set** |
| `NIRIKSHAN_SESSION_HOURS`, `NIRIKSHAN_SESSION_IDLE_MINUTES` | 8, 30 | Session lifetime |
| `NIRIKSHAN_TRUST_X_FORWARDED_FOR` | off | Behind a proxy that appends the client address |
| `NIRIKSHAN_FIRST_ADMIN_USERNAME`, `..._PASSWORD_FILE` / `..._PASSWORD`, `..._DISPLAY_NAME` | unset | First-admin bootstrap (above) |
| `NIRIKSHAN_DEMO_VIEWER_PASSWORD_FILE` / `..._PASSWORD` | unset | Password for `create-demo-viewer` |
| `NIRIKSHAN_KEY_PASSPHRASE_FILE` / `NIRIKSHAN_KEY_PASSPHRASE` | unset | Protects the signing keys at rest (`docs/security/auth.md`) |
| `NIRIKSHAN_DB_POOL_SIZE`, `NIRIKSHAN_DB_MAX_OVERFLOW`, `NIRIKSHAN_DB_POOL_TIMEOUT_S` | 20, 30, 30 | Database pool |
| `NIRIKSHAN_LOG_FORMAT`, `NIRIKSHAN_LOG_LEVEL` | `json`, `INFO` | Structured logs (method, path without query, status, ms, principal; never bodies, tokens or passwords) |
| `NIRIKSHAN_MODELS_DIR`, `NIRIKSHAN_JOB_WORKERS`, `NIRIKSHAN_ISOLATE_JOBS`, `NIRIKSHAN_WORKER_LIMITS` | image defaults | Models and subprocess workers with best-effort limits (`docs/workers.md`) |

Frontend (build time, Vite):

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_URL` | empty = same origin | Base URL of the backend for a **split deployment**, e.g. `https://api.example.org` (no trailing slash). Leave empty when the bundled nginx proxies `/api` |

## Split deployment (frontend on Vercel, backend elsewhere)

1. Backend host: set `NIRIKSHAN_PRODUCTION=1`, `CORS_ORIGINS=https://<your-frontend-origin>`, and the rest above; put TLS in front of it.
2. Vercel project (root `frontend/`): set `VITE_API_URL=https://<backend-host>`; `vercel.json` already rewrites app routes to `index.html`.
3. The app authenticates with a bearer token (sessionStorage). Clip playback then downloads the MP4 with the token instead of streaming it with the cookie, so very large clips load fully into browser memory first. Same-origin deployment (the bundled nginx) streams with Range requests.

## Database schema

The backend refuses to start on a database whose schema version differs from the code's (currently **11**); there are no migrations yet. A database from before schema 11 must be reset with `python -m app.cli reset-db --yes` (drops and recreates the schema; evidence files already on disk are not removed). Check `GET /api/system` (`schema_version`).

## Backup

Back up **both** named volumes (or the directories behind `NIRIKSHAN_DATA_DIR` and `NIRIKSHAN_KEY_DIR`) together: the data volume holds the database, acquired images, clips and reports; the key volume holds the custody and package signing keys. Without the keys, existing signatures can no longer be extended and new reports/packages are signed by a new key. Stop the backend (or snapshot the volume) while copying SQLite. The incoming volume holds uploaded files not yet acquired.

```bash
docker compose -f docker-compose.prod.yml -p nirikshan-prod stop backend
docker run --rm -v nirikshan-prod_nirikshan_data:/d -v nirikshan-prod_nirikshan_keys:/k -v "$PWD":/out alpine tar czf /out/nirikshan-backup.tgz /d /k
docker compose -f docker-compose.prod.yml -p nirikshan-prod start backend
```

## Public-instance warnings

- Reference test data only. Never load real evidence, real case numbers or real names.
- Uploads and block-device acquisition are disabled by `NIRIKSHAN_PUBLIC_INSTANCE=1`; give visitors only the `demo-viewer` account.
- The application does not terminate TLS, encrypt the database, or protect against someone with access to the host (`docs/security/auth.md`).
