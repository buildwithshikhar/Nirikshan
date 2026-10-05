# Architecture

Phased plan: [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md). Current state: **P1 evidence core + P2 carving**.

- **Backend** (`backend/app`): FastAPI + SQLAlchemy (schema is created with `create_all`; there are **no migrations yet**, so an existing development database must be recreated after schema changes, e.g. `carve_runs.parse_json`, `clips.engine`); SQLite by default, Postgres via `DATABASE_URL` (the P1 suite, including the append-only triggers, passed against Postgres 16 from the compose file).
- **Frontend** (`frontend/src`): React 19 + Vite + Tailwind 4. Pages: cases, case/evidence, custody log, per-evidence analysis (vendor evidence, clip table with offsets/hashes/decode status, MP4 preview, orphans).
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

### Source path policy
`NIRIKSHAN_EVIDENCE_ROOTS` (os.pathsep-separated) lists the only folders acquisition sources may come from; with none configured every acquisition is refused (403). The requested path is resolved (`../` collapsed, symlinks followed) first, the policy is applied to the resolved path, and that resolved path is what is opened (`O_RDONLY|O_NOFOLLOW`). Block devices are not subject to roots but need `NIRIKSHAN_ALLOW_BLOCK_DEVICES=1`. The custody entry records both the requested and resolved path. Residual risk: a path swapped between check and open by someone with write access to an evidence root (TOCTOU) is narrowed by opening the resolved path with `O_NOFOLLOW`, not eliminated.

### Acquisition flow
1. Source is stat'ed; only regular files and block devices are accepted (`classify`). It is opened `O_RDONLY`; block-device size comes from `lseek`.
2. Bytes are streamed once, updating MD5 and SHA-256 and writing the copy.
3. The copy is made read-only and re-read from disk; hashes and size must equal the stream hashes. Failure deletes the copy, marks the evidence `failed` and logs `acquisition_failed`.
4. A signed `evidence_acquired` custody entry records hashes, size, source path/type, examiner and the write-blocker attestation (`yes`/`no`/`unknown`).

Analysis stages must call `open_verified()`: it re-hashes, logs an `evidence_verified` entry and refuses (`IntegrityError`) on any mismatch.

### Custody log
Each entry holds: `seq`, `timestamp_utc` (system clock, UTC), `action`, `evidence_id`, `examiner`, `tool_version`, `ntp_status`, canonical-JSON `details`, `prev_hash`, `entry_hash`, `signature`, `key_id`.
`entry_hash = SHA-256(canonical JSON of all fields except entry_hash/signature/key_id)`; `signature = Ed25519(entry_hash)`. `GET /api/cases/{id}/custody/verify` checks sequence continuity, `prev_hash` links, recomputed hashes and signatures; a chain recomputed by someone without the key fails on signatures.

### Recording the head_hash outside the system
The chain alone cannot reveal that the newest entries were deleted. **Record `head_hash` outside Nirikshan** (signed paper log, case file, email to a supervisor, the P7 report) at the end of each session and after every acquisition. Later, a mismatch between the recorded value and the current chain (or a chain that is shorter than the entry count you recorded) proves truncation or rollback. `head_hash` is shown with a Copy button on the case and custody pages, returned by `GET /api/cases/{id}/custody/verify`, and printed by the CLI:

```
cd backend && .venv/bin/python -m app.cli head <case_id> [--json]   # exit 0 = valid, 1 = invalid, 2 = no such case
```

### Key handling
- Private key: `$NIRIKSHAN_KEY_DIR/custody_ed25519.pem` (default `~/.nirikshan/keys`), generated on first use, mode 0600; refused if the directory is inside `NIRIKSHAN_DATA_DIR` or the file is group/world accessible.
- Back it up separately from case data. Losing it means old entries can no longer be verified by this installation; leaking it lets anyone forge entries. Rotation is not implemented (entries carry `key_id`, so verification of multiple keys can be added later).
- The public key is available from `GET /api/signing-key` for external verification; publish `head_hash` and `key_id` (reports, P7) to anchor the chain.

### Known limits
Examiner identity is an `X-Examiner` attestation, not authentication. Tail truncation of the custody log is detectable only against an externally recorded `head_hash`. `custody_entries` and `audit_log` have BEFORE UPDATE/DELETE triggers (SQLite and Postgres; also TRUNCATE on Postgres, see `app/triggers.py`) so direct SQL edits fail. A database owner/superuser can still drop the triggers; that is exactly what the hash chain and signatures detect, so the triggers are a safeguard against accidents and casual edits, not the integrity guarantee. Real-disk (block device) acquisition has only been tested with file-backed fixtures.

