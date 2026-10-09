# API

Authentication (Round D): log in with `POST /api/auth/login` and send the returned token as `Authorization: Bearer <token>`. Roles: admin, examiner, reviewer, read-only; case content needs case membership (non-members get 404). The `X-Examiner` header is honoured only when `NIRIKSHAN_DEV_HEADER_AUTH=1` (default off; development, tests, `make demo`; unauthenticated attestation). Every `/api` request is written to the audit log. Details: `docs/security/auth.md`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness: `{status, service, version}` |
| GET | `/api/system` | Tool version, ffmpeg availability/version, mode (full/degraded), NTP status, signing key id, configured evidence roots, block-device flag |
| GET | `/api/signing-key` | Public Ed25519 key (hex) and key id |
| POST | `/api/cases` | Create case `{case_number, title, description?}`; 409 on duplicate number |
| GET | `/api/cases`, `/api/cases/{id}` | List / get cases |
| POST | `/api/cases/{id}/evidence` | Acquire `{source_path, label, write_blocker: yes\|no\|unknown}`; returns hashes. 403 if the resolved path is outside `NIRIKSHAN_EVIDENCE_ROOTS` or a block device is not enabled |
| GET | `/api/cases/{id}/evidence` | Evidence list |
| POST | `/api/evidence/{id}/verify` | Re-hash stored image, compare, log custody entry |
| POST | `/api/evidence/{id}/analyze` | Identify vendor + carve clips (body optional: `max_pad` 0-4096 default 64, `join_gap` 0-16 MiB default 0 = reassembly off, `h264_continuity` default true, `validate_params` default true). Reads the image only after re-verifying its hashes (409 + `carve_failed` custody entry on mismatch; 503 if ffmpeg/ffprobe are missing). `parser_options` (`{"<vendor>": {...}}`) are passed to matched vendor parsers. Synchronous. Returns the run with `parsers` (structured parse results: status, parsed/inferred/unknown fields, raw timestamps, inconsistencies, generic cross-check) and  `vendor_matches` (vendor, tier, confidence, evidence offsets, caveats), `stats`, timings and `clips` (kind `clip` or `orphan`, byte extents, SHA-256 of the carved bitstream and of the MP4, `decode_status` ok / decode_errors / export_failed, listed decode errors, nominal duration) |
| GET | `/api/evidence/{id}/runs`, `/api/runs/{id}` | Carve runs |
| GET | `/api/clips/{id}/video` | The exported MP4 (`video/mp4`, Range supported) |
| POST | `/api/clips/{id}/verify` | Re-hash the exported MP4 against the hash recorded at carve time (custody entry `clip_verified`) |
| GET | `/api/cases/{id}/custody` | Custody entries |
| GET | `/api/cases/{id}/custody/verify` | Chain + signature verification `{ok, entries, head_hash, key_id, failures[]}` |
| GET | `/api/audit?case_id=&limit=` | Audit trail |

CLI: `python -m app.cli head <case_id> [--json]` verifies the chain and prints `head_hash`.
CLI: `python -m app.cli reset-db --yes` (DEV ONLY) drops and recreates the schema; the app refuses to start on a database whose `schema_meta` version differs from the code's `SCHEMA_VERSION` (there are no migrations yet). `/api/system` reports `schema_version`.

