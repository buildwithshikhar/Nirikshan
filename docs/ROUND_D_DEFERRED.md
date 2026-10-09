# Round D deferred items

Items that could not be built honestly in Wave 1, with the reason. The API returns an explicit "not available" state for each.

## Stream 2 (acquisition, device intelligence, explorer, recovery, OEM registry)

| Item | Reason | API state |
|---|---|---|
| E01/EWF ingest | libewf/pyewf is LGPL-3.0-or-later: adoptable as an unmodified dynamically linked library (like psycopg), so the licence is not the blocker. Deferred because it is a new dependency for the shared `requirements.txt`, needs a native libewf build in the image, and no E01 test image can be produced here (no `ewfacquire`), so it could not be tested. Workaround: `ewfexport` to raw outside Nirikshan (outside its custody), then acquire the raw file. | `GET /api/acquisition/ewf` and `capabilities.ewf`: `{"available": false, "reason": ...}` |
| Byte-level storage parsing / identification for CP Plus, Uniview, TP-Link, Godrej, Matrix, Axis, Bosch, Hanwha Vision, VIVOTEK, Avigilon, Pelco, Tiandy, Reolink | No public byte-level documentation found (time-boxed search 2026-10-09, `docs/oem-registry.md`). Registered Tier C: standard-export ingest + generic carving only. | `/api/oem-registry` rows say `proprietary_storage_parsing: none`; identification returns `manufacturer.status: unknown` with the reason |
| Firmware identification (all vendors) | No documented on-disk firmware field for Hikvision, Dahua or Honeywell (Honeywell's firmware appears only in a UI screenshot of the source). | `device.firmware.status: unknown` with the reason |
| Verification of vendor-signed exports (e.g. AXIS Camera Station signed exports) | The signature scheme is not documented in the source read. The file is hashed and ingested; its vendor signature is not checked. | not offered; registry limitation text says so |
| Recoverability agreement for parser-engine clips | The measurement harness scores generic-engine clips only; the rule applies to parser clips but its agreement there is unmeasured. | `GET /api/clips/{id}/recoverability` gives the estimate with the limitation; `measured_agreement` describes the generic-engine measurement only |
## Stream 3 (events, correlation, validation center)

| Item | Why it is deferred | What the API says |
|---|---|---|
| Per-frame evidence byte offset for an AI event | Detections are made on decoded frames of the exported MP4. The carver records the clip's byte extents in the evidence image, but no mapping from a decoded frame back to the byte range of its NAL units is stored, so a per-frame offset would be a guess. | Every search hit gives the clip's byte range and extents plus `source.frame_byte_offset = {"available": false, "reason": ...}`. |
| Clock drift inside one clip | Event UTC = clip start interval + nominal in-clip offset (frame / stream fps). Drift models are fitted per evidence item at the clip start; nothing measures drift or frame-rate irregularity within a clip. | Documented in `docs/events.md`; the uncertainty bar is the clip-start bar shifted, not widened. |
| Validation re-run through `app.jobs` | The job system's rows require a case and an evidence item (foreign keys); a validation run has neither. Re-runs use a single, time-limited subprocess with its own table instead (`docs/validation-center.md`). | Not an "unavailable" state; the re-run endpoint works, with this limitation stated. |
