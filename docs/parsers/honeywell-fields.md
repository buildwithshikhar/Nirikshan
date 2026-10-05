# Honeywell NVR (HN35080200) on-disk field table

Status: research note for the Nirikshan parser. Access date for all sources: 2026-10-05.
Scope: ONE device model, firmware shown in the paper's Fig. 3 screenshot "1.24.1.146.20241120", 8 channels, H.264 only. Nothing here is verified on a second model.

## 0. Sources, conventions, confidence tags

| ID | Source | Fully read? |
|---|---|---|
| P | Yoon and Hwang, "Forensic analysis of video data deletion and recovery in Honeywell surveillance file system", arXiv:2605.07430v1 (8 May 2026). https://arxiv.org/abs/2605.07430 ; HTML https://arxiv.org/html/2605.07430v1 (full text, Sections 1-9, Tables 1-2, references read). Figures 2-9 (SVG) and 3, 11 (PNG) were rasterised and the hex values read visually. | Yes, full text and all byte-level figures (Fig. 1 workflow and Fig. 10 diagram not needed for byte values; Fig. 10 only glanced at). The PDF was downloaded but text-extracted via the HTML version. |
| R | github.com/eraw1am/Honeywell-NVR-Filesystem-Tools: README.md, dat_carving.py, compare_partition.py (raw files). NO licence. No code copied; only constants are recorded, each tagged "R only" where P does not give them. | Yes (all 3 files) |
| D | Derived: arithmetic by the note author on P's own examples. Always labelled "derived". | n/a |
| G | Standard GPT/UEFI knowledge, not from P. Labelled "GPT std". | n/a |

