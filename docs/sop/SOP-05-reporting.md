# SOP-05: Reporting (DRAFT; the court-style PDF report is PLANNED for P7 and does not exist yet)

*Audience: forensic examiners preparing a written account of what Nirikshan did and found, and reviewers checking that account.*

Status: draft for Nirikshan v0.1.0. Written with reference to the guidance in `docs/RESEARCH.md` section 8 (NIST SP 800-86; SWGDE 17-V-002-1.4; ISO/IEC 27037 and ACPO not accessible). **Not audited** against any of them; no compliance claim is made.

## 1. Purpose
Define what any report built from Nirikshan output must contain so that every statement is traceable to a hash, a tool version, a recorded parameter or a stated limitation.

## 2. Scope
Today: a manual report assembled by the examiner from exports. Planned (P7): an automatically generated PDF. This SOP gives the manual procedure now and the planned report contents so the manual report is already structured the same way.

## 3. Roles
Examiner (author), reviewer (checks traceability and wording), supervisor (approves, holds external `head_hash` record).

## 4. Preconditions
- Evidence acquired, verified (SOP-01, SOP-02); analysis run (SOP-03); timestamp statements prepared per SOP-04.
- Image verify and chain verify pass **at report time**, and `head_hash` matches your external record.

## 5. Procedure: manual workflow available today
1. Re-run **Verify** on every evidence item and **Verify chain and signatures**. Save the outputs. Compare `head_hash` and entry count with your external record.
2. Export the custody log (`GET /api/cases/{id}/custody`) and the verification result (`GET /api/cases/{id}/custody/verify`); save the public key (`GET /api/signing-key`). Optionally export the audit trail (`GET /api/audit?case_id=`).
3. Export the analysis run (`GET /api/runs/{id}`): parameters, vendor matches, parser results, cross-check, clip list with offsets and hashes.
4. For each clip you will cite: press "Verify MP4 hash", copy the bitstream SHA-256 and MP4 SHA-256, and the byte extents. Compute SHA-256 of any file you hand over (e.g. `shasum -a 256 clip.mp4`) and list it.
5. Compute and record the SHA-256 of the report file itself when final (the planned P7 feature will record this in the custody log; today it is manual).
6. Write the report with the **mandatory content** in section 6, and have it reviewed against section 7.
7. Record the report's hash and the report date in your external log together with the current `head_hash`.

## 6. What must appear in any report
| Item | Content |
|---|---|
| Identification | Case number and id, examiner name(s) as attested, dates, report version |
| Tool | Nirikshan version (`tool_version`), ffmpeg version, signing `key_id`, commit/tag if known |
| Evidence | For every item: label, source path as acquired, size, **MD5 and SHA-256**, write-blocker attestation exactly as entered (`yes`/`no`/`unknown`, noting it is an examiner statement), acquisition time (UTC), imaging-tool hash comparison |
| Custody | Chain verification result, entry count, `head_hash`, whether it equals the externally recorded value, how the external record was kept |
| Method | Analysis run id, all parameters (`max_pad`, `join_gap`, `h264_continuity`, `validate_params`), parser options, pipeline order |
| Vendor / parser | Vendor match and confidence (low/medium only), **parser tier (B or C) and its caveats**: not validated on any real device; synthetic layouts are a circular check; no Tier A |
| Parser field status | Which fields were parsed, inferred or unknown, and the raw values quoted |
| Open conflicts | Each source conflict relevant to the findings (Hikvision UTC vs local, block size, Master Sector base, Honeywell header length semantics, Dahua checksum and frame-number tolerance), the option used, and that it is unsettled |
| Results | Per clip: engine, offsets (decimal and hex), sizes, bitstream and MP4 SHA-256, decode status and listed errors, orphans, failed decodes, cross-check disagreements and how each was decided |
| Timestamps | Per SOP-04: raw value, field, basis, offset evidence, uncertainty; "unknown" where unknown |
| Error rates | The synthetic validation figures with the statement that they are synthetic, do not predict real-device performance and carry the circularity caveat (cite `docs/VALIDATION_REPORT.md` and its digest). Report the reassembler false-accept rate (11.8% (35/297), 95% CI 9-16%, synthetic) if reassembly was used. **No real-device recovery rate may be stated**; none exists |
| Limitations | The known limits in SOP-03 section 9 that apply (decode ok is not byte-faithful; absence of clips is not absence of video; nominal durations; channel attribution; encryption) |
| Reviewer | Who reviewed, when, which checks were done |

Wording rules: write "identified as consistent with <vendor> signatures (Tier B, not validated on real devices)", never "the recorder was <vendor>"; write "recovered candidate clip", never "the recording"; never write "validated" for a real device.

## 7. Integrity checks (before release)
- Every number and hash in the report appears in a saved export; spot-check at least the cited clip hashes against a fresh "Verify MP4 hash".
- Tier and caveat text matches the current code and `IMPLEMENTATION_PLAN.md` (Hikvision B, Dahua B, Honeywell B; others C; none A).
- The report states which parts are examiner statements (write blocker, time zone, reference clock) and which are tool outputs.
- Chain valid and `head_hash` matches at the moment of release.

## 8. Failure handling
| Situation | Action |
|---|---|
| Chain verify fails at report time | Do not release a report that relies on the case; escalate (SOP-02 section 8); if a report must be issued, it must state the failure |
| Hash mismatch on a clip | Re-run the analysis from the verified image; report both |
| Open conflict affects a conclusion | State the conclusion as conditional on each side of the conflict, or escalate for a real-image test |
| Report text later found to overstate | Issue a corrected version; keep the old one and its hash |

## 9. What the tool does NOT do today
- It does **not** generate a report. The court-style PDF is planned (P7) and has not been built; nothing below is available until it is merged.
- It does not record a report's hash in the custody log yet.
- It does not check your wording against the evidence.

## 10. Planned report (P7; per `IMPLEMENTATION_PLAN.md`, not built, subject to change)
Planned contents: case id, examiner, tool and parser versions, evidence hashes (MD5 + SHA-256), acquisition log, custody chain verification result, audit trail, per-vendor tier and limitations, recovery results with offsets, timestamp assumptions, and analytics error rates; the PDF's SHA-256 recorded in the custody log; a tampered custody chain makes the report state a chain failure. Planned tests: required sections and hashes parsed back from the PDF, regeneration determinism. Companion planned deliverables: validation report (a draft exists: `docs/VALIDATION_REPORT.md`), SOP and manual revisions. Until P7 exists, the manual procedure above is the only supported route, and a generated report, when it exists, will not remove the examiner's duty to review it.
