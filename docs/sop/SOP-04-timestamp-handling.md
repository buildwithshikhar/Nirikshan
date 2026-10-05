# SOP-04: Timestamp Handling (DRAFT; automated normalization is IN PROGRESS, not available)

*Audience: forensic examiners who must state when recorded video was recorded and how certain that statement is.*

Status: draft for Nirikshan v0.1.0. Written with reference to NIST SP 800-86 (clock inaccuracy warning, read) and SWGDE 17-V-002-1.4 (record the DVR time against a standardised reference, do not change the DVR time, calculate the offset; page read), as summarised in `docs/RESEARCH.md` sections 6 and 8. ISO/IEC 27037 and ACPO were not accessible. **Not audited** against any of them; no compliance claim is made.

## 1. Purpose
Prevent unsupported time statements. Describe what Nirikshan reports today (raw values only), what the examiner must supply, and the planned P5 workflow.

## 2. Scope
Per-vendor timestamp fields reported by parsers (Dahua, Hikvision, Honeywell), the reference-time evidence the examiner collects, and the manual calculation used until P5 exists. Clip "nominal durations" are not timestamps (SOP-03).

## 3. Roles
Examiner (collects reference evidence, states assumptions); reviewer (checks that every stated time carries its basis and uncertainty).

## 4. Preconditions
- Whenever the recorder is available: its configured **time zone and DST setting**, its displayed clock, and a photograph of its clock next to a trusted reference clock (NTP-synchronised device) taken at one moment, with the reference device named. Do not change the recorder's time (SWGDE practice as summarised in RESEARCH section 6).
- If the recorder is not available, record that fact; the offset is then unknown and must be reported as unknown.
- Burned-in on-screen-display (OSD) times visible in recovered footage, if any, preserved as evidence (screenshots with clip id and frame position).

## 5. Procedure (what is possible today)
1. **Read the raw values only.** The parser panel lists each timestamp as: field name, byte offset, raw integer, format, a plain decode of the integer "as stored", and `tz_basis` = **"not assumed"**. The plain decode is arithmetic on the integer and is **not** a time-zone claim.
2. **Never assume a time zone.** Nirikshan does not default one. Neither should you: a time zone must come from evidence (device setting recorded in the preconditions, or a measured offset).
3. **Know the per-vendor facts and conflicts** (RESEARCH sections 2, 3, 6; parser docs):

| Vendor / field | Format | What the sources say | Status |
|---|---|---|---|
| Hikvision Master Sector init time, HIKBTREE entry times | Unix seconds, u32 LE | Han 2015 describes them as UTC | **Conflict**: Dragonas states log times are in the recorder's local zone and that neither study could determine whether an offset is stored on disk. The structures differ and no single device was tested for both; the true basis of each field is unsettled |
| Hikvision log (RATS) record time | Unix seconds, u32 LE | Local time of the recorder per Dragonas | The same author's tool comments say the opposite; unsettled |
| Dahua DHAV frame date | bit-packed Y/M/D/h/m/s (+2000), with a 16-bit sub-second field | FFmpeg `dhav.c` reads it as wall-clock time with no time-zone or DST field | "Local wall-clock time" is an **inference from code**, not a documented statement |
| Honeywell block times / per-NAL times | Unix seconds / Unix microseconds | The paper does not state UTC or local; its quoted wall-clock strings equal the UTC rendering of the stored values | Time zone **unknown**; the paper's authors may have rendered UTC |
| DST, all vendors | | No source documents DST handling | **Unknown** |

   Parser option `time_basis_label` (`utc` / `local`) for Hikvision and Honeywell only **relabels** the `tz_basis` text; it changes no value and proves nothing. Use it only to record your documented assumption.
4. **Collect reference evidence** (preconditions). Compute the clock offset: `offset = recorder displayed time - reference time` at the same instant, with the readings, the reference device and the photograph recorded.
5. **State a time only in this form**: "Device-local time as stored: `<raw decode>` (field `<name>`, vendor `<v>`, basis `<assumed/unknown>`); offset to reference `<value ± reading uncertainty>`, measured `<date>` from `<evidence>`; time zone `<source or unknown>`; DST `<source or unknown>`." If the time zone or offset is unknown, say so; do not give a UTC time.
6. **Cross-check the metadata against the footage.** If the clip shows a burned-in clock, compare it by eye with the metadata time and record the difference. No source we read compares OSD to container time; do not assume they agree.
7. **Check for time reversals** in Hikvision data (init time, IDR-table times and HIKBTREE times out of order indicate re-initialisation or clock change per Han 2015; this is an indicator, not a proof of tampering).
8. **Do not extend one clock reading to the whole recording period.** Drift and clock changes are not corrected by the tool; a single measured offset describes the moment of the measurement.

## 6. Records to keep
Recorder time-zone/DST setting and evidence; the clock-versus-reference photograph and reading; reference device name; each raw timestamp with field, offset, vendor and the parser option settings; the offset calculation; every assumption and who made it; OSD comparison notes.

## 7. Integrity checks
- Each stated time can be traced to a raw value in the parser output and to an offset measurement.
- The assumption (zone, offset) is written next to every time; a reviewer can find the evidence for it.
- Conflict fields (Hikvision UTC vs local) are named as conflicts in the report.

## 8. Failure handling
| Situation | Action |
|---|---|
| Recorder unavailable, no photo | Report times as "device-local, offset unknown"; no UTC |
| Recorder zone not configured or unknown | Report unknown; do not guess from location |
| Decoded date implausible (e.g. year far from the case period) | Record as an inconsistency; it may reflect a wrong clock, a wrong field interpretation or corruption |
| Hikvision UTC-vs-local question matters to the case | Escalate for a real-image test (REAL_IMAGE_PLAYBOOK checklist item on time basis) before stating a conclusion |
| Reference photo shows the recorder clock drifted or was changed | Report the measured offset with its date; do not apply it retroactively |

## 9. What the tool does NOT do today
- It does not normalise to UTC, does not model DST, drift or offsets, does not read OSD burned-in times and does not build a cross-camera timeline. Raw values and a plain arithmetic decode only.
- It does not know the recorder's time zone and will not guess.
- It has not been tested against any real device's timestamps; all timestamp parsing is validated only on synthetic per-paper layouts (a circular check).
- Nominal clip durations are not recording times.

## 10. Planned workflow (P5, IN PROGRESS, not merged; subject to change)
Per `IMPLEMENTATION_PLAN.md` P5 the intended design is: the examiner enters the device time zone and reference times; each timestamp keeps its raw value, field, format, assumed zone and the evidence for the assumption; an unknown zone is surfaced and never defaulted; the Hikvision UTC-vs-local and Dahua local-time inference are flagged; a drift model estimates offset and linear drift with an interval from reference observations; an OSD OCR cross-check compares burned-in time to metadata and reports the delta distribution; a cross-camera timeline shows per-source uncertainty and gaps; timeline exports carry the uncertainty. Its stated acceptance test is synthetic images with injected offset, DST and drift normalised within a stated bound, which will again be a synthetic result. This SOP will be revised when P5 is merged and its behaviour can be checked in the code; until then follow sections 5 to 9.
