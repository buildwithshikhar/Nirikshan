# Changelog

## Unreleased
- Project scaffold: FastAPI skeleton, React shell (navy/orange theme), CI, compose Postgres, Playwright smoke test.
- P1 evidence core: cases, read-only acquisition, MD5+SHA-256, Ed25519-signed hash-chained custody log, audit trail, UI.
- P1 hardening: acquisition restricted to `NIRIKSHAN_EVIDENCE_ROOTS`, block devices gated; DB triggers reject UPDATE/DELETE on custody/audit; `head_hash` shown with copy button and printed by `python -m app.cli head`; compose Postgres port overridable (`NIRIKSHAN_DB_PORT`).
- P2: vendor-agnostic H.264/H.265 carving, parser plugin interface and signature identification (Hikvision, Dahua, Honeywell: Tier B), `-c copy` MP4 export with decode test, per-clip hashes and custody entries, analysis API and UI.

