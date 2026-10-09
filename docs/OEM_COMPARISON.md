# OEM Comparison: Public Documentation and Nirikshan Support Level

*Audience: reviewers (NTRO and SIH evaluators) and engineers who need to know, per recorder vendor, what is publicly documented, what Nirikshan implements, and what real data would raise its support tier.*

Derived from `docs/RESEARCH.md` sections 3 and 4 (compiled 2026-10-05); source ids `[S1]`..`[S30]` resolve in RESEARCH section 10. Implementation status is taken from `IMPLEMENTATION_PLAN.md`, `docs/ARCHITECTURE.md` and `docs/parsers/`. Confidence tags follow RESEARCH: **documented** (primary source we read), **partly documented** (single model, abstract-level, or internal inconsistency), **unknown** (no verifiable public source; nothing inferred).

**No vendor is Tier A. Nothing in Nirikshan has been tested on a real DVR/NVR image; all validation is on SYNTHETIC images and parser-versus-same-layout results are a circular check** (`docs/VALIDATION_REPORT.md`). Tier B means a public byte-level signature we can match plus generic carving, with a vendor parser that is **not validated on any real device**. Tier C means planned only.

**Round D:** the machine-readable registry of all 16 target OEMs (standard-export support, proprietary-storage parsing, deleted-video recovery, tier, evidence, limitations, parser version, sources) is `backend/app/oem/registry.json`, served at `GET /api/oem-registry`, documented in `docs/oem-registry.md` and checked against the parser registry in code by a test. The 13 OEMs without a parser are Tier C: a roughly 15-minute public search found no byte-level storage documentation for them. Only export formats are cited (Matrix, TP-Link, Uniview, Axis, Reolink); Hanwha, Bosch and Avigilon rest on search snippets and are tagged low confidence.

## 1. Summary table

| OEM | Filesystem | Container / codec | Timestamps | Logs | Public documentation level | Tier today |
|---|---|---|---|---|---|---|
| Hikvision | Proprietary "HIKVISION FS": Master Sector `HIKVISION@HANGZHOU`, system logs, video blocks with `OFNI` IDR tables, HIKBTREE [S1][S2] | Raw H.264 NAL with 4-byte start code and a `0xBA`/`0xBC` index byte; H.265 unknown [S1] | Unix seconds; HIKBTREE UTC per Han, log time local per Dragonas (conflict); DST unknown [S1][S2] | `RATS` records documented (6 devices) [S1][S2] | High for the 2015 DVR structure, medium for logs, newer firmware unverified | **B** |
| Dahua | DHFS (internals not read); XFS second partition on some XVRs [S2] | DHAV frames, from FFmpeg source; MPEG-4, MJPEG, H.264, HEVC ids [S9] | Bit-packed date, no time-zone field (local time inferred from code) [S9] | SQLite `{serial}_log.db` on XFS partition; internal-memory logs not imaged [S2][S4 abstract] | Medium: container strong, DHFS internals unread | **B** |
| Honeywell | GPT: proprietary partition 1 + 10 GB ext4 partition 2 [S5] | Raw H.264 NAL with 20-byte custom header; H.265 unknown [S5] | Unix seconds (blocks), Unix microseconds (per NAL); zone unknown [S5] | Not analysed [S5] | Medium: one 2026 paper, one model (HN35080200); tools repository unlicensed [S6] | **B** |
| CP Plus | Unknown | Unknown | Unknown | Unknown | None found; business tie to Dahua (distributor) only [S14] | **C** |
| Uniview | Unknown | Unknown | Unknown | Unknown | None found [S15 marketing, not relied on] | **C** |
| TP-Link VIGI | Unknown (not stated) | Codecs H.265+/H.265/H.264+/H.264 per vendor spec; container unknown [S16] | NTP supported; disk format unknown [S16] | Alarm categories in spec; on-disk unknown [S16] | Marketing only | **C** |
| Godrej | Unknown | Unknown | Unknown | Unknown | None found; retail snippets not relied on | **C** |
| Matrix Comsec | Unknown | H.265/H.264/MJPEG per spec listing (thin extraction) [S17] | Unknown | Unknown | Marketing only | **C** |

