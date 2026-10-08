# Nirikshan User Manual (DRAFT)

*Audience: forensic examiners who will install Nirikshan and use it to acquire, analyse and document DVR/NVR disk images.*

Status: draft for Nirikshan v0.1.0 (P1 evidence core, P2 carving and export, P3 synthetic validation, P4 vendor parsers, parser-first pipeline). Everything described in sections 1 to 8 exists in the code. Section 9 lists features that are **in progress or planned** and are not available. **No vendor is Tier A: nothing in this tool has been validated on a real DVR/NVR image.** Procedures that carry evidential weight are in the SOPs: [SOP-01](sop/SOP-01-acquisition.md), [SOP-02](sop/SOP-02-hashing-and-integrity.md), [SOP-03](sop/SOP-03-recovery.md), [SOP-04](sop/SOP-04-timestamp-handling.md), [SOP-05](sop/SOP-05-reporting.md).

## 1. Install and run

Requirements: Python 3.10 or newer, Node 22 or newer, and `ffmpeg` with `ffprobe` (`brew install ffmpeg` on macOS; use your package manager elsewhere).

```bash
# backend (terminal 1)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
export NIRIKSHAN_EVIDENCE_ROOTS=/path/to/images        # required, see below
.venv/bin/uvicorn app.main:app --port 8000

# frontend (terminal 2)
cd frontend
npm ci
npm run dev                                             # http://localhost:5173
```

The UI proxies `/api` and `/health` to `http://localhost:8000` (override with `VITE_PROXY_TARGET`). The backend allows browser origin `http://localhost:5173` by default (`CORS_ORIGINS`).

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `NIRIKSHAN_EVIDENCE_ROOTS` | none | Folders (separated by the OS path separator, `:` on Linux/macOS) from which images may be acquired. **With none set every acquisition is refused (403).** Paths are resolved (`../`, symlinks) before the check |
| `NIRIKSHAN_DATA_DIR` | `./data` | Case workspaces: evidence copies (mode 0444) and exported clips |
| `NIRIKSHAN_KEY_DIR` | `~/.nirikshan/keys` | Custody signing key `custody_ed25519.pem`, generated on first use with mode 0600. Must be **outside** `NIRIKSHAN_DATA_DIR` and not group/world readable, or the application refuses it |
| `NIRIKSHAN_ALLOW_BLOCK_DEVICES` | off | Set to `1`, `true` or `yes` to allow reading block devices. Real-disk acquisition is unverified (SOP-01) |
| `DATABASE_URL` | `sqlite:///./nirikshan.db` | SQLAlchemy URL. Postgres 16 is supported (`docker compose up -d db`, host port 5433, user/password/db `nirikshan`) |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed browser origins |

Back up the signing key separately from case data (SOP-02).

### Schema guard and reset

The database carries a schema version. A fresh database is created and stamped. A database from an older build is **refused at startup** with instructions; there are no migrations yet. For a **development** database only:

```bash
cd backend && .venv/bin/python -m app.cli reset-db --yes
```

This drops every table (cases, evidence records, custody log, runs, clips). Files already on disk are not removed, but without the database their custody record is gone. **Never run it on a case you intend to rely on.** `GET /api/system` reports `schema_version`.

## 2. Dashboard (`/`)

Shows the tool version, whether ffmpeg is installed ("not installed (degraded mode)" means MP4 export and analysis are unavailable), the clock NTP status and the custody signing key id. The three summary cards are placeholders and show a dash; they are not counters.

What to look for: ffmpeg present; NTP status (`synchronized`, `not_synchronized` or `unknown`; only systemd hosts are probed, so macOS shows `unknown`); the key id you expect.

## 3. Cases (`/cases`)

Create a case with a case number and title (description optional). Duplicate case numbers are rejected (409). The list shows number, title, examiner and creation time (UTC). The examiner name is an attestation sent with each change, not a login.

## 4. Case page (`/cases/<id>`): acquisition and evidence

