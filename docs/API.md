# API

Mutating calls (`POST`) require an `X-Examiner: <name>` header (attestation, not authentication). Every `/api` request is written to the audit log.

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
