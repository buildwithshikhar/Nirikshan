# OEM registry (16 targets)

*Round D stream 2e. Data: `backend/app/oem/registry.json` (versioned, `registry_version` 1). Loader and consistency check: `backend/app/oem/registry.py`. API: `GET /api/oem-registry`. Test: `backend/tests/test_oem_registry.py` fails if the file disagrees with the parser registry in code (`vendors.default_registry()`, `vendors.TIER_C_VENDORS`, each parser's `PARSER_VERSION`).*

**No vendor is above Tier B and nothing is validated on a real device.** Tier B = a public byte-level signature we read ourselves plus a parser written from published research (unvalidated on real devices). Tier C = no public byte-level storage documentation found: standard-export ingest and generic carving only, images left unattributed.

## Support matrix

"Standard-export ingest" (`POST /api/cases/{id}/native-exports`, `docs/acquisition.md`) works for any container ffprobe recognises and makes no vendor claim. It was tested with ffmpeg-generated MP4, MKV, AVI, MPEG-TS and raw H.264 files only. **No real export file from any of these OEMs was tested.** The "documented export formats" column repeats what the cited vendor document says the product can export.

| OEM | Tier | Documented export formats (source) | Proprietary storage parsing | Deleted-video recovery | Parser version |
|---|---|---|---|---|---|
| Hikvision | B | none cited | partial: Master Sector, RATS, HIKBTREE, OFNI per the 2015 DVR layout [S1][S2] | parser + generic carving | 1.0 |
| Dahua | B | none cited (ffmpeg's dhav demuxer may read .dav; untested) | partial: DHAV frames only [S9]; DHFS not parsed | parser + generic carving | 1.0 |
| Honeywell | B | none cited | partial: one model (HN35080200) [S5] | parser + generic carving | 1.0 |
| CP Plus | C | none found | none | generic carving only | - |
| Uniview | C | .mp4 to USB, .TS to disc [R3] | none | generic carving only | - |
| TP-Link (VIGI) | C | Speed Mode "original format", Compatible Mode converted to H.264; container not named [R2] | none | generic carving only | - |
| Godrej | C | none found | none | generic carving only | - |
| Matrix (SATATYA) | C | Recording Format "AVI, Native" [R1] | none | generic carving only (MJPEG not carved) | - |
| Axis | C | ASF, MP4, MKV, optional digital signature [R4] (signature not verified by Nirikshan) | none | generic carving only | - |
| Bosch | C | MP4; native copy via VRM eXport Wizard [R7, low] | none | generic carving only | - |
| Hanwha Vision | C | AVI/MP4/MKV; SEC needs a designated viewer [R6, low] | none | generic carving only | - |
| VIVOTEK | C | none retrieved | none | generic carving only | - |
| Avigilon | C | AVI; native .AVE [R8, low] | none | generic carving only | - |
| Pelco | C | none retrieved | none | generic carving only | - |
| Tiandy | C | none retrieved | none | generic carving only | - |
| Reolink | C | MP4 or raw H.264 files [R5] | none | generic carving only | - |

Per-OEM limitations and test/doc evidence are in the data file (`limitations`, `evidence`).

## Sources

Confidence: **high** = primary document fetched and read; **medium** = primary document read in part; **low** = search-result snippet only (page not retrievable or not readable). S-ids are from `docs/RESEARCH.md` section 10 (accessed 2026-10-05); R-ids were retrieved on 2026-10-09 in a time-boxed search (about 15 minutes, queries for each OEM plus "forensic", "file system", "export format", "backup format").

| Id | Source | Retrieved | What it says | What it does NOT say | Confidence |
|---|---|---|---|---|---|
| S1 | Han, Jeong, Lee 2015, Analysis of the HIKVISION DVR File System (eudl.eu) | 2026-10-05 | Master Sector, HIKBTREE, RATS, OFNI layouts for one DVR | newer firmware, H.265 | high |
| S2 | Dragonas thesis 2023, ch. 4-5 | 2026-10-05 | Hikvision logs on 6 devices; Dahua partition layouts, SQLite logs | DHFS internals | high |
| S5 | Yoon and Hwang 2026, arXiv:2605.07430 | 2026-10-05 | Honeywell GPT layout, Machine Data, custom headers, one model | other models, H.265 | high |
| S9 | FFmpeg libavformat/dhav.c | 2026-10-05 | DHAV frame container | DHFS | high |
| S14 | ICICI Securities, Aditya Infotech IPO review | 2026-10-05 | Aditya Infotech (CP Plus) is exclusive Dahua distributor in India | anything about CP Plus storage or containers | medium |
| S16 | TP-Link VIGI NVR1016H product page | 2026-10-05 | codec list | container or disk format | medium |
| R1 | Matrix SATATYA NVR0801X Technical Specifications, https://matrixcomsec.com/wp-content/uploads/2023/09/Matrix-IPVS-SATATYA-NVR0801X-Technical-Specifications.pdf | 2026-10-09 | Recording Format AVI, Native; Compression H.265/H.264/Motion JPEG | what "Native" is; any on-disk structure | high |
| R2 | TP-Link VIGI FAQ 5043, https://www.vigi.com/ae/support/faq/5043 | 2026-10-09 | Speed Mode exports "in the original format"; Compatible Mode converts to H.264 | container/extension of either mode; on-disk format | high |
| R3 | Uniview, How to backup Recording & image (2019 PDF), https://global.uniview.com/de/res/201907/03/20190703_1730433_How%20to%20backup%20Recording%20&%20image_852034_168459_0.pdf | 2026-10-09 | .mp4 default to USB; .TS to disc; file naming; USB FAT32/NTFS | on-disk recording format | high |
| R4 | AXIS Camera Station Pro datasheet, https://www.axis.com/dam/public/9b/38/a4/datasheet-axis-camera-station-pro-en-US-521838.pdf | 2026-10-09 | Export to ASF, MP4, MKV; digital signature on exports; standalone player | recording storage format; signature scheme | high |
| R5 | Reolink support, Backup Recordings to USB Drive from PoE NVR, https://support.reolink.com/hc/en-us/articles/360003575873 | 2026-10-09 | "MP4 Format File" option, otherwise H.264 files | on-disk format | high |
| R6 | Hanwha Vision FAQ 20498, https://hanwhavision.com/vn/support/faq/20498 | 2026-10-09 (HTTP 404; snippet) | (snippet) SEC/AVI/NVR backup types; MP4/MKV/native from Wisenet Viewer | everything; page unreadable | low |
| R7 | Keenfinity (Bosch) knowledge base, VRM eXport Wizard article | 2026-10-09 (index only; snippet) | (snippet) native copy without transcoding; MP4 export; ASF replaced by MP4 in BVMS 10.0.1 | everything; article unreadable | low |
| R8 | IPVM discussion, Convert Avigilon .AVE to .MP4 | 2026-10-09 (not fetched; snippet) | (snippet) ACC Player exports native .AVE or .AVI | everything; subscriber forum | low |

**Searched, nothing usable found:** CP Plus (results covered Hikvision/Honeywell only; generic statements about .dav files are not CP Plus documentation), Godrej (retail and other vendors' manuals only), VIVOTEK (no VIVOTEK document in results), Pelco (results were other VMS vendors' docs; the one Pelco-related statement in a result summary had no Pelco URL behind it, so it is not used), Tiandy (other vendors' manuals only).

## Outcome for byte-level support

**No public byte-level storage documentation was found for any of the 13 Tier C OEMs.** Nothing was implemented beyond Tier C for them: no signature, no parser, no model/firmware identification. Export-format statements above do not describe on-disk structures and are not used for identification. OEM relationships (CP Plus and Dahua distribution, rebadging) are never used to infer a format; only a real image can establish one (promotion rules: `docs/OEM_COMPARISON.md` section 3).

## Keeping docs and code in agreement

`registry.check()` (run by the test and reported by the API as `consistent_with_code`) requires: all 16 targets present, every field present, tier in {B, C}; each Tier B row maps to a parser in `default_registry()` with the same tier and `parser_version` equal to the parser's `PARSER_VERSION`; every row without a parser is in `TIER_C_VENDORS`, Tier C, `parser_version` null, proprietary parsing `none` and recovery `generic carving only`; every source id resolves and has url, retrieval date, scope ("says"/"does_not_say") and a confidence tag. Bump `PARSER_VERSION` in a parser module when its output changes and update the registry row in the same commit.
