# Validation matrix on SYNTHETIC images (see docs/validation/). Needs ffmpeg and backend/.venv.
.PHONY: validate validate-quick test demo demo-data offline-models offline-build offline-save offline-up offline-down
validate:
	cd backend && .venv/bin/python -m app.validation.run --seed 20260101 --trials 20 --out ../docs/validation --check

validate-quick:
	cd backend && .venv/bin/python -m app.validation.run --seed 20260101 --trials 3 --check

test:
	cd backend && .venv/bin/pytest -q

# One-command SYNTHETIC demo (backend + frontend, demo-only data dir ./demo-data, Ctrl-C stops).
# Needs ffmpeg, backend/.venv and frontend/node_modules. Flags: scripts/demo.py --help.
demo:
	backend/.venv/bin/python scripts/demo.py

# Build the SYNTHETIC demo case against an ALREADY RUNNING backend (DEMO_API, default
# http://localhost:8000). DEMO_EVIDENCE must lie under that backend's NIRIKSHAN_EVIDENCE_ROOTS.
DEMO_API ?= http://localhost:8000
demo-data:
	backend/.venv/bin/python scripts/demo.py --data-only --api-url $(DEMO_API) $(if $(DEMO_EVIDENCE),--evidence-dir $(DEMO_EVIDENCE))

# Offline packaging (see docs/OFFLINE_DEPLOYMENT.md). NIRIKSHAN_EVIDENCE_DIR must be set for up/down.
# offline-down omits -v on purpose: `down -v` would delete the case data and the signing-key volumes.
offline-models:
	backend/.venv/bin/python scripts/fetch_models.py && backend/.venv/bin/python scripts/model_manifest.py write

offline-build:
	docker compose -f docker-compose.offline.yml build

offline-save: offline-build
	docker save nirikshan-offline-backend nirikshan-offline-frontend | gzip > nirikshan-offline-images.tar.gz
	shasum -a 256 nirikshan-offline-images.tar.gz

offline-up:
	docker compose -f docker-compose.offline.yml -p nirikshan-offline up -d

offline-down:
	docker compose -f docker-compose.offline.yml -p nirikshan-offline down
