# SOP-03: Vendor Identification and Video Recovery (DRAFT)

*Audience: forensic examiners running Nirikshan's identify, parse and carve pipeline on an acquired DVR/NVR image and interpreting its output.*

Status: draft for Nirikshan v0.1.0. Written with reference to the guidance in `docs/RESEARCH.md` section 8 (NIST SP 800-86; SWGDE 17-V-002-1.4 page read, SWGDE 15-V-002 on advanced recovery from H.264 DVRs listed but **not opened**; ISO/IEC 27037 and ACPO not accessible). **Not audited** against any of them; no compliance claim is made. All performance figures below come from SYNTHETIC images (`docs/VALIDATION.md`, `docs/VALIDATION_REPORT.md`) and **do not predict performance on real devices**. No vendor is Tier A.

## 1. Purpose
Identify the likely recorder vendor, recover candidate video clips from the image, and record what was done and what remains uncertain.

## 2. Scope
Evidence already acquired and verified (SOP-01, SOP-02). Covers vendor identification, the parser-first pipeline, generic H.264/H.265 carving, MP4 export, and reading the results. Timestamps are SOP-04; reporting is SOP-05.

## 3. Roles
Examiner (runs and interprets), reviewer (re-runs from the same image and options and compares hashes).

## 4. Preconditions
- Evidence status verified; custody chain valid.
- `ffmpeg` and `ffprobe` installed (analysis returns 503 without them; `/api/system` shows mode `degraded`).
- You have noted the analysis parameters you intend to use. Defaults: `max_pad` 64 bytes, `join_gap` 0 (reassembly off), `h264_continuity` true, `validate_params` true.