Analytics (triage only): `GET /api/analytics/models`; `POST /api/clips/{id}/analytics` (motion/objects/faces with parameters; 503 with the fetch command if a model is missing, 409 if the clip's MP4 no longer matches its recorded hash); `GET /api/clips/{id}/analytics`; `GET /api/analytics/{run_id}`. Every result carries the label `triage, not identification`, model hash and error rates.

Timestamps and timeline: `GET/PUT /api/evidence/{id}/time-assumption`, `GET/POST /api/evidence/{id}/time-references`, `POST /api/evidence/{id}/time-model/fit`, `GET /api/cases/{id}/timeline`, `GET /api/cases/{id}/timeline/export?format=csv|json`, `POST /api/clips/{id}/osd-check`. Mutations need `X-Examiner` and are written to the custody log.

Reports and exports (P7): `POST /api/cases/{id}/report` (X-Examiner; stores the PDF, custody entry), `GET /api/cases/{id}/reports`, `GET /api/reports/{id}/download` (re-hashes; 409 on mismatch), `GET /api/cases/{id}/certificate-draft?evidence_id=` (DRAFT s.63(4) certificate PDF), `GET /api/cases/{id}/export.jsonld`.
Jobs (P8): `POST /api/evidence/{id}/jobs/analyze` (202; same request while active returns the existing job), `GET /api/jobs/{id}` (status, stage, progress), `GET /api/cases/{id}/jobs`, `POST /api/jobs/{id}/cancel` (202). `Evidence` responses include `synthetic`. `GET` endpoints need no `X-Examiner` header and no authentication (docs/SECURITY_REVIEW.md 2.1).



## Round D additions (Wave 1)

Unavailable capabilities answer `{"available": false, "reason": "..."}`; nothing returns placeholder data. "Write" = case member with role admin or examiner; "read" = any case member; "any" = any authenticated user. Rules live in `backend/app/auth/policy.py`.

**Auth and users** (`docs/security/auth.md`): `POST /api/auth/login` (public), `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/password`, `GET|POST /api/users`, `GET|PATCH /api/users/{id}`, `POST /api/users/{id}/password|unlock` (admin), `GET /api/cases/{id}/members` (member or admin), `POST /api/cases/{id}/members`, `DELETE /api/cases/{id}/members/{uid}` (admin). CLI: `create-admin`, `protect-key`, `key-status`.

**Approvals, transfers, packages** (`docs/package.md`): `POST /api/reports/{id}/request-approval` (write), `/approve`, `/reject` (reviewer or admin, not the author or requester), `/finalize`, `GET /api/reports/{id}/review`; `POST|GET /api/evidence/{id}/transfers`, `GET /api/cases/{id}/transfers`; `POST /api/cases/{id}/package` (write), `GET /api/cases/{id}/packages`, `GET /api/packages/{id}/download`, `GET /api/package-key` (public). CLI: `verify-package <zip>`.

**Workflow and performance** (`docs/workers.md`, `docs/performance.md`): `POST /api/clips/{id}/jobs/analytics`, `POST /api/jobs/{id}/then/analytics`, `POST /api/jobs/{id}/retry`, `POST /api/cases/{id}/jobs/batch`, `GET /api/cases/{id}/batches/{batch_id}`, `?depends_on=` on `POST /api/evidence/{id}/jobs/analyze`; `GET /api/cases/{id}/performance`, `GET|POST /api/cases/{id}/performance/baselines`.

**Acquisition and identification** (`docs/acquisition.md`, `docs/device-intelligence.md`): `GET /api/acquisition/capabilities`, `GET /api/acquisition/ewf` (not available), `POST|GET /api/cases/{id}/acquisitions`, `GET /api/acquisitions/{id}`, `POST /api/acquisitions/{id}/resume`, `GET /api/evidence/{id}/bad-sectors`, `POST /api/cases/{id}/native-exports`, `GET /api/evidence/{id}/native-export`, `GET /api/evidence/{id}/identification?refresh=`.

**Storage explorer and recovery** (`docs/storage-explorer.md`, `docs/recoverability.md`): `GET /api/evidence/{id}/hex?offset=&length=` (max 4096 bytes), `/regions`, `/partitions`, `/anomalies`; `GET /api/clips/{id}/recoverability`, `GET /api/recovery/fragment-reassembly`, `GET /api/recovery/agreement`.

**OEM registry** (`docs/oem-registry.md`): `GET /api/oem-registry` (16 targets, versioned data file checked against the parser registry).

**AI events** (`docs/events.md`; triage, not identification): `POST /api/cases/{id}/events/reindex` (also runs after each analytics run), `GET /api/cases/{id}/events/status`, `GET /api/cases/{id}/events/search?q=`, `GET /api/cases/{id}/summaries?by=clip|camera`, `GET /api/events/grammar`.

**Correlation** (`docs/correlation.md`; time, topology and class only): `GET|PUT /api/cases/{id}/correlation/topology`, `GET|PUT /api/cases/{id}/correlation/floorplan`, `GET|POST /api/cases/{id}/correlation/external-logs`, `GET /api/correlation/external-logs/{id}`, `POST /api/cases/{id}/correlation/links/generate`, `GET /api/cases/{id}/correlation/links`, `POST /api/correlation/links/{id}/decision`.

**Validation Center** (`docs/validation-center.md`; every number carries the circularity statement): `GET /api/validation/summary|scorecards|regression|false-rates|crosscheck`, `POST /api/validation/reruns` (admin or examiner), `GET /api/validation/reruns[/{id}]`.
