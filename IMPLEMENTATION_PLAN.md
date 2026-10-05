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
**Scope:** `VendorParser` plugin interface (`identify(image) -> Match(vendor, confidence, evidence_offsets)`, optional `enumerate()`, `carve_hints()`); signature-based identification using only RESEARCH-documented signatures (`HIKVISION@HANGZHOU` @0x200, `HIKBTREE`, `RATS`; DHAV/`dhav` header/footer pair; Honeywell Machine Data string and header per §3.4); generic Annex-B scanner for H.264 (NAL type = low 5 bits) and H.265 (verify bit layout against spec/ffmpeg `hevc.h` first); GOP carving from IDR/IRAP with SPS/PPS (VPS for HEVC); fragment reassembly (contiguous run + validity checks: parameter-set presence, slice header sanity, decode test); ffmpeg export to MP4 (`-c copy` first, re-encode never); every clip gets offset range, SHA-256, tool version, custody entry.
**Done when:** a mixed image yields clips as playable MP4 with hashes and offsets; failed decodes are listed, not hidden; unknown vendor still carves.
**Tests:** unit tests on NAL parsing with ffmpeg-generated bitstreams (H.264 and H.265, various profiles); fuzz/garbage input (no crash, bounded memory); fragmentation/overwrite cases; ffprobe validation of exported MP4; plugin interface contract tests with a dummy parser; large-image streaming memory test.
**Known limits to document:** encrypted payloads, MJPEG/MPEG-4 streams (no NAL start codes, RESEARCH §5), interleaved multi-channel streams without channel IDs.

## P3: Validation harness + synthetic DVR generator
**Scope:** generator that builds `SYNTHETIC` images with a known-answer manifest: configurable layout (generic Annex-B stream; Hikvision-like/DHAV-like/Honeywell-like layouts built *only from documented fields*, labelled "per-paper layout, not a real device image"), live clips, deleted clips (overwritten partially/fully, fragmented), noise regions, multiple channels; harness that runs the pipeline and scores clip-level recall, precision, byte-exact match, frame-level recovery, hash integrity; JSON + Markdown results, seeded and reproducible; baseline run committed.
**Done when:** `make validate` prints recovery rate/precision/hash-integrity tables across the scenario matrix with seeds; results state "synthetic".
**Tests:** generator determinism (same seed → same SHA-256); manifest self-consistency; harness scoring unit tests with hand-built perfect/empty/partial outputs; regression threshold test in CI.
**Honesty note:** synthetic scores prove the pipeline works on the layouts we modelled; they do not predict real-device performance. The validation report says so on page 1.

## P4: Vendor parsers (documentation-ordered)
Each parser: structured parsing behind the plugin interface, falls back to generic carving on any inconsistency, reports which fields were parsed vs. inferred.

| Order | Vendor | Source basis | Work | Starts at → target |
|---|---|---|---|---|
| 1 | Dahua | ffmpeg `dhav.c` (fully read), Dragonas thesis ch.4-5 | DHAV frame parser (header/footer, frame types, bit-packed date, sub-second); DHFS internals are **not** documented in what we read: parse only DHAV frames, not DHFS metadata; log SQLite (`{serial}_log.db`) reader if XFS partition present | B → B (A after real image) |
| 2 | Hikvision | Han 2015, Dragonas | Master Sector, HIKBTREE, IDR table `OFNI`, `RATS` log records; resolve Han's block-size contradiction (0x400000 vs "1 GB") on a real image before trusting either | B → B |
| 3 | Honeywell | arXiv 2605.07430 (single model HN35080200) | Machine Data string, 20-byte header, per-NAL microsecond timestamps; re-implement, no repo code | B → B |
| 4 | CP Plus | none found (only a Dahua distribution relationship) | Identify only if a real image shows DHFS/DHAV; otherwise generic carving | C → C |
| 5-8 | Uniview, TP-Link, Godrej, Matrix | marketing only | Collect-and-document step: if you obtain a device, a research note first, parser later | C |

**Done when (per vendor):** parser passes synthetic harness for its documented layout; refuses to claim fields it did not parse; tier recorded in code and UI.
**Tests:** parser unit tests with byte fixtures built from documented fields; mismatch/corruption tests (fall back to generic carving, never crash); cross-check parser output vs generic carver on the same synthetic image.

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