## Vendor-agnostic carving (P2)

Code: `backend/app/carving/` (`nal.py` scanner, `carve.py` clip builder, `export.py` MP4 export, `bits.py` header parsing).

**Scanner (`nal.scan`).** Streams the image in 4 MiB chunks (memory O(chunk)) and yields Annex-B start codes and zero runs. Start codes that straddle chunk boundaries are handled by carrying the unfinished tail; tests compare results across chunk sizes from 1 byte upward. A NAL unit ends at the next start code or at a run of 3+ zero bytes that is not a start code (emulation prevention guarantees `00 00 00/01/02` never occur inside a NAL, so this is how trailing zeros and zero-filled gaps are detected).

**NAL header layouts** (checked against FFmpeg `h2645_parse.c` and `hevc/hevc.h`, master, 2026-10-05; cited in `nal.py`): H.264 = 1 byte (`forbidden(1) ref_idc(2) type(5)`); H.265 = 2 bytes (`forbidden(1) type(6) layer_id(6) temporal_id_plus1(3)`), type = `(b0>>1)&0x3F`. The ITU-T texts themselves were not available to us.

**Clip builder (`Carver`).** A clip begins at an IRAP picture (H.264 IDR; H.265 BLA/IDR/CRA) accompanied by parameter sets (SPS+PPS; VPS+SPS+PPS for H.265) and continues while NAL units are plausible and contiguous (max padding 64 bytes by default). It ends on: a gap, an invalid NAL header, an implausible slice header, new parameter sets, an oversize NAL, or (H.264) a `frame_num` discontinuity, which catches foreign data spliced into a clip. Anything that cannot become a clip is returned as an **orphan** (slices without a preceding IRAP + parameter sets, or an IRAP without parameter sets) with its byte range; nothing is dropped silently. Optional H.264 **fragment reassembly** (`join_gap`, off by default) joins runs across a gap when the next slice has a known PPS and a continuing `frame_num`.

**Export (`export_clip`).** Extents are concatenated into a raw bitstream (SHA-256 recorded), muxed with `ffmpeg -c copy` (never re-encoded; tests assert every slice NAL in the MP4 is byte-identical to the input), then the raw bitstream is **decoded** to detect damage. Statuses: `ok`, `decode_errors` (MP4 is kept, errors listed), `export_failed`. `-avoid_negative_ts make_zero` is required: without it, B-frame streams copied from a raw bitstream lose two frames when the MP4 is decoded. Durations come from the stream frame rate (ffmpeg assumes 25 fps without timing info) and are **not** wall-clock recording durations.

### Known limits (not hidden)
- **Encrypted payloads** are not handled; they carve as noise or not at all.
- **MJPEG / MPEG-4 Part 2** streams (seen in the Dahua DHAV codec table) have no NAL start codes and are not carved.
- **Interleaved multi-channel streams** without channel IDs are carved as one stream: frames from different cameras can be merged or split by the parameter-set/`frame_num` rules; channel demultiplexing needs vendor metadata (P4).
- **Random non-zero garbage** between NAL units cannot be distinguished from payload and is absorbed into the preceding NAL; only the decode test reveals it. Zero-filled gaps are detected exactly.
- **H.265** has no continuity check and no reassembly (needs POC/DPB logic); a gap ends the clip.
- Fragment reassembly is a heuristic: with a 4-bit `frame_num` a wrong candidate passes the test about 1 time in 8. It stays off by default and joined clips are labelled `reassembled`.
- Vendor headers inside the stream (e.g. DHAV frame headers, Honeywell 20-byte headers) are not stripped in P2; they sit between NAL units and show up as absorbed bytes or as decode errors until the P4 parsers handle them.
- Measured recovery rates on ground-truth images are produced in P3, not claimed here.

## Device identification and the parser plugin interface (P2)

Code: `backend/app/vendors/`. A `VendorParser` declares `vendor`, `tier` (`B` or `C`, never `A`), `sources` (RESEARCH sections), and contributes fixed-offset `probes()` and byte `signatures()` (each with an optional structural validator). `ParserRegistry.identify()` runs **one streaming pass** over the image for all parsers' signatures (bounded memory, boundary-safe) and returns `Match` objects: vendor, tier, confidence, evidence offsets (first 20 per signature; exact total counts reported), the RESEARCH basis and caveats. Optional `enumerate()` (structured parsing, P4) and `carve_hints()` exist on the interface but are unused by the generic carver.

