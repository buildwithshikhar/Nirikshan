# Round D deferred items

Items that could not be built honestly in Wave 1, with the reason. The API returns an explicit "not available" state for each.

## Stream 2 (acquisition, device intelligence, explorer, recovery, OEM registry)

| Item | Reason | API state |
|---|---|---|
| E01/EWF ingest | libewf/pyewf is LGPL-3.0-or-later: adoptable as an unmodified dynamically linked library (like psycopg), so the licence is not the blocker. Deferred because it is a new dependency for the shared `requirements.txt`, needs a native libewf build in the image, and no E01 test image can be produced here (no `ewfacquire`), so it could not be tested. Workaround: `ewfexport` to raw outside Nirikshan (outside its custody), then acquire the raw file. | `GET /api/acquisition/ewf` and `capabilities.ewf`: `{"available": false, "reason": ...}` |
| Byte-level storage parsing / identification for CP Plus, Uniview, TP-Link, Godrej, Matrix, Axis, Bosch, Hanwha Vision, VIVOTEK, Avigilon, Pelco, Tiandy, Reolink | No public byte-level documentation found (time-boxed search 2026-10-09, `docs/oem-registry.md`). Registered Tier C: standard-export ingest + generic carving only. | `/api/oem-registry` rows say `proprietary_storage_parsing: none`; identification returns `manufacturer.status: unknown` with the reason |
| Firmware identification (all vendors) | No documented on-disk firmware field for Hikvision, Dahua or Honeywell (Honeywell's firmware appears only in a UI screenshot of the source). | `device.firmware.status: unknown` with the reason |
| Verification of vendor-signed exports (e.g. AXIS Camera Station signed exports) | The signature scheme is not documented in the source read. The file is hashed and ingested; its vendor signature is not checked. | not offered; registry limitation text says so |
| Recoverability agreement for parser-engine clips | The measurement harness scores generic-engine clips only; the rule applies to parser clips but its agreement there is unmeasured. | `GET /api/clips/{id}/recoverability` gives the estimate with the limitation; `measured_agreement` describes the generic-engine measurement only |
## Stream 3 (events, correlation, validation center)

| Item | Why it is deferred | What the API says |
|---|---|---|
| Per-frame evidence byte offset for an AI event | Detections are made on decoded frames of the exported MP4. The carver records the clip's byte extents in the evidence image, but no mapping from a decoded frame back to the byte range of its NAL units is stored, so a per-frame offset would be a guess. | Every search hit gives the clip's byte range and extents plus `source.frame_byte_offset = {"available": false, "reason": ...}`. |
| Clock drift inside one clip | Event UTC = clip start interval + nominal in-clip offset (frame / stream fps). Drift models are fitted per evidence item at the clip start; nothing measures drift or frame-rate irregularity within a clip. | Documented in `docs/events.md`; the uncertainty bar is the clip-start bar shifted, not widened. |
| Validation re-run through `app.jobs` | The job system's rows require a case and an evidence item (foreign keys); a validation run has neither. Re-runs use a single, time-limited subprocess with its own table instead (`docs/validation-center.md`). | Not an "unavailable" state; the re-run endpoint works, with this limitation stated. |
## Stream 1 (security, custody, workflow)

| Item | Status | Reason | What exists instead |
|---|---|---|---|
| OS-level network isolation of workers (Linux network namespace / seccomp, macOS sandbox profile) | Deferred | Needs privileges or platform-specific profiles that cannot be tested on the development host (macOS, unprivileged); claiming it untested would be dishonest | Best-effort in-process socket guard, tested (`docs/workers.md`); the offline Docker network for the backend container |
| Hard memory limit for workers on macOS | Partial | macOS does not enforce `RLIMIT_AS` | Sampled physical-footprint watchdog (0.5 s); `RLIMIT_AS` on Linux |
| Isolation of the synchronous `POST /api/evidence/{id}/analyze` and `POST /api/clips/{id}/analytics` | Partial | Those routes live in shared modules and are kept unchanged for compatibility | Background job routes run isolated; the UI should use them |
| SSO / LDAP / OIDC / MFA / client certificates | Deferred | No identity provider or hardware tokens in scope; local accounts only | Local users with scrypt hashes, sessions, lockout (`docs/security/auth.md`) |
| TLS | Deferred (deployment) | The application does not terminate TLS | Bind to loopback, or a TLS-terminating reverse proxy |
| Client address in `audit_log` | Deferred to merge | Needs a column on the shared `AuditEntry` model (`models.py`) | Session rows record the login address; audit rows record the authenticated principal |
| Database encryption | Not provided | The app does not encrypt SQLite/Postgres | Documented disk-encryption guidance (FileVault, LUKS, BitLocker) |
| Visible status stamp inside a final report PDF | Partial | Rewriting the PDF would change the SHA-256 already in the custody log | Status in `X-Nirikshan-Report-Status`, in the download file name and in the package manifest |
| Signing-key rotation (several valid public keys) | Deferred | Needs a key registry and a verification policy decision | Entries and packages carry `key_id`; protected keys at rest |
| Report generation time in "time saved" | Deferred | Report generation duration is not stored | `time_saved` covers `analyze` and `analytics`; other tasks return `available: false` |
