# Nirikshan: DVR/NVR Forensics Research Basis

Status: research note, compiled 2026-10-05. Purpose: give Nirikshan (multi-vendor DVR/NVR forensic analysis platform) a defensible, source-backed statement of what is publicly documented about each OEM, what is not, and what must be verified on real disk images before any parser is called "supported".

## 0. How to read this document

- Every factual row carries a confidence tag and source IDs, e.g. `[S1]`. The IDs resolve in the Source index (section 10), which says whether each source was fully read, partly read, or not accessible.
- Confidence tags:
  - **documented**: a primary technical source (peer-reviewed paper, open-source code) describes it, and we read that source.
  - **partly documented**: described in part, from a single device model or an abstract-level source, or with an internal inconsistency we found.
  - **unknown**: no verifiable public technical source found. Nothing is inferred.
- "Tier" definitions used here: Tier A = validated against real images (no OEM qualifies today), Tier B = signature identification plus generic NAL/GOP carving, Tier C = planned.
- Honest limitation: several key papers (Dragonas 2023a/b/2024 journal papers, Rzayeva 2025/2026 MDPI full text, Sandeepa 2018, Li and Zuo DHFS, Yang 2015) could not be opened in full (HTTP 403 / paywall / anti-bot). For those we use only what a fetched, readable source states about them (the arXiv Honeywell paper's related-work section, the Crossref abstract record, or Dragonas's open-access PhD thesis). Where we rely on that, it is stated.
- Nothing in this document comes from examining a real DVR/NVR image. Nirikshan has none yet.

## 1. Key sources at a glance

| Short name | What it is | What we actually read |
|---|---|---|
| Han 2015 [S1] | "Analysis of the HIKVISION DVR File System", Han, Jeong, Lee, ICDF2C 2015, LNICST 157, pp.189-199 | Full text (14 pp PDF, via eudl.eu) |
| Dragonas thesis 2023 [S2] | Doctoral thesis, Univ. of Piraeus, CC BY-NC-ND 3.0 GR; chapters 4 (Dahua) and 5 (Hikvision) contain the content of the JFS 2023/2024 log papers | Full text of chapters 4-5 relevant sections (139 pp PDF) |
| Dragonas 2023b / 2024 [S3][S4] | JFS 68:2002 (Hikvision logs); JFS 69:117 (Dahua logs, DOI 10.1111/1556-4029.15401) | Dahua paper: Crossref abstract only. Hikvision paper: not accessed (content covered by [S2]) |
| Yoon and Hwang 2026 [S5] | "Forensic analysis of video data deletion and recovery in Honeywell surveillance file system", arXiv:2605.07430, accepted DFRWS USA 2026 | Full text (9 pp) |
| Honeywell tools repo [S6] | github.com/eraw1am/Honeywell-NVR-Filesystem-Tools | README, both scripts read in full; GitHub API checked for licence |
| Rzayeva et al. 2025 [S7] | MDPI Information 16(11):983, "Automated Forensic Recovery Methodology for Video Evidence from Hikvision and Dahua DVR/NVR Systems" | Abstract only (Crossref); MDPI full text returned 403 |
| Rzayeva et al. 2026 [S8] | MDPI Information 17(5):493, "Forensic Video Recovery from Multi-Channel Analog DVR Systems: Channel Demultiplexing and Temporal Reconstruction from Interleaved DHAV Streams", published 2026-05-17 | Abstract only (Crossref); MDPI full text returned 403 |
| FFmpeg dhav.c [S9] | `libavformat/dhav.c` (DHAV demuxer, (c) 2018 Paul B Mahol, LGPL-2.1+) | Full source read |

## 2. Cross-vendor corrections and caveats found while reading

1. **Han 2015 internal inconsistency on data block size [S1].** The Master Sector sample lists "size of a data block (0x400000)" (4 MiB) and a "total number of data blocks (0x94)", but the Video Data Area section states "The size of one data block is generally 1 GB (0x40000000 bytes)". The paper does not reconcile them. A parser must read the field, not hard-code either.
2. **Hikvision log timestamp timezone: sources disagree.** Han 2015 describes the system-initialisation time and HIKBTREE block times as UNIX time in UTC [S1]. Dragonas's thesis states the log record "Time" is stored in the local time zone the DVR was set to, not UTC, despite being UNIX-seconds, and that neither prior work nor his could determine whether the offset is stored on disk [S2]. These apply to different fields (log records vs. HIKBTREE/Master Sector), so they are not necessarily contradictory, but a normaliser must treat each field's timezone as an explicit per-field assumption.
3. **The Honeywell paper does not claim Honeywell is an OEM of Dahua/Hikvision.** It only says prior work covered Hikvision and Dahua and that Honeywell had not been examined [S5]. Its Honeywell layout (GPT, proprietary partition + ext4 partition) is structurally different from the Hikvision layout in [S1] (no GPT described). It also analysed a single model only (HN35080200). Do not generalise to all Honeywell devices.
4. **Honeywell repo has no licence.** GitHub API reports `license: null` and the repository root contains only `README.md`, `compare_partition.py`, `dat_carving.py` [S6]. Under default copyright, Nirikshan must not copy this code; re-implement from the paper's published structure description, and cite.

## 3. Per-OEM findings

Row format: finding | confidence | sources.

