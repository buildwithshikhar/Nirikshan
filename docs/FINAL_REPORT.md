<!-- GENERATED FILE: edit docs/FINAL_REPORT.template.md and docs/traceability.yaml, then run
     python scripts/build_final_report.py. Numbers in sections 4-6 are parsed from data files. -->
# Nirikshan: Final Report

*SIH PS 26150, multi-vendor DVR/NVR forensic analysis. Audience: NTRO technical reviewers.*

> **Reading rule for this report.** Everything below was built and tested on **synthetic data**. No real DVR or NVR image has been processed. No vendor is Tier A. Statements are traceable to code, results files or cited sources; where evidence is missing we say so. Pending items from unmerged work are marked `[[PENDING-MERGE: A]]` or `[[PENDING-MERGE: B]]`.

## 1. What Nirikshan is

A prototype platform that takes a disk image from a surveillance recorder, preserves it under a signed chain of custody, identifies the recorder family where public signatures exist, recovers video that is still present in the image (including deleted footage that has not been overwritten), exports it as playable MP4 with hashes, places clips on a timeline with explicit timestamp assumptions and uncertainty, and offers CPU-only motion/object/face-detection triage with measured error rates. It is built for transparency: every result carries its tier, parameters and the limits of the evidence behind it.

## 2. Architecture summary

Full detail: [ARCHITECTURE.md](ARCHITECTURE.md), [API.md](API.md).

| Layer | Implementation |
|---|---|
| Evidence core | Read-only acquisition from allow-listed folders into a case workspace, single-pass MD5 + SHA-256, re-verification before every analysis stage, hash-chained Ed25519-signed custody log (separate key directory), append-only DB triggers |
| Identification | Parser plugin interface; signatures from public sources only; confidence capped below "high" because no vendor is Tier A |
| Vendor parsers | Dahua (DHAV frames), Hikvision (Master Sector, RATS, HIKBTREE), Honeywell (one documented model); fields tagged parsed / inferred / unknown; any inconsistency falls back to generic carving |
| Generic carving | Streaming Annex-B scanner, H.264/H.265 clip builder, `ffmpeg -c copy` MP4 export plus decode test, orphans reported |
| Timestamps and timeline | Raw records with assumptions and evidence, no default timezone, DST/epoch flags, drift model, OSD OCR cross-check, interval timeline |
| Analytics | Motion (numpy), YOLOX-Nano objects, YuNet face detection; labelled "triage, not identification"; no recognition |
| Frontend | React + Vite, one page per stage |
| Packaging | Offline Docker images and hardened compose file ([OFFLINE_DEPLOYMENT.md](OFFLINE_DEPLOYMENT.md)) |
| Reporting, jobs, demo | `[[PENDING-MERGE: A]]` PDF report, BSA 63(4) draft certificate, JSON-LD export; `[[PENDING-MERGE: B]]` background jobs, `make demo`, accessibility pass |

## 3. Requirement traceability (PS 26150)

Source of truth: [traceability.yaml](traceability.yaml). The report builder fails if any listed path does not exist.

Counts (computed): Built 8, Partial 14, Planned 2 of 24. Built means implemented and tested on synthetic data in this repository, not validated on a real device.

