# Offline (air-gapped) Deployment

Files: `backend/Dockerfile`, `frontend/Dockerfile`, `deploy/nginx.conf`, `docker-compose.offline.yml`, `scripts/model_manifest.py`, `.dockerignore`. All commands run from the repository root. Threat model and residual risks: [SECURITY_REVIEW.md](SECURITY_REVIEW.md). This is packaging for a single-host install, not a hardened appliance; it has no authentication (SECURITY_REVIEW 2.1).

## 1. What is in the stack

| Service | Image | User | Network | Notes |
|---|---|---|---|---|
| backend | `nirikshan-offline-backend` (python:3.12-slim, Debian ffmpeg/ffprobe, pinned Python wheels, models at `/opt/nirikshan/models`) | uid 10001 | `internal` (Docker `internal: true`, no route out) | `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, `/tmp` tmpfs, port 8000 not published |
| frontend | `nirikshan-offline-frontend` (Vite static build on `nginxinc/nginx-unprivileged`) | uid 101 | `internal` + `edge` | proxies `/api/` and `/health` to the backend; published only on `127.0.0.1:${NIRIKSHAN_PORT:-8080}` |
| database | none: SQLite file on volume `nirikshan_data` | | | single host, single writer. Postgres is supported by the code (`DATABASE_URL`) but is not packaged in this file |

Volumes: `nirikshan_data` (cases, acquired images, clips, SQLite), `nirikshan_keys` (custody signing key; separate volume, mounted only into the backend, never in the image), and the evidence folder bind-mounted `:ro` at `/evidence` (`NIRIKSHAN_EVIDENCE_DIR`, required). `NIRIKSHAN_EVIDENCE_ROOTS=/evidence`; block devices stay disabled.

## 2. Models: two supported routes

Models are not in git. Both routes are checksum-pinned by `backend/app/analytics/registry.py`.

**A. Baked into the image (default).** The `models` build stage runs `scripts/fetch_models.py` (SHA-256 verified, deletes the download on mismatch), then writes and re-verifies a manifest with `scripts/model_manifest.py`; any mismatch fails the build. Needs network at *build* time only.

**B. Air-gapped transfer of weights (read-only volume or directory).**
1. On a connected machine: `python scripts/fetch_models.py` (fills `backend/models/`), then `python scripts/model_manifest.py write` (creates `backend/models/SHA256SUMS`).
2. Transfer `backend/models/*.onnx` and `SHA256SUMS` on approved media.
3. On the target: `cd models && sha256sum -c SHA256SUMS` (plain coreutils) and/or `python scripts/model_manifest.py verify --dir models --manifest models/SHA256SUMS` (also compares with the hashes pinned in the code, so a manifest altered together with its files fails).
4. Mount the directory read-only over `/opt/nirikshan/models` (add `- ./models:/opt/nirikshan/models:ro` to the backend `volumes`). The application re-checks the pinned SHA-256 each time it loads a model and refuses a mismatch.

The OCR models ship inside the `rapidocr-onnxruntime` wheel and are covered only by the package pin (SECURITY_REVIEW 2.9).

## 3. Build on a connected machine, transfer, run offline

```
# connected machine
docker compose -f docker-compose.offline.yml build
docker save nirikshan-offline-backend nirikshan-offline-frontend | gzip > nirikshan-offline-images.tar.gz
sha256sum nirikshan-offline-images.tar.gz        # record on the transfer sheet
# air-gapped host (after verifying the hash)
gunzip -c nirikshan-offline-images.tar.gz | docker load
NIRIKSHAN_EVIDENCE_DIR=/cases/incoming docker compose -f docker-compose.offline.yml -p nirikshan-offline up -d
curl -s http://127.0.0.1:8080/health
```

Base images (`python:3.12-slim`, `node:22-alpine`, `nginxinc/nginx-unprivileged:1.27-alpine`) are referenced by tag, not digest; record the image IDs after build. The Debian `ffmpeg` package is a GPL build ([THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)).

## 4. Verification performed (2026-10-09, Docker Desktop 29.7.2, macOS arm64, project `nirikshan-offline`)

| Check | Result |
|---|---|
| Image sizes (as reported by `docker images`, uncompressed on disk / content size) | backend 1.48 GB / 385 MB; frontend 76.5 MB / 21.9 MB |
| `GET /health` through the published frontend port | `{"status":"ok","service":"nirikshan-api","version":"0.1.0"}` |
| `GET /api/system` | ffmpeg 7.1.5 (Debian), mode full, `evidence_roots: ["/evidence"]`, block devices false |
| Models | both reported `installed: true` |
| Functional smoke | created a case, acquired a 6-byte file from `/evidence` (hashes returned), custody verify `ok: true`, `/etc/passwd` acquisition refused with 403, `POST /analyze` completed on that file (0 clips, as expected) |
| `id` | backend uid 10001 (nirikshan); frontend uid 101 (nginx) |
| Backend egress | TCP connect to 1.1.1.1:53 and 8.8.8.8:443: "Network is unreachable"; DNS lookup fails |
| **Frontend egress** | **NOT blocked**: `wget http://1.1.1.1` from the frontend container returned a page, with or without `enable_ip_masquerade: "false"` on the `edge` network. Docker cannot publish ports from an `internal: true` network (tested). Mitigate with a host firewall rule (below) |
| Evidence mount | `touch /evidence/x`: "Read-only file system" |
| Root filesystem | `touch /app/x`: "Read-only file system" |
| Capabilities / privileges | CapEff `0000000000000000`; NoNewPrivs 1 |
| Key and data dirs | keys dir mode 0700 on its own volume; signing key id stable across container recreation (volume persisted) |
| Teardown | `docker compose -p nirikshan-offline down -v`, then `docker rmi nirikshan-offline-backend nirikshan-offline-frontend`; no `nirikshan-offline*` containers, volumes or networks left |

Not tested: a native Linux engine (where the masquerade option and firewall rules behave differently), amd64 images (the build was arm64), an actual analytics run on a clip inside the container (models were confirmed installed, ffmpeg export path was exercised only on an empty result), Postgres, a 1 GB+ image, and the pre-merge Stream A/B features.

## 5. Making "no outbound" true for the frontend

On a Linux host, drop forwarded traffic from the compose `edge` network except to the host, for example (adapt the subnet from `docker network inspect nirikshan-offline_edge`):

```
iptables -I DOCKER-USER -s <edge-subnet> ! -d <edge-subnet> -j DROP
```

Rule placement and interaction with published ports must be tested on the target; this was not tested here. Alternative: serve the static files from a host web server and run only the backend container.

## 6. Operations notes

- Backup the `nirikshan_keys` volume separately and offline; losing it means old custody entries can no longer be verified here; leaking it lets anyone forge entries (ARCHITECTURE "Key handling").
- A schema change in the code makes the backend refuse to start on an older database volume (no migrations yet).
- Analysis is synchronous; the nginx read timeout is 3600 s.
- Logs go to the container's stdout; configure Docker's log driver per your retention policy.
