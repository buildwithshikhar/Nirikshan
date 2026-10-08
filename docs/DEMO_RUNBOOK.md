# Demo Runbook (5-minute and 10-minute videos)

*For the person recording. Audience: NTRO reviewers. Rule of the demo: show what exists, say plainly what it is not. Every honesty line below is mandatory; do not cut them to save time.*

**Dependencies on unmerged work.** The demo data and one-command start rely on `make demo` `[[PENDING-MERGE: B]]`; the PDF report step relies on the report feature `[[PENDING-MERGE: A]]`; background jobs `[[PENDING-MERGE: B]]` change how long the analyse step blocks. Until those merge, use the fallbacks marked **FB**. The lead must update steps marked (verify after merge) once the final commands are known.

## 0. Preconditions

- Backend and frontend running (`make demo` `[[PENDING-MERGE: B]]`, or manually per [README](../README.md): backend with `NIRIKSHAN_EVIDENCE_ROOTS` set, `npm run dev`). UI at http://localhost:5173 (dev) or http://127.0.0.1:8080 (offline compose).
- `ffmpeg`/`ffprobe` on the backend PATH (Dashboard must say ffmpeg present).
- Models fetched (`python scripts/fetch_models.py`); without them skip analytics (FB in 4.5).
- A **synthetic** demo image inside an evidence root. `make demo` `[[PENDING-MERGE: B]]` creates a labelled synthetic case; otherwise generate one with the validation harness (the image carries a SYNTHETIC banner) and place it under the evidence root. (verify after merge: exact command)
- A fresh database (`python -m app.cli reset-db --yes`, dev only) so case ids start at 1.
- Browser window at 1280x720, zoom 100%, no bookmarks bar, notifications off. Terminal font large.
- Optional second terminal with `python -m app.cli head <case_id>`.
- Pre-generated screenshots `[[PENDING-MERGE: B]]` (docs/img) and the files docs/validation/results.md and docs/FINAL_REPORT.md open in tabs.

## 1. Pre-flight checklist (do all before recording)

- [ ] Dashboard: version shown, ffmpeg present, signing key id visible, NTP status noted (expected `unknown` on macOS and in containers: say so if asked).
- [ ] `curl -s localhost:<port>/health` returns `ok`.
- [ ] Run the whole script once end to end; time it. Note the analyse duration.
- [ ] Reset the database again and delete any test case you do not want on screen.
- [ ] Open docs/validation/results.md at the top (SYNTHETIC banner visible) in a tab.
- [ ] `python scripts/build_final_report.py --check` prints ok (the traceability table you will show is current).
- [ ] If recording the offline stack: `docker compose -f docker-compose.offline.yml -p nirikshan-offline up -d` finished and the UI loads at 127.0.0.1:8080. Do not claim "no network" for the frontend container (see docs/OFFLINE_DEPLOYMENT.md).
- [ ] Decide the examiner name you will type (use a clearly fictional demo name).

## 2. Five-minute script (4:45 target)

| Time | Show (exact clicks) | Say | Emphasise | Fallback if it fails |
|---|---|---|---|---|
| 0:00-0:30 | Dashboard `/`. Point at version, ffmpeg, key id. | "Nirikshan is a prototype for recovering and documenting surveillance-recorder evidence. Everything you will see runs on synthetic data we generated. No real DVR image has been processed." | Say "synthetic" and "prototype" in the first 15 seconds. | Backend down: show docs/FINAL_REPORT.md section 1 instead and say the live demo is unavailable. |
| 0:30-1:15 | `/cases` > create case `DEMO-001`, title "Synthetic demo", examiner name in the header field. Then case page `/cases/1`: Acquire the synthetic image path, label, write blocker `unknown`. | "Acquisition opens the source read-only, copies once while computing MD5 and SHA-256 together, re-reads the copy and compares. The write-blocker field is an attestation, not a technical control." | Hashes appear; custody entry created. Mention folders are allow-listed (fail-closed). | 403: the path is outside `NIRIKSHAN_EVIDENCE_ROOTS`: say so, fix, retry once; if still failing use the screenshots. |
| 1:15-1:45 | Case page: click Copy on `head_hash`; open `/cases/1/custody`; click "Verify chain and signatures". | "Every action is a signed, hash-chained entry. Verification passes. If someone deletes the newest entries the chain still verifies, so the head hash must be recorded outside the system. That is a documented limit." | Limits stated before the audience finds them. | Verify not ok: stop, explain it is a tamper-detection result, show SOP-02 section 8; do not re-run silently. |
| 1:45-3:15 | `/evidence/1/1` > "Identify + carve". Show vendor box (tier, confidence), clip table, play one clip. | "The vendor is identified from public signatures only. Tier B means signature plus generic carving; the vendor parser has never seen a real device. Confidence is capped at medium for that reason. These clips were recovered from a synthetic image whose answer we know." | Tier B, "circular check", offsets and hashes per clip, MP4 stream copy + decode test. | Slow analyse: cut the recording, resume when finished (jobs `[[PENDING-MERGE: B]]` make this non-blocking). Browser cannot play H.264: show the clip table and say Chromium builds may lack H.264; open the MP4 in a native player. |
| 3:15-4:00 | `/cases/1/timeline`. Show a clip with an uncertainty bar and the "unplaceable" group. | "Timestamps are never given a default time zone. Until the examiner states one, clips are listed as unplaceable. This is deliberate." | The unplaceable group is a feature, not a bug. | Empty timeline: show docs/timeline.md figure descriptions. |
| 4:00-4:45 | Open docs/FINAL_REPORT.md: the traceability table and sections 4 and 7 (or `/` of the PDF report `[[PENDING-MERGE: A]]`). | "Here is the requirement matrix. Read the computed counts line: only a minority are Built, most are Partial, and real-device validation is Planned. What we need next is real recorder images with ground truth." | Show the Planned rows and the digest of the validation results. | Report page missing: use the markdown FINAL_REPORT. |

