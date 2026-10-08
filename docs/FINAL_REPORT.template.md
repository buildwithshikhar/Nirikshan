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

{{TRACE_MATRIX}}

### Vendor tiers

{{TIER_TABLE}}

## 4. Measured results: recovery on SYNTHETIC images

{{VALIDATION}}

**How to read this.** The generic carver is scored on images built by the same team that wrote it (single encoder family, scenarios co-developed with the carver); several scenarios score poorly on purpose and are reported, not hidden. Parser-versus-same-layout rows are circular. See [VALIDATION.md](VALIDATION.md) ("Limits of this validation") and [VALIDATION_REPORT.md](VALIDATION_REPORT.md).

## 5. Measured results: analytics triage

{{ANALYTICS}}

These come from public still-image datasets and synthetic clips. They do not describe DVR footage.

## 6. Measured results: OSD timestamp OCR

{{OCR}}

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

{{PENDING}}

## 10. Document index

[README](../README.md) | [Architecture](ARCHITECTURE.md) | [API](API.md) | [User manual](USER_MANUAL.md) | [SOPs](sop/) | [OEM comparison](OEM_COMPARISON.md) | [Research basis](RESEARCH.md) | [Validation](VALIDATION.md) | [Validation report](VALIDATION_REPORT.md) | [Timeline](timeline.md) | [Analytics](analytics/README.md) | [Security review](SECURITY_REVIEW.md) | [Offline deployment](OFFLINE_DEPLOYMENT.md) | [Third-party licences](THIRD_PARTY_LICENSES.md) | [Demo runbook](DEMO_RUNBOOK.md) | [Real-image playbook](REAL_IMAGE_PLAYBOOK.md)
