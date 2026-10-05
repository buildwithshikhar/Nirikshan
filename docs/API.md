# API

Mutating calls (`POST`) require an `X-Examiner: <name>` header (attestation, not authentication). Every `/api` request is written to the audit log.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness: `{status, service, version}` |
| GET | `/api/system` | Tool version, ffmpeg availability/version, mode (full/degraded), NTP status, signing key id |
| GET | `/api/signing-key` | Public Ed25519 key (hex) and key id |
| POST | `/api/cases` | Create case `{case_number, title, description?}`; 409 on duplicate number |
| GET | `/api/cases`, `/api/cases/{id}` | List / get cases |
| POST | `/api/cases/{id}/evidence` | Acquire `{source_path, label, write_blocker: yes\|no\|unknown}`; returns hashes |
| GET | `/api/cases/{id}/evidence` | Evidence list |
| POST | `/api/evidence/{id}/verify` | Re-hash stored image, compare, log custody entry |
| GET | `/api/cases/{id}/custody` | Custody entries |
| GET | `/api/cases/{id}/custody/verify` | Chain + signature verification `{ok, entries, head_hash, key_id, failures[]}` |
| GET | `/api/audit?case_id=&limit=` | Audit trail |