Note on a RESEARCH inconsistency: RESEARCH section 4 (written before P4) says the Hikvision structured parser "stays C until validated". P4 has since built a Hikvision parser; the plan and code keep the vendor at **Tier B**, which is the tier used here. RESEARCH section 4 should be updated by the document owner.

## 2. Per OEM detail

### 2.1 Hikvision (Tier B)
- **Public basis:** Han, Jeong, Lee 2015 [S1] (full text read; one DVR, DS-7204HVI-SV, 160 GB disk) and Dragonas thesis chapters 4-5 [S2] (six devices, 5 XVR + 1 NVR). Field-level tables with confidence tags: `docs/parsers/hikvision-fields.md`.
- **Known source conflicts (not resolved):** data-block size 0x400000 (4 MiB) versus "generally 1 GB" in the same paper [S1]; HIKBTREE and Master Sector times UTC per Han versus log times local per Dragonas [S1][S2]; Master Sector at 0x200 (Han) versus signature at 0x210 (Dragonas figure).
- **Implemented:** signature identification (`HIKVISION@HANGZHOU` at 0x200, `HIKBTREE`, `RATS` with documented follower bytes; confidence at most `medium`); structured parser: Master Sector, RATS records (bounded sample), HIKBTREE entries, `OFNI` counts, generic Annex-B carving inside blocks the entries point to; options `block_size_mode`, `time_basis_label` (relabel only), `master_sector_offset`, `btree_first_entry_offset`; raw timestamps with "timezone not assumed"; H.264 only (H.265 reported as an orphan). The 56-byte IDR record content and any checksum are not read.
- **Measured (synthetic, circular):** on the per-paper layout the parser matches the generic carver except where HIKBTREE entries are cleared: parser recall 20/60 versus generic 60/60 on `deleted_intact_zero@hik`; the parser-first pipeline keeps both.
- **Not implemented:** H.265, encrypted recordings, BA/BC payload, Hik-Connect artefacts, newer firmware generations, Dragonas NVR log area.
- **Promotion to Tier A needs:** at least 2 real images from at least 1 Hikvision model, created by us with ground truth (see `REAL_IMAGE_PLAYBOOK.md`); the checklist there settles the three conflicts above, the HIKBTREE entry layout and the cleared-entry behaviour. Candidate hardware: `HARDWARE_SHOPPING.md`.

