# Device intelligence

*Round D stream 2b. Code: `backend/app/identify/`. Tests: `backend/tests/test_identify_engine.py`. All tests use reference images built from the per-paper layouts (SYNTHETIC); nothing is validated on a real device and no vendor is above Tier B.*

`GET /api/evidence/{id}/identification[?refresh=true]` returns a structured, UI-ready description of what the image is, from documented signatures and structures only.

## How it works

1. The image is read through `evidence.open_verified` (full hash verification, custody-logged).
2. The parser registry's own `Probe` and `Signature` definitions are wrapped (not copied) so the shared single-pass scan (`vendors.base.scan_image`) also records every candidate occurrence, every structural-validation rejection, and the bytes seen at each fixed-offset probe.
3. Each parser's own `identify()` turns the scan into a `Match`, exactly as in analysis. A test asserts that the vendor/confidence list equals `ParserRegistry.identify()` on the same image, so this breakdown and the analysis pipeline cannot disagree.
4. Model and firmware attributes are read only where `docs/parsers/` documents an on-disk field (table below), by calling the parsers' own field readers.
5. The result is stored (`device_identifications`, keyed by image SHA-256, tool version and parser versions) and custody-logged as `device_identified`. Later calls return the stored result (`cached: true`) unless `refresh=true`.

## Output (abridged)

```json
{
  "manufacturer": {"value": "Honeywell", "status": "identified|ambiguous|unknown", "source": "...", "note": "confidence medium ...; Tier B"},
  "device": {
    "model":     {"value": "HN350802xx", "status": "parsed", "offset": 17512, "source": "docs/parsers/honeywell-fields.md 1.3 ...", "note": "..."},
    "device_id": {"value": "...", "status": "parsed", "offset": 17472},
    "firmware":  {"value": null, "status": "unknown", "note": "the source shows firmware only in a UI screenshot ..."}
  },
  "matches": [{"vendor": "Honeywell", "tier": "B", "confidence": "medium"}],
  "routing": {"engine": "Honeywell parser first, then generic carving of uncovered bytes", "reason": "..."},
  "parsers": [{"vendor": "...", "confidence": "none|low|medium", "signatures_matched": 2, "signatures_total": 2,
               "signatures": [{"name": "...", "kind": "probe|signature", "matched": true, "count": 5, "offsets": [...],
                               "details": [...], "candidates": 7, "rejected": 2, "rejected_offsets_sample": [...],
                               "reason": "only when not matched"}]}],
  "not_identifiable": {"vendors": ["CP Plus", "..."], "reason": "Tier C: no public byte-level signature ..."}
}
```

Reasons for a non-match are one of: `pattern not present in the image`; `pattern found N time(s) but every occurrence failed the documented structural validation` (with sample offsets); `bytes at the documented offset X do not satisfy the documented check` (with the bytes seen); `image ends before the documented offset`.

## What each vendor can tell us

| Vendor | Manufacturer basis | Model | Firmware | Other |
|---|---|---|---|---|
| Honeywell | Machine Data `HN<digits>` at sector 34 + 20-byte custom headers [S5] | **parsed**: ASCII at 0x4468 (field doc 1.3); device ID at 0x4440 | **unknown**: the paper shows `1.24.1.146.20241120` only in a UI screenshot; no on-disk field is documented | One model only (HN35080200); the label does not imply one format across Honeywell products |
| Hikvision | `HIKVISION@HANGZHOU` at 0x200/0x210, `HIKBTREE`, `RATS` [S1][S2] | **unknown**: no model field documented | **unknown**: none documented | The Master Sector text at +0x20 (e.g. `HIK.2011.03.08`) is returned as `filesystem_version_like_string`, status `unknown`; its meaning is undocumented and it is **not** presented as firmware |
| Dahua | DHAV frames with verified trailer [S9] | **unknown**: DHAV has no model field | **unknown** | DHFS internals undocumented |
| anything else | none | unknown | unknown | routed to generic carving |

Tier C OEMs (CP Plus, Uniview, TP-Link, Godrej, Matrix, Axis, Bosch, Hanwha Vision, VIVOTEK, Avigilon, Pelco, Tiandy, Reolink) have no public byte-level signature, so they can never be identified; their images get `manufacturer.status = unknown` and generic carving (see `docs/oem-registry.md`).

## Confidence

Per parser, from its `identify()`: `medium` needs a documented structurally validated signature combination (for example the Master Sector at its documented offset, or at least three Honeywell headers plus Machine Data), `low` a weaker subset. `high` is never produced (no vendor is Tier A). If two vendors match with equal confidence, `manufacturer.status` is `ambiguous` and both are listed in `matches`.

## Limits

- Identification proves only that documented byte patterns are present; it does not prove the image came from that manufacturer's device (a copied or embedded file can carry them).
- Model strings are reported as stored; they are not checked against a product list.
- The stored result is invalidated by a new image hash, tool version or parser version; otherwise it is reused.