| ID | Requirement | Status | Code | Tests | Docs | Note |
|---|---|---|---|---|---|---|
| R01 | Standardized evidence acquisition | **Built** | `backend/app/evidence.py`<br>`backend/app/routes.py`<br>`backend/app/config.py` | `backend/tests/test_evidence.py`<br>`backend/tests/test_evidence_roots.py`<br>`backend/tests/test_api.py` | `docs/sop/SOP-01-acquisition.md`<br>`docs/ARCHITECTURE.md` | Raw/dd image files from allow-listed folders, read-only open; block devices are gated and tested only with file-backed fixtures, never a real disk. |
| R02 | Forensic imaging | **Partial** | `backend/app/evidence.py`<br>`backend/app/hashing.py` | `backend/tests/test_evidence.py`<br>`backend/tests/test_hashing_clock.py` | `docs/sop/SOP-01-acquisition.md`<br>`docs/REAL_IMAGE_PLAYBOOK.md` | Bit-for-bit copy of an existing image with re-hash; no E01/AFF, no hardware write blocker (attested only), no physical-disk imaging tested. |
| R03 | Proprietary filesystem parsing | **Partial** | `backend/app/vendors/hikvision_fs.py`<br>`backend/app/vendors/honeywell_fs.py`<br>`backend/app/vendors/dahua_dhav.py` | `backend/tests/test_hikvision_parser.py`<br>`backend/tests/test_honeywell_parser.py`<br>`backend/tests/test_dahua_parser.py` | `docs/parsers/hikvision.md`<br>`docs/parsers/honeywell.md`<br>`docs/OEM_COMPARISON.md` | Hikvision (Master Sector, RATS, HIKBTREE) and Honeywell (one documented model) partly parsed from papers; Dahua DHFS is not parsed at all (only DHAV frames); no real image tested; open source conflicts exposed, not resolved. |
| R04 | Video format parsing and carving | **Partial** | `backend/app/carving/nal.py`<br>`backend/app/carving/carve.py`<br>`backend/app/carving/export.py`<br>`backend/app/vendors/dahua_dhav.py` | `backend/tests/test_carving.py`<br>`backend/tests/test_export.py`<br>`backend/tests/test_dahua_parser.py` | `docs/ARCHITECTURE.md`<br>`docs/VALIDATION.md` | H.264/H.265 Annex-B carving and DHAV framing; MJPEG, MPEG-4 and encrypted payloads are not recovered; vendor headers inside streams only handled for the three Tier B vendors. |
| R05 | Deleted-footage recovery | **Partial** | `backend/app/analyze.py`<br>`backend/app/carving/carve.py`<br>`backend/app/validation/scenarios.py` | `backend/tests/test_analyze.py`<br>`backend/tests/test_validation.py`<br>`backend/tests/test_pipeline_parser_first.py` | `docs/VALIDATION.md`<br>`docs/VALIDATION_REPORT.md`<br>`docs/validation/results.md`<br>`docs/sop/SOP-03-recovery.md` | Measured on SYNTHETIC images only (see the results section); some scenarios score 0 (for example wide zero padding inside clips); nothing is known about real devices. |
| R06 | Timestamp normalization | **Partial** | `backend/app/timeline/timestamps.py`<br>`backend/app/timeline/drift.py`<br>`backend/app/timeline/osd.py` | `backend/tests/test_timeline_timestamps.py`<br>`backend/tests/test_timeline_drift.py`<br>`backend/tests/test_timeline_osd.py` | `docs/timeline.md`<br>`docs/sop/SOP-04-timestamp-handling.md` | Explicit assumptions, uncertainty intervals, drift fit and OSD OCR cross-check implemented and unit-tested; vendor time-basis conflicts remain open and nothing is validated on a real device. |
| R07 | MD5 and SHA-256 hashing with integrity verification | **Built** | `backend/app/hashing.py`<br>`backend/app/evidence.py` | `backend/tests/test_hashing_clock.py`<br>`backend/tests/test_evidence.py` | `docs/sop/SOP-02-hashing-and-integrity.md` | Single-pass MD5+SHA-256, re-hash on every read, clip MP4 hashes recorded and re-checked; known-answer tests against hashlib. |
| R08 | Cross-camera event correlation | **Partial** | `backend/app/timeline/timeline.py`<br>`backend/app/timeline/routes.py`<br>`frontend/src/pages/Timeline.tsx` | `backend/tests/test_timeline_build.py`<br>`backend/tests/test_timeline_api.py`<br>`frontend/e2e/timeline.spec.ts` | `docs/timeline.md` | Interval timeline with gaps/overlaps and CSV/JSON export; clips without parsed timestamps (all generic-carved clips) are unplaceable, and event-level correlation (objects/faces across cameras) is not built. |
| R09 | Chain of custody | **Built** | `backend/app/custody.py`<br>`backend/app/signing.py`<br>`backend/app/triggers.py`<br>`backend/app/cli.py` | `backend/tests/test_custody.py`<br>`backend/tests/test_signing.py`<br>`backend/tests/test_triggers.py`<br>`backend/tests/test_cli.py` | `docs/ARCHITECTURE.md`<br>`docs/SECURITY_REVIEW.md` | Hash-chained, Ed25519-signed, tamper-tested; examiner identity is an attestation (no authentication), tail truncation needs an external head_hash, and the key holder can forge entries. |
| R10 | Reporting | **Partial** | `backend/app/timeline/routes.py` | `backend/tests/test_timeline_api.py` | `docs/sop/SOP-05-reporting.md`<br>`docs/USER_MANUAL.md` | In this tree only the timeline CSV/JSON export and the reporting SOP exist; the PDF report is built on another branch and is not counted here. [[PENDING-MERGE: A]] court-style PDF report, BSA 63(4) draft certificate, CASE JSON-LD export, SOP-06 intake checklist (docs/report.md, docs/legal/, docs/sop/SOP-06-*) |
| R11 | AI analytics (face, object, motion) as triage | **Partial** | `backend/app/analytics/runner.py`<br>`backend/app/analytics/detect.py`<br>`backend/app/analytics/motion.py`<br>`backend/app/analytics/registry.py` | `backend/tests/test_analytics.py`<br>`frontend/e2e/analytics.spec.ts` | `docs/analytics/README.md`<br>`docs/analytics/error_rates.json` | Motion, object detection and face detection (no recognition) labelled triage; error rates are from public still-image datasets and synthetic clips, not DVR footage. |
| R12 | Hikvision support | **Partial** | `backend/app/vendors/hikvision.py`<br>`backend/app/vendors/hikvision_fs.py` | `backend/tests/test_hikvision_parser.py`<br>`backend/tests/test_vendors.py` | `docs/parsers/hikvision.md`<br>`docs/parsers/hikvision-fields.md`<br>`docs/OEM_COMPARISON.md` | Tier B - public signatures plus a parser validated only against a synthetic layout built from the same paper (circular). |
| R13 | Dahua support | **Partial** | `backend/app/vendors/dahua.py`<br>`backend/app/vendors/dahua_dhav.py` | `backend/tests/test_dahua_parser.py`<br>`backend/tests/test_vendors.py` | `docs/OEM_COMPARISON.md` | Tier B - DHAV frames only (from FFmpeg dhav.c); DHFS filesystem unparsed; synthetic validation only. |
| R14 | Honeywell support | **Partial** | `backend/app/vendors/honeywell.py`<br>`backend/app/vendors/honeywell_fs.py` | `backend/tests/test_honeywell_parser.py`<br>`backend/tests/test_vendors.py` | `docs/parsers/honeywell.md`<br>`docs/parsers/honeywell-fields.md`<br>`docs/OEM_COMPARISON.md` | Tier B - written from one 2026 paper about one model; header length semantic partly inferred; synthetic validation only. |
| R15 | CP Plus, Uniview, TP-Link, Godrej, Matrix support | **Planned** | `backend/app/carving/carve.py` | `backend/tests/test_carving.py` | `docs/OEM_COMPARISON.md`<br>`docs/RESEARCH.md` | Tier C - no public format data found; generic carving may run but no vendor is attributed and no parser exists. |
| R16 | Validation on real DVR/NVR devices | **Planned** | `backend/app/validation/run.py` | `backend/tests/test_validation.py` | `docs/REAL_IMAGE_PLAYBOOK.md`<br>`docs/HARDWARE_SHOPPING.md`<br>`docs/VALIDATION_REPORT.md` | No real image has been processed. The harness and playbook exist; the work needs hardware and ground truth. |
| R17 | Working prototype (API and UI) | **Built** | `backend/app/main.py`<br>`frontend/src/App.tsx`<br>`frontend/src/pages/Analysis.tsx`<br>`frontend/src/pages/CustodyLog.tsx` | `backend/tests/test_health.py`<br>`frontend/e2e/smoke.spec.ts` | `README.md`<br>`docs/API.md`<br>`docs/USER_MANUAL.md` | Runs end to end on synthetic data; synchronous analysis; no authentication. [[PENDING-MERGE: B]] background jobs, `make demo`, accessibility pass, screenshots (docs/jobs.md, docs/accessibility.md, docs/demo.md) |
| R18 | Offline packaging | **Built** | `backend/Dockerfile`<br>`frontend/Dockerfile`<br>`docker-compose.offline.yml`<br>`deploy/nginx.conf`<br>`scripts/model_manifest.py` | - | `docs/OFFLINE_DEPLOYMENT.md` | Built and smoke-tested once on one host (arm64, Docker Desktop); the frontend container is not egress-blocked there; no automated test, no amd64 or native Linux run. |
| R19 | Security review | **Partial** | `backend/app/config.py`<br>`backend/app/signing.py` | `backend/tests/test_evidence_roots.py`<br>`backend/tests/test_signing.py` | `docs/SECURITY_REVIEW.md`<br>`docs/security/audit-pip.txt`<br>`docs/security/audit-npm.txt` | Self-review and dependency audit only; not an independent penetration test. |
| R20 | Deliverable - OEM comparison | **Built** | `backend/app/vendors/base.py` | `backend/tests/test_vendors.py` | `docs/OEM_COMPARISON.md`<br>`docs/RESEARCH.md` | Documentation-level comparison with confidence tags; its facts are as good as the public sources we could read. |
| R21 | Deliverable - architecture docs | **Built** | `backend/app/main.py` | - | `docs/ARCHITECTURE.md`<br>`docs/API.md` | Kept in step with the code by hand; the traceability check covers paths, not prose. |
| R22 | Deliverable - SOPs | **Partial** | - | - | `docs/sop/SOP-01-acquisition.md`<br>`docs/sop/SOP-02-hashing-and-integrity.md`<br>`docs/sop/SOP-03-recovery.md`<br>`docs/sop/SOP-04-timestamp-handling.md`<br>`docs/sop/SOP-05-reporting.md` | Drafts written from the tool's behaviour, not reviewed by a forensic laboratory or accredited by any body. [[PENDING-MERGE: A]] SOP-06 intake checklist |
| R23 | Deliverable - validation report | **Partial** | `backend/app/validation/run.py` | `backend/tests/test_validation.py` | `docs/VALIDATION.md`<br>`docs/VALIDATION_REPORT.md`<br>`docs/validation/results.json` | Synthetic only; the real-image section is empty by design. |
| R24 | Deliverable - user manual | **Built** | - | - | `docs/USER_MANUAL.md` | Describes the existing UI; the report and job features are not covered until merged. |