Confidence tags: **documented** (P states it in text/figure), **partly documented** (P shows bytes but gives no explicit statement or only an example), **derived** (inferred from P's numbers, internally consistent but not stated), **unknown** (not stated anywhere read).

Global statement in P Sec. 5.4: "data are stored in little-endian format" for Partition 1. P does NOT state the endianness of the start-sector GPT structures (they are standard GPT, little-endian per GPT std), and it never discusses sector size (512 is used by R's `sector_size=512`, and P's "40 sectors (approximately 20 KB)" implies 512).

Abbreviations: "rel" = offset within Partition 1; "abs" = offset from byte 0 of the disk. abs = rel + 0x5000, **derived** from P Fig. 2 (label "0x5000" at the start of Partition 1), P Sec. 5.2 (40 start sectors = 20 KiB) and R (`START_OFFSET = 0x80005000` = 0x5000 + 0x80000000; Partition 1 sector range starts at sector 40). Partition 1 start LBA 40 is therefore consistent across P and R, but P never prints the partition entry bytes.

---

## 1. Disk layout

### 1.1 Overall layout (P Sec. 5.1, Fig. 2, Sec. 5.3; R compare_partition.py)

| Region | Sectors (512 B) | abs offset | Size | Content | Source | Conf. |
|---|---|---|---|---|---|---|
| Start sectors | 0-39 | 0x0000-0x4FFF | 20 KiB | GPT structures + Machine Data | P 5.1/5.2, Fig. 2 | documented |
| Partition 1 | 40 .. (variable) | 0x5000 | variable | proprietary video store | P 5.1 | documented |
| Partition 2 | follows P1 | variable | fixed 10 GB (R: 10 GiB = 20,971,520 sectors) | "Ext4", "considered to store system-related files and configuration"; contents not examined | P 5.1 | documented (fs type); contents unknown |
| Unpartitioned | last 2 GB | variable | 2 GB | backup GPT | P 5.3 | documented |

R-only concrete sector ranges for the two disks used (disk image size = last sector + 1):
- 160 GB disk: P1 sectors 40..287,415,984-1 = 40..287,415,983; P2 287,415,984..308,387,503; unallocated 308,387,504..312,581,808 (total 312,581,809 sectors). R only.
- 250 GB disk: P1 40..463,231,343; P2 463,231,344..484,202,863; unallocated 484,202,864..488,397,168 (total 488,397,169 sectors). R only (commented-out lines).
- R's unallocated range is 4,194,305 sectors while P says "Sectors 1-31 and 33-4,194,303" (i.e. about 4,194,304 sectors). Off-by-one-ish discrepancy; unresolved. Treat the P2/unallocated boundary as: P2 starts right after P1 and is exactly 10 GB, per P and R.
- Partition 1 size is NOT stored in the paper in any printed field; a parser must read the GPT partition entry (standard fields) rather than hard-code.

### 1.2 Start sectors 0-39 (P Sec. 5.2, Fig. 3)

| Sector | abs offset | Content per P | Conf. |
|---|---|---|---|
| 0 | 0x0000 | Protective MBR | documented (name only; no bytes shown) |
| 1 | 0x0200 | Primary GPT Header | documented (name only) |
| 2 | 0x0400 | Partition Entry Array ("defines starting locations, sizes, GUIDs of each partition, confirming ... two main partitions") | documented (name only) |
| 3-33 | 0x0600-0x43FF | "None area ... unused or reserved" (P). Caveat: a standard 128-entry array would occupy sectors 2-33; P does not say how many entries exist. | documented as unused; entry count unknown |
| 34 | 0x4400 | "Machine Data" | documented |
| 35-39 | 0x4600-0x4FFF | "None area ... no meaningful data" | documented |

Protective MBR / GPT header / entry array field-level layout: P gives NO byte offsets, values, or example hex for any of them. Use the UEFI spec (GPT std) for those; P only cites it ("UEFI Forum 2023") and states that formatting changes "the GUIDs in the start sectors for both the disk and partitions, which in turn changes the header and partition table checksums" (Sec. 6.1, Fig. 9a/b: Header Checksum, Entire Disk GUID, Partition table Checksum, Partition GUID). Endianness of these: not stated by P (GPT std: little-endian).

### 1.3 Machine Data, sector 34 (P Sec. 5.2, Fig. 3). Source of the bytes: P Fig. 3 hex dump (rows labelled 0x4400.. = absolute offsets). Text under "Content" is my ASCII reading of the figure's hex.

| Field | abs offset | Sector-relative | Size | Type | Example (hex from Fig. 3) | Decoded | Source | Conf. |
|---|---|---|---|---|---|---|---|---|
| (unlabelled string, grey) | 0x4400 | 0x00 | 15 + NUL (0x4400-0x440F) | ASCII, NUL padded | 73 6E 20 70 72 69 76 61 74 65 20 64 69 73 6B 00 | "sn private disk" (my decoding; P does not label or describe it) | Fig. 3 | unknown meaning; bytes shown |
| (unlabelled, grey) | 0x4420 | 0x20 | 3 (0x4420-0x4422) | ASCII | 32 2E 32 | "2.2" (my decoding; version?) | Fig. 3 | unknown meaning |
| Device ID | 0x4440 | 0x40 | 17 (0x4440-0x4450); remaining bytes to the next field are 00 | ASCII, NUL padded | 42 30 31 31 30 30 33 41 57 46 4E 52 5A 45 46 4B 56 | "B011003AWFNRZEFKV"; the Fig. 3 screenshot of the NVR UI shows Device ID "B011003AWFNRZEFKV" | Fig. 3; Sec. 5.2 | documented |
| Model | 0x4468 | 0x68 | 10 (0x4468-0x4471) | ASCII, NUL padded | 48 4E 33 35 30 38 30 32 78 78 | "HN350802xx" (UI screenshot shows "HN350802xx") | Fig. 3 | documented |
| rest of sector | | | | | 00 | | Fig. 3 only shows to 0x447F | partly (only 0x4400-0x447F shown) |

Notes: (a) P names the device "HN35080200" in Sec. 4.1 but the bytes/UI show "HN350802xx"; the last two characters are literally 'x','x' on disk. Do not match on "HN35080200". (b) Field lengths/terminators/max sizes are not stated; the NUL padding is only visible in the figure. (c) Sector 34 contents beyond offset 0x7F in the sector, and any checksum, are unknown. (d) Whether Machine Data exists/is at sector 34 on other models: unknown.

### 1.4 Partitions 1 and 2

Partition 1: see Section 2. Partition 2: Ext4, 10 GB, not analysed; P assumes system/config files. Ext4 superblock magic (0xEF53 at fs offset 0x438) is GPT/ext4 std, not from P. Partition names "Partition 1/2" are the authors' labels (P 5.1). Whether the GPT partition type GUIDs/names have any Honeywell-specific values: unknown (not shown).

### 1.5 Unpartitioned space / backup GPT (P Sec. 5.3, Fig. 2)

| Item | Position | Size | Content | Conf. |
|---|---|---|---|---|
| Region | last 2.0 GB of disk | 2 GB | holds only backup metadata | documented |
| Sector 0 of region | region start | 1 sector (but as an array, standard size) | "Secondary GPT Partition Entry Array" | documented |
| Sectors 1-31 | | | reserved, no recorded data | documented |
| Sector 32 of region | region start + 32*512 | 1 sector | "Secondary GPT Header" (disk layout, partition ranges, CRC32) | documented |
| Sectors 33-4,194,303 | | | reserved, no data | documented |

Observation: this is unusual relative to the GPT standard, which places the backup header at the last LBA of the disk; P says the secondary header is at sector 32 of the 2 GB region. A parser must NOT assume the standard last-LBA location for this device; locate it per P, and note that the primary header's "alternate LBA" field value is not shown in P. Whether the primary header's alternate-LBA points at this sector: unknown (not shown).

---

## 2. Proprietary video partition (Partition 1)

Endianness: little-endian (P Sec. 5.4, explicit). All offsets below are "rel" (partition-relative) unless "abs" given; abs = rel + 0x5000 (derived, see Sec. 1).

Overall map (P Sec. 5.4.x, Fig. 2):

| Region | rel start | rel end | Size | Source | Conf. |
|---|---|---|---|---|---|
| Header | 0x00000000 | 0x00003FFF | 16 KiB | 5.4.1 | documented |
| (gap 0x4000-0x3FFFF) | | | | P is silent (Fig. 2 shows no gap; Fig. 5(a) labels rows "0x4000.."; see note) | unknown |
| Video Block List | 0x00040000 | 0x003FFFFF | 3.75 MiB | 5.4.2 | documented in text |
| Video Channel List | 0x00400000 | 0x3FFFFFFF | ~1 GiB | 5.4.3 | documented |
| Record State | 0x40000000 | 0x4011FFFF (8 ch) | (channels+1) x 0x20000 | 5.4.4 | documented |
| Fixed Value | after Record State (Fig. 7 shows bytes at 0x44000000) | | | 5.4.5, Fig. 7 | start/end unknown; "not analysed" |
| "None" | between Fixed Value and Video Data (Fig. 2) | | | Fig. 2 | unknown |
| Video Data | 0x80000000 | end of partition | | 5.4.6 | documented |

Note on Fig. 5(a): the row labels in the figure read 0x4000, 0x4010, ... while the text says the Video Block List starts at 0x40000. Treat as a figure-label truncation (text and Fig. 2 ordering agree on 0x40000); this is **partly documented** and should be confirmed on a real image.

Units: size/offset-type fields in the Header and Channel Index are stored as 4 KiB (0x1000) "pages", not bytes. P says values are "rounded at the third digit", with examples ("E9 01" -> 0x01E9000; "00 00 08 00" -> 0x08000000 [sic]; header offset 0x01BB349E000). Derived interpretation, checked against P's own numbers (all consistent): stored_u32 x 0x1000 = byte value.
- Header video-data offset 00 00 08 00 -> 0x00080000 x 0x1000 = 0x80000000 (= start of Video Data; P text writes "0x08000000" for the same bytes, a typo; the figure value 0x80000000 is what matches Fig. 8).
- Header next-write 9E 34 BB 01 -> 0x01BB349E x 0x1000 = 0x1BB349E000, matching P's text value "0x01BB349E000".
- Channel entry 1: length E9 01 (0x1E9 pages) and start 0x80000 -> 0x80000000; entry 2 start 0x801E9 -> 0x801E9000 = exactly where Fig. 8 shows the second stream beginning (0x801E9000) and 0x80000000 + 0x1E9000 = 0x801E9000.
- Entry 2 length EA 01 (0x1EA) and entry 3 start 0x803D3 = 0x801E9 + 0x1EA. OK.
Status: **derived** (P never states "4096-byte units").

### 2.1 Header (rel 0x0000-0x3FFF) (P 5.4.1, Fig. 4, Fig. 9, Fig. 11)

| Field | rel off | abs off | Size | Endian | Type | Example (Fig. 4) | Meaning | Conf. |
|---|---|---|---|---|---|---|---|---|
| Video Data Offset | 0x00 | 0x5000 | 4 (P: "offsets 0x00-0x03"; bytes 0x04-0x07 are 00 in Fig. 4) | LE | u32, x0x1000 | 00 00 08 00 | start of video data = 0x80000000 | documented (value), derived (unit) |
| Next Video Offset | 0x08 | 0x5008 | 4 (P: 0x08-0x0B) | LE | u32, x0x1000 | 9E 34 BB 01 | "offset for the next video write" (0x1BB349E000) | documented / derived unit |
| Available Memory | 0x10 | 0x5010 | 4 (0x10-0x13) | LE | u32, x0x1000 | 33 FF 07 00 | remaining allocatable space; grows on expiration; equals total after format | documented text; unit derived |
| Total Allocatable Memory | 0x18 | 0x5018 | 4 (0x18-0x1B) | LE | u32, x0x1000 | D1 33 BB 01 (0x01BB33D1) | allocatable (not physical) capacity; "disk full" is reported when this is exhausted though physical space remains | documented text; unit derived |
| Block Group Index [n] | 0x40 + 16n | 0x5040 + 16n | 16 each | LE | struct | see below | "continuously added as the video is recorded" | documented |

Fields wider than shown: P lists 4-byte fields; the figure shows the 4 bytes after each are 00 (so 8-byte fields are possible). Width is **4 stated**, 8 **not excluded**.

Block Group Index entry (16 B), Fig. 4 (entries at 0x40 and 0x50):

| entry off | Size | Example | Meaning | Conf. |
|---|---|---|---|---|
| +0x00..0x03 | 4 | 00 00 00 00 | not described | unknown (zero) |
| +0x04..0x07 | 4 | A3 75 27 69 | block group start time, Unix seconds LE = 0x692775A3 = 2025-11-26 21:48:19 (value rendered as UTC by derived arithmetic; P prints no zone) | documented |
| +0x08..0x0B | 4 | D3 26 0B 00 / CF 86 00 00 (greyed) | not described | unknown |
| +0x0C | 1 | 04 / 05 | block group number | documented (figure label; P text confusingly says "start time ... located at offset 0x4C", which is the group-number byte, not the start time) |
| +0x0D..0x0F | 3 | 00 00 00 | not described | unknown |

Semantics (P 5.4.1, 7.2): the start time = "time when the first video was captured for each block group"; "Data prior to the capture time cannot be viewed on the NVR". Video with timestamps earlier than it that is still in Video Data "is highly likely" deleted. After expiration it becomes the oldest remaining block time (e.g. 0x693185FF = 2025-12-04 13:00:47 UTC arithmetic; P says "December 4, 2025, 13:00"). Group numbers in the example start at 4 (not 1), so group numbering is not necessarily 0/1-based: unknown rule.
Number of entries and the terminator (entry of all zeros?): not stated.

### 2.2 Video Block List (rel 0x40000-0x3FFFFF) (P 5.4.2, Fig. 5a)

16-byte "block index" entries, sequential, 256 blocks (0x00-0xFF) per block group, then next group.

| entry off | Size | Endian | Example (Fig. 5a) | Meaning | Conf. |
|---|---|---|---|---|---|
| +0x00..0x03 | 4 | | 00 00 00 00 | "reserved (set to 0x00)" | documented |
| +0x04..0x07 | 4 | LE | A3 75 27 69 | block start time, Unix s | documented |
| +0x08..0x0B | 4 | ? | 61 01 00 00; B8 01 00 00; EF 01 00 00; D4 01 00 00 (greyed) | NOT described. Values 0x161, 0x1B8, 0x1EF, 0x1D4 look like a size/offset-like count; do not interpret | unknown |
| +0x0C (P: "the 12th byte") | 1 | | 00,01,02,03 | block number within block group | documented (0-based index; figure confirms 0x0C) |
| +0x0D (P: "the 13th byte") | 1 | | 04 | block group number (matches Header entry's group number 04) | documented (same 0-based index) |
| +0x0E..0x0F | 2 | | 00 00 | not described | unknown |

Fig. 5a times are not monotonic by position in the figure (0x692775A3, 0x6930A93C, 0x6930AAC4, 0x6930AC88): first block is the first recording; later blocks are from the Dec 3 session. Per block, whether this list holds the sorted, wrapped, or insertion order: unknown.

### 2.3 Video Channel List (rel 0x400000-0x3FFFFFFF) (P 5.4.3, Fig. 5b)

16-byte "Channel Index"; "Stream entries are not recorded in a fixed order".

| entry off | Size | Endian | Example (Fig. 5b) | Meaning | Conf. |
|---|---|---|---|---|---|
| +0x00 | 1 | | 05, 07, 02, 04, 04 | channel identifier (1-byte) | documented that it exists; value base (1-based?) and mapping to physical camera/PoE port NOT stated (derived hint: Record State text says "channel 1 starts in the second subregion", i.e. 1-based) |
| +0x01 | 1 | | 00, 00, 00, 00, 20 | stream type: 0x00 main, 0x20 sub | documented; other values unknown |
| +0x02..0x03 | 2 | LE | E9 01 | frame (stream-chunk) length in 0x1000 units: 0x01E9 -> 0x1E9000 B | documented text, unit derived |
| +0x04..0x07 | 4 | LE | B7 75 27 69 | stream start time, Unix s (0x692775B7 = 2025-11-26 21:48:39) | documented ("frame start time" in text; "Stream Start Time" in figure; consistent with first custom-header timestamp 21:48:39.93, derived) |
| +0x08..0x0B | 4 | LE | 00 00 08 00 | start offset in 0x1000 units, relative to Partition 1 start (0x80000 -> 0x80000000) | documented text, unit derived |
| +0x0C..0x0F | 4 | | 00 0F 01 00; 00 09 01 00; 00 16 01 00; 00 0C 01 00; 00 18 01 00 (greyed) | NOT described | unknown |

Naming caution: P text calls the 2-byte field "frame length" but it is the length of the whole contiguous per-channel chunk (derived: 0x1E9000 bytes spans the NAL run and its padding up to the next 4 KiB boundary where Fig. 8 shows the next chunk). It is not one video frame.
Multiple chunks per channel/time exist (entries are per chunk; chunk starts are 4 KiB-aligned, derived from every start offset being a whole number of 0x1000 units).

### 2.4 Record State (rel 0x40000000-0x4011FFFF for 8 channels) (P 5.4.4, Fig. 6)

- Divided into (number of channels + 1) subregions of 0x20000 bytes. First (0x40000000-0x4001FFFF) "unassigned"; channel 1 at 0x40020000-0x4003FFFF; channel 8 is the ninth. Layout scales with channel count (stated).
- First byte of a channel subregion: number of time anchors (Fig. 6: 2F = 47 at 0x40020000; P text: 47 anchors for the example). Count width is "first byte" (so max 255 per P's wording; whether it is wider: unknown).
- Each "Record Index" is 20 bytes: 4-byte full-hour timestamp (Unix seconds LE) + 15 bytes recording status ("encoding the recording status for the corresponding hours"). P states "4 + 15" (19 bytes); Fig. 6 shows a 20th byte after each entry's status (9E, D7, F4: greyed, undescribed).
- Fig. 6 geometry: first Record Index begins at 0x40020014 (anchor 50 6A 27 69 = 0x69276A50 = 2025-11-26 21:00:00 exactly, status 00 00 00 00 00 00 00 00 00 00 00 00 55 15 00, trailing 9E); second begins 0x40020028 (D0 A4 30 69 = 0x6930A4D0 = 2025-12-03 21:00:00, status ... 50 55x10, trailing D7); third 0x4002003C (E0 B2 30 69 = 2025-12-03 22:00:00). Stride 20 confirmed. Bytes 0x40020001-0x40020013 are 00 except 0x40020013 = 85 (greyed, unlabelled) in the figure; i.e. the entry array starts 0x14 after the count byte (derived; P does not state this offset).
- Status byte meaning (per-hour encoding such as 0x55 = ?): unknown. Position of the 0x55 pattern is not decoded by P.
- Anchors increase in 1-hour steps (P). The anchors in the examples fall exactly on whole UTC hours when decoded as Unix seconds (derived), which is evidence the values are epoch-UTC based (see Sec. 5).

### 2.5 Fixed Value (P 5.4.5, Fig. 7)

Fig. 7 shows bytes at 0x44000000: `08 00 40 00 01 40 04 00 42 80 04 00 83 C0 04 00 / C4 00 05 00 05 41 05 00 46 81 05 00 87 C1 05 00 / C8 01 06 00 ...` then 00. P: "fixed values that remain unchanged and are unrelated to recording behavior, suggesting that they are device- or firmware-specific"; not analysed. Extent, meaning: unknown. Do not parse.

### 2.6 Video Data (rel 0x80000000 to partition end; abs = 0x80005000 onwards) (P 5.4.6, Fig. 8)

See Section 3. Per P, "Video Data is stored per channel as identified in the Video Channel List, and its length corresponds to the value specified in the Video Channel List." Chunks begin on 4 KiB boundaries (Fig. 8: 0x80000000 and 0x801E9000; derived from every Channel Index start offset). Each chunk is followed by the 20-byte End of Channel Data and a padding gap (Section 3.4).

### 2.7 What survives each deletion mode (P Sec. 6, Table 2, Fig. 9-11)

| Mode | Header | Block List / Channel List / Record State | Video Data |
|---|---|---|---|
| Format (image 21) | Video Data Offset/Next Offset reset to 0x80000000 (bytes 00 00 08 00); Available Memory = Total (0x01BB33D1); Block Group Index entries erased (zeros); disk GUID, partition GUID, GPT header CRC and partition-table CRC change | "completely removed" (Fig. 9 red) | untouched until new recording overwrites from 0x80000000 |
| Expiration (image 19) | Next offset, Available Memory updated (Fig. 11c: next 71 D7 BE 01, available 8D C5 BB 00); block-group start time moved to oldest remaining (FF 85 31 69) | entries of expired videos removed; empty groups' Block Group Index removed; later Record Indices shift forward | untouched; new data appended after existing, wraps to start when partition full |
| Overwrite (image 20) | same as expiration; Available Memory ~unchanged (Fig. 11d: 6E 8B 08 00; next 8D D7 BE 01; group start 88 AC 30 69) | same | untouched except where new data lands |

---

## 3. 20-byte Custom Header, NAL stream, delimiters (P 5.4.6, Fig. 8, Sec. 7.1, Fig. 11)

Header is written before every NAL unit (P: "a 20 byte Custom Header precedes each NAL unit"). Byte positions from Fig. 8 (header starts at 0x80000000: `02 | 80 01 00 | 80 07 | 38 04 | CD 00 00 00 | 38 CB FD 5B 86 44 06 00`) and a second header (starts 0x8001852D: `82 80 01 00 | 80 07 | 38 04 | 60 65 01 00 | E6 CE 1B 5C 86 44 06 00`).

| hdr off | Size | Endian | Type | Example | Meaning | Source | Conf. |
|---|---|---|---|---|---|---|---|
| 0 | 1 | n/a | flag byte | 0x82 (IDR), 0x02 (non-IDR) | frame type | 5.4.6 text, Fig. 8 | documented |
| 1-3 | 3 | n/a | constant | 80 01 00 | "fixed 3 byte value" (meaning unknown) | 5.4.6 | documented as fixed; meaning unknown |
| 4-5 | 2 | LE (derived) | u16 | 80 07 | width = 0x0780 = 1920 | 5.4.6 ("2 bytes each for width and height"), Fig. 8 | documented layout; endianness derived from 1920x1080 stated in P |
| 6-7 | 2 | LE (derived) | u16 | 38 04 | height = 0x0438 = 1080 | same | same |
| 8-11 | 4 | LE (derived) | u32 | CD 00 00 00 (=205); 60 65 01 00 (=0x16560 = 91,488) | "length of the NAL unit"; P text calls 0x016560 "length" of the IDR frame. Whether it includes the 5 start-code+NAL-header bytes, or all NALs of an access unit (the IDR header is followed by SPS, PPS and IDR slice NALs in Fig. 8, which sit under ONE header), is NOT stated | 5.4.6 | endianness: derived (0x16560 as P text value matches LE reading of 60 65 01 00); exact semantic: partly documented |
| 12-19 | 8 | LE (derived) | u64, Unix microseconds | 38 CB FD 5B 86 44 06 00 -> 0x000644865BFDCB38 (=1764193719929656 us = 2025-11-26 21:48:39.929656 UTC arithmetic); E6 CE 1B 5C 86 44 06 00 -> 0x000644865C1BCEE6 = 21:48:41.896678 | frame timestamp | 5.4.6 ("0x000644865C1BCEE6 ... 21:48:41.896") | documented; LE confirmed by comparing P's printed big-endian value with Fig. 8 byte order |

P never writes the word "endianness" for any individual Custom Header field; the global Partition 1 statement is little-endian, and the figure bytes agree (derived above). Timezone of the microsecond value: NOT stated (see Sec. 5).

What follows (P 5.4.6, Fig. 8): the NAL start code `00 00 00 01` then NAL header byte, e.g. `00 00 00 01 21` (non-IDR slice, nal_ref_idc 1), `00 00 00 01 27` (SPS), `00 00 00 01 28` (PPS), `00 00 00 01 25` (IDR slice). P says "6 bytes consisting of the NAL unit start code and NAL unit header" while a 4-byte start code + 1-byte header is 5 bytes (Fig. 8 shows 5; the sixth is unexplained). SPS, PPS and the IDR slice appear back-to-back after a single 0x82 header (the figure labels "NAL Type: SPS", "PPS", "IDR"): so a custom header is NOT strictly per-NAL for parameter sets (partly documented / unclear). The first frame's `CD 00 00 00` = 205 bytes with the first NAL type 0x21 follows header byte 0x02.

H.265: P tested only H.264; layout, header flag values for HEVC: unknown.

### 3.1 Delimiters and padding (P 5.4.6, 7.1)

| Item | Bytes | Position | Source | Conf. |
|---|---|---|---|---|
| End of Channel Data | 20 x 0x00 | after the last frame of each per-channel chunk. In Fig. 8: 0x801E86DC-0x801E86EF (last 4 bytes of the 0x...86D0 row + all 16 of 0x...86E0) | 5.4.6, Fig. 8, 7.1 | documented |
| Padding | "A dummy value is stored in the gap between the actual data length and the rounded data length" | from after the delimiter to the next 4 KiB-aligned chunk (Fig. 8: 0x801E86F0 .. 0x801E8FFF; next chunk starts 0x801E9000 with `02 80 01 00 ...`) | 5.4.6 | documented that it exists; the byte value is NOT stated (Fig. 8 shows 0x801E86F0 area only elided) |
| Next chunk | begins with a Custom Header | at the next 0x1000 boundary | Fig. 8 | derived |

Extraction rule used in P (Sec. 7.1/7.2): from the custom header holding the deleted timestamp "to the next delimiter" (the 20-byte 0x00 run); save as .dat; ffplay plays it (it skips the custom header); playback also works with the custom header removed.
R (constants only, R only): `ZERO_RUN_THRESHOLD = 20` (run of >=20 consecutive 0x00 ends a chunk); scan start abs 0x80005000 (rel 0x80000000); scan end abs 0x22433D6000 (160 GB image, equals the end of Partition 1 = sector 287,415,984 x 512); runs shorter than 20 are kept as data. R's README states carving was verified only qualitatively.
Risk (derived from the rule, not stated by P): a payload that legitimately contains >= 20 consecutive zero bytes would be split; encoded H.264 can contain zero runs (emulation-prevention limits them to `00 00 03` patterns inside NAL payload, so 3+ zeros in a row cannot occur in valid H.264 NAL bytes; but this note's author did not test that on a Honeywell stream and the padding byte is unspecified). Use the Channel Index length where available, delimiter only for carving.

---

## 4. Channel identification

| Location | Channel info? | Source | Conf. |
|---|---|---|---|
| Custom Header (20 B) | No channel field is described or visible in Fig. 8 (flag, constant, WxH, length, time only) | 5.4.6 | documented (absence in described fields); bytes 1-3 "fixed 80 01 00" have unknown meaning |
| Video Channel List entry byte +0x00 | 1-byte channel identifier (examples 02, 04, 05, 07) plus stream type (00 main, 20 sub) | 5.4.3, Fig. 5b | documented |
| Record State | per-channel subregion (channel n at 0x40000000 + n x 0x20000 for 1-based n, derived from text) | 5.4.4 | documented |
| Video Data | stored "per channel as identified in the Video Channel List"; a raw carve with no metadata has NO channel marker | 5.4.6, Sec. 8 ("identifying deleted content (e.g., playback duration or channel)" is future work) | documented |

Consequence: after format (Channel List erased) the channel of carved video is unknown from P alone. Whether SPS/PPS or the width/height can discriminate channels: not studied. Channel-id base (0/1) and mapping to physical port/camera name: unknown.

---

## 5. Timestamp formats

| Field | Epoch / unit | Width | Endian | UTC or local? | Example | Source | Conf. |
|---|---|---|---|---|---|---|---|
| Block Group Start Time (Header +0x44) | Unix s | u32 | LE | not stated | 0x692775A3 = "November 26, 2025, 21:48:19" | 5.4.1 | documented (value), zone unknown |
| Video Block List start time | Unix s | u32 | LE | not stated | A3 75 27 69 | 5.4.2 | documented |
| Channel Index "frame/stream start time" | Unix s | u32 | LE | not stated | B7 75 27 69 | 5.4.3 | documented |
| Record Index anchor | Unix s, full hour | u32 | LE | not stated | 50 6A 27 69 = 21:00:00 | 5.4.4, Fig. 6 | documented |
| Custom header time | Unix microseconds | u64 | LE (derived) | not stated | 0x000644865C1BCEE6 -> "21:48:41.896" | 5.4.6, 7.1-7.3 | documented |

Timezone/DST: P never states the device timezone setting, never says UTC/local, never mentions DST. Every P-quoted wall-clock string equals the UTC rendering of the epoch value (checked by arithmetic: 0x692775A3 -> 2025-11-26 21:48:19 UTC; 0x693185FF -> 2025-12-04 13:00:47 UTC; 0x000644865C3A52D5 -> 21:48:43.896 UTC; the on-screen OSD in Fig. 11a shows 2025/11/26 21:48:43). That means: either the device was set to UTC, or the authors rendered UTC; P gives no way to tell. Also all Record Index anchors decode to exact UTC hour boundaries, so the stored epochs are not shifted by a non-whole-hour offset relative to UTC (derived). Do not claim device-local time from the on-disk value without a real image and a known setting. The OSD burned in the picture (Fig. 11 screenshots) and the on-disk custom-header time agree to the second in P's four examples (derived from Fig. 11 caption values), but P does not discuss the OSD as a separate artefact.

---

## 6. Overwrite behaviour after format (P 6.1, 6.4, Table 2, 7.1)

- Formatting "modifies the GUIDs in the start sectors for both the disk and partitions", changes header and partition-table checksums, resets the Partition 1 header, removes all Block/Channel/Record indices; the NVR "recognize[s] the disk as newly connected".
- "None of the deletion methods explicitly erase video data in the Video Data region" (6.4 item 2).
- "When recording resumes after formatting-based deletion ... new video data are written from the beginning of the video data region, progressively overwriting previously stored video data in real time"; metadata rewritten from the start of each region. Hence recoverability "Medium" (Table 2), decaying with new recording; "timely recovery is critical" (7.1).
- Expiration/overwrite: metadata of oldest data removed, new data appended after the latest remaining data; wrap to the start of the video region once Partition 1 fills (6.2). Recoverability "High".
- Not quantified: P gives no percentage/size of recoverable data; "comprehensive quantitative evaluation" is future work (Sec. 8). Table 2 ratings are qualitative.
- Detection of deleted data used by P: compare per-NAL timestamps with Header Block Group start time (earlier = deleted). Not described: detecting a format event, ordering of old vs new data after wrap.

---

## 7. Corruption and consistency checks usable with only documented facts

1. Header: Video Data Offset (x0x1000) == 0x80000000 (all of P's figures); reject/flag otherwise.
2. Available Memory <= Total Allocatable Memory; Next Video Offset (x0x1000) >= 0x80000000 and < Partition 1 size.
3. After format signature (derived from P Fig. 11b): Next Offset == Video Data Offset, Available == Total, Block Group Index entries (header 0x40+) all zero => format event candidate while Video Data still non-empty.
4. Block Group Index and Block Index: reserved first 4 bytes == 0; block number 0x00-0xFF; times plausible (e.g. >= 2000-01-01, <= acquisition time + slack).
5. Channel Index: stream type in {0x00, 0x20}; start offset (x0x1000) >= 0x80000000 and 4 KiB aligned by construction; start+length within the partition; the bytes at start offset begin a Custom Header (byte0 in {0x82,0x02}, bytes1-3 == 80 01 00).
6. Chunk end consistency: 20 zero bytes exist before start+length (P: End of Channel Data); within a chunk the next header begins right after the previous NAL ends (if the length semantic in 3 is confirmed on real data, enforce length == bytes to next header).
7. Custom Header: flag 0x82 followed by SPS/PPS/IDR NAL types (0x27/0x28/0x25 in P's example), 0x02 followed by slice type 0x21 (example); width/height sane (1920x1080 in the example); microsecond time monotonically non-decreasing inside a chunk; time/1e6 within the chunk's Channel Index start time + chunk duration.
8. Header Block Group start time vs Video Data timestamps: any NAL older than the earliest Block Group start time => deleted/unindexed (P rule).
9. Record State: anchors are multiples of 3600 s, strictly +3600 per step within contiguous recording (P states 1-hour increments); count byte == number of populated anchors (P example 47).
10. GPT: standard CRC32 checks of primary vs secondary header; remember secondary header lives at sector 32 of the final 2 GB region, not at the last LBA, per P.
11. Cross-image: IDR times older than Header times, or Header time reversals, identify wrap/format (P 6.2/7.2; the Hikvision-style detection in RESEARCH.md was not tested here).

## 8. Facts needing a real image

- Exact Partition 1 start/end LBAs, partition type GUIDs, entry count; location of the primary header's alternate LBA; whether the secondary header really is at region sector 32 on all disk sizes (R/P disagree by about 2 sectors on the unallocated size).
- Machine Data: meaning of "sn private disk" and "2.2" strings, any fields beyond 0x447F, field widths, other models' strings, whether sector 34 is stable across firmware.
- Header: widths of the four fields (4 vs 8 bytes), exact 0x1000-unit interpretation, unknown bytes 0x08-0x0B of Block Group Index entries, group numbering rule, entry count/terminator, header bytes 0x20-0x3F and 0x4000+.
- Video Block List: start (0x4000 vs 0x40000) as noted; meaning of entry bytes +8..+11, +14..+15; ordering after wrap.
- Channel List: channel id base and mapping; meaning of entry bytes +12..+15; stream types other than 0x00/0x20; per-channel chunk granularity; ordering.
- Record State: 20th byte of Record Index, status-byte encoding (0x55, 0x15, 0x50), the 0x85 byte at +0x13, region beyond 0x4011FFFF for other channel counts, Fixed Value extent, "None" gap before Video Data.
- Custom Header: semantics of the 3-byte constant 80 01 00 (may vary with codec, H.265 or audio), exact length semantics (NAL vs access unit; whether it includes start code), whether SPS/PPS carry their own headers, header at 0x82 vs other flag values (audio, metadata, H.265), the "6 byte" vs 5 byte start-code statement, padding byte value.
- Timestamps: device timezone setting, UTC vs local, DST behaviour, clock changes, OSD vs metadata drift.
- Encrypted recording, H.265, multi-disk/RAID, fragmentation, other Honeywell models/firmwares, Partition 2 (ext4) contents (logs, config, user events) - none analysed.
- Fig. 11 low-resolution detail: the first header bytes at 0x80000000 appear as "02 08 01 00" in the downscaled Fig. 11 but as "02 80 01 00" in Fig. 8 and the text; treated as a render/reading artefact, rely on Fig. 8 and text but check on a real image.