### 2.2 Dahua (Tier B)
- **Public basis:** FFmpeg `libavformat/dhav.c` [S9] (full source read) for the DHAV frame container; Dragonas [S2] for partition layouts and SQLite logs; Rzayeva 2025/2026 abstracts only [S7][S8] (author-reported 91.8% recovery on 27 HDDs; unreplicated and not used by us). DHFS on-disk structure: **unknown** (Li and Zuo not accessible).
- **Implemented:** DHAV signature identification (frame length and `dhav` trailer agree; `DAHUA` file prefix for exported files); DHAV frame parser: header, extension TLVs (0x80/0x81/0x82), trailer check, channel demultiplexing by channel byte, key-frame clip starts, `frame_gap_tolerance` option (default 3; an inferred heuristic); date field returned raw plus a plain wall-clock decode, no zone. **DHFS internals are not parsed.** Header checksum byte is not verified (algorithm undocumented). MPEG-4/MJPEG listed, not exported.
- **Measured (synthetic, circular):** on the DHAV layout the parser gives byte-exact extents and exact channel separation; the generic carver cannot.
- **Not implemented:** DHFS, XFS partition and SQLite log parsing, H.265 beyond the demuxer's codec id, smart-codec frames, internal-memory logs.
- **Promotion needs:** real Dahua/XVR images; read the DHFS structure from image analysis; settle the checksum algorithm and `frame_number` tolerance on real streams (Rzayeva's abstract reports +/-3, unread in full).

### 2.3 Honeywell (Tier B)
- **Public basis:** Yoon and Hwang 2026, arXiv:2605.07430 [S5] (full text read; one model HN35080200, GPT layout, 160 and 250 GB disks). The tools repository [S6] has **no licence**: nothing was copied; the parser is written from the facts recorded in `docs/parsers/honeywell-fields.md`. RESEARCH notes the Honeywell label does not imply one on-disk format (an IPVM forum post [S11] says some Honeywell NVRs are sourced from Dahua, Hikvision, OpenEye and DynaColor).
- **Implemented:** identification by Machine Data (`HN<digits>` at sector 34) plus the 20-byte custom header; parser for Machine Data, Block Group Index, Video Block List, custom headers (flag byte 0x82/0x02, 8-byte microsecond time), the 20-zero-byte delimiter; GPT, Partition 1 header values, Channel Index mapping and clip boundaries tagged `inferred`; `80 01 00`, padding, timezone, checksums, Partition 2 `unknown`. Channel only if a surviving Channel Index entry covers the clip. A frame is accepted only when its length lands on the next header, the delimiter or the image end, otherwise the parser falls back.
- **Measured (synthetic, circular):** parser byte-exact where the generic carver is not, because 20-byte headers sit between NAL units.
- **Open points:** whether the header length covers one NAL or the whole access unit (the paper is silent; the synthetic layout uses the whole access unit span); delimiter versus zeroed data; other models; H.265.
- **Promotion needs:** a real Honeywell NVR (the documented model, if purchasable in the target market, otherwise another model with its own claim), per the playbook.

### 2.4 CP Plus (Tier C)
No public technical source found. The only sourced fact is a commercial one: Aditya Infotech (CP Plus manufacturer/trader) holds exclusive Dahua distribution rights in India [S14]. This does **not** establish that CP Plus recorders use DHFS or DHAV; Nirikshan does not label them Dahua-compatible. Implemented: generic carving only. Promotion C to B needs one real image yielding a documented signature (hex dump saved in `docs/`) and a signature-identification test against it. If the unit shows DHAV frames, the Dahua parser could be exercised on it; verify by image, not by assumption.

### 2.5 Uniview, TP-Link VIGI, Godrej, Matrix Comsec (Tier C)
No technical sources on filesystem, container, timestamps or logs for any of them; only marketing or retail material [S15][S16][S17] was reached, partly at summary level, and the Godrej support PDF returned 404. Codec lists (TP-Link, Matrix) are vendor specifications, not on-disk facts. Implemented: generic carving only. Each needs one real image to determine filesystem and container independently; do not infer from OEM relationships (RESEARCH section 9, item 5).

## 3. What real data promotes each tier

| Promotion | Requirement (from `IMPLEMENTATION_PLAN.md`) | Applies to |
|---|---|---|
| C to B | A public byte-level signature we have read ourselves, or one real image from that vendor yielding a documented signature (hex dump saved in `docs/`), plus a signature-identification test against that image | CP Plus, Uniview, TP-Link, Godrej, Matrix |
| B to A | At least 2 real images from at least 1 model, created by us with a known ground-truth set (N clips with known times and channels, some deleted), imaged read-only; acquire and hash before and after; run the pipeline; report recall, precision and timestamp error with numbers; a second firmware or model strengthens the claim | Hikvision, Dahua, Honeywell |
| A to model-broad | More models and firmware versions; one claim per model, never per brand | none yet |

## 4. Cross-vendor facts that affect every row

- Generic H.264/H.265 carving works on any image regardless of tier but attributes no vendor, channel or time without vendor metadata.
- MJPEG and MPEG-4 Part 2 are not carved; encrypted recordings are not covered by any source and are not recovered.
- Timestamp time-zone and DST storage are unsettled or unknown for every vendor (RESEARCH section 6); Nirikshan reports raw values only today (SOP-04). Timestamp normalization (P5) is in progress.
- Author-reported recovery figures (S7, S8) were read at abstract level only and are not used as Nirikshan results.
