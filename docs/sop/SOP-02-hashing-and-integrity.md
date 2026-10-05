# SOP-02: Hashing, Verification and Custody-Chain Integrity (DRAFT)

*Audience: forensic examiners and system administrators responsible for keeping Nirikshan evidence and its custody record verifiable.*

Status: draft for Nirikshan v0.1.0. Written with reference to the guidance in `docs/RESEARCH.md` section 8 (NIST SP 800-86 read in full; SWGDE 17-V-002-1.4 page read, its integrity guidance is deferred to SWGDE 17-I-001 which we did not read; ISO/IEC 27037 and ACPO not accessible). **Not audited** against any of them; no compliance claim is made.

## 1. Purpose
Describe how evidence integrity is established, re-checked and demonstrated, and how the custody chain and its signing key are handled.

## 2. Scope
Image hashing at acquisition, verify-on-read before every analysis, clip and MP4 hash re-verification, custody chain and signature verification, signing-key handling and backups, and the recorded `head_hash`.

## 3. Roles
| Role | Responsibility |
|---|---|
| Examiner | Records hashes and `head_hash` externally, runs verifications |
| Reviewer | Independently verifies the chain using the public key and recorded `head_hash` |
| System administrator | Owns the signing key, backups, database and data directory permissions |

## 4. Preconditions
- Evidence acquired under SOP-01.
- `NIRIKSHAN_KEY_DIR` (default `~/.nirikshan/keys`) is **outside** `NIRIKSHAN_DATA_DIR`; the key file `custody_ed25519.pem` is mode 0600. The application refuses a key directory inside the data directory and a key file readable by group or others.
- A medium outside the Nirikshan host for recording `head_hash` (paper log, supervisor e-mail, case file).

## 5. Procedure
### 5.1 What is hashed and when
1. **At acquisition**: MD5 and SHA-256 are computed in a single pass over the source (4 MiB chunks) while the copy is written; the copy is then re-read from disk and both hashes and the size must match (`hashing.py`, `evidence.py`). Both hashes are recorded in the signed `evidence_acquired` entry. SHA-256 is the integrity value of record; MD5 is kept for compatibility with tools and procedures that still quote it. MD5 is not collision resistant and must not be the only hash relied upon (RESEARCH section 8 notes NIST SP 800-86's hash advice is dated; SHA-256 is our recommendation).
2. **Verify-on-read**: every analysis stage opens the image through `open_verified`, which re-hashes the file, writes an `evidence_verified` custody entry and refuses (`IntegrityError`, API 409 and a `carve_failed` entry) on any mismatch. You cannot analyse an image that no longer matches its recorded hashes.
3. **Derived data**: each carved clip records the SHA-256 of its raw bitstream and of the exported MP4 and the byte extents in the source image. `POST /api/clips/{id}/verify` (UI: "Verify MP4 hash") recomputes the MP4 hash and writes a `clip_verified` entry. The bitstream hash can be reproduced independently by concatenating the recorded extents from the image.

### 5.2 Routine verification
1. After acquisition and at the start and end of each working session: run **Verify** on each evidence item (Case page).
2. On the custody page press **Verify chain and signatures**. Confirm `ok`, entry count and `key_id`.
3. Record in your external log: date/time, entry count, `head_hash`, `key_id`. CLI alternative:
   `cd backend && .venv/bin/python -m app.cli head <case_id> [--json]` (exit code 0 valid, 1 invalid, 2 no such case).
4. Before relying on a result in a report, re-run steps 1 and 2 and compare `head_hash` with your last external record: the current chain must contain the recorded entry count, and the entry at that position must have the recorded hash.

### 5.3 What the chain check proves
`verify_chain` checks sequence continuity, `prev_hash` links, recomputed `entry_hash` values and Ed25519 signatures. Editing, deleting or reordering a middle entry fails. Recomputing the whole chain without the private key fails on signatures. `custody_entries` and `audit_log` also carry database triggers that reject UPDATE/DELETE (and TRUNCATE on Postgres), which is a safeguard against accidents and casual edits, not the integrity guarantee.

### 5.4 Key handling
1. The private key `custody_ed25519.pem` is generated on first use. Do not copy it into the data directory or into case folders.
2. **Back up the key separately from case data**, to a protected medium with controlled access, and record who holds the copy. Losing it means old entries can no longer be verified by this installation; leaking it lets the holder forge entries.
3. Publish or hand to reviewers the **public key** and `key_id` (`GET /api/signing-key`) so the chain can be verified without the private key.
4. Key rotation is **not implemented**. Do not replace the key file on a live installation: entries carry `key_id` but verification of multiple keys is not built.

### 5.5 Backups
Back up together: the database (SQLite file or Postgres dump), `<NIRIKSHAN_DATA_DIR>/cases/` (evidence copies, clips), and, separately, the signing key. After restoring, re-run Verify on all evidence and Verify chain, and compare with the external `head_hash` record.

## 6. Records to keep
- External log of `head_hash`, entry count and `key_id` per session and per acquisition.
- Imaging-tool hash vs Nirikshan hash comparison.
- Public key and `key_id`.
- Custody log export and chain verification output for each report.
- Backup inventory (what, where, when, who) including where the key copy is held.

## 7. Integrity checks (summary)
| Check | Command / location | Expected |
|---|---|---|
| Evidence re-hash | Case page "Verify" / `POST /api/evidence/{id}/verify` | hashes equal acquisition values |
| Chain + signatures | Custody page / `GET /api/cases/{id}/custody/verify` | `ok: true`, no `failures` |
| Head vs external record | `python -m app.cli head <id>` | equal to recorded value; entry count not lower |
| Clip MP4 | "Verify MP4 hash" | matches carve-time hash |

## 8. Failure handling
| Symptom | Likely meaning | Action |
|---|---|---|
| Evidence verify fails | Image bytes changed (corruption, disk fault, tampering) | Stop analysis; do not repair in place; compare with the original image and the imaging-tool hash; document |
| Chain verify lists a failure at entry N | Edit, deletion, reorder, wrong or replaced key, or database restore from a different state | Preserve database and key; do not append further entries; escalate; compare with an earlier backup and external record |
| Chain `ok` but `head_hash` differs from record, or entry count is lower | Tail truncation or rollback (valid shorter chain) | Treat as a possible integrity incident |
| Chain `ok` but `head_hash` differs and count is higher | Normal if work happened after your record; confirm the extra entries are expected | Review the new entries |
| Cannot verify old entries after reinstall | Signing key lost or replaced | Restore the key from backup; do not generate a new one on top |
| Clip MP4 hash mismatch | The exported file changed after carving | Re-export from the verified image (re-run analysis); keep the failed verify entry |

## 9. What the tool does NOT do
- **Tail truncation**: deleting the newest custody entries leaves a valid shorter chain. It is detectable only against a `head_hash` (and entry count) recorded outside the system.
- Whoever holds the signing key can forge entries; the database owner can drop the triggers. Tampering is detected (chain and signatures), not prevented.
- Examiner identity is an `X-Examiner` header attestation, not authentication; the audit trail records that value.
- It does not timestamp entries with a trusted external time source: entries carry the workstation clock in UTC plus an NTP status that is `unknown` on non-systemd hosts.
- It does not rotate keys, and it does not prove an image corresponds to the original disk; that rests on the imaging step and the examiner's records (SOP-01).
- A matching hash shows the stored bytes are unchanged since acquisition. It says nothing about whether those bytes are a faithful copy of the device or whether the device's own clock was correct.
