# Nirikshan Implementation Plan

Scope: SIH PS 26150, multi-vendor DVR/NVR forensics. Basis: [docs/RESEARCH.md](docs/RESEARCH.md) (every vendor claim below cites it; do not add format details that are not there).
Status: scaffold done. No forensic code exists. Phases stop for approval ("go") at each end.

## Ground rules

- **No overclaiming.** Reports and UI state the vendor tier and the measured error rates. Recovery rates come only from our own validation runs, never from the MDPI-reported figures (unreplicated).
- **Synthetic labeling.** Every synthetic image carries a `SYNTHETIC` marker in its manifest, filename and any report that uses it.
- **Never write to evidence.** Source images are opened read-only; derived data goes to a case workspace.
- **Honeywell tools repo has no licence** (RESEARCH §3.4): re-implement from the paper, do not copy code.
- **Reading-gap caveats.** The MDPI papers and Dragonas journal papers were not readable (403); HEVC NAL-header bit layout and ITU Annex B were not verified in the spec text. Each is a task in the phase that depends on it.

## Tier definitions

| Tier | Meaning | Claim allowed |
|---|---|---|
| A | Validated on real images with ground truth we created | "Supported; recovery X% / precision Y% on N images of model M" |
| B | Public byte-level signature identified + generic NAL/GOP carving | "Identified; generic carving available; no filesystem parsing validated" |
| C | Planned only | "Not supported; generic carving may run opportunistically, vendor not attributed" |

Today: **Hikvision B, Dahua B, Honeywell B; CP Plus, Uniview, TP-Link, Godrej, Matrix C. No Tier A.**

## Order and rationale

Research confirms the requested order with two adjustments: (1) vendor-agnostic carving is the sole path for 5 of 8 OEMs (no public format data), so P2 is the product's core, not a fallback; (2) P4 order is by documentation strength: Dahua DHAV (open ffmpeg demuxer) → Hikvision (Han 2015) → Honeywell (arXiv 2605.07430). Timestamp work (P5) depends on P4 parsers for per-vendor decoding but its normalization model is vendor-neutral.

## P1: Evidence core
**Scope:** cases; acquisition of raw/dd image files, plus block devices opened strictly `O_RDONLY` (refusing anything else); examiner attestation "write blocker used: yes/no/unknown" recorded in the custody log; streaming MD5+SHA-256 in one pass while copying into the case workspace (copy then re-hashed from disk); verify-on-read gate (`open_verified`) that every analysis stage must use; hash-chained append-only custody log, one chain per case, **every entry Ed25519-signed** with a key stored outside the case workspace (generated on first run, mode 0600, refused if inside the data dir or group/world-readable); each entry records examiner, tool version, system clock in UTC and NTP sync status (`synchronized` / `not_synchronized` / `unknown`; only systemd `timedatectl` is consulted, so macOS reports `unknown`); `verify-chain` checks sequence, hash links, recomputed hashes **and** signatures; audit trail of every `/api` request; ffmpeg presence check (`/api/system`, degraded mode if missing); UI: cases, case evidence list, custody log viewer. Python 3.10 minimum, CI matrix 3.10 + 3.12.
**Done when:** a 1 GB image acquires with both hashes and a custody entry; re-verify passes; modifying one byte of the image, one custody row, or recomputing the whole chain without the key is detected and reported; UI shows both; no code path opens evidence for writing.
**Tests:** known-answer hashes vs `hashlib`/`shasum`; tamper tests (image byte flip, custody edit/delete/reorder, forged signature, fully recomputed chain without the key, recomputed + re-signed with an attacker key, key-id spoof); read-only enforcement (spy on `os.open` flags, source mtime/content unchanged, 0444 image); block-device path with file-backed fixtures and mocked `S_IFBLK` stat only; key-handling tests; API tests; one Playwright flow (create case → acquire → verify → custody verify).
**Known limits (documented, not hidden):** examiner identity is an attestation (`X-Examiner` header), not authentication; deleting the *newest* custody entries leaves a valid shorter chain, so `head_hash` must be recorded externally (reports in P7 print it); UPDATE/DELETE on custody and audit tables are rejected by DB triggers (SQLite, Postgres), but a DB owner can drop them, so tampering is ultimately detected (chain + signatures), not prevented; whoever holds the signing key can forge entries; acquisition sources are restricted to `NIRIKSHAN_EVIDENCE_ROOTS` (resolved paths; fail-closed) and block devices need `NIRIKSHAN_ALLOW_BLOCK_DEVICES=1`, with a residual check-to-open race. **Unverified:** acquisition of a real physical disk; NTP detection on non-systemd hosts. (Backend suite also run once against compose Postgres 16: pass.)
**Not in scope:** E01/AFF formats, write blockers (hardware), live acquisition from a DVR over network.

