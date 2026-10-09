# Demo Runbook (5-minute and 10-minute videos)

*For the person recording. Audience: NTRO reviewers. Rule of the demo: show what exists, say plainly what it is not. Every honesty line below is mandatory; do not cut them to save time.*

**Data origin line (say it in the first 15 seconds).** "Everything you will see runs on reference test data: built from published research and open-source format documentation, with known ground truth. It was not captured from a physical DVR. No vendor is supported above Tier B and nothing has been validated on a real device." The UI shows the same text in a banner on every screen and in the footer.

**Rehearsal status.** Every step below was run against `make demo` on 2026-10-09 with `frontend/scripts/rehearse.mjs` (a Playwright script, `node scripts/rehearse.mjs`), on an Apple-silicon Mac with a warm cache. Timings are what that run measured; your machine will differ. A live recording on a real laptop adds typing and talking time; the timings below are the machine's share only. Not rehearsed: the offline Docker stack (see the checklist), a browser other than Chromium, and any real recorder image (none was ever processed).

## 0. Pre-recording checklist (do all of it, in order)

- [ ] **Ports free, IPv4 and IPv6.** `make demo` picks API port 8100 and web port 5273, or the next free ones upward, and prints the real URLs; a previous run that is still shutting down can push it to 8101/5274. Check first: `lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(810[0-9]|527[0-9]) '` should print nothing. Vite listens on IPv6 `::1`, so a plain `curl 127.0.0.1` probe can miss a leftover. Stop a leftover with `pkill -INT -f scripts/demo.py`, wait about 8 seconds, check again.
- [ ] **ffmpeg and ffprobe on PATH** (`ffmpeg -version`; on macOS Homebrew: `export PATH=/opt/homebrew/bin:$PATH`). The Dashboard must say ffmpeg is present. Without it, clip export fails.
- [ ] **Models fetched** for the analytics step: `backend/.venv/bin/python scripts/fetch_models.py`. Without them skip analytics (fallback in step 7).
- [ ] **Clean data dir.** `make demo` uses its own throw-away data directory and re-creates it on every start, so the case always has id 1 and the three reference images are evidence 1 (Hikvision layout), 2 (Dahua DHAV layout) and 3 (raw H.264). Do not point the demo at your working database. If you run the backend by hand instead, reset the dev database with `python -m app.cli reset-db --yes` first.
- [ ] **Start the demo in its own terminal** (`make demo`) and leave it running. Warm start to "API up, web up, case seeded" measured 1-5 seconds; the first start after cloning also installs dependencies and takes longer, so do that before recording.
- [ ] Dashboard shows version, ffmpeg, signing key id. NTP status `unknown` is expected on macOS and in containers; say so if asked.
- [ ] `python scripts/build_final_report.py --check` prints ok (the report and README numbers are current).
- [ ] Browser window 1280x720, zoom 100%, bookmarks bar hidden, notifications off, terminal font large.
- [ ] Tabs ready: `docs/validation/results.md` (top of page, the "Reference test data" headline visible), `docs/FINAL_REPORT.md`, `docs/img/report-sample-page1.png`.
- [ ] Decide the examiner name you will type (clearly fictional). It must be typed in the header field before any action, otherwise actions are refused.
- [ ] Run the whole script once end to end; delete anything you created (restart `make demo` to get a clean case).
- [ ] Offline stack only if you will show it: `docker compose -f docker-compose.offline.yml -p nirikshan-offline up -d`; UI at 127.0.0.1:8080. Do not claim "no network" for the frontend container (docs/OFFLINE_DEPLOYMENT.md). Not rehearsed in this pass.

## 1. What `make demo` has already done for you

It seeded case `DEMO-REFERENCE-001` (case id 1) with three reference images, acquired them, and ran identify + carve on each, so the case page, evidence pages, timeline and report already have content. The images start with a 256-byte machine marker, `NIRIKSHAN SYNTHETIC TEST IMAGE - NOT REAL DVR DATA`, which is intentionally unchanged. You can re-do any step live (acquire, carve) as the script shows; the demo case is only a head start. URLs below assume the default ports.

## 2. Five-minute script (4:45 target)

Measured machine time per step is in the last column (rehearsal, warm).