**Acquire (read-only)**: enter the server-side source path (must be inside an evidence root), a label, and the write-blocker attestation (`yes`, `no`, `unknown`). The tool opens the source read-only, copies it into the case workspace while computing MD5 and SHA-256 in one pass, re-reads the copy and compares. The attestation is **your statement; the tool cannot verify it**. Read SOP-01 first.

**Custody head_hash** (shown with a Copy button): record it outside Nirikshan after every acquisition and session (SOP-02). A truncated log is detectable only against that record.

**Evidence table**: label and source type, size, MD5 and SHA-256, the write-blocker value ("WB"), status and last verification. **Verify** re-hashes the stored copy and logs a custody entry. **Analyze** opens the analysis page.

What to look for: status not `failed`; hashes equal to your imaging tool's; verification passes; `WB` shows what you attested.

## 5. Custody log (`/cases/<id>/custody`)

A table of every custody entry: sequence number, time (UTC, workstation clock), action, examiner, NTP status, tool version and details. **Verify chain and signatures** checks sequence, hash links, recomputed hashes and Ed25519 signatures and shows the entry count, `head_hash` and `key_id`; failures list the entry and reason. Compare `head_hash` and the entry count with your external record.

What to look for: `ok`; no gaps; actions you recognise (`evidence_acquired`, `evidence_verified`, `clip_carved`, `carve_completed`, `clip_verified`, and failure entries such as `acquisition_failed` or `carve_failed`, which are part of the record and must not be ignored).

## 6. Analysis page (`/evidence/<case>/<evidence>`)

Controls: **Identify + carve**; **Fragment join gap** (bytes; 0 = off, the default; leave it off unless you have a reason, SOP-03); **Parser options** (JSON by vendor, for example `{"Hikvision": {"block_size_mode": "1gib"}}` or `{"Dahua": {"frame_gap_tolerance": 3}}`). The page states that carving results are leads, not a statement of what was recorded. The run is synchronous: large images take time. The image hash is re-verified first.

### Reading the results

**Vendor identification.** Vendor, **Tier**, and **confidence** (`low` or `medium`; `high` is never shown because no vendor is Tier A), then the offsets and detail of each signature found, plus caveats. "Unknown vendor" means no documented signature was found; generic carving still ran.

| Tier | Meaning | Today |
|---|---|---|
| A | Validated on real images with ground truth we created | **No vendor** |
| B | Public byte-level signature identified; generic carving available; parsers exist but are not validated on real devices | Hikvision, Dahua, Honeywell |
| C | Planned only; generic carving may run but the vendor is not attributed | CP Plus, Uniview, TP-Link, Godrej, Matrix |

Confidence is the strength of the signature match only. It is not a probability that the vendor attribution is correct.

**Parser panel** (one per matched parser): name, **Tier** (parsing does not change it) and status. `parsed`: (Hikvision parser definition) at least one clip and no inconsistency; `partial`: something was found but with inconsistencies or limits; `fallback`: the parser could not proceed and the generic carver's results stand.

Each field has a chip:

