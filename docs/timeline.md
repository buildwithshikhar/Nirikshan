# Timestamp normalisation and cross-camera timeline (P5)

Code: `backend/app/timeline/` (`timestamps.py`, `drift.py`, `osd.py`, `timeline.py`, `models.py`,
`routes.py`); UI: `frontend/src/pages/Timeline.tsx` (+ `components/TimeSettings.tsx`,
`TimelineChart.tsx`, `api_timeline.ts`).

**Nothing here was validated on a real DVR/NVR.** All tests use synthetic values, rendered
overlays and synthetic MP4s. The decoders follow the public sources in RESEARCH sections 2, 3 and
6; those sources conflict or are silent on timezone semantics, so every UTC value is conditional
on an examiner assumption that is stored with its evidence.

## 1. Data model

`TimestampRecord` (one per raw parser timestamp, derived on demand from `Clip.parsed_json`; never
stored, so a changed assumption re-derives it) always carries:

| Field | Meaning |
|---|---|
| `raw`, `field`, `format`, `offset` | exactly what the parser emitted (value, name, format string, byte offset) |
| `source` | evidence id, clip id, parser/vendor |
| `wall_clock_as_stored` | plain decode, no timezone claim |
| `assumed_timezone`, `epoch_basis` | the examiner's assumption (IANA name or None; `utc`/`device_local`/None) |
| `tz_evidence` | `examiner_entered: <notes>` / `device_setting_note: <notes>` / `none` |
| `tz_status` | `unknown` or `examiner_assumed` |
| `utc_lo`, `utc_hi` | UTC interval, **None when the timezone/basis is unknown** (never defaulted to UTC or local) |
| `candidates` | both instants for a DST-ambiguous time |
| `flags` | `tz_unknown`, `dst_ambiguous`, `dst_gap`, `epoch32_signed_overflow`, `epoch32_u32_wrap`, `invalid_date`, `source_conflict`, `unsupported_format`, `implausible_date` |
| `corrected_utc_lo/hi`, `drift_model_id` | drift-corrected interval, reported next to (never instead of) the uncorrected one |

DB tables (`timeline/models.py`): `time_assumptions` (one current row per evidence; history is the
custody log), `time_references` (device clock reading, true UTC time, method, notes, photo path
reference, reading uncertainty, examiner), `time_models` (append-only fitted models), `osd_checks`.
Every create/update writes a custody entry with the full values: `time_assumption_set` (before and
after), `time_reference_added`, `time_model_fitted`, `osd_check`.

## 2. Assumed vs observed

* **Observed** (read from bytes): raw values, offsets, formats.
* **Assumed** (examiner): device timezone, epoch basis, that the reference observation is right.
* **Inferred by the tool** (stated in outputs): DHAV packed date is a local wall clock (no tz field
  exists; inference from ffmpeg `dhav.c`); linear drift; for a single reference observation, zero
  drift plus an assumed maximum drift bound (default 100 ppm, an engineering assumption, not a
  sourced figure) used only to widen the interval.
* Epoch fields (Hikvision, Honeywell) are placed only if the examiner states `epoch_basis`:
  `utc` places the instant directly; `device_local` needs a timezone and treats the number as a
  wall clock. With the basis unset they are placed only if the timezone is exactly `UTC` (both
  readings agree). A timezone alone does NOT imply a basis.
* Resolution: DHAV and unix seconds are 1 s, Honeywell 1 us; the instant lies in
  `[value, value + resolution)`.

## 3. Source conflicts (kept visible)

All three vendors set the `source_conflict` flag plus a note on every record: Hikvision (Han 2015
calls init/HIKBTREE times UTC; Dragonas says log times are the recorder's local time; no device was
tested for both), Dahua (no timezone field; local wall clock is an inference from `dhav.c`),
Honeywell (the paper never states UTC or local). The flag is not removed by choosing an
assumption; it records that the sources disagree or are silent.

## 4. DST and calendar handling

Local wall clock to UTC uses the IANA database via `zoneinfo`. Europe/Berlin 2025-10-26 02:30 is
ambiguous: two candidate instants (00:30Z and 01:30Z) are kept and the interval is their envelope.
America/New_York 2025-03-09 02:30 does not exist: `dst_gap`, no UTC value, item listed as
unplaceable. DHAV dates are range-checked (month, per-month day count, 2024-02-29 valid,
2100-02-29 invalid, hour/minute/second). Unsigned 32-bit seconds >= 2^31 are decoded unsigned and
flagged `epoch32_signed_overflow` (a signed reader sees a negative time); 0xFFFFFFFF
(2106-02-07 06:28:15) and values beyond 32 bits flag `epoch32_u32_wrap`.

## 5. Clock offset / drift

