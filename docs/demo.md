# One-command demo (reference test data)

```
make demo
```

Needs `ffmpeg`, `backend/.venv` and `frontend/node_modules` (`npm ci`). Everything it creates is
reference test data: images we generated in per-paper vendor layouts, built from published
research and open-source format documentation, with known ground truth. They were not captured
from a physical DVR, and nothing in the demo validates a real device. The Hikvision and Dahua parsers were written from the same
documents as these layouts, so parsing them is a circular self-consistency check.

## What it does

1. Wipes and recreates `./demo-data` (gitignored): SQLite database, case workspaces, evidence
   images and a **demo-only signing key** (`demo-data/keys`; `~/.nirikshan` is never touched).
2. Starts the backend (uvicorn, default port 8100) and the Vite dev server (default 5273); logs go
   to `demo-data/backend.log` and `frontend.log`.
3. Through the HTTP API: creates case `DEMO-REFERENCE-001`; builds three reference-data images with the
   validation-harness builders (Hikvision layout, Dahua DHAV layout, raw H.264) in `demo-data/evidence`,
   each starting with the 256-byte machine marker ("NIRIKSHAN SYNTHETIC TEST IMAGE - NOT REAL DVR DATA", intentionally unchanged); acquires them; runs three analysis **jobs**
   (progress is polled and printed); sets time assumptions (Asia/Kolkata, invented notes) for the
   Hikvision and Dahua images, adds two invented reference observations and fits a drift model for
   the Dahua image; leaves the raw image's **timezone unknown on purpose** (its clips are
   unplaceable); runs motion, objects and faces analytics on one clip (objects/faces are skipped
   with a message if the models are not fetched); generates the report only if
   `POST /api/cases/{id}/report` exists, otherwise prints that it was skipped.
4. Prints the API, web and case URLs. Ctrl-C stops both servers cleanly.

## Flags (`backend/.venv/bin/python scripts/demo.py ...`)

| Flag | Meaning |
|---|---|
| `--data-dir DIR` | demo data directory (default `./demo-data`) |
| `--api-port N`, `--web-port N` | preferred ports (a free one is used if taken) |
| `--keep` | keep an existing data dir instead of wiping it |
| `--no-web` | API only |
| `--exit-after-seed` | stop everything after the data is built (used by tests) |
| `--data-only --api-url URL [--evidence-dir DIR]` | only build the demo case against a running backend |

## `make demo-data`

Builds the same case against an already running backend (`DEMO_API`, default
`http://localhost:8000`). The images are written to `DEMO_EVIDENCE` (default `./demo-data/evidence`),
which must lie under that backend's `NIRIKSHAN_EVIDENCE_ROOTS`. If the case already exists it is
reported, not duplicated. The e2e global setup and the README screenshots use this path.