| Time | Show (exact clicks) | Say | Emphasise | Fallback if it fails | Measured |
|---|---|---|---|---|---|
| 0:00-0:30 | Dashboard `http://localhost:5273/`. Point at the "Reference test data" banner, version, ffmpeg, key id, and the Tier B footer. | The data-origin line above, then: "Nirikshan is a prototype for recovering and documenting surveillance-recorder evidence." | "Reference test data", "prototype" and "Tier B" in the first 15 seconds. | Backend down: show docs/FINAL_REPORT.md section 1 and say the live demo is unavailable. | 0.3 s |
| 0:30-1:15 | `/cases`: type your examiner name in the header field. Open case 1 (`/cases/1`). Acquire a new image: path from the demo evidence folder (`demo-data/evidence/…`, shown in the demo terminal), a label, write blocker `unknown`. | "Acquisition opens the source read-only, copies once while computing MD5 and SHA-256 together, re-reads the copy and compares. The write-blocker field is an attestation, not a technical control." | Hashes appear; a custody entry is created. Folders are allow-listed (fail-closed). | 403: the path is outside `NIRIKSHAN_EVIDENCE_ROOTS`; say so, use the path the demo terminal printed, retry once; else use docs/img screenshots. | 0.2 s (tiny image) |
| 1:15-1:45 | Case page: click Copy on `head_hash`; open `/cases/1/custody`; click "Verify chain and signatures". | "Every action is a signed, hash-chained entry. Verification passes. If someone deletes the newest entries the chain still verifies, so the head hash must be recorded outside the system. That is a documented limit." | Limits stated before the audience finds them. | Verify not ok: stop, explain it is a tamper-detection result, show SOP-02 section 8; do not re-run silently. | 0.1-0.2 s |
| 1:45-3:15 | `/evidence/1/3` (the raw image): "Identify + carve". Show the vendor box (tier, confidence), clip table, play one clip. For a vendor layout use `/evidence/1/1` or `/evidence/1/2`. | "The vendor is identified from public signatures only. Tier B means signature plus generic carving; the vendor parser has never seen a real device. Confidence is capped at medium. These clips were recovered from an image whose answer we know." | Tier B, "circular check", offsets and hashes per clip, MP4 stream copy plus decode test. | Slow analyse: cut and resume (it runs as a background job with a progress bar). Browser cannot play H.264: show the clip table, say Chromium builds may lack H.264, open the MP4 natively. | Job 2.0 s; 3 clips; MP4 ~0.2 MB |
| 3:15-4:00 | `/cases/1/timeline`. Show placed clips with uncertainty bars and the "unplaceable" group (7-9 items in the rehearsal). | "Timestamps are never given a default time zone. Until the examiner states one, clips are listed as unplaceable. This is deliberate." | The unplaceable group is a feature. | Empty timeline: show docs/timeline.md. | 0.3 s |
| 4:00-4:45 | `docs/FINAL_REPORT.md`: the highlights table at the top, the traceability table, sections 4 and 7; or the generated PDF (`docs/img/report-sample-page1.png`). | "Read the computed counts: only a minority are Built, most are Partial, real-device validation is Planned. What we need next is real recorder images with ground truth." | The Planned rows and the digest of the validation results. | Report page missing: use the markdown FINAL_REPORT. | n/a |

Closing line: "Prototype, reference test data, Tier B, not validated on real devices. The path forward is in section 8 of the report."

## 3. Ten-minute script (9:30 target)

Follow the five-minute script with the timings below and the extra segments.