### Vendor tiers

Tier A = validated on real images; B = signature + generic carving; C = planned. Tier A vendors: 0.

| OEM | Tier (claimed) | OEM_COMPARISON.md | Parser in code | Public documentation |
|---|---|---|---|---|
| Hikvision | B | B | Tier B | see OEM_COMPARISON |
| Dahua | B | B | Tier B | see OEM_COMPARISON |
| Honeywell | B | B | Tier B | see OEM_COMPARISON |
| CP Plus | C | C | none | none found |
| Uniview | C | C | none | none found |
| TP-Link VIGI | C | C | none | none found |
| Godrej | C | C | none | none found |
| Matrix Comsec | C | C | none | none found |

## 4. Measured results: recovery on SYNTHETIC images

Source: `docs/validation/results.json` (tool 0.1.0, seed 20260101, 20 trials per scenario, engine `all`, 77 scenario/engine rows). **Results digest (SHA-256, excludes timings): `ba75170eb2516cd0306aff1b72c33fd1fc5b32cc8cc613cfb92814802166526b`.** All images are SYNTHETIC; vendor-layout rows are a circular check.

> SYNTHETIC: every image in this report was generated by Nirikshan's validation harness. Scores show that the pipeline behaves as designed on the layouts we modelled; they do NOT predict performance on real DVR/NVR images.
> Parsers built from a paper's layout and tested on images generated from the same layout are a circular check, not independent validation. Layout variants are labeled 'per-paper layout, not a real device image'.
> No vendor is Tier A (validated on real images with ground truth we created).