## P2: Device ID, parser plugin interface, vendor-agnostic carving, MP4 export
**Status: implemented (see docs/ARCHITECTURE.md "Vendor-agnostic carving", "Device identification...", "Analysis pipeline").**
**Scope as built:** `VendorParser` plugin interface (`probes`, `signatures`, `identify`, optional `enumerate`, `carve_hints`) with a shared one-pass signature scan; identification for Hikvision, Dahua and Honeywell using only RESEARCH-documented signatures, reporting evidence offsets and a tier-bound confidence (max `medium`, never `high`: no Tier A); streaming, boundary-safe Annex-B scanner; H.264/H.265 clip builder (IRAP + parameter sets, contiguity, slice sanity, H.264 `frame_num` continuity, orphan reporting, optional H.264 fragment join, off by default); `ffmpeg -c copy` MP4 export with a decode test of the carved bitstream; per-run `carve_runs`/`clips` records; custody entries `clip_carved` (offsets, bitstream and MP4 SHA-256, tool + ffmpeg version) and `carve_completed`; all reads through `open_verified`; API (`/analyze`, runs, clip video with Range, clip hash verify); UI analysis page (vendor evidence, clip table with offsets/hashes/nominal durations/decode status, preview player, orphans, failed decodes).
**Step 0 hardening done first:** evidence-root restriction (+ block-device flag), DB triggers on custody/audit, head_hash UI/CLI, backend suite passed against compose Postgres 16.
**Done when (met, synthetic data only):** a mixed image yields clips as ffprobe-valid MP4s with hashes and offsets; failed decodes are listed; an unknown vendor still carves.
**Tests:** ffmpeg-generated H.264 (baseline/main+B-frames/high) and H.265 streams labelled synthetic; scanner chunk-boundary property tests down to 1-byte chunks; clean/zero-padded/overwritten/spliced/fragmented images; garbage and mutation fuzzing; bounded-memory checks; export asserts every slice NAL in the MP4 is byte-identical (stream copy) and uses ffprobe; plugin contract tests with a dummy parser; analysis tests for custody, tamper blocking, Range serving; Playwright flow for identify + carve.
**Known limits (documented):** encrypted payloads; MJPEG/MPEG-4 streams; interleaved multi-channel streams without channel IDs; random non-zero garbage between NAL units is absorbed (only the decode test reveals it); H.265 has no continuity check or reassembly; fragment reassembly is a heuristic (roughly 1-in-8 false accept with a 4-bit `frame_num`); vendor headers inside streams are not stripped until P4; durations are nominal (stream frame rate), not recording time; analysis runs synchronously. **Unverified:** everything on real DVR images; browser playback of H.264/H.265 in e2e (Playwright Chromium has no H.264, the served bytes and ffprobe are asserted instead); throughput on cold disks.
**Measured (this Mac, synthetic 2 GiB image, cache-warm):** identify 224 MiB/s, carve scan 569 MiB/s, peak RSS 80 MiB.

## P3: Validation harness + synthetic DVR generator
**Status: implemented (see docs/VALIDATION.md, docs/validation/).**
**Scope as built:** `app/validation/` generator (seeded, deterministic, every image bannered SYNTHETIC, manifest with ground truth computed by byte comparison), 22-scenario matrix scored separately (clean live, deleted-intact, zero gaps, narrow/wide zero padding inside clips, random-garbage gaps between/inside clips, partial overwrite by zeros or a newer recording, fully overwritten, fragmented with reassembly off/on, fragment decoys for the reassembler false-accept study, adversarial noise, multi-channel by GOP/frame, and negatives: noise with false start codes, whole-stream and partial encryption, MJPEG, MPEG-4 Part 2); metrics: clip recall/precision, byte-exact, frame recall/precision (NAL coverage), decode ok, hash integrity, mixed-clip rate, reassembler false/true accept with Wilson intervals; `make validate` (JSON + Markdown, baseline committed in docs/validation/), `make validate-quick`; regression thresholds (`thresholds.json`) enforced in `tests/test_validation.py`; page-1 statements that synthetic scores do not predict real-device performance and that parser-vs-same-layout checks are circular.
**Carver hardening driven by the harness:** SPS/PPS/VPS syntax validation, PPS-reference rule, trailing-zero trimming at EOF, join-decision log.
**Done when (met):** `make validate` prints the tables with seeds; same seed gives the same SHA-256; results state SYNTHETIC.
**Tests:** generator determinism (SHA-256 per scenario), banner/manifest marking, ground-truth byte-comparison tests, scorer unit tests (perfect/empty/partial/false positive/ties/zero-tolerant extents/hash mismatch/negatives), Wilson interval, threshold checker, digest reproducibility, fresh 3-trial regression run, integrity and thresholds of the committed baseline.
**P4 extension:** vendor-layout scenarios (`@dhav`, `@hik`, `@honeywell`) run generic + parser engines with cross-check; thresholds fail on missing scenarios in full runs.
**Honesty notes:** see "Limits of this validation" in docs/VALIDATION.md (single encoder family, scenarios co-developed with the carver, NAL coverage is not decoded pictures, clean decode does not prove byte-faithfulness). Measured reassembler false-accept rate: 11.8% (35/297), 95% CI 9-16%.

