# Validation matrix on SYNTHETIC images (see docs/validation/). Needs ffmpeg and backend/.venv.
.PHONY: validate validate-quick test
validate:
	cd backend && .venv/bin/python -m app.validation.run --seed 20260101 --trials 20 --out ../docs/validation --check

validate-quick:
	cd backend && .venv/bin/python -m app.validation.run --seed 20260101 --trials 3 --check

test:
	cd backend && .venv/bin/pytest -q