## 5. Procedure
1. **Run "Identify + carve"** on the Analysis page (`/evidence/<case>/<id>`) or `POST /api/evidence/{id}/analyze`. The image hash is re-verified first; a mismatch stops the run with 409.
2. **Read the vendor identification.** Each match shows vendor, tier, confidence (`low` or `medium` only; `high` is never produced because no vendor is Tier A) and the evidence offsets of the signatures found. "Unknown vendor" means no documented signature was found; clips are still carved generically. CP Plus, Uniview, TP-Link, Godrej and Matrix have no signatures and are never attributed. Identification is a lead based on public signatures, not a determination of make or model.
3. **Understand the pipeline order (parser first).**
   1. Identify (one streaming pass over all vendors' signatures).
   2. Vendor parsers (Dahua DHAV frames, Hikvision, Honeywell) run for matched vendors. Their clips are exported and stored with `engine` = vendor.
   3. **Generic carving then runs only over byte ranges that no parser clip covers**, so nothing is carved twice and a partial parser does not lose clips. If a parser falls back, generic carving covers the whole image. (`generic_scope="all"` restores a full generic pass.)
   4. A separate dry full-image generic pass is used only for the cross-check (nothing exported).
4. **Read each parser panel.**
   - Status `parsed`, `partial` or `fallback`. `fallback` means the generic results stand alone.
   - Field chips: **parsed** (read at a position the source documents), **inferred** (our reading or a heuristic), **unknown** (present but not interpreted). Do not report an inferred or unknown field as established.
   - Raw timestamps are shown with "timezone: not assumed". Do not convert them to local or UTC time on your own authority (SOP-04).
   - Open source conflicts and options in effect are shown; the parser options JSON field takes e.g. `{"Hikvision": {"block_size_mode": "1gib"}}`. Changing an option is a documented examiner decision and must be recorded.
5. **Read the cross-check disagreements.** The parser's clips are compared with a generic carve of the same image. Kinds:
   - `parser_clip_not_found_by_generic`: the parser found a clip the generic carver did not. Review the clip's decode status; possible cause is vendor framing the generic carver cannot parse.
   - `generic_clip_not_explained_by_parser`: video exists that the parser's metadata did not point to. Known cause: cleared Hikvision HIKBTREE entries hide intact video from the parser (on the synthetic layout, parser recall 20/60 vs generic 60/60). Treat these clips as **generic engine** results, without vendor time or channel attribution.
   - `frame_count_mismatch`, `generic_includes_extra_bytes`: expected effects of vendor headers inside the stream.
   - `codec_mismatch`: investigate before using the clip.
   Disagreements are listed, not resolved; an examiner must decide and document.
6. **Review the clip table.** For each clip: engine, codec, channel (only where a parser read one), byte offsets (decimal and hex), size, SHA-256 of the bitstream and of the MP4, resolution, nominal duration, frame count, decode status and listed decode errors. "Nominal duration" comes from the stream frame rate (25 fps is assumed without timing info) and is **not** a recording time.
7. **Check failed decodes.** `decode_errors` and `export_failed` clips are listed, not hidden; the MP4 is kept for `decode_errors`. Review them separately and do not present them as clean recoveries. Encrypted slices behind clear parameter sets are known to produce such clips.
8. **Review orphans** (slices without a preceding IRAP + parameter sets, or an IRAP without parameter sets). They are not exported; their byte ranges are listed.
9. **Preview** clips in the player and press "Verify MP4 hash" for any clip you will cite.
10. **Fragment reassembly** (join gap): leave at 0. If you enable it (H.264 only), treat every clip labelled `reassembled (heuristic)` as a hypothesis. On synthetic decoys the reassembler **falsely accepted 11.8% (35/297, 95% CI 9-16%)** of wrong candidates (`docs/VALIDATION.md`, measured on synthetic images, reason: 4-bit `frame_num`). Run once with it off and once on, keep both runs, and name which one a claim comes from.
11. **Record** the run id, tool and ffmpeg versions, all parameters and parser options, vendor matches and confidence, counts (clips, orphans, decode errors, export failures), and the clip hashes you rely on. The custody log already holds `clip_carved` and `carve_completed` entries; export it (SOP-02).

## 6. Records to keep
Run id and parameters; vendor matches with offsets; parser status, options and open-conflict fields; the cross-check disagreement list; per-clip offsets and hashes for cited clips; decode status; decisions on disagreements and the reason; head_hash after the run.

## 7. Integrity checks
- Clip bitstream SHA-256 equals a recomputation from the image bytes at the recorded extents.
- MP4 hash verification passes at report time.
- Image verify and chain verify pass after the run (SOP-02).
- Reproducibility: re-running the same image with the same parameters should reproduce clip extents and hashes; compare.

## 8. Failure handling
| Symptom | Action |
|---|---|
| 409 on analyze | Image failed hash verification; follow SOP-02 section 8 |
| 503 on analyze | Install ffmpeg/ffprobe; restart backend |
| Parser status `fallback` | Not an error: generic carving covers the image; record it |
| Many `decode_errors` | Review manually; consider whether the data is encrypted, overwritten or fragmented; do not rely on those clips |
| No clips, vendor unknown | Possible causes: unsupported codec (MJPEG, MPEG-4 Part 2 are not carved), encryption, fully overwritten data, an unmodelled container. Absence of output is not evidence of absence of video |
| Run error | Keep the run record and the failed custody entry; report |

## 9. Known limits (read before any statement about completeness)
- **Decode ok is not byte-faithful.** On synthetic images with random non-zero garbage between NAL units, 60/60 clips decoded cleanly while byte-exact extents were 0/60. A clip that plays is not thereby proven unaltered or complete.
- Zero padding inside a clip wider than `max_pad` (64 bytes default) loses it (synthetic wide padding: 0/2175 frames recovered).
- Interleaved multi-channel streams without channel metadata are mixed by the generic carver (synthetic clip precision 40.0% (8/20) GOP-interleaved, 30.0% (6/20) frame-interleaved). Channel demultiplexing exists only where a parser reads a channel field, and the Dahua figure for that is a circular check.
- H.265 has no continuity check and no reassembly; a gap ends the clip.
- Encrypted payloads, MJPEG and MPEG-4 Part 2 are not recovered.
- Dahua DHFS on-disk structures are not parsed (DHAV frames only). Hikvision parsing locates blocks by plausibility and is blind to cleared entries. Honeywell: one documented model, H.264 only.
- Vendor parsers have never touched a real device image; the synthetic layouts and the parsers come from the same documents (circular check). Open source conflicts are exposed as options, not resolved.
- Durations are nominal; channel and wall-clock attribution are absent unless a parser read them; timestamps are raw only today.
- Scan throughput on a 2 GiB synthetic image (cache warm, one Mac): identify 224 MiB/s, carve scan 569 MiB/s. Real disks and cold caches are untested.

## 10. What the tool does NOT do
It does not establish that a recovered clip is complete, unaltered, from a particular camera, or recorded at a particular time. It does not decrypt. It does not validate vendor attribution on real devices. It does not replace manual review of footage. Analytics (motion, objects, faces) are not part of this SOP; they are in progress as triage only.