## P4: Vendor parsers (documentation-ordered)
**Status: implemented for Dahua (DHAV frames only), Hikvision and Honeywell; all three remain Tier B. Nothing here has touched a real device image.**
Shared design (docs/ARCHITECTURE.md "Vendor parsers (P4)"): `VendorParser.parse()` returns a `ParseResult` whose fields are tagged `parsed` / `inferred` / `unknown`, with raw timestamps (`tz_basis` "not assumed"; P5 normalizes), inconsistencies and a cross-check against the generic carver on the same image. Any inconsistency or exception falls back to generic carving, which always runs; parser clips are stored next to generic ones (`engine` column), never substituted. Open source conflicts are exposed as options/flags, not resolved. Corruption tests (truncation, wrong magic, bad offsets/lengths, circular pointers, fuzz) assert no crash and no claim of unparsed fields; where a source documents no checksum (all three), tests prove none is claimed.

| Order | Vendor | Source basis | Built | Open points exposed (not resolved) |
|---|---|---|---|---|
| 1 | Dahua | FFmpeg `dhav.c` | DHAV frame parser: header, extension TLVs, trailer check, channel demultiplexing, key-frame clip starts, `frame_gap_tolerance` option; **DHFS internals unparsed** | header checksum byte unverified (algorithm undocumented); date has no timezone field; codecs other than H.264/H.265 listed, not exported |
| 2 | Hikvision | Han 2015, Dragonas (field table in docs/parsers/hikvision-fields.md) | Master Sector, RATS records, HIKBTREE entries, `OFNI` counts; generic NAL scan inside located blocks | block size 0x400000 vs 1 GB (`block_size_mode`), UTC vs local (`time_basis_label`), Master Sector base 0x200 vs 0x210 (`master_sector_offset`); HIKBTREE entry location chosen by plausibility; cleared entries hide intact video from the parser |
| 3 | Honeywell | arXiv 2605.07430 as recorded in docs/parsers/honeywell-fields.md (unlicensed repo not used) | Machine Data, block index structures, 20-byte custom headers, delimiter; channel only if a Channel Index entry survives | length-field semantic and endianness partly inferred; 20-zero-byte delimiter ambiguity; one model, H.264 only |
| 4 | CP Plus | none found | not built; generic carving only | needs a real image |
| 5-8 | Uniview, TP-Link, Godrej, Matrix | marketing only | not built | need real images |

**Done when (met on synthetic per-paper layouts):** each parser passes its harness scenarios (`@dhav`, `@hik`, `@honeywell`), refuses to claim fields it did not parse, and its tier is recorded in code and UI. **This is a circular check** (layouts and parsers come from the same documents) and is labeled so in every result.
**Tests:** `tests/test_dahua_parser.py`, `test_hikvision_parser.py`, `test_honeywell_parser.py` (parse correctness, tagging, options, corruption, fuzz, exception to fallback, cross-check, pipeline integration), harness scenarios with parser engines and thresholds (strict mode fails on missing scenarios), Playwright flow for the Dahua parser panel.
**Unverified:** every parser on real images; the Hikvision page-entry layout and block offset base; the Honeywell header length semantic; Dahua frame-number tolerance on real streams.

### Promoting a vendor between tiers