| Time | Show | Say | Emphasise | Fallback | Measured |
|---|---|---|---|---|---|
| 0:00-0:45 | Dashboard, then docs/FINAL_REPORT.md sections 1-2 | Five-minute opening plus one sentence on scope: acquisition, carving, parsers, timeline, triage, custody. | "Prototype", "reference test data", Tier B. | As above. | 0.3 s |
| 0:45-2:15 | Case + acquisition (as above); then on the case page click **Verify** next to an evidence item. | MD5+SHA-256, re-verification before every analysis stage. | Integrity gate: an altered image is refused (409). | To show tamper detection live, do it on a copy outside the demo case and say so. | 0.2 s |
| 2:15-3:15 | Custody page: verify; `python -m app.cli head 1` in a terminal. | Head-hash practice; the key is the trust anchor; examiner identity is an attestation (anyone who can reach the API can claim any name). | Say the authentication gap aloud (SECURITY_REVIEW 2.1). | Skip the CLI if no terminal. | 0.1 s |
| 3:15-5:15 | `/evidence/1/1` (Hikvision layout): identify + carve; parser panel (parsed / inferred / unknown chips, "timezone: not assumed"); cross-check box; clip table; play a clip. | "Fields are tagged by how we know them. Open-source conflicts are options, not silent choices." | Parser results are a circular check; DHFS is not parsed; five vendors have no parser. | No vendor image: use `/evidence/1/3` and say the parser panel needs a vendor-layout image. | ~2 s |
| 5:15-6:15 | docs/validation/results.md: the "Reference test data" headline, a good row (`clean_live`, 100%) and a bad row (`zero_pad_inside_wide`, 0 of 40 clips) plus the digest. | "We publish the scenarios we fail. These numbers describe our own generated images, not field performance." | Show a failing row on camera. | If the page will not render, show the FINAL_REPORT section 4 table. | n/a |
| 6:15-7:15 | `/clips/<id>/analytics` (click "Triage analytics" on a clip): "Run objects". | "Triage, not identification. Face detection only; no recognition exists in the code. Error rates come from public still-image sets and do not transfer to DVR footage." Show the error-rate panel. | "Triage, not identification" and the model hash. | Models missing (503 with the fetch command): skip, show docs/analytics/error_rates.json via FINAL_REPORT section 5. | 0.5-0.8 s |
| 7:15-8:15 | Timeline: on evidence 3 (raw) set a device timezone and a note, press "Save time assumption", reopen the timeline. Show CSV export. | "The time zone is an examiner assumption with evidence, recorded in custody. Without it nothing is placed. Notice that the raw-image clips stay unplaceable even now: they carry no timestamps in the data, so the assumption has nothing to convert." | Uncertainty bars; `source_conflict` flags; the banner changes to "assumed by examiner … not an observation". | Skip the assumption step; show the unplaceable group only. | 0.7 s; CSV 0.1 s |
| 8:15-9:00 | Case page: press "Generate report", then "Download PDF"; open it; show the cover block (data origin, Tier B limit), chain verification result and limits section. | "The report carries the head hash, tiers and error rates; the BSA 63(4) certificate is a draft with no legal review." | Draft status of the certificate. | Report unavailable: show `docs/img/report-sample-page1.png` and SOP-05. | 0.2 s; ~0.1 MB |
| 9:00-9:30 | docs/FINAL_REPORT.md sections 7 and 8; docs/SECURITY_REVIEW.md summary. | Honest limits and "what we need from NTRO". | Planned rows; GPL ffmpeg and licence flags; the dependency audit results in SECURITY_REVIEW 5.0. | None needed. | n/a |

## 4. Rehearsal findings (what changed because of running it)

- The old runbook told the presenter to create case `DEMO-001` and open `/evidence/1/1`. `make demo` now creates `DEMO-REFERENCE-001` with three images, so ids are fixed as above.
- The old text said the banner reads "SYNTHETIC"; the banner and footer now carry the reference-data wording and the Tier B limit.
- `make demo` can move to the next free ports (8101/5274) when a previous run is still closing; the URLs are printed in the demo terminal. A leftover Vite on IPv6 used to abort the start; fixed in `scripts/demo.py` (probes IPv4 and IPv6, scans upward).
- Found by the rehearsal: the timezone dropdown listed `Asia/Calcutta` but not `Asia/Kolkata` in Chromium, so an Indian examiner could not pick Kolkata. Fixed: the common zone names are always offered.
- Carving a demo-sized image finishes in about 2 seconds, so the "slow analyse" fallback is for larger images only; none was timed.

## 5. Things never to say

- "Validated", "accurate", "court-ready", "admissible", "forensically sound on real devices".
- Any recovery percentage without the words "on reference test data (generated, not captured from a physical DVR)".
- "Supports" any OEM without its tier; never mention CP Plus, Uniview, TP-Link, Godrej or Matrix as supported.
- "Secure" or "air-gapped" without the caveats in SECURITY_REVIEW and OFFLINE_DEPLOYMENT.
- That the face feature identifies anyone.

## 6. Recording tips

Record at 1080p; keep the cursor slow; leave each limit on screen for two seconds; show the exact documents named in this runbook rather than paraphrasing them. If any step fails twice, use its fallback and say on camera that it is a fallback.
