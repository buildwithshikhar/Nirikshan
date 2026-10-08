# Nirikshan

Vendor-agnostic surveillance forensics platform enabling standardized evidence acquisition, deleted video recovery, metadata analysis, timeline correlation, chain-of-custody tracking, and AI-powered investigation workflows.

Built for SIH PS 26150 (multi-vendor DVR/NVR forensic analysis).

**Status: working prototype, validated on SYNTHETIC data only.** Evidence core, carving and MP4 export, vendor parsers for Dahua (DHAV frames), Hikvision and Honeywell (all Tier B), timestamp/timeline model, analytics triage and offline packaging exist. **No real DVR/NVR image has been processed and no vendor is Tier A.** CP Plus, Uniview, TP-Link, Godrej and Matrix have generic carving only. A reproducible court-style PDF report, a **draft** BSA 63(4) certificate (not legal advice), a JSON-LD export, background analysis jobs with cancel, a one-command `make demo` (SYNTHETIC data) and an accessibility pass (axe gate) are included. See [docs/FINAL_REPORT.md](docs/FINAL_REPORT.md) for the requirement traceability matrix and honest limits, and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the plan.

## Screenshots

All screenshots show the SYNTHETIC demo case (`make demo`); the amber banner on every page says
the data is generated test data. Regenerate with `cd frontend && npm run screenshots`.

| | |
|---|---|
| ![Dashboard](docs/img/dashboard.png) | ![Case with evidence](docs/img/case.png) |
| ![Analysis with the parser panel](docs/img/analysis.png) | ![Timeline with unplaceable evidence](docs/img/timeline.png) |
| ![Triage analytics](docs/img/analytics.png) | ![Custody log](docs/img/custody.png) |

## Layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI service (`app/`), pytest suite (`tests/`), backend Dockerfile |
| `frontend/` | React + Vite + Tailwind UI, Playwright e2e (`e2e/`), frontend Dockerfile |
| `deploy/` | nginx config for the packaged frontend |
| `scripts/` | `fetch_models.py`, `model_manifest.py`, `licenses.py`, `build_final_report.py`, `eval_analytics.py` |
| `ml/` | Analytics triage package (Phase 6) |
| `docs/` | Architecture, API, research, SOPs, validation, security, licences, final report |
| `docker-compose.yml` | DEV ONLY Postgres (fixed password, published port) |
| `docker-compose.offline.yml` | Offline, hardened stack (backend + frontend, SQLite on a volume) |

## Demo (SYNTHETIC data only)

```
make demo
```

Starts the backend and the web UI with a throw-away data directory (`./demo-data`, demo-only
signing key), builds the case `DEMO-SYNTHETIC-001` from three generated images (Hikvision and Dahua
per-paper layouts, a raw H.264 image), runs the analysis as background jobs with progress, sets time
assumptions (one image is left with an unknown timezone on purpose), runs triage analytics and
prints the URLs. Ctrl-C stops everything. Every image, label and screen is marked SYNTHETIC: this is
generated test data, not real DVR/NVR evidence, and the demo does not validate any real device.
`make demo-data` builds the same case against a backend that is already running. Details:
[docs/demo.md](docs/demo.md); background jobs: [docs/jobs.md](docs/jobs.md); accessibility status:
[docs/accessibility.md](docs/accessibility.md).

## Development

Requires Python 3.10+, Node 22+, and `ffmpeg` with `ffprobe` (`brew install ffmpeg` on macOS).

```bash
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python ../scripts/fetch_models.py      # analytics weights, SHA-256 verified, not in git
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
NIRIKSHAN_EVIDENCE_ROOTS=/path/to/images .venv/bin/uvicorn app.main:app --reload

# frontend
cd frontend && npm ci && npm run lint && npm run build && npm run dev

# validation on SYNTHETIC images (writes docs/validation/, checks regression thresholds)
make validate

# optional Postgres (host port 5433; override if taken: NIRIKSHAN_DB_PORT=5434)
docker compose up -d db
# run the backend suite against it:
# TEST_DATABASE_URL=postgresql://nirikshan:nirikshan@localhost:5433/nirikshan .venv/bin/pytest -q
```

## Offline stack (Docker)

```bash
NIRIKSHAN_EVIDENCE_DIR=/path/to/images \
  docker compose -f docker-compose.offline.yml -p nirikshan-offline up -d --build
curl http://127.0.0.1:8080/health        # UI at http://127.0.0.1:8080
```

Backend and frontend run as non-root with read-only root filesystems and all capabilities dropped; the evidence folder is mounted read-only; the signing key lives on its own volume; the backend network is `internal` (no route out). **Caveat:** the frontend container was measured to have internet reachability on Docker Desktop; read [docs/OFFLINE_DEPLOYMENT.md](docs/OFFLINE_DEPLOYMENT.md) (air-gapped procedure, model checksum manifest, tested results) before relying on it. Make targets: `make offline-models`, `offline-build`, `offline-save`, `offline-up`, `offline-down`.

## Documentation
- Start here: [Final report](docs/FINAL_REPORT.md) (traceability matrix generated from [docs/traceability.yaml](docs/traceability.yaml) by `python scripts/build_final_report.py`), [Demo runbook](docs/DEMO_RUNBOOK.md)
- [User manual](docs/USER_MANUAL.md) and [SOPs](docs/sop/) (acquisition, hashing and integrity, recovery, timestamp handling, reporting)
- [Validation (SYNTHETIC)](docs/VALIDATION.md), [validation report draft](docs/VALIDATION_REPORT.md), [OEM comparison](docs/OEM_COMPARISON.md), [research basis](docs/RESEARCH.md)
- [Real-image playbook](docs/REAL_IMAGE_PLAYBOOK.md) and [hardware shopping list](docs/HARDWARE_SHOPPING.md)
- [Architecture](docs/ARCHITECTURE.md), [API](docs/API.md), [parsers](docs/parsers/), [timeline](docs/timeline.md), [analytics](docs/analytics/README.md)
- [Security review](docs/SECURITY_REVIEW.md) (threat model, hardening checklist, dependency audits in [docs/security/](docs/security/)), [Third-party licences](docs/THIRD_PARTY_LICENSES.md) (generated by `scripts/licenses.py`; includes a GPL ffmpeg flag)
- [Report](docs/report.md), [BSA 63(4) notes](docs/legal/BSA-63-4-notes.md), [SOP-06 intake checklist](docs/sop/SOP-06-evidence-intake-checklist.md); [jobs](docs/jobs.md), [demo](docs/demo.md), [accessibility](docs/accessibility.md)