| Vendor | Signatures used (all from docs/RESEARCH.md) | Best confidence |
|---|---|---|
| Hikvision | `HIKVISION@HANGZHOU` at 0x200 (Master Sector), `HIKBTREE`, `RATS` + documented follower bytes | medium: Master Sector at 0x200, or two distinct signature kinds; else low |
| Dahua | `DHAV` frame whose length field and `dhav` + u32 trailer agree (dhav.c arithmetic); `DAHUA` file prefix (exported file) | medium: >= 3 verified frames; else low |
| Honeywell | 20-byte custom header (`82/02`, `80 01 00`, start code at +20, plausible length/time) + Machine Data `HN<digits>` at sector 34 | medium: >= 3 headers and Machine Data; else low |

**Confidence semantics.** `medium` = a documented signature was found *and* structurally validated; `low` = a weaker or single signature. `high` is never produced because no vendor is Tier A (validated on a real image of our own). CP Plus, Uniview, TP-Link, Godrej and Matrix have no public signature, so they have no parser; their images are carved generically and the vendor stays "unknown". CP Plus is not assumed to be Dahua-compatible. Honeywell's tools repository is unlicensed and was not used. `OFNI` (Hikvision IDR table) is documented but too short to identify reliably without parsing, so it is not used in P2.

## Analysis pipeline and custody (P2)

`app/analyze.py::analyze` is the only caller of the carver. It runs inside `evidence.open_verified` (one hash verification per run; a mismatch aborts with `carve_failed`), identifies the vendor, scans and carves, and exports each clip as soon as it is found (streaming, so memory stays bounded). Per run it writes `carve_runs` and `clips` rows (orphans are `clips` rows with `kind='orphan'`) and custody entries: `evidence_verified`, one `clip_carved` per clip (extents, byte count, SHA-256 of the carved bitstream and of the MP4, decode status, ffmpeg version; tool version and examiner are on every entry), and `carve_completed` (parameters, vendor matches, counts, scan throughput). Exported MP4s are read-only (0444) under `<data>/cases/<case>/clips/<evidence>/run<id>/`.