Closing line (spoken at the end of the last row): "Prototype, synthetic data, Tier B, not validated on real devices. The path forward is in section 8 of the report."

## 3. Ten-minute script (9:30 target)

Follow the five-minute script, replacing the timings below, and add the extra segments.

| Time | Show | Say | Emphasise | Fallback |
|---|---|---|---|---|
| 0:00-0:45 | Dashboard, then docs/FINAL_REPORT.md section 1-2 | As 5-minute opening plus one sentence on scope: acquisition, carving, parsers, timeline, triage, custody. | "Prototype" and "synthetic". | As above. |
| 0:45-2:15 | Case + acquisition (as above); then the evidence table: click **Verify**. | Explain MD5+SHA-256, re-verification before every analysis stage. | Integrity gate: an altered image is refused (409). | If you want to show tamper detection live, do it on a copy outside the demo case and say so. |
| 2:15-3:15 | Custody page: verify; `python -m app.cli head 1` in the terminal. | Head-hash practice; the key is the trust anchor; examiner identity is an attestation (anyone who can reach the API can claim any name). | Say the authentication gap aloud (SECURITY_REVIEW 2.1). | Skip the CLI if the terminal is unavailable. |
| 3:15-5:15 | Analysis page: identify + carve; open the parser panel (parsed / inferred / unknown chips; "timezone: not assumed"); cross-check box; clip table; play a clip. | "Fields are tagged by how we know them. Open source conflicts are options, not silent choices." | Parser results are a circular check; DHFS is not parsed; five vendors have no parser. | If no vendor image is available, run on a generic image and show the generic carver only; say the parser panel needs a vendor-layout image. |
| 5:15-6:15 | docs/validation/results.md: the SYNTHETIC banner, a good row (`clean_live`) and a bad row (`zero_pad_inside_wide`, clip recall 0 in the table), plus the digest. | "We publish the scenarios we fail. These numbers describe our own synthetic images, not field performance." | Show a failing row on camera. | If the page will not render, show the FINAL_REPORT section 4 table. |
| 6:15-7:15 | `/clips/<id>/analytics`: run objects (or motion) on a clip. | "Triage, not identification. Face detection only; no recognition exists in the code. Error rates come from public still-image sets and do not transfer to DVR footage." Show the error-rate panel. | The label "triage, not identification" and the model hash. | Models missing (503 with fetch command): skip, show the panel from docs/analytics/error_rates.json via FINAL_REPORT section 5. |
| 7:15-8:15 | Timeline: set a device time zone assumption with a note on one evidence item, then reopen the timeline. Show CSV export. | "The time zone is an examiner assumption with evidence, recorded in custody. Without it nothing is placed." | Uncertainty bars; `source_conflict` flags. | Skip the assumption step; show the unplaceable group only. |
| 8:15-9:00 | Report step: generate the PDF report `[[PENDING-MERGE: A]]` and open it; show chain verification result and tier/limits section. (verify after merge) | "The report carries the head hash, tiers and error rates; the BSA 63(4) certificate is a draft with no legal review." | Draft status of the certificate. | Report unavailable: show SOP-05 and say the PDF is pending. |
| 9:00-9:30 | docs/FINAL_REPORT.md sections 7 and 8; docs/SECURITY_REVIEW.md summary table. | Honest limits and "what we need from NTRO". | Planned rows; GPL ffmpeg and licence flags; unreachable-but-open `cryptography` advisories. | None needed. |

## 4. Things never to say

- "Validated", "accurate", "court-ready", "admissible", "forensically sound on real devices".
- Any recovery percentage without the words "on synthetic images".
- "Supports" any OEM without its tier; never mention CP Plus, Uniview, TP-Link, Godrej or Matrix as supported.
- "Secure" or "air-gapped" without the caveats in SECURITY_REVIEW and OFFLINE_DEPLOYMENT.
- That the face feature identifies anyone.

## 5. Recording tips

Record at 1080p; keep the cursor slow; leave each limit on screen for two seconds; show the exact documents named in this runbook rather than paraphrasing them. If any step fails twice, use its fallback and say on camera that it is a fallback.
