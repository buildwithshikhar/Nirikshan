# SOP-06: Evidence intake checklist for DVR/NVR evidence (DRAFT)

*Audience: examiners receiving a recorder or its disk image.*

Status: draft for Nirikshan v0.1.0. **No compliance with SWGDE, NIST, ISO/IEC 27037 or any law is claimed.** The checklist was written after reading the SWGDE document below, and has not been audited against it.

## Sources consulted

| Document | URL | Accessed | Read status |
|---|---|---|---|
| SWGDE Best Practices for Data Acquisition from Digital Video Recorders, version 1.0 (25 Apr 2018; sections 9 and 10 list the documentation items) | https://www.swgde.org/wp-content/uploads/2023/11/2018-04-25-SWGDE-Best-Practices-for-Data-Acquis.pdf and https://www.swgde.org/documents/published-complete-listing/17-v-002-swgde-best-practices-for-data-acquisition-from-digital-video-recorders/ | 2026-10-09 | partly: read through a summarising fetch tool (section headings and the item lists), not the full text verbatim |
| SWGDE 17-V-002-1.4 (the current revision, referenced in docs/RESEARCH.md) | https://www.swgde.org/documents/published-complete-listing/17-v-002-1-4/ | 2026-10-09 | snippet only (search result); not read, so differences from v1.0 are unknown |

## Checklist and what Nirikshan records

"Recorded" means stored by the tool; "examiner" means the tool has no field, so write it in your own notes (the case description is free text).

| # | Item (from the 2018 v1.0 lists, as summarised) | Nirikshan |
|---|---|---|
| 1 | Scene address and point of contact | not recorded: examiner |
| 2 | Type of recorder; make, model, serial number | not recorded as fields: examiner (evidence label is free text; the draft certificate leaves them blank) |
| 3 | Usernames/passwords | not recorded; do not store secrets in the case |
| 4 | Cameras capable vs connected; microphones | not recorded: examiner |
| 5 | System time and date versus actual time and date; offset from a known reference; do not change the recorder's clock | recorded as reference observations (device clock reading, true UTC, method, notes, uncertainty) and a fitted offset/drift model with intervals (SOP-04); the tool cannot confirm the clock was untouched |
| 6 | Earliest recorded date/time, storage capacity, overwrite setting, quality/frame rate/resolution | not recorded as fields: examiner; per-clip codec, resolution and frame rate are recorded for carved clips |
| 7 | Firmware version, system logs, photographs of the setup | not recorded; `photo_path` on a reference observation is a reference, not a copy |
| 8 | Write protection for storage devices | recorded as the examiner's attestation (yes/no/unknown), shown as "examiner attestation, not verified by the tool" |
| 9 | Acquisition method and who did it | image acquired read-only; examiner (header attestation), time, source path, type recorded; custody entry written |
| 10 | Integrity of the copy | MD5 and SHA-256 at acquisition; re-hash on every analysis read; verify action recorded |
| 11 | Verification of retrieved date/time and playback | per-clip decode status; OSD cross-check available (SOP-04); no playback proof of byte-faithfulness |
| 12 | Chain of custody | hash-chained, Ed25519-signed log; head_hash printed in the report for external recording |
| 13 | Worksheet kept throughout | the report (SOP-05) is generated from the records; items marked "examiner" above need a paper or separate record |

Do not treat this table as a statement that the tool makes an acquisition conform to SWGDE: the physical acquisition steps happen outside the tool.