Model `true - device = a + b x` (x = seconds since the first observation's device time). Device
clock readings are converted to UTC with the examiner's timezone, so the fit needs a timezone
assumption (HTTP 409 otherwise) and refuses ambiguous/nonexistent local reference times.

* 1 observation, or all at one device time: pure offset, drift assumed zero (stated), interval =
  reading uncertainty + assumed drift bound x time distance.
* 2 observations: exact line, no residual degrees of freedom; interval from the reading
  uncertainty only (sigma = u/sqrt(3), z = 1.96), stated as such.
* >= 3 observations: least squares, sigma = max(residual sd, u/sqrt(3)), Student t 95 % (table,
  no scipy).
* Warnings: non-monotonic observations (model not applied), drift > 500 ppm (warning), >= 10000
  ppm (not applied), baseline under 1 h, shared device times. Clock steps and NTP slews are not
  modelled.
* Measured on seeded synthetic trials (300 trials, 5 observations over 20 days, uniform +/-0.5 s
  reading noise, assumed u = 1 s): the 95 % intervals contained the true offset, true drift and
  the true error at +30 days in at least 90 % of trials (test asserts >= 0.90). This shows the
  implementation is self-consistent; it says nothing about real DVR clocks.

## 6. OSD time-overlay cross-check

* OCR library: **rapidocr-onnxruntime 1.4.4**, licence **Apache-2.0** (PP-OCR detection and
  recognition ONNX models bundled in the wheel, Apache-2.0), running on **onnxruntime 1.23.2**
  (MIT), CPU, offline. Also pulls numpy 2.2.6, Pillow 12.3.0, opencv-python, shapely, pyclipper.
  Tesseract was not available and is not required. The record in each result comes from
  `osd.ocr_library_info()`.
* Frames: ffmpeg accurate seek at evenly spaced positions; ROI is an examiner parameter, default
  the top-left strip (x 0, y 0, w 0.6, h 0.12 of the frame).
* Parsed formats: `YYYY-MM-DD HH:MM:SS`, `DD-MM-YYYY`, `MM/DD/YYYY`, 12 h AM/PM. A day/month
  order that cannot be determined (e.g. 03/09/2025) is reported `ambiguous` with both candidates
  and excluded from the statistics; it is never guessed. OCR often drops the space between date
  and time; the parser tolerates that.
* Unreadable input (low contrast, OCR confidence < 0.6, text that does not parse) is `unreadable`
  or `unparsed`; no value is produced.
* Comparison is wall clock to wall clock (the overlay shows the device clock), delta = OSD -
  metadata. Statistics: median, MAD, min, max, outliers (> max(3 x 1.4826 MAD, 1 s) from the
  median). Verdict: `pass` (all readable samples within the tolerance, default 2 s, and at least
  3 readable), `fail` (median outside tolerance), `inconclusive` (median inside, some outside),
  `unreadable`, `no_reference` (metadata wall clock not derivable). Overlays show whole seconds,
  so deltas carry about 1 s of granularity. Agreement does not prove the clock was right: the DVR
  may render the overlay from the same clock.
* **Measured accuracy on rendered synthetic overlays: 91 of 100 exactly correct, 9 unreadable
  (6 of 25 `YYYY-MM-DD`, 3 of 25 `YYYY-MM-DD hh:mm:ss AM/PM`, none in the two day-first/month-first
  styles), 0 confidently wrong.** Setup: Pillow's bundled default font at 18/22/28 px on a
  640x360 frame, light text on a dark strip over coloured rectangles, seeded random times in
  2024-2025, fixed seed in `tests/test_timeline_osd.py`. The test asserts floors of >= 80 %
  exact and <= 5 % wrong, not the measured values. Degraded overlays (contrast 0.02-0.03 of
  full scale, with and without blur) were all reported unreadable; heavy blur (radius 6) at
  normal contrast never produced a valid-looking wrong time in 5 samples (a small sample).
  These are rendered, clean, uncompressed overlays; real DVR overlays (small bitmap fonts,
  H.264 blocking, interlacing) will be harder, and no real-footage accuracy is claimed.
  Roughly 9 % unreadable on clean synthetic input suggests the real unreadable rate will be
  higher, which is why `unreadable` is a first-class outcome.

## 7. Timeline

Each clip is an interval: start/end uncertainty bars from the timestamp records (resolution, DST
envelope) and, if a usable drift model exists, the corrected interval (the axis uses the
corrected one when present; both are exported). A clip with only a start gets
end = start + exported media duration (flagged in `end_note`) or a point.

* Tie-break rule: (nominal start, nominal end, evidence id, channel with None last, clip id),
  nominal = midpoint of the plotted interval. Order is presentation only; clips whose start bars
  overlap list each other in `ambiguous_order_with`.
* Gaps per (evidence, channel): nominal gap > `min_gap_s` (default 1 s); `certain` only if the
  bars also leave a positive gap. Overlaps across (evidence, channel) pairs, plus `same_channel`
  overlaps as an anomaly; `certain` only if the inner bounds overlap.
* Unplaceable group: unknown timezone/basis, DST gap, invalid date or no metadata timestamp
  (generic carves have none; Hikvision per-clip times are not available from the parser). Shown
  with the reason and never drawn on the axis by default.
* Export (`GET /api/cases/{id}/timeline/export?format=csv|json`): raw value, field, format, byte
  offset, assumed timezone, evidence for it, epoch basis, tz status, flags, conflict note,
  uncorrected and corrected intervals, plotted interval, drift model id, OSD status/median/MAD.

## 8. API

`GET/PUT /api/evidence/{id}/time-assumption`, `GET/POST /api/evidence/{id}/time-references`,
`POST /api/evidence/{id}/time-model/fit`, `GET /api/evidence/{id}/time-model`,
`GET /api/cases/{id}/timeline`, `GET /api/cases/{id}/timeline/export`,
`POST /api/clips/{id}/osd-check`. Mutations require `X-Examiner`. UI route expected:
`/cases/:id/timeline`.

## 9. Limits

* No real-device validation; no checksum or timezone fields are documented for any vendor.
* Linear drift only; clock steps, NTP slews and temperature effects are not modelled. Time-reversal
  detection across structures (Han) is not implemented here.
* The assumed drift bound for single observations is an engineering assumption.
* OSD OCR accuracy on real footage is unknown (see section 6); the frame time is the seek
  position, not a decoded pts.
* One timezone per evidence item; a recorder whose timezone/DST setting changed during the
  recording is not modelled.
* The fit and OSD check run synchronously inside the request.
