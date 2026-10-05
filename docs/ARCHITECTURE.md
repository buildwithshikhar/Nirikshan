# Architecture

Phased plan: [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md). Current state: **P1 evidence core**.

- **Backend** (`backend/app`): FastAPI + SQLAlchemy; SQLite by default, Postgres via `DATABASE_URL` (Postgres is untested so far).
- **Frontend** (`frontend/src`): React 19 + Vite + Tailwind 4.
- **ml** (`ml/nirikshan_ml`): analytics triage, added in Phase 6.

## Evidence core (P1)

| Module | Responsibility |
|---|---|
| `evidence.py` | Opens sources `O_RDONLY` only (`open_source_readonly`), copies once into `<data>/cases/<id>/evidence/<evidence_id>.img` (mode 0444) while hashing, re-hashes the copy, `verify_evidence`, `open_verified` |
| `hashing.py` | Single-pass MD5 + SHA-256 (4 MiB chunks) |
| `custody.py` | Per-case hash chain; `verify_chain` |
| `signing.py` | Ed25519 key management and signing |
| `clock.py` | UTC timestamps, best-effort NTP status |
| `main.py` | Audit middleware: every `/api` request recorded in `audit_log` |

### Acquisition flow
1. Source is stat'ed; only regular files and block devices are accepted (`classify`). It is opened `O_RDONLY`; block-device size comes from `lseek`.
2. Bytes are streamed once, updating MD5 and SHA-256 and writing the copy.
3. The copy is made read-only and re-read from disk; hashes and size must equal the stream hashes. Failure deletes the copy, marks the evidence `failed` and logs `acquisition_failed`.
4. A signed `evidence_acquired` custody entry records hashes, size, source path/type, examiner and the write-blocker attestation (`yes`/`no`/`unknown`).

Analysis stages must call `open_verified()`: it re-hashes, logs an `evidence_verified` entry and refuses (`IntegrityError`) on any mismatch.

### Custody log
Each entry holds: `seq`, `timestamp_utc` (system clock, UTC), `action`, `evidence_id`, `examiner`, `tool_version`, `ntp_status`, canonical-JSON `details`, `prev_hash`, `entry_hash`, `signature`, `key_id`.
`entry_hash = SHA-256(canonical JSON of all fields except entry_hash/signature/key_id)`; `signature = Ed25519(entry_hash)`. `GET /api/cases/{id}/custody/verify` checks sequence continuity, `prev_hash` links, recomputed hashes and signatures; a chain recomputed by someone without the key fails on signatures.

### Key handling
- Private key: `$NIRIKSHAN_KEY_DIR/custody_ed25519.pem` (default `~/.nirikshan/keys`), generated on first use, mode 0600; refused if the directory is inside `NIRIKSHAN_DATA_DIR` or the file is group/world accessible.
- Back it up separately from case data. Losing it means old entries can no longer be verified by this installation; leaking it lets anyone forge entries. Rotation is not implemented (entries carry `key_id`, so verification of multiple keys can be added later).
- The public key is available from `GET /api/signing-key` for external verification; publish `head_hash` and `key_id` (reports, P7) to anchor the chain.

### Known limits
Examiner identity is an `X-Examiner` attestation, not authentication. Tail truncation of the custody log is detectable only against an externally recorded `head_hash`. The DB itself does not block UPDATE/DELETE on custody rows; tampering is detected, not prevented. Real-disk (block device) acquisition has only been tested with file-backed fixtures.
