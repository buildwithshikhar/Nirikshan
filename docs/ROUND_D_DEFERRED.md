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