| Promotion | Requires |
|---|---|
| C → B | A public byte-level signature we have read ourselves **or** one real image from that vendor yielding a documented signature (hex dump saved in `docs/`); signature-ID test against that image |
| B → A | ≥2 real images from ≥1 model of that vendor, created by you with a known ground-truth set (record N clips with known times/channels, delete some, record again, image the HDD **read-only** via write blocker); acquire and hash before/after; run the pipeline; report recall/precision/timestamp error with numbers; a 2nd firmware/model strengthens the claim. Needs: the DVR, 2 HDDs (or one + cloned), SATA write blocker or USB dock with read-only, a USB-SATA adapter, a reference clock (NTP-synced phone/laptop), notes of DVR time settings, timezone and DST setting |
| A → "model-broad" | Additional models/firmware versions; one claim per model, never per brand |

Likely purchase: Hikvision or Dahua (strongest documentation, validates P4 order); CP Plus if the unit turns out to be Dahua-OEM (verify by image, not assumption).

## P5: Timestamp normalization and timeline correlation
**Scope:** per-field raw record (raw value, field, format, assumed timezone, evidence for the assumption); normalise to UTC with explicit uncertainty; timezone/DST handling (device-configured zone; unknown → flagged, never defaulted silently; Hikvision HIKBTREE-UTC vs log-local conflict, Dahua local-time inference both flagged per RESEARCH §2/§6); clock-drift model (offset measured against a reference photo/OSD/known event, linear drift estimate with confidence interval); OSD-time cross-check: OCR burned-in time overlay on sampled frames (CPU), compare to metadata, report delta distribution; cross-camera timeline (merge by normalised time with per-source uncertainty bars, gap detection, overlap view); UI timeline.
**Done when:** synthetic images with injected offset/DST/drift are normalised to within the stated bound; unknown timezones are surfaced; timeline export includes the uncertainty.
**Tests:** DST boundary cases (spring forward/fall back ambiguous hour), leap day, 32-bit epoch edge, offset/drift recovery on synthetic data, OSD OCR accuracy on rendered overlays (synthetic), correlation ordering with tie/overlap cases.

## P6: Analytics as triage (CPU-only)
**Scope:** motion (frame-differencing/background subtraction), object detection (small CPU model, e.g. ONNX runtime; model + licence recorded), face detection (detection first; recognition only if licensing and error rates are acceptable). All outputs labelled "triage, not identification"; each run stores model name/version/hash, parameters and the measured precision/recall on a documented test set with confidence intervals.
**Done when:** analytics results are searchable per clip, each with confidence, tool version and stated error rates; the UI shows them as leads.
**Tests:** known-answer synthetic clips (moving block, rendered objects); public benchmark subset for object/face error rates (dataset licence recorded); CPU runtime budget test; determinism test (same input → same output).
**Risk:** DVR footage is low-res/high-compression; error rates measured on public data will not transfer, so report both and say so.

## P7: Reporting, SOPs, manual
**Scope:** court-style PDF (case ID, examiner, tool/parser versions, evidence hashes MD5+SHA-256, acquisition log, custody chain verification result, audit trail, per-vendor tier and limitations, recovery results with offsets, timestamp assumptions, analytics error rates); report integrity (SHA-256 of the PDF recorded in custody log); drafts of SOPs (acquisition, hashing, recovery, timestamp handling, reporting), user manual, validation report (from P3 numbers; real-image section stays empty until P4 data exist).
**Done when:** a full synthetic-case demo produces a PDF whose hashes and chain verification match the database; the validation report cites the committed baseline run.
**Tests:** PDF content tests (required sections/hashes present, parsed back from PDF), report-regeneration determinism, tampered custody → report states chain failure.

## P8: Polish, UI, demo flow, final docs
UI polish and accessibility pass, guided demo (synthetic case, labelled), OEM comparison deliverable from RESEARCH §4, architecture docs, final report, performance on large images, packaging (docker-compose for app, no deploy), full e2e run.
**Done when:** the demo runs end to end from clean state in one command; all docs consistent with the code and with the tier table.

## Deliverable map

| PS deliverable | Where |
|---|---|
| OEM comparison | docs/RESEARCH.md §4 (kept in sync), P8 |
| Forensic image | P1 (acquisition) + P3 (synthetic) + real images when available |
| Architecture docs | docs/ARCHITECTURE.md (grown per phase), P8 |
| Working prototype | P1-P7, polished P8 |
| SOPs | P7 |
| Validation report | P3 numbers (synthetic), real-image numbers when P4 data exist |
| User manual | P7 |
| Final report | P8 |