| Scenario (generic engine) | Clip recall | Clip precision | Byte-exact | Decode ok |
|---|---|---|---|---|
| `clean_live` | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) |
| `deleted_intact_zero` | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) |
| `zero_gaps` | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) | 100.0% (60/60) |
| `zero_pad_inside_narrow` | 100.0% (40/40) | 100.0% (40/40) | 100.0% (40/40) | 100.0% (40/40) |
| `zero_pad_inside_wide` | 0.0% (0/40) | n/a | 0.0% (0/40) | n/a |
| `random_gaps_between` | 100.0% (60/60) | 100.0% (60/60) | 0.0% (0/60) | 100.0% (60/60) |
| `random_gaps_inside` | 100.0% (40/40) | 100.0% (59/59) | 0.0% (0/40) | 98.3% (58/59) |
| `partial_overwrite_zero` | 100.0% (40/40) | 100.0% (43/43) | 100.0% (20/20) | 76.7% (33/43) |
| `partial_overwrite_foreign` | 100.0% (60/60) | 100.0% (64/64) | 100.0% (20/20) | 53.1% (34/64) |
| `fully_overwritten` | 100.0% (26/26) | 100.0% (26/26) | 100.0% (20/20) | 76.9% (20/26) |
| `fragmented_zero_join_off` | 100.0% (20/20) | 100.0% (55/55) | 0.0% (0/20) | 100.0% (55/55) |
| `fragmented_zero_join_on` | 100.0% (20/20) | 100.0% (23/23) | 85.0% (17/20) | 100.0% (23/23) |
| `fragmented_decoy_join_off` | 100.0% (40/40) | 100.0% (54/54) | 50.0% (20/40) | 100.0% (54/54) |
| `fragmented_decoy_join_on` | 100.0% (600/600) | 100.0% (844/844) | 44.2% (265/600) | n/a |
| `adversarial_noise_with_clips` | 100.0% (40/40) | 100.0% (40/40) | 100.0% (40/40) | 100.0% (40/40) |
| `multi_channel_gop` | 100.0% (52/52) | 40.0% (8/20) | 0.0% (0/52) | 100.0% (20/20) |
| `multi_channel_frame` | 100.0% (54/54) | 30.0% (6/20) | 0.0% (0/54) | 85.0% (17/20) |

