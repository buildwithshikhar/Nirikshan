# Architecture

Status: scaffold. The target architecture is described phase by phase in [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).

- **Backend** (`backend/app`): FastAPI + SQLAlchemy; SQLite by default, Postgres via `DATABASE_URL`.
- **Frontend** (`frontend/src`): React 19 + Vite + Tailwind 4; polls `/health` for backend status.
- **ml** (`ml/nirikshan_ml`): analytics triage, added in Phase 6.