### 3.1 Hikvision

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| Storage layout / partitioning | Four physical sections: Master Sector, System Logs, Video Data Area, HIKBTREE. Master Sector starts at offset 0x200, 256 bytes, little-endian, signature ASCII `HIKVISION@HANGZHOU` (48 49 4B 56 49 53 49 4F 4E 40 48 41 4E 47 5A 48 4F 55). A backup Master Sector sits after the system logs. Master Sector holds disk capacity, offset/size of system logs, offset to video data area, data block size, number of data blocks, offset/size of HIKBTREE, and time of last system initialisation. Test device: DS-7204HVI-SV DVR, 160 GB Seagate. Partition table presence/absence not described. | documented (one DVR model; 2015 firmware) | [S1] |
| Master Sector log pointers | Dragonas: offset of log area stored at Master Sector offset 0x260 (8 bytes LE), total log size at 0x268 (8 bytes LE). Across all of his test systems the log start was 64,041,472 (0x03D13200) (this equals Han's sample value). | documented (his 6 devices: 5 XVR + 1 NVR) | [S2] |
| Filesystem | Proprietary, unnamed ("HIKVISION file system" is the authors' provisional name). Simple: no file delete, no rename. | documented | [S1][S2] |
| Video block structure | Data blocks hold video per channel/time. Each block has an "IDR table" at its end: records of 56 bytes each, signature `OFNI` (4F 46 4E 49), written from the block end towards lower offsets, giving index, channel, timestamp of each IDR picture. | documented | [S1] |
| HIKBTREE | Signature `HIKBTREE` (48 49 4B 42 54 52 45 45); header, page list, pages (4 KB), footer; backup copy follows. Each page has data-block entries: existence flag (0x00 = block full of video, 0xFF = no video/not recorded), channel, start/end time (UNIX, UTC per Han; written only when block is full, otherwise `FF FF FF 7F 00 00 00 00`), offset to data block. Page has next-page offset (0xFF filled on last page). | documented | [S1] |
| Container / codec | Video stored as H.264 NAL units. Han's table: SEI 0x06, AUD 0x09, non-IDR 0x61, IDR 0x65, SPS 0x67, PPS 0x68, each preceded by 4-byte `00 00 00 01`. Before each NAL, a picture-index header byte `0xBA` or `0xBC` combined with `00 00 01`. This extra header causes screen noise in generic players (Han). H.265 handling: not described. | documented for H.264; H.265 unknown | [S1] |
| Timestamps | HIKBTREE entry times, Master Sector init time: UNIX seconds. Han says UTC. Log record time (4 bytes LE UNIX seconds) is in the device's configured local time zone per Dragonas; whether the offset is stored on disk is unresolved. OSD (burned-in) time vs metadata: not discussed in the sources. DST handling: not documented. | partly documented (conflict between fields, see section 2) | [S1][S2] |
| Logs / metadata | System Logs area. Record signature `RATS`; Han saw `52 41 54 53 01 00 00 00`, Dragonas saw `52 41 54 53 14 00 00 00` consistently on his devices. Then 4-byte time, 2-byte Major Type, 2-byte Minor Type, then variable "Details". For "Operation" major type, first 16 bytes of Details are username, next 4 are IP address. Han's four log classes: Alarm 0x01, Exception 0x02, Operation 0x03, Information 0x04. First 2048 bytes of log area were uninterpreted. Exported text logs from GUI capped at 2000 records per file. One test image held 19,063 `RATS` records; Hikvision LocalPlayback showed 114; Dragonas's open-source "Hikvision Log Analyzer" interpreted ~75% (fully or partly). Hikvision Log Analyzer: github.com/theAtropos4n6/HikvisionLogAnalyzer, API reports no licence. | documented | [S1][S2][S10] |
| Deleted-footage recovery | DVR has no delete function; initialisation resets init-time, zeroes system logs and re-initialises HIKBTREE, but video data remains in blocks and can be carved (Han). Detection: time-reversal between init time, IDR-table times and HIKBTREE times indicates re-initialisation; IDR times older than HIKBTREE entry times indicate the disk has wrapped (overwritten) at least once. Overwrite resets entry channel and sets start/end time to `FF FF FF 7F 00 00 00 00`. Per the Honeywell paper's related work, Sandeepa 2018 built automated recovery from known metadata regions (fails if metadata is deleted/corrupt) and Yang 2015 identified vendor headers/footers for H.264 segment carving [S5]; neither paper was read directly. | documented (Han); partly documented (Sandeepa, Yang via secondary description) | [S1][S5] |
| OEM relationships | None needed. Honeywell sourcing Hikvision-made recorders is reported by an IPVM forum post (see Honeywell). | n/a | [S11] |
| Mobile app artefacts | Hik-Connect (Android/iOS) artefacts analysed; parsers contributed to ALEAPP/iLEAPP. Out of scope for disk parsing but relevant to correlation. | documented (secondary via Honeywell paper and thesis) | [S2][S5] |

Known gaps / needs real image to verify (Hikvision):
- Data block size (Han's two conflicting values) and whether it varies by firmware/disk size.
- Whether newer firmware (post-2015, H.265/"H.265+", HikvisionOS NVR generations) keeps `HIKVISION@HANGZHOU`, `HIKBTREE`, `OFNI`, `RATS`. Han tested one 2015-era DVR; Dragonas tested six devices in about 2022-2023 and found offsets identical across them, but this is still a small sample.
- Whether a GPT/MBR exists on disk and where Master Sector sits relative to it.
- Timezone/DST storage for each timestamp field; any per-block timezone marker.
- H.265 frame header layout (the `0xBA`/`0xBC` prefix is documented for H.264 only).
- Encrypted recordings (Hikvision "video encryption" feature): not covered by any source read.
- Interpretation of the first 2048 bytes of the log area, and the ~25% of log types not parsed.

### 3.2 Dahua

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| Storage layout / partitioning | Dahua HDDs observed in five devices: NVR2108-4KS2 and DHI-HCVR514C-S3 had one partition with DHFS; DH-XVR5216AN-4KL-I2 and DH-XVR5104HS-I3 had two partitions: DHFS first, XFS second. The IP camera used a FAT32 microSD. DHFS on-disk structure (offsets, magic) is NOT described in any source we could read; Li and Zuo's DHFS paper (cited by Dragonas and the Honeywell paper) was not accessible. | documented for partition combinations (5 devices); unknown for DHFS internals | [S2] |
| Filesystem | DHFS (Dahua File System), proprietary; XFS (standard) used for a second partition on some XVRs. Some Dahua products use only standard file systems (FAT32 on microSD). DVR Examiner release notes name a "DHFS_41" filesystem among its supported types (suggests versioned DHFS; vendor docs for versions not read). | documented (existence, combinations); unknown (versions) | [S2][S12] |
| Container / codecs | DHAV frames. FFmpeg's demuxer (code read) shows: probe accepts file prefix `DAHUA` (then skips to 0x400) or `DHAV` followed by type byte 0xf0, 0xf1, 0xfc or 0xfd. Frame header (little-endian): bytes 0-3 `DHAV`; byte 4 type (0xfd video I-frame/key, 0xfc video non-key, 0xf0 audio, 0xf1 other/skipped); byte 5 subtype; byte 6 channel; byte 7 frame sub-number; bytes 8-11 frame number (u32); bytes 12-15 frame length (u32; must be >= 24); bytes 16-19 date (u32 bit-packed); bytes 20-21 16-bit timestamp; byte 22 extension length; byte 23 checksum; then extension TLVs (types 0x80, 0x81, 0x82, 0x83, 0x88, 0x8c ... parsed for width/height, video codec, frame rate, audio params). Trailer: ASCII `dhav` followed by a 4-byte LE length used for backward scanning. Video codec IDs in the demuxer: 0x1 MPEG-4, 0x3 MJPEG, 0x2/0x4/0x8 H.264, 0xc HEVC. Audio IDs map to PCM S8, PCM S16LE, mu-law, A-law, AAC, MP2, MP3, ADPCM-MS. Resolution: either 8*byte (type 0x80) or 16-bit LE width and height (type 0x82). The demuxer also marks frames key unless type is 0xfc. The `.dav` extension is the demuxer's declared extension. | documented (FFmpeg source; this is the OEM-exported or carved DHAV stream, not the on-disk DHFS structure) | [S9] |
| Timestamps | Date field decoded in FFmpeg as: sec = bits 0-5; min = bits 6-11; hour = bits 12-16; day = bits 17-21; month = bits 22-25; year = bits 26-31 plus 2000. FFmpeg converts it with `av_timegm`, i.e. it treats the fields as wall-clock time with no timezone or DST information; no UTC offset appears in the header fields the demuxer reads. Sub-second resolution is derived from the 16-bit timestamp field (milliseconds-style difference within the same second; wraps handled with +65535) or from frame number and frame rate. Therefore Dahua DHAV time is local wall-clock time as configured on the recorder; this is an inference from the code (no timezone field parsed), flagged as such. | documented (bit layout, from code); partly documented (timezone semantics are inferred) | [S9] |
| Logs / metadata | Dahua logs are split by type between recorder internal memory (non-removable flash, not imaged in the study) and the HDD. HDD location: SQLite database `{SerialNumber}_log.db` in the XFS partition (tables `log` and `vlog`; `vlog.timep` event time, `modename`, `optname`, `data`, `username`). On DHFS-only recorders no filesystem listing was possible; SQLite databases had to be carved (X-Ways) and metadata such as filename was lost. By type (observed): Playback, Storage (disk, format, SMART), System (reboot/shutdown/time sync) are in internal memory; System save-config, Account (login/logout/illegal login/user changes), Alarm (video loss, tamper, intelligent), Record mode, Remote info are on disk. AI-related SQLite DBs (face detection/recognition, IVS) found on XFS under `\data\appdata\database\...`. GUI/WebUI "Backup" exports logs, limited to one month per text file. | documented (5 devices, firmware 2.680.0000000.22.R to 4.001.0000005.0) | [S2][S4 abstract] |
| Deleted-footage recovery | "Format storage" does not delete logs. "Format + Clear HDD database" empties `log_db`, but deleted rows were recovered with FQLite. "Clear Logs" deletes internal-memory and `log_db` entries (rows still recoverable). AI databases untouched by all three. Video recovery: Rzayeva 2025 abstract: dual-signature header/footer validation of DHFS frames, adaptive temporal sequencing, automatic manufacturer identification, tested on 27 HDDs (Hikvision and Dahua), reported 91.8% recovery, 96.7% temporal accuracy, 2.4% false positives. Rzayeva 2026 abstract: channel demultiplexing of interleaved DHAV streams from analog DVRs, up to 32 cameras, frame-number tolerance +/-3 and <=1 s temporal check, tested on 14 analog Dahua DVR drives. These are author-reported results; we only read the abstracts. | documented (logs, Dragonas thesis); partly documented (video recovery, abstracts only) | [S2][S7][S8] |
| OEM relationships | See CP Plus, Honeywell. Search-engine summaries say Lorex and Amcrest are built on Dahua firmware; we did not open a primary source for that, so it is not used. | partly documented | see 3.3, 3.4 |
| Open-source / commercial support | DVR Examiner, VIP, HX-Recovery, Dahua's own Disk Manager were tested on log artefacts and did not fully recognise them [S2]. A Sleuth Kit forum thread states Autopsy does not understand DHFS (forum post, user-level claim) [S13]. | partly documented | [S2][S13] |

Known gaps / needs real image to verify (Dahua):
- Entire DHFS on-disk layout: superblock/magic, index structures, block size, how DHAV frames are located (DHFS structure never read from a primary source).
- DHFS version differences (the "DHFS_41" naming in DVR Examiner suggests versions).
- Timezone/DST storage; whether recorders write a UTC offset anywhere.
- Handling of H.265 and "H.265+" / smart-codec frames and any non-standard SPS/PPS.
- Whether the `DAHUA` 0x400-byte file prefix appears inside DHFS or only in exported `.dav` files.
- Meaning of subtype and extension TLVs the demuxer skips.
- Contents of internal memory (not imaged in [S2]), which hold Playback/Storage/System logs.

### 3.3 CP Plus

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| Storage layout / partitioning | No public technical source found. | unknown | n/a |
| Filesystem | No public source found stating which filesystem CP Plus recorders use. | unknown | n/a |
| Container / codecs | Not documented in any source read. | unknown | n/a |
| Timestamps | Not documented. | unknown | n/a |
| Logs / metadata | Not documented. | unknown | n/a |
| Deleted-footage recovery | Not documented. | unknown | n/a |
| OEM relationships | An ICICI Securities IPO review (July 2025) of Aditya Infotech Ltd states the business has (a) manufacturing/trading of CP Plus products and (b) distribution of Dahua products, with exclusive distribution rights for Dahua products in India (~25% of FY25 revenue). That establishes a commercial relationship with Dahua. It does NOT state that CP Plus recorders run Dahua firmware or DHFS. Do not assume a shared on-disk format. | documented (business relationship only); unknown (technical relationship) | [S14] |

Known gaps (CP Plus): everything technical. Needs real images from several CP Plus DVR/NVR/XVR generations; test whether DHFS/DHAV signatures (see 3.2) appear.

### 3.4 Honeywell

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| Storage layout / partitioning | One NVR studied: HN35080200 (8 PoE cameras HN40E-2030I, 160 GB and 250 GB Seagate HDDs, remote app "HSV"). GPT layout. First 40 sectors (20 KiB) = start sectors: sector 0 protective MBR, 1 primary GPT header, 2 partition entry array, 3-33 unused, sector 34 "Machine Data" (device ID and model strings, e.g. "HN350802xx"), 35-39 unused. Partition 1 (variable size) = proprietary video store. Partition 2 = fixed 10 GB ext4 (system/config). Final 2 GB unpartitioned with backup GPT (secondary header at sector 32 of that region). Partition names are the authors' own labels. | documented (single model) | [S5] |
| Partition 1 internal map (offsets relative to partition start, little-endian) | Header 0x00-0x3FFF (video data start offset at 0x00, next-write offset at 0x08, available memory at 0x10, total allocatable memory at 0x18; 16-byte Block Group Index entries from 0x40, with a 4-byte block-group start time Unix seconds at +4 and block group number). Video Block List 0x40000-0x3FFFFF (16-byte entries: start time, block number, block group, 256 blocks per group). Video Channel List 0x400000-0x3FFFFFFF (16-byte Channel Index: 1 byte channel, 1 byte stream type 0x00 main / 0x20 sub, 2-byte frame length, 4-byte frame start time, 4-byte start offset; values rounded at the third hex digit per paper). Record State 0x40000000-0x4011FFFF (per-channel 0x20000 subregions; per-hour "time anchors", 20-byte Record Index). Fixed values region (unanalysed). Video Data 0x80000000 to end. | documented (single model) | [S5] |
| Filesystem | Proprietary ("undocumented") partition 1 plus ext4 partition 2. Honeywell appears to have no official public name for it. | documented | [S5] |
| Container / codecs | Raw H.264 NAL units, each preceded by a 20-byte "Custom Header": byte 0 frame type (0x82 IDR, 0x02 non-IDR), bytes 1-3 `80 01 00`, bytes 4-7 resolution (2-byte width, 2-byte height), bytes 8-11 NAL length (4 bytes), bytes 12-19 Unix time in microseconds (8 bytes). Then `00 00 00 01` plus NAL header. Per-channel data ends with 20 bytes of 0x00 ("End of Channel Data"); gaps padded with dummy data to the rounded length. Device supports H.264/H.265, but only H.264 was tested; H.265 layout unknown. Extracted streams played with ffplay, which skips the custom header; playback also works with it removed. | documented (H.264, single model); unknown (H.265) | [S5] |
| Timestamps | Block group start time and Video Block List times: 4-byte Unix seconds (example 0x692775A3 reported as 2025-11-26 21:48:19; our arithmetic confirms this equals that wall-clock value as UTC). Per-NAL custom header time: 8-byte Unix microseconds. Paper does not state the device's timezone setting or whether stored values are UTC or local. Observed: the block-group start time marks the oldest viewable recording; video timestamps older than that header time imply deletion. | partly documented (format yes; timezone/DST unknown) | [S5] |
| Logs / metadata | The paper does not analyse system/event logs. ext4 partition assumed to hold config/system files ("considered", not examined). | unknown | [S5] |
| Deleted-footage recovery | Three delete modes analysed: format, expiration, overwrite. None erases raw video. Format resets header and removes all Block/Channel/Record indices and changes disk and partition GUIDs, but video data remains until recording restarts from the beginning of the video region and overwrites it. Expiration and overwrite remove oldest metadata and append new data after existing data, so deleted video is likelier to persist. Recovery recipe: carve between the custom header and the next 20-zero-byte delimiter; stream is playable in ffplay. Deleted data identified by comparing per-NAL timestamps with Header block-group start time. Authors rate recoverability: format Medium, expiration High, overwrite High. No quantitative evaluation (stated as future work). | documented (single model; case study on one image) | [S5][S6] |
| OEM relationships | An IPVM forum post states Honeywell "released NVR kits from Dahua as part of their Performance Series" in addition to existing DVRs and NVRs from Hikvision and OpenEye, plus new DynaColor-made models. This is a forum post (date not captured) and is not a technical on-disk finding. The Honeywell paper's own filesystem is neither of those vendors' layouts, so a Honeywell label does not imply a single on-disk format. | partly documented | [S11][S5] |
| Open code | `compare_partition.py` (byte-level compare with hard-coded sector ranges for 160/250 GB disks) and `dat_carving.py` (splits a hard-coded range of Partition 1 at 20+ zero bytes into `.dat` files; hard-coded scan range 0x80005000-0x22433D6000). README states carving is only qualitatively verified. No licence file; GitHub licence field null. | documented | [S6] |

Known gaps (Honeywell): other models/generations (the paper says it expects generalisation but tested one device); H.265 layout; encrypted storage; timezone/DST; logs; stream-type values beyond 0x00/0x20; fixed-values region; behaviour with fragmentation or multi-disk arrays.

### 3.5 Uniview (UNV)

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| Storage layout, filesystem, container, codecs, timestamps, logs, deletion recovery | No peer-reviewed or open-source technical description found. Uniview's storage product pages are marketing material. A search for "Uniview NVR file system forensic" returned only general statements about proprietary DVR file systems. | unknown | [S15 (marketing page not read for this)] |
| OEM relationships | No sourced statement found. | unknown | n/a |

Known gaps (Uniview): everything. Needs real images.

### 3.6 TP-Link (VIGI NVR)

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| Filesystem | Not stated in the vendor's NVR1016H product page; no forensic literature found. | unknown | [S16] |
| Container / codecs | Product page: video compression H.265+/H.265/H.264+/H.264; 16 channels; 1 SATA interface up to 16 TB (page read; an earlier search snippet said 10 TB, the page itself says 16 TB for NVR1016H). Container on disk: unknown. | codecs documented (marketing spec); container unknown | [S16] |
| Timestamps | NTP is a supported protocol; storage-level timestamp format and timezone handling unknown. | partly documented (NTP only) | [S16] |
| Logs / metadata | Spec lists anomaly alarms (Video Loss, Offline/IP Conflict, Disk Exception, Login Exception). On-disk log format unknown. | unknown (on-disk) | [S16] |
| Deleted-footage recovery, storage layout, OEM relationships | No public source found. | unknown | n/a |

Known gaps (TP-Link): all disk-level facts. VIGI is a newer product line (tested here only as marketing specification). Possible use of standard filesystems has not been verified or ruled out.

### 3.7 Godrej (SeeThru)

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| All rows | A search found only retail listings (8-channel H.264 recorder, optional HDD, USB 2.0 port; "manufacturer/packer/importer" listed as Godrej Consumer Products Limited, made in India). The Godrej support FAQ PDF URL returned 404. No technical source for filesystem, container, timestamps, logs, or deletion recovery. Whether Godrej recorders are rebadged from another OEM was not found in any source we opened. | unknown | none opened as primary |

Known gaps (Godrej): everything. Note the retail listing text in the search result was not opened as a page, so even the "H.264" and "manufacturer" statements are search-snippet level and are not relied upon.

### 3.8 Matrix (Matrix Comsec SATATYA)

| Topic | Finding | Confidence | Sources |
|---|---|---|---|
| Codecs | Matrix datasheet for NVR3204X was opened but the extracted content was thin; a search result summary states H.265 primary with H.264 and MJPEG options. The fetched document itself did not state filesystem, export format, time sync or logs. | partly documented (codec level, from search-listing; not verified in the opened spec) | [S17] |
| Filesystem, container, timestamps, logs, deletion recovery, OEM relationships | No public technical source found. Matrix Comsec is an Indian company that designs its own products per its own marketing, but we did not locate a sourced statement on whether recorder firmware is in-house. | unknown | n/a |

Known gaps (Matrix): all disk-level facts. Needs real images from SATATYA DVR/NVR models and ideally the vendor's player/export software to map the format.

## 4. OEM comparison table (required deliverable)

"Public documentation level" counts only what we verified. Tier column = recommended Nirikshan support tier today. No OEM is Tier A.

| OEM | Filesystem | Container | Codecs | Timestamp | Logs | Public documentation level | Recommended tier today |
|---|---|---|---|---|---|---|---|
| Hikvision | Proprietary "HIKVISION FS": Master Sector `HIKVISION@HANGZHOU` @0x200, HIKBTREE, IDR table `OFNI`, log area `RATS` [S1][S2] | Raw H.264 NAL with 4-byte start code plus 0xBA/0xBC index byte [S1] | H.264 documented; H.265 unknown | Unix seconds; HIKBTREE UTC (Han), log time local (Dragonas); DST unknown | System logs (RATS records) documented; app artefacts documented | High for 2015 DVR structure; medium for logs (6 devices); newer firmware unverified | **B** (signature ID: `HIKVISION@HANGZHOU`, `HIKBTREE`, `RATS`; NAL carving). Structured parser (P4) is built from the papers only and is not validated on any real image; the tier stays B |
| Dahua | DHFS (proprietary; internals not read); some devices add XFS 2nd partition [S2] | DHAV frames (`DHAV`...`dhav`), fully readable from FFmpeg source [S9] | MPEG-4, MJPEG, H.264, HEVC IDs seen in demuxer; audio PCM/G.711/AAC/MP2/MP3 [S9] | Bit-packed local-time date plus 16-bit sub-second; no timezone field read (inferred local) [S9] | SQLite `{serial}_log.db` on XFS partition; internal-memory logs not imaged [S2] | Medium: container strong, DHFS internals not read, journal papers not accessed in full | **B** (DHAV signature ID and frame carving; strongest basis because the container is open-source documented) |
| CP Plus | Unknown | Unknown | Unknown | Unknown | Unknown | None found. Business tie to Dahua (distributor) only [S14] | **C** (run generic carving opportunistically; do not label as Dahua-compatible until a real image shows DHFS/DHAV) |
| Honeywell | GPT: proprietary partition 1 + 10 GB ext4 partition 2 [S5] | Raw H.264 NAL with 20-byte custom header [S5] | H.264 documented; H.265 unknown | Unix seconds (block metadata); Unix microseconds (per-NAL); timezone unknown [S5] | Not analysed [S5] | Medium: one 2026 paper, one model, one disk image set; tools repo unlicensed | **B** (Machine Data string + custom header 0x82/0x02 `80 01 00` + NAL carving; model coverage limited) |
| Uniview | Unknown | Unknown | Unknown | Unknown | Unknown | None found | **C** |
| TP-Link VIGI | Unknown (not stated in spec) | Unknown | H.265+/H.265/H.264+/H.264 (vendor spec) [S16] | NTP supported; disk format unknown | Alarm categories in spec; on-disk unknown | Marketing only | **C** |
| Godrej | Unknown | Unknown | Unknown | Unknown | Unknown | None found | **C** |
| Matrix Comsec | Unknown | Unknown | H.265/H.264/MJPEG (spec listing) [S17] | Unknown | Unknown | Marketing only | **C** |

Rationale for Tier B vs C: Tier B is only claimed where there is a public byte-level signature we can match (Hikvision, Dahua, Honeywell). "Generic NAL/GOP carving" (section 5) can run on any image regardless of tier, but without a published signature we cannot attribute the vendor, so those OEMs stay at Tier C until real images are collected.

## 5. Vendor-agnostic carving (the basis of vendor-independent recovery)

What the sources establish:

- **Annex B start codes.** All three documented layouts store NAL units behind an Annex-B style start code: Hikvision uses `00 00 00 01` followed by a one-byte NAL header [S1]; Honeywell has a 20-byte custom header followed by `00 00 00 01` and the NAL header [S5]; Dahua DHAV payloads feed FFmpeg's H.264/HEVC decoders as packets [S9]. FFmpeg's `h2645_parse.c` itself searches for start codes in raw bitstreams ("search start code", logs "No start code is found.") [S18]. We could not open the Annex B text of ITU-T H.264/H.265 itself (ITU pages return recommendation index only) [S19][S20]; the three-byte form `00 00 01` and four-byte form `00 00 00 01` are shown in the Hikvision paper's sequences [S1].
- **H.264 NAL types** (from FFmpeg's `libavcodec/h264.h` [S21]): 1 non-IDR slice, 5 IDR slice, 6 SEI, 7 SPS, 8 PPS, 9 AUD, 10 end of sequence, 11 end of stream, 12 filler. With the NAL header byte, Han's observed bytes decode consistently: 0x65 = ref_idc 3 + type 5 (IDR), 0x61 = ref_idc 3 + type 1 (non-IDR), 0x67 = type 7 (SPS), 0x68 = type 8 (PPS), 0x06 = SEI, 0x09 = AUD [S1]. (Our decoding: NAL type = low 5 bits.)
- **H.265 NAL types** (from FFmpeg's `libavcodec/hevc/hevc.h` [S22]): 0-9 trail/TSA/STSA/RADL/RASL, 16-21 BLA/IDR_W_RADL(19)/IDR_N_LP(20)/CRA(21), 32 VPS, 33 SPS, 34 PPS, 35 AUD, 39/40 SEI. IRAP pictures (types 16-21) are the HEVC equivalent of GOP entry points. For HEVC, NAL type is in bits 1-6 of the first header byte (stated from H.265; not verified in the document text here, so treat as implementation to confirm against the spec).
- **IDR/GOP carving principle.** A decodable segment starts at an IDR (H.264) or IRAP (H.265) preceded or accompanied by SPS/PPS (VPS/SPS/PPS for HEVC). IDR slices decode independently; non-IDR slices need references [S5]. Hikvision's IDR table and Honeywell's custom-header frame type byte (0x82 vs 0x02) offer vendor shortcuts to the same GOP structure [S1][S5].
- **Frame-level recovery works without filesystem metadata** in the documented cases: Honeywell video data survived formatting (metadata erased, raw NAL data remained) and was extracted purely by header and zero-run delimiters [S5]; Hikvision video remained after initialisation and can be carved [S1].

Known limits and caveats (all source-backed unless marked):

1. **Overwrite is destructive.** After format on Honeywell, new recording restarts from the beginning of the video region and progressively overwrites old data [S5]. Hikvision overwrite replaces old data when the disk is full [S1].
2. **Metadata-less carving loses channel/time attribution**, unless each frame carries its own time (Honeywell per-NAL microseconds, Dahua DHAV date, Hikvision IDR table). Rzayeva 2025/2026 abstracts report that gap detection and channel demultiplexing need adaptive thresholds and frame-number checks [S7][S8] (abstract-level only).
3. **Interleaving/fragmentation.** Multi-channel analog DVRs interleave frames from many cameras in one stream; the 2026 abstract reports demultiplexing up to 32 cameras by embedded channel IDs and temporal coherence [S8] (abstract-level).
4. **Vendor headers break stock players.** Hikvision's 0xBA/0xBC index byte causes screen noise in non-vendor players [S1]; Honeywell's custom header is skipped by ffplay [S5].
5. **False positives.** Dragonas's `RATS` log search had no false positives on his image, but he notes false positives may occur elsewhere [S2]. The same applies to any 4-byte signature; validate with structure checks (e.g., header-footer pairs as in DHAV `DHAV`/`dhav` [S9]).
6. **Encryption.** None of the sources read cover vendor-encrypted recordings. Treat as unknown; carving will yield noise if payloads are encrypted.
7. **Codec coverage.** MJPEG and MPEG-4 appear in the Dahua demuxer ID table [S9]; they do not use H.264 NAL start codes, so NAL carving does not recover them.
8. **Validation.** The Honeywell repo itself says its carving results are only qualitatively verified [S6]. Nirikshan must publish its own error rates measured on ground-truth images before claiming recovery percentages. The MDPI 91.8% / 92.3% recovery figures are author-reported and unreplicated here.

## 6. Timestamp normalisation

Principles for Nirikshan, supported by the sources:

- **Store raw plus assumption.** For each carved/parsed timestamp keep: raw value, field name, format, assumed timezone, and the evidence for that assumption. The sources show that formats and timezone semantics differ even within one vendor (section 2, item 2).
- **Per-format decoding facts (verified):**
  - Hikvision HIKBTREE/Master: UNIX seconds, UTC per Han [S1]. Hikvision log "Time": UNIX seconds but local time zone of the recorder per Dragonas; stored timezone offset not found [S2].
  - Dahua DHAV: bit-packed Y(6 bits, +2000)/M/D/h/m/s; no timezone field in the parsed header; FFmpeg uses `av_timegm` to form a number [S9].
  - Honeywell: Unix seconds for blocks, Unix microseconds for per-NAL data, timezone not stated [S5].
- **Clock drift and wrong-clock risk.**
  - NIST SP 800-86 (2006) warns that timestamps may be inaccurate because the clock was not synchronised, the time may lack detail, or an attacker altered it; recommends knowing the time, date and time-zone settings of the system analysed and notes NTP as a means to keep clocks accurate [S23].
  - SWGDE 17-V-002-1.4 (2025-08-21): record the DVR's system time versus a standardised atomic-clock time (and document the device used), do not change the DVR time, and calculate the offset between real time and the DVR clock [S24].
  - Han (2015): time reversals across the init time, IDR table times and HIKBTREE times indicate re-initialisation; this is a tamper indicator and also a data-quality check for drift/clock changes [S1].
  - The Honeywell paper uses block-group start time versus per-NAL times to infer deletion, so comparisons must use the same timezone basis [S5].
- **DST.** We found no source in this set that documents how any of the eight OEMs store or apply DST. Treat DST as unknown for all; require the examiner to record the device's configured timezone/DST setting and the observed offset from the SWGDE procedure.
- **OSD vs metadata.** No source read compares burned-in on-screen-display time to container metadata. Do not assume they agree. Keep both and flag mismatches.
- **Output convention (recommended, an engineering decision, not a sourced claim):** emit UTC only when the timezone is established with evidence; otherwise emit "device-local, offset unknown" and carry the raw value forward.

## 7. Existing tooling and literature (publicly documented only)

| Item | What public sources say | Source |
|---|---|---|
| DVR Examiner (DME Forensics/Magnet) | A Magnet release note lists supported filesystems including PSF, Stream, `DHFS_41`, `RSF4_L`, "HIK" families and a new `Stream_db_I_e4`; the post does not map filesystem names to brands. Dragonas found DVR Examiner (3.8.0), VIP, HX-Recovery, and Dahua Disk Manager did not fully recover the Hikvision/Dahua log artefacts he studied. | [S12][S2] |
| HX-Recovery, VIP, others | Tested in [S2]; not otherwise documented here. Gillware/SalvationData pages exist but were not opened. | [S2] |
| Hikvision LocalPlayback | Vendor tool; found 114 of 19,063 `RATS` records on one image (<1%). | [S2] |
| Hikvision Log Analyzer | Python, open source (no licence declared), carves `RATS` records from `.dd`/`.001` images, exports CSV/HTML. | [S2][S10] |
| ffmpeg dhav demuxer | LGPL-2.1+; reads DHAV frames and `.dav`; latest touching commit seen: `50e65074f5` (2026-05-20, "Fix second integer overflow in get_duration()"). File fetched from `master` on 2026-10-05; analysis in 3.2 reflects that version. | [S9] |
| ffmpeg Hikvision demuxer | A listing of the FFmpeg repository tree (10,963 entries) shows no `libavformat` file whose name contains "hik"; ffmpeg's `h264dec.c`/`hevcdec.c` raw demuxers exist. Whether a Hikvision container (as distinct from raw carved NAL with a 0xBA/0xBC prefix) is parsed by some other demuxer was not determined. | [S25] |
| Autopsy / Sleuth Kit | Forum post: does not understand DHFS. | [S13] |
| ALEAPP / iLEAPP | Contain parsers for Hikvision app artefacts (per [S5] related work). | [S5] |
| Other open research | Lee et al. 2023 (RTOS in-vehicle camera FS), Poole et al. 2009 and Tobin et al. 2014 (CCTV DVR reverse engineering), Gomm (AVTECH) cited in [S1][S2][S5]; not read directly. | [S1][S2][S5] |

## 8. Standards and acceptance

What the Nirikshan evidence-handling workflow should align with, using only documents we opened:

| Standard / guidance | What we verified | Link |
|---|---|---|
| NIST SP 800-86, Guide to Integrating Forensic Techniques into Incident Response (Aug 2006) | Full PDF read (text extracted). Recommends bit-stream imaging when file times matter; use write-blockers; verify copies with message digests (document names MD5/SHA-1 and says federal agencies should use the FIPS-approved SHA-1); maintain chain of custody; warns on clock inaccuracy. The hash algorithm advice is dated; modern practice should use SHA-256 or stronger (our recommendation). | https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-86.pdf |
| SWGDE 17-V-002-1.4, Best Practices for Data Acquisition from Digital Video Recorders (2025-08-21) | Page read. Use a write blocker when accessing the DVR drive directly; prefer native/proprietary format as best evidence, with open-format exports as secondary; acquire proprietary player/codec; document DVR vs atomic-clock time offset and do not change DVR time; imaging when the exports are too big or ports are non-functional; integrity guidance deferred to SWGDE 17-I-001. | https://www.swgde.org/17-v-002-1-4/ |
| SWGDE 15-V-002, Proposed Techniques for Advanced Data Recovery from Security DVRs Containing H.264 Data (2016-06-23) | Listed on SWGDE video-committee page only; the document itself was not opened. | https://www.swgde.org/documents/published-complete-listing/15-v-002-swgde-proposed-techniques-for-advanced-data-recovery-from-security-digital-video-recorders-containing-h-264-data/ |
| ISO/IEC 27037 (identification, collection, acquisition, preservation of digital evidence) | ISO page returned 403; standard text is paywalled. We can cite it only by title; its requirements were not verified. | https://www.iso.org/standard/44381.html (not accessible) |
| ACPO Good Practice Guide for Digital Evidence v5 | NPCC PDF URL returned 403; content not verified. Do not quote the four principles from this document without re-checking the source. | https://www.npcc.police.uk/ (not accessible) |

Implications for Nirikshan (engineering recommendations, not sourced claims): work on a write-blocked image only; record acquisition and analysis hashes; record the DVR clock-offset evidence; keep original proprietary-format files plus converted outputs; log every tool version and parameter. Note the Han paper's point that reconnecting a collected disk to a DVR damages integrity, so access must be via the image [S1].

## 9. Consolidated list of what must be verified on real images before upgrading any tier

1. Re-test every signature (`HIKVISION@HANGZHOU`, `HIKBTREE`, `OFNI`, `RATS`, `DHAV`/`dhav`, Honeywell Machine Data and custom header) on at least three firmware generations per vendor.
2. Establish timezone/DST storage per timestamp field for each vendor, using DVRs with known configured time zones.
3. Confirm H.265 frame/container layout for Hikvision, Dahua, Honeywell.
4. Obtain DHFS internals via image analysis (no primary source read).
5. Collect CP Plus, Uniview, TP-Link VIGI, Godrej, Matrix images; determine filesystem/container independently; do not infer from OEM relationships.
6. Measure carving precision/recall on ground-truth images; compare with the author-reported figures in [S7][S8].
7. Test encrypted-recording modes.
8. Resolve the Hikvision data-block size ambiguity.

## 10. Source index (access date 2026-10-05)

Status key: **Full** = opened and read in full or the relevant parts in full; **Partial** = opened but only part usable (summary, abstract, or partial extraction); **Not accessible** = could not open (403/404/paywall/anti-bot) or not opened.

| ID | Title | URL | Status |
|---|---|---|---|
| S1 | Han, Jeong, Lee, "Analysis of the HIKVISION DVR File System", ICDF2C 2015 (LNICST 157, pp.189-199), DOI 10.1007/978-3-319-25512-5_13 | https://eudl.eu/pdf/10.1007/978-3-319-25512-5_13 (landing: https://link.springer.com/chapter/10.1007/978-3-319-25512-5_13) | Full |
| S2 | Dragonas, E., "IoT forensics" doctoral thesis, Univ. of Piraeus, 2023 (DOI 10.26267/unipi_dione/3228) | https://dione.lib.unipi.gr/xmlui/handle/unipi/15806 (PDF: .../bitstream/handle/unipi/15806/Dragonas_de180.pdf) | Full for chapters 4-5 (Dahua/Hikvision); other chapters not read |
| S3 | Dragonas, Lambrinoudakis, Kotsis, "IoT forensics: Exploiting unexplored log records from the Hikvision file system", J. Forensic Sci. 68:2002-2011 (2023) | cited in [S5]; DFRWS PDF https://dfrws.org/wp-content/uploads/2023/07/dragonas-hikvision.pdf | Not accessible (403); content covered via [S2] |
| S4 | Dragonas, Lambrinoudakis, Kotsis, "IoT forensics: Exploiting log records from the DAHUA Technology CCTV systems", J. Forensic Sci. 69:117-130 (2024), DOI 10.1111/1556-4029.15401 | https://onlinelibrary.wiley.com/doi/10.1111/1556-4029.15401 ; metadata via https://api.crossref.org/works/10.1111/1556-4029.15401 | Wiley page not accessible (403); abstract read via Crossref (Partial) |
| S5 | Yoon, Hwang, "Forensic analysis of video data deletion and recovery in Honeywell surveillance file system", arXiv:2605.07430 (May 2026) | https://arxiv.org/abs/2605.07430 ; https://arxiv.org/pdf/2605.07430 | Full |
| S6 | eraw1am/Honeywell-NVR-Filesystem-Tools (GitHub; created 2026-04-07; no licence) | https://github.com/eraw1am/Honeywell-NVR-Filesystem-Tools (read via API and raw files) | Full (README plus two scripts) |
| S7 | Rzayeva et al., "Automated Forensic Recovery Methodology for Video Evidence from Hikvision and Dahua DVR/NVR Systems", Information 16(11):983 (2025-11-13), DOI 10.3390/info16110983 | https://www.mdpi.com/2078-2489/16/11/983 ; abstract via https://api.crossref.org/works/10.3390/info16110983 | MDPI not accessible (403); abstract only (Partial) |
| S8 | Rzayeva et al., "Forensic Video Recovery from Multi-Channel Analog DVR Systems: Channel Demultiplexing and Temporal Reconstruction from Interleaved DHAV Streams", Information 17(5):493 (2026-05-17), DOI 10.3390/info17050493 | https://www.mdpi.com/2078-2489/17/5/493 ; abstract via https://api.crossref.org/works/10.3390/info17050493 | MDPI not accessible (403); abstract only (Partial) |
| S9 | FFmpeg `libavformat/dhav.c` | https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/dhav.c (fetched via raw.githubusercontent.com, master, 2026-10-05) | Full |
| S10 | theAtropos4n6/HikvisionLogAnalyzer | https://github.com/theAtropos4n6/HikvisionLogAnalyzer | Partial (README header and API metadata; code not inspected) |
| S11 | IPVM forum, "Honeywell Cannot Pick An OEM" | https://ipvm.com/forums/video-surveillance/topics/honeywell-cannot-pick-an-oem | Partial (page summary only; post date not captured) |
| S12 | Magnet Forensics blog, "Stream_db_I_e4 Filesystem Support Now Available in DVR Examiner 3.1.5" | https://www.magnetforensics.com/blog/stream_db_i_e4-filesystem-support-now-available-in-dvr-examiner-3-1-5/ | Partial (page summary) |
| S13 | Sleuth Kit forum, "Support for DHfs file system or unknown file system" | https://sleuthkit.discourse.group/t/support-for-dhfs-file-system-or-unknown-file-system/2006 | Partial (forum post, user claims) |
| S14 | ICICI Securities, Aditya Infotech IPO review (Jul 2025) | https://www.icicidirect.com/mailcontent/idirect_adityainfotech_iporeview-jul_25.pdf | Partial (text searched for "Dahua" only) |
| S15 | Uniview storage product pages | https://global.uniview.com/Products/Storage | Not accessible/not opened (listed from search) |
| S16 | TP-Link VIGI NVR1016H product page | https://www.vigi.com/in/business-networking/vigi-network-video-recorder/vigi-nvr1016h/ | Partial (page summary) |
| S17 | Matrix IPVS SATATYA NVR3204X Technical Specifications | https://matrixcomsec.com/wp-content/uploads/2023/09/Matrix-IPVS-SATATYA-NVR3204X-Technical-Specifications.pdf-.pdf | Partial (extraction thin) |
| S18 | FFmpeg `libavcodec/h2645_parse.c` | https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/h2645_parse.c | Skimmed (grep for start-code handling only) |
| S19 | ITU-T H.264 (06/26) recommendation page | https://www.itu.int/rec/T-REC-H.264 | Partial (index page; spec text not read) |
| S20 | ITU-T H.265 (01/26) recommendation page | https://www.itu.int/rec/T-REC-H.265 | Partial (index page; spec text not read) |
| S21 | FFmpeg `libavcodec/h264.h` (H264 NAL type enum) | https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/h264.h | Skimmed (enum read) |
| S22 | FFmpeg `libavcodec/hevc/hevc.h` (HEVC NAL type enum) | https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/hevc/hevc.h | Skimmed (enum read) |
| S23 | NIST SP 800-86 (Aug 2006) | https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-86.pdf | Full text extracted; relevant sections read (skimmed overall) |
| S24 | SWGDE 17-V-002-1.4, Best Practices for Data Acquisition from Digital Video Recorders | https://www.swgde.org/17-v-002-1-4/ | Partial (page content; SWGDE document list at https://www.swgde.org/documents/published-by-committee/video/ also read) |
| S25 | FFmpeg repository tree listing (GitHub API) | https://api.github.com/repos/FFmpeg/FFmpeg/git/trees/master?recursive=1 | Full listing scanned for file names |
| S26 | ISO/IEC 27037 | https://www.iso.org/standard/44381.html | Not accessible (403) |
| S27 | ACPO Good Practice Guide for Digital Evidence v5 (NPCC) | https://www.npcc.police.uk/documents/crime/2014/Digital%20Evidence%20ACPO%20Good%20Practice%20Guide%20v5.pdf | Not accessible (403) |
| S28 | Yang, Li, Wu, "Basic principle and application of video recovery software for 'Dahua' and 'Hikvision' brand", SHS Web of Conferences 14 (2015) | https://www.shs-conferences.org/10.1051/shsconf/20151402010 | Not accessible (403); known only via [S1][S5] |
| S29 | Sandeepa et al., 2018 (Hikvision unallocated video recovery); Li and Zuo (Dahua DHFS) | cited in [S2][S5] | Not located/not accessible; secondary description only |
| S30 | Magnet Forensics / DME Forensics, Gillware, SalvationData, forensicfocus threads on DVR recovery | various (appeared in search results) | Not opened (not relied on) |