Negatives (no cleanly decoding clip must be produced):

| Negative scenario | Clips emitted | Decoded cleanly | Emitted but flagged failed |
|---|---|---|---|
| `neg_noise_start_codes` | 0.0% (0/20) | 0.0% (0/20) | 0.0% (0/20) |
| `neg_encrypted_whole` | 0.0% (0/20) | 0.0% (0/20) | 0.0% (0/20) |
| `neg_encrypted_slices_params_clear` | 90.0% (18/20) | 0.0% (0/20) | 90.0% (18/20) |
| `neg_encrypted_all_payloads` | 0.0% (0/20) | 0.0% (0/20) | 0.0% (0/20) |
| `neg_mjpeg` | 0.0% (0/20) | 0.0% (0/20) | 0.0% (0/20) |
| `neg_mpeg4` | 0.0% (0/20) | 0.0% (0/20) | 0.0% (0/20) |

Vendor-layout rows (54, engines: dahua, dahua+generic, generic, hikvision, hikvision+generic, honeywell, honeywell+generic) are in `docs/validation/results.md`; they measure parsers against images built from the same paper-derived layout and are not independent evidence.

**How to read this.** The generic carver is scored on images built by the same team that wrote it (single encoder family, scenarios co-developed with the carver); several scenarios score poorly on purpose and are reported, not hidden. Parser-versus-same-layout rows are circular. See [VALIDATION.md](VALIDATION.md) ("Limits of this validation") and [VALIDATION_REPORT.md](VALIDATION_REPORT.md).