| Chip | Meaning | How to treat it |
|---|---|---|
| parsed (green) | Read from bytes at a position the source documents | Still unverified on real devices, quote with the tier caveat |
| inferred (amber) | Our reading or a heuristic | Do not present as established |
| unknown (grey) | Present but not interpreted (for example Dahua's checksum byte) | Report as unknown |

Raw timestamps appear with the raw integer, its format, the plain decode "as stored" and **"timezone: not assumed"**. Do not convert them yourself without evidence (SOP-04). Warnings and inconsistencies appear in amber. The **cross-check** line lists parser clips, generic clips and each disagreement by kind (see SOP-03 for what each kind means).

**Run summary**: run id, status, tool and ffmpeg versions, timings, counts of clips, orphans, decode errors, export failures.

**Clip table**: engine (`generic` or the vendor) and codec, channel where a parser read one, byte offsets (decimal and hex), size, SHA-256 of the carved bitstream and of the MP4, resolution, **nominal** duration (stream frame rate, not recording time), frame count, decode test status (`ok`, `decode_errors`, `export_failed`) with listed errors, notes (for example "reassembled (heuristic)"), a preview player and **Verify MP4 hash**. A clip that decodes `ok` is not thereby proven byte-faithful or complete (SOP-03).

**Orphan fragments**: video-like data that could not become a clip (for example slices with no preceding key frame and parameter sets). Listed with byte ranges and not exported.

## 7. Command line

```bash
cd backend
.venv/bin/python -m app.cli head <case_id> [--json]    # verify chain, print head_hash. exit 0 valid, 1 invalid, 2 no such case
.venv/bin/python -m app.cli reset-db --yes             # DEV ONLY, destroys the database contents
make validate                                          # regenerate the SYNTHETIC validation baseline (about 80 s; needs ffmpeg and backend/.venv)
make validate-quick                                    # 3 trials per scenario
make test                                              # backend test suite
```

The same functions are available over HTTP; see [API.md](API.md). All mutating calls need an `X-Examiner` header; every `/api` request is written to the audit log.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Dashboard says ffmpeg not installed; analysis returns 503 | Install ffmpeg and ffprobe, make sure they are on the backend's `PATH`, restart the backend |
| `uvicorn` "address already in use" | Another process holds port 8000. Stop it or start with `--port 8001` and set `VITE_PROXY_TARGET=http://localhost:8001` for the frontend. For Postgres in Docker, host port 5433 can be changed with `NIRIKSHAN_DB_PORT` |
| Frontend shows "API unavailable" | Backend not running, wrong port, or the origin is not in `CORS_ORIGINS` |
| Backend refuses to start with a schema message | The database is from an older build. For a development database run `python -m app.cli reset-db --yes`; otherwise keep the old build to read it (there are no migrations) |
| Acquire returns 403 | Path resolves outside `NIRIKSHAN_EVIDENCE_ROOTS`, no roots configured, or a block device without `NIRIKSHAN_ALLOW_BLOCK_DEVICES` |
| Backend refuses the signing key | `NIRIKSHAN_KEY_DIR` is inside `NIRIKSHAN_DATA_DIR`, or the key file is group/world accessible: move it and `chmod 600` |
| Analyze returns 409 | The stored image no longer matches its hashes: stop and follow SOP-02 |
| Browser cannot play a clip | Browser support for H.264/H.265 varies (Chromium builds may lack H.264). The MP4 is served with `Range`; download it or play it in a standard player. This was not tested in a browser during automated tests |
| Parser status `fallback` | Expected when the layout is not recognised; generic results stand |
| Custody verify not ok | See SOP-02 section 8 |

## 9. In progress and planned (NOT available in this version)

These items are described so you know what is coming; do not rely on them or cite them.

- **Timestamp normalization and timeline (P5, now implemented; see [timeline.md](timeline.md). This manual does not yet give step-by-step instructions for it).** Intended: the examiner enters the device time zone and reference times; an unknown time zone is never defaulted; an OCR cross-check of burned-in on-screen time; a drift model with intervals; a cross-camera timeline with uncertainty carried into exports. Today only raw values are shown (SOP-04).
- **Analytics triage (P6, now implemented; see [analytics/README.md](analytics/README.md). This manual does not yet give step-by-step instructions for it).** Intended: motion, object and face *detection* only, run on CPU and offline, every output labelled "triage, not identification", with model version, parameters and measured error rates stored. Not identification, not recognition.
- **Court-style PDF report (P7, built on another branch, not in this tree `[[PENDING-MERGE: A]]`).** Intended contents are in SOP-05 section 10. Today reports are assembled manually (SOP-05).
- Also not built: Dahua DHFS file-system parsing (only DHAV frames), vendor parsers for CP Plus, Uniview, TP-Link, Godrej and Matrix, E01/AFF image formats, acquisition over the network, authentication of examiners, key rotation, schema migrations.
