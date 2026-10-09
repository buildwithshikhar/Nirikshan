# Round D plan

Part 1 (this document's scope): Wave 1, the backend. Part 2: the frontend, built from `ROUND_D_UI_MAP.md`. Gap source: `PS_GAP_ANALYSIS.md`. Resume state: `ROUND_D_LOG.md`. Deferred items: `ROUND_D_DEFERRED.md`.

## Honesty rules (apply to code, UI text, docs, reports)
Reference test data only; no vendor above Tier B; no real-device claim; no mocked data in production paths; no invented vendor signatures or firmware strings (new OEM support only from a cited, documented source, otherwise Tier C with standard-export ingest and generic carving); anything not honestly buildable goes to `ROUND_D_DEFERRED.md` and the API answers "not available" with the reason; face detection is detection only (no recognition, no embeddings, no appearance matching; correlation uses time, camera topology and detection class only); authentication replaces the X-Examiner attestation as the identity source, and the docs state what it does and does not protect.

## Wave plan
| Stream | Scope | Owner of shared files |
|---|---|---|
| 1 | security, custody, workflow: auth/RBAC/case access, approvals and transfers, signed manifest + evidence package + `verify-package`, isolated workers + job chains/retries/batch, performance analytics, key-at-rest passphrase | main agent merges |
| 2 | acquisition (resume, bad-sector map, native-export ingest), device intelligence, storage explorer API, recoverability estimate, OEM registry (16 targets) | main agent merges |
| 3 | AI event index + query grammar + summaries, correlation + external logs, validation center API | after 1 and 2 |

At most two subagents at a time, each in its own git worktree; each stream puts code in new modules and does not edit `main.py`, `models.py`, `routes.py`, `schema.py`, `requirements*.txt` or docs indexes (the main agent does that when merging). Each table-adding stream bumps the schema version at merge time.

## API contract summary (all under `/api`, documented in `docs/API.md` as they land)
- Auth: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `/users` and `/cases/{id}/members` admin routes. Identity comes from the session token; `X-Examiner` is accepted only when `NIRIKSHAN_DEV_HEADER_AUTH=1` (default off).
- Approvals/transfers/packages: `/reports/{id}/approve`, `/reports/{id}/finalize`, `/evidence/{id}/transfers`, `/cases/{id}/package`, CLI `verify-package`.
- Workflow/perf: job chains, batch, retry; `/cases/{id}/performance`.
- Acquisition/identification/recovery: resume, bad-sector map, native-export ingest, `/evidence/{id}/identification`, `/evidence/{id}/regions`, `/evidence/{id}/hex`, `/clips/{id}/recoverability`, `/oem-registry`.
- Analysis: `/cases/{id}/events/search`, `/cases/{id}/summaries`, `/cases/{id}/correlation/*`, `/validation/*`.
- Every unavailable capability returns `{"available": false, "reason": "..."}`, never a placeholder result.

## Gates
Full backend suite on SQLite and on this repo's Postgres 16 compose db; ruff clean; pip-audit with new dependencies recorded in `THIRD_PARTY_LICENSES.md`; `make validate` thresholds; `make demo`; docs (`API.md`, `SECURITY_REVIEW.md`, `CHANGELOG.md`, tier tables, log); push `main`; one CI check.