## 5. Measured results: analytics triage

Source: `docs/analytics/error_rates.json`. Nothing here was validated on real DVR footage. Public-benchmark numbers will not transfer to low-resolution, highly compressed DVR footage; synthetic numbers are not representative either.

| Task | Condition | Confidence | Precision | Recall | n | Label |
|---|---|---|---|---|---|---|
| person detection (Penn-Fudan) | original | 0.3 | 0.6871 | 0.9811 | 170 | public benchmark, not DVR footage; will not transfer to DVR footage |
| person detection (Penn-Fudan) | original | 0.5 | 0.7807 | 0.9764 | 170 | public benchmark, not DVR footage; will not transfer to DVR footage |
| person detection (Penn-Fudan) | original | 0.7 | 0.8805 | 0.9409 | 170 | public benchmark, not DVR footage; will not transfer to DVR footage |
| person detection (Penn-Fudan) | 352x288_crf30 | 0.3 | 0.7351 | 0.9645 | 170 | public benchmark, not DVR footage; will not transfer to DVR footage |
| person detection (Penn-Fudan) | 352x288_crf30 | 0.5 | 0.8319 | 0.9362 | 170 | public benchmark, not DVR footage; will not transfer to DVR footage |
| person detection (Penn-Fudan) | 352x288_crf30 | 0.7 | 0.9421 | 0.8463 | 170 | public benchmark, not DVR footage; will not transfer to DVR footage |
| face detection (BioID) | original | 0.5 | 0.9987 | 1.0000 | 1521 | public benchmark, not DVR footage; will not transfer to DVR footage |
| face detection (BioID) | original | 0.7 | 0.9987 | 1.0000 | 1521 | public benchmark, not DVR footage; will not transfer to DVR footage |
| face detection (BioID) | original | 0.9 | 0.9993 | 0.9987 | 1521 | public benchmark, not DVR footage; will not transfer to DVR footage |
| face detection (BioID) | 352x288_crf30 | 0.5 | 0.9948 | 1.0000 | 1521 | public benchmark, not DVR footage; will not transfer to DVR footage |
| face detection (BioID) | 352x288_crf30 | 0.7 | 0.9987 | 0.9993 | 1521 | public benchmark, not DVR footage; will not transfer to DVR footage |
| face detection (BioID) | 352x288_crf30 | 0.9 | 1.0000 | 0.9816 | 1521 | public benchmark, not DVR footage; will not transfer to DVR footage |
| motion (synthetic clips) | 320x240_crf23 | - | 1.0000 | 1.0000 | 30 | synthetic, not representative of DVR footage |
| motion (synthetic clips) | 352x288_crf33 | - | 1.0000 | 1.0000 | 30 | synthetic, not representative of DVR footage |

These come from public still-image datasets and synthetic clips. They do not describe DVR footage.

## 6. Measured results: OSD timestamp OCR

On 100 rendered synthetic overlays: 91 exactly correct, 9 unreadable, 0 confidently wrong (source: `docs/timeline.md`, parsed). Real DVR overlays are untested.

## 7. Honest limits

