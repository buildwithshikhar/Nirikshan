# SOP-01: Evidence Acquisition (DRAFT)

*Audience: forensic examiners and their supervisors who bring a DVR/NVR disk image into Nirikshan.*

Status: draft written for Nirikshan v0.1.0. Written with reference to the guidance listed in `docs/RESEARCH.md` section 8 (NIST SP 800-86, read; SWGDE 17-V-002-1.4, page read; ISO/IEC 27037 and the ACPO guide, **not accessible to us, not read**). It has **not been audited** against any of them and makes no claim of compliance with ISO/IEC 27037, ACPO, NIST or SWGDE.

## 1. Purpose
Bring a disk image of a DVR/NVR hard disk into a Nirikshan case so that the evidence copy is hashed, read-only, and recorded in a signed, hash-chained custody log.

## 2. Scope
Covers acquisition of an **existing image file** (raw/dd) or a block device into a case workspace. It does not cover removing the disk from the recorder, imaging it, or exporting from the recorder's own menu. Those physical steps are the examiner's and are only attested to here. Not in scope: E01/AFF formats, live acquisition over the network, hardware write blockers (`IMPLEMENTATION_PLAN.md` P1).

## 3. Roles
| Role | Responsibility |
|---|---|
| Examiner | Performs the steps, enters their name (sent as the `X-Examiner` header; an attestation, not authentication) |
| Supervisor / reviewer | Checks the recorded hashes and `head_hash` against the external record |
| System administrator | Sets `NIRIKSHAN_EVIDENCE_ROOTS`, protects the signing key (SOP-02) |

## 4. Preconditions
1. Nirikshan backend runs and `GET /api/system` shows the expected tool version, ffmpeg available (mode `full`), and the evidence roots you intend to use.
2. `NIRIKSHAN_EVIDENCE_ROOTS` lists the folder(s) holding images. With none configured **every acquisition is refused (403)**.
3. The source image already exists, was produced by a method you can describe in the case notes, and ideally is marked read-only at the file-system level.
4. For a physical disk: you know whether a write blocker was used and which one (see Procedure step 2).
5. A place outside Nirikshan to record hashes and `head_hash` (paper log, case file, e-mail to a supervisor).
6. Time: note the workstation's clock status. The custody log stores the system clock in UTC and an NTP status (`synchronized` / `not_synchronized` / `unknown`; only systemd `timedatectl` is consulted, so macOS reports `unknown`).

## 5. Procedure
1. **Create the case** (Cases page, or `POST /api/cases`). Record case number and title in your own case file.
2. **Record the physical acquisition facts outside the tool first**: DVR/NVR make, model, firmware if visible, disk serial number, how the disk was removed, the write blocker model and serial (or "none"), the date and operator, and photographs. Never reconnect the disk to the recorder (reconnecting can alter it; Han 2015 via `docs/RESEARCH.md` section 8 implication note).
3. **Image the disk** with your imaging tool through a write blocker, and hash the image with that tool. Keep that hash; it is your independent comparison value.
4. **Place the image file inside an evidence root.** The path is resolved (`../` collapsed, symlinks followed), checked against the roots, and the resolved path is what is opened with `O_RDONLY|O_NOFOLLOW`. A path outside the roots returns 403.
5. **Acquire** (Case page, form with the "Acquire (read-only)" button, or `POST /api/cases/{id}/evidence`): enter the server-side source path, a label, and choose the **write-blocker attestation**: `yes`, `no` or `unknown`. Choose `unknown` rather than `yes` if you cannot state it. The tool stores this as your statement; **it cannot verify that a write blocker was used**.
6. The tool streams the source once, computes MD5 and SHA-256 in one pass, writes the copy to `<NIRIKSHAN_DATA_DIR>/cases/<id>/evidence/<evidence_id>.img` (mode 0444), re-reads the copy from disk and compares hash and size. On mismatch the copy is deleted, the evidence is marked `failed`, and an `acquisition_failed` entry is logged.
7. **Compare** the SHA-256 shown by Nirikshan with the hash your imaging tool reported in step 3. They must be equal. If not, stop (see Failure handling).
8. **Record externally**: both hashes, size, evidence id, and the case's `head_hash` (shown with a Copy button on the case and custody pages; also `cd backend && .venv/bin/python -m app.cli head <case_id>`).
9. Run **Verify** on the evidence once and confirm it passes; this writes an `evidence_verified` custody entry.

### Block devices (read this before use)
- Reading a block device directly requires `NIRIKSHAN_ALLOW_BLOCK_DEVICES=1`. It is off by default. Block devices are not subject to the evidence-root check.
- The tool opens block devices strictly read-only, but **acquisition of a real physical disk has not been verified**: it was only tested with file-backed fixtures and a mocked block-device stat (`IMPLEMENTATION_PLAN.md` P1). Prefer imaging with your normal tool first and acquiring the resulting file.
- The tool does not stop the operating system or other software from writing to a mounted disk. Only a write blocker (hardware) does that.

## 6. Records to keep
- Case file entries from step 2 (device, disk serial, write-blocker identity, photographs, operator, date).
- Imaging-tool hash and Nirikshan MD5/SHA-256 for each evidence item, size, evidence id.
- `head_hash`, entry count, and `key_id`, recorded outside the tool after every acquisition and at end of each session.
- Export of the custody log (`GET /api/cases/{id}/custody`) and the verify result (`.../custody/verify`).
- The public signing key (`GET /api/signing-key`) so the chain can be verified independently.

## 7. Integrity checks
- Both hashes equal the imaging tool's hash (step 7).
- `POST /api/evidence/{id}/verify` passes.
- `GET /api/cases/{id}/custody/verify` returns `ok: true`, and its `head_hash` equals your external record.
- Every later analysis re-verifies the image first; a mismatch stops the run (409, `carve_failed` entry).

## 8. Failure handling
| Symptom | Action |
|---|---|
| 403 on acquire | Path resolved outside `NIRIKSHAN_EVIDENCE_ROOTS`, or block device without the flag. Fix configuration; do not move the original. Note that the resolved path (after symlinks) is what is checked |
| `acquisition_failed` / status `failed` | The copy did not re-hash equal to the stream. Check disk space and the source medium; retry; keep the failed custody entry (it is part of the record) |
| Nirikshan hash differs from imaging-tool hash | Do not proceed. Re-image, check for a flaky source, and document both values |
| Verify fails later | Treat the stored image as compromised: stop analysis, preserve the evidence directory, compare with the original image, report |
| Custody verify not ok, or `head_hash` differs from your record | Do not continue; escalate. Tail truncation is detectable only against the external record |
| Database refused at startup (schema) | See USER_MANUAL troubleshooting. `reset-db` destroys the custody records of a development database and must never be used on a case you intend to rely on |

## 9. What the tool does NOT do
- It does **not** verify that a write blocker was used or that it worked; the attestation is yours.
- It does not authenticate examiners; the name is a header value.
- It does not prevent writes by other software to the source medium.
- It does not acquire from a DVR over the network or in its native export format.
- Real-disk (block device) acquisition is unverified.
- It does not protect against someone with the signing key forging entries, nor against deletion of the newest custody entries unless you recorded `head_hash` externally (SOP-02).
- A check-to-open race on the source path is narrowed (`O_NOFOLLOW` on the resolved path) but not eliminated.
- NTP status is `unknown` on non-systemd hosts; the UTC timestamps are only as good as the workstation clock.