### Measured scan throughput (not a guarantee)
2 GiB synthetic image (35% H.264/H.265 clips, 30% random noise, 35% zero fill; 550 clips), Apple-silicon Mac, Python 3.10, page-cache warm, no export: **identify 224 MiB/s** (one pass, all vendors' signatures), **carve scan 569 MiB/s** (about 81,600 NAL units), peak RSS 80 MiB including the two source streams the generator keeps in memory. Export time (ffmpeg mux + decode test) is extra and scales with clip count. Cold-disk and real-device numbers are untested.

## Validation harness (P3)

`backend/app/validation/`: `streams.py` (ffmpeg testsrc2 variants, aux MJPEG/MPEG-4), `image.py` (builder + byte-comparison ground truth), `scenarios.py` (the matrix), `score.py` (metrics, Wilson intervals, join classification), `run.py` (runner, JSON/Markdown, digest), `thresholds.py/.json` (regression guard). Method, results and limits: [VALIDATION.md](VALIDATION.md). The carver gained `validate_params` (SPS/PPS/VPS syntax checks plus "slice must reference a PPS from the clip"), trailing-zero trimming at EOF, and a join-decision log (`Carver.join_log`) used to measure the reassembler's false-accept rate.

## Vendor parsers (P4)

Interface: `VendorParser.parse(f, size, options) -> ParseResult | None` (`backend/app/vendors/parse.py`). Rules for every parser:
- **Fallback, never crash.** Any inconsistency or exception yields `status` `partial`/`fallback` plus warnings; the generic carver always runs on the same image and its output is kept next to the parser's (`clips.engine` = `generic` or the vendor name), never silently replaced.
- **Parsed vs inferred vs unknown.** Every field is tagged `parsed` (read from bytes the source documents), `inferred` (our reading or a heuristic) or `unknown` (present but undocumented/unverified, e.g. Dahua's checksum byte). A parser must not report a field it did not parse.
- **Raw timestamps only.** `RawTimestamp(field, offset, raw, format, wall_clock_as_stored, tz_basis="not assumed")`. No timezone is assumed; P5 normalizes.
- **Cross-check.** `crosscheck()` compares parser clips with generic clips on the same image and lists every disagreement (`parser_clip_not_found_by_generic`, `generic_clip_not_explained_by_parser`, `codec_mismatch`, `frame_count_mismatch`, `generic_includes_extra_bytes`; the last two are expected benign effects of vendor headers).
- **Tiers do not change** with parsing: Dahua, Hikvision and Honeywell stay Tier B.
- Parser options are passed per vendor in the analyze request (`parser_options: {"Dahua": {...}}`) and echoed in results and custody entries.

### Dahua (DHAV frames only; `vendors/dahua_dhav.py`)
Parses DHAV frames per FFmpeg `dhav.c` (header, extension TLVs 0x80/0x81/0x82, trailer `dhav` + u32 = length - 8), follows contiguous frame chains and rescans after breaks, demultiplexes by the channel byte, starts a clip at a key frame (0xfd) and continues while `frame_number` deltas stay within `frame_gap_tolerance` (option, default 3, an inferred heuristic) and codec/resolution do not change; payload extents are exported (headers/trailers excluded). **DHFS on-disk structures are not parsed** (undocumented in what we read). The header checksum byte is not verified (algorithm not documented). The date field is returned raw plus a plain wall-clock decode with no timezone. Non-H.264/H.265 codec ids (MPEG-4, MJPEG) are listed but not exported. On its own per-paper layout the parser demultiplexes channels exactly; that result is a circular check (see VALIDATION.md).

### Analysis page (P4 additions)
Per run the UI shows each matched parser's name, tier, status (`parsed`/`partial`/`fallback`), its options, every field with a `parsed`/`inferred`/`unknown` chip and its source, raw timestamps with "timezone: not assumed", inconsistencies/warnings, and the cross-check against the generic carver; the clip table has an engine column (`generic` or the vendor) and the channel where the parser read one. Parser options are entered as JSON by vendor.

### Hikvision (`vendors/hikvision_fs.py`; details in [parsers/hikvision.md](parsers/hikvision.md))
Parses, from documented offsets only: Master Sector, RATS log records (bounded sample and summary), HIKBTREE header/pages/entries, and counts `OFNI` IDR-table signatures; locates video blocks from HIKBTREE entries plus the Master Sector geometry and runs the generic Annex-B carver inside each block (the 56-byte IDR record layout is only partly documented, so no IDR field is read). Open source conflicts are exposed, never silently resolved: block size 0x400000 vs 1 GB (`block_size_mode` = `field` default / `0x400000` / `1gib`, and a `block_size_conflict_in_source` field is always emitted), UTC vs local timestamps (raw epoch values, `tz_basis` "not assumed", `time_basis_label` only relabels), and Master Sector base 0x200 vs 0x210 (`master_sector_offset`). Entry location inside HIKBTREE pages (stride 48, first-entry offset, page-list stride) is chosen by plausibility, which only a real image can settle. **Known behaviour:** blocks whose HIKBTREE entry is cleared (existence 0xFF, as after re-initialisation) are invisible to the parser even if the video is intact; the cross-check reports them as `generic_clip_not_explained_by_parser` and the generic carver recovers them (pinned in the thresholds: parser recall on `deleted_intact_zero@hik` stays below 0.6 on the synthetic layout). H.265 is reported as an orphan. No checksum is documented, so none is verified.

### Honeywell (`vendors/honeywell_fs.py`; details in [parsers/honeywell.md](parsers/honeywell.md))
Implemented from the paper's facts as recorded in `docs/parsers/honeywell-fields.md`; the paper's unlicensed tools repository was not used. Parses the Machine Data sector (device ID and model strings), Block Group Index time/group number, Video Block List, and the 20-byte custom headers (frame-type flag byte, 8-byte little-endian microsecond time, the 20-zero-byte end-of-channel delimiter); GPT fields, Partition 1 header values (4 KiB units), Channel Index mapping and clip boundaries are tagged `inferred`; the meaning of `80 01 00`, the padding byte, timezone, checksums, Partition 2, the secondary GPT and H.265 are `unknown`. Clips carry only the NAL payload after each header. There is no channel field in the header: `channel` is `None` unless a surviving Channel Index entry covers the clip. The header's length semantic is not stated in the paper, so a frame is accepted only when its length lands on the next header, the delimiter or the image end; a device that uses a different semantic would fall back to generic carving. A run of 20 zero bytes is treated as the delimiter, so zeroed data cannot be told from a real delimiter (the `end_reason` says so). Documented for one model (HN35080200), H.264 only. Timestamps are raw with `tz_basis` "not assumed" (`time_basis_label` only relabels).