- **No real-device validation.** Every score is on synthetic images. Real firmware, encryption, interleaving, wear and file-system quirks are unknown to us.
- **Proprietary filesystem parsing is partial.** Dahua DHFS is not parsed; Hikvision and Honeywell are parsed only as far as public papers describe, with open source conflicts (block size, UTC vs local time, Master Sector offset, header length semantics) exposed as options, not resolved.
- **Five of eight OEMs have no format data** (CP Plus, Uniview, TP-Link, Godrej, Matrix); they get generic carving only and no vendor attribution.
- **Timestamps.** Time zone and time basis are unknown for every vendor until an examiner states them; generic-carved clips carry no timestamps and are unplaceable on the timeline.
- **Not recovered:** MJPEG, MPEG-4 Part 2, encrypted recordings; H.265 has no continuity check.
- **Chain of custody:** examiner identity is an attestation (no authentication); tail truncation is detectable only against an externally recorded `head_hash`; the holder of the signing key can forge entries; no key rotation.
- **Analytics are triage.** Face detection is not recognition; error rates do not transfer to DVR footage.
- **Security and packaging:** self-review only ([SECURITY_REVIEW.md](SECURITY_REVIEW.md)); one dependency (`cryptography` 46.0.7) has open advisories judged unreachable in our usage but not fixed; the offline stack was tested once on one host and its frontend container is not egress-blocked there.
- **Legal:** the BSA 63(4) draft certificate `[[PENDING-MERGE: A]]` is a draft and has had no legal review. Nothing here is accredited or admissible by virtue of being in this report.
- **Licences:** the image's ffmpeg is a GPL build; two datasets have no licence grant ([THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)).
- **Performance:** throughput numbers in ARCHITECTURE.md are one Mac, cache-warm, synthetic; analysis is synchronous until the job work `[[PENDING-MERGE: B]]` merges.

## 8. What we need from NTRO or from a real device

1. **Real DVR/NVR disk images with ground truth** (known clips, times, channels, some deleted) for each OEM in scope, ideally two or more per model, created per [REAL_IMAGE_PLAYBOOK.md](REAL_IMAGE_PLAYBOOK.md). This is the only path from Tier B to Tier A and from C to B.
2. **Firmware and model variety** per OEM; one claim per model, never per brand.
3. **Resolution of the open source conflicts** by inspection of real images (Hikvision block size, time basis, Master Sector offset; Honeywell header length; Dahua checksum and DHFS structure).
4. **Access to vendor documentation** or SDKs under a licence that permits implementation, especially for Dahua DHFS, CP Plus, Uniview, TP-Link, Godrej and Matrix.
5. **Legal review** of the BSA 63(4) draft certificate `[[PENDING-MERGE: A]]` and of how the tool's outputs would be presented.
6. **An authentication and authorisation decision** (identity provider, roles, binding examiner identity to the signed custody entries).
7. **Accredited-laboratory validation** and an agreed acceptance protocol (error-rate reporting, test corpus, review of the SOPs).
8. **Policy on the ffmpeg build and dataset licences** for any redistribution of the packaged images.

## 9. Pending merges at the time of generation

- R10: [[PENDING-MERGE: A]] court-style PDF report, BSA 63(4) draft certificate, CASE JSON-LD export, SOP-06 intake checklist (docs/report.md, docs/legal/, docs/sop/SOP-06-*)
- R17: [[PENDING-MERGE: B]] background jobs, `make demo`, accessibility pass, screenshots (docs/jobs.md, docs/accessibility.md, docs/demo.md)
- R22: [[PENDING-MERGE: A]] SOP-06 intake checklist

## 10. Document index

[README](../README.md) | [Architecture](ARCHITECTURE.md) | [API](API.md) | [User manual](USER_MANUAL.md) | [SOPs](sop/) | [OEM comparison](OEM_COMPARISON.md) | [Research basis](RESEARCH.md) | [Validation](VALIDATION.md) | [Validation report](VALIDATION_REPORT.md) | [Timeline](timeline.md) | [Analytics](analytics/README.md) | [Security review](SECURITY_REVIEW.md) | [Offline deployment](OFFLINE_DEPLOYMENT.md) | [Third-party licences](THIRD_PARTY_LICENSES.md) | [Demo runbook](DEMO_RUNBOOK.md) | [Real-image playbook](REAL_IMAGE_PLAYBOOK.md)
