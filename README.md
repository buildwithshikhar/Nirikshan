# Nirikshan

Vendor-agnostic surveillance forensics platform enabling standardized evidence acquisition, deleted video recovery, metadata analysis, timeline correlation, chain-of-custody tracking, and AI-powered investigation workflows.

Built for SIH PS 26150 (multi-vendor DVR/NVR forensic analysis). Status: **scaffold only** — no forensic capability is implemented yet. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the phased plan and [docs/RESEARCH.md](docs/RESEARCH.md) for what is publicly documented per OEM.

## Layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI service (`app/`), pytest suite (`tests/`) |
| `frontend/` | React + Vite + Tailwind UI, Playwright e2e (`e2e/`) |
| `ml/` | Analytics triage package (Phase 6) |
| `docs/` | Architecture, API, research, SOPs |

## Development

Requires Python 3.10+, Node 22+, and `ffmpeg` (used from Phase 2 for MP4 export; install with `brew install ffmpeg` on macOS).

```bash
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
.venv/bin/uvicorn app.main:app --reload

# frontend
cd frontend && npm ci && npm run lint && npm run build && npm run dev

# optional Postgres (host port 5433; override if taken: NIRIKSHAN_DB_PORT=5434)
docker compose up -d db
# run the backend suite against it:
# TEST_DATABASE_URL=postgresql://nirikshan:nirikshan@localhost:5433/nirikshan .venv/bin/pytest -q
```
