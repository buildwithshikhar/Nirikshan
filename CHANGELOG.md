# Changelog

## Unreleased
- Project scaffold: FastAPI skeleton, React shell (navy/orange theme), CI, compose Postgres, Playwright smoke test.
- P1 evidence core: cases, read-only acquisition, MD5+SHA-256, Ed25519-signed hash-chained custody log, audit trail, UI.
- P1 hardening: acquisition restricted to `NIRIKSHAN_EVIDENCE_ROOTS`, block devices gated; DB triggers reject UPDATE/DELETE on custody/audit; `head_hash` shown with copy button and printed by `python -m app.cli head`; compose Postgres port overridable (`NIRIKSHAN_DB_PORT`).
- P2: vendor-agnostic H.264/H.265 carving, parser plugin interface and signature identification (Hikvision, Dahua, Honeywell: Tier B), `-c copy` MP4 export with decode test, per-clip hashes and custody entries, analysis API and UI.
- P3: seeded SYNTHETIC validation harness (22 scenarios incl. negatives), `make validate`, committed baseline, regression thresholds; carver hardening (parameter-set syntax validation, PPS-reference rule, EOF zero trimming, join log).
- P4 (Dahua): DHAV frame parser behind the plugin interface (parsed/inferred/unknown field tags, raw timestamps without timezone, generic cross-check, fallback on any inconsistency); per-paper DHAV layout for the validation harness; clips carry `engine`/`channel`.
- P4 (Hikvision): Master Sector/RATS/HIKBTREE parser with explicit options for the open block-size, timestamp-basis and Master Sector base conflicts; per-paper layout in the harness.
