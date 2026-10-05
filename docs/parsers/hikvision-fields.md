# Hikvision DVR on-disk format: byte-level field table (research note)

Status: research only, compiled 2026-10-05. Nothing here comes from examining a real DVR image. All offsets are from published figures and text; values read off figures are my transcription of rendered hex dumps and faded/occluded bytes may be misread (flagged where relevant).

Confidence tags: **documented** = stated in text or labelled in a figure of a source; **partly documented** = value visible or implied but meaning/size/boundary not stated; **unknown** = not in any source read.

Source keys (full list at the end): **[H]** Han, Jeong, Lee 2015 (printed pages 189-199; PDF page n = printed page 188+n). **[D]** Dragonas thesis 2023, section 5.2.3 (printed pp. 65-68, 111). **[A]** theAtropos4n6/HikvisionLogAnalyzer source, used only to cross-check offsets (no licence; no code copied; facts only).

Conventions: "struct+0x.." = offset from the first byte of the structure's signature. Multi-byte integers are little-endian unless stated ([H] p.191: "The data in each field is stored by Little-endian systems").

---

## 0. Layout overview

[H] Fig. 1 / Sec. 2 (p.190): four physical sections in order: Master Sector, System Logs, Video Data Area (Data Block #1..#N), HIKBTREE 1, HIKBTREE 2 (Fig. 1 shows two HIKBTREE boxes; text p.194: "The backup HIKBTREE is located after the former one"). Backup Master Sector: [H] p.190: "The Backup Master Sector is located next to system logs and stores exactly the same data." Its exact offset is **unknown** (see section 1).

Sample numbers from [H] Fig. 2 (160 GB disk): logs 0x03D13200..0x04C55E00 (size 0xF42C00), video area starts 0x04C5E000, HIKBTREE1 0x25433BDC00 (size 0x6000), HIKBTREE2 0x25433C3C00. Gap between end of logs (0x4C55E00) and video start (0x4C5E000) is 0x8200 bytes (my arithmetic); what lives there (backup master?) is not stated: **unknown**.

---

## 1. Master Sector

Location/base discrepancy (important):
- [H] p.190: "This area starts from the offset 0x200 and the size of master sector is 256 bytes." Fig. 2 shows the dump with the signature in row 0 (struct+0x00).
- [D] Fig. 21 (p.65) shows a hex dump with absolute offsets: row 0x200 is `86 21 00 ...` (not explained anywhere) and the signature `48 49 4B 56 ...` is at **absolute 0x210**. [D] text p.65: log start at "offset 608 (0x260)", size at "616 (0x268)".
- [A] `parse_fs_info` reads a 512-byte block and indexes the signature at byte 16 of that block, version at 48, capacity at 72, log offset at 96, log size at 104, init time at 240 (hex-string indices 32, 96, 144, 192, 208, 480 divided by 2). That equals struct+0x00/0x20/0x38/0x50/0x58/0xE0 with a +0x10 base inside a 0x200-aligned block.
- Consistency: struct+0x50 + 0x210 = 0x260 and struct+0x58 + 0x210 = 0x268, matching [D]. init time at struct+0xE0 is absolute 0x2F0, still inside a 256-byte sector 0x200..0x2FF.
- Conclusion (inference, tagged): the signature is at absolute 0x210 in [D]'s images and [H]'s Fig. 2 most likely shows the dump starting at the signature. [H]'s "starts from 0x200" is then the sector start, with 0x10 bytes (observed `86 21 00..`) before the signature. Real images must confirm; a parser should search the sector for the signature rather than hard-code 0x210.

| Field | struct offset | Absolute offset (base 0x210, per [D]) | Size | Type / endian | Example value | Meaning | Source | Confidence |
|---|---|---|---|---|---|---|---|---|
| (pre-signature bytes) | n/a | 0x200..0x20F | 16 | bytes | `86 21 00 00 ...` ([D] Fig.21) | Not explained | [D] Fig.21 | unknown |
| Signature | +0x00 | 0x210 | 18 | ASCII | `48 49 4B 56 49 53 49 4F 4E 40 48 41 4E 47 5A 48 4F 55` = "HIKVISION@HANGZHOU" | File system signature | [H] p.190-191 text and Fig.2; [D] p.65 | documented |
| Padding after signature | +0x12 | 0x222 | 14 | bytes | 00 | Zeros in both samples | [H] Fig.2, [D] Fig.21 | partly documented (unlabelled) |
| Version-like string | +0x20 | 0x230 | 14 (+2 zero) | ASCII | "HIK.2011.03.08" ([H] Fig.2 and [D] Fig.21) | Unlabelled in both papers. [A] names the variable `fs_version`; that is a tool label, not a source claim about semantics | [H] Fig.2 (faded), [D] Fig.21, [A] | partly documented (value seen, meaning unknown) |
| Capacity of hard disk | +0x38 | 0x248 | 8 | u64 LE | `00 60 3D 43 25 00 00 00` = 0x25433D6000 = 160,041,885,696 ([H]); [D] sample `00 40 BE 40 25 00 00 00` = 0x2540BE4000 = 160,000,000,000 | Disk capacity, bytes (my reading of units: values match 160 GB drives; [H] text only says "capacity") | [H] p.191 + Fig.2; [D] Fig.21; [A] | documented (units inferred) |
| Unlabelled | +0x41 | 0x251 | 1 | byte | 0x82 (both [H] Fig.2 and [D] Fig.21 show `00 82 00..` in row +0x40) | Unknown | [H] Fig.2 faded, [D] Fig.21 | unknown |
| Unlabelled | +0x48 | 0x258 | 8 | u64? | `00 B0 D0 03 00 00 00 00` (0x03D0B000) in both | Unknown. It is 0x8200 below the log offset 0x03D13200 (my arithmetic, no claim) | [H] Fig.2, [D] Fig.21 | unknown |
| Offset to System Logs | +0x50 | 0x260 | 8 | u64 LE | `00 32 D1 03 00 00 00 00` = 0x03D13200 = 64,041,472 | Byte offset of log area (offset origin = disk start; [D] uses it directly on images) | [H] p.191 + Fig.2; [D] p.65, 67 | documented |
| Size of System Logs | +0x58 | 0x268 | 8 | u64 LE | `00 2C F4 00 00 00 00 00` = 0xF42C00 = 16,002,048 | Log area size in bytes | [H] p.191; [D] p.65, 67 | documented |
| Unlabelled | +0x60 | 0x270 | 8 | bytes | `01 00 00 00 00 00 00 00` | Unknown | [H] Fig.2 faded; [D] Fig.21 faded | unknown |
| Offset to Video Data Area | +0x68 | 0x278 | 8 | u64 LE | `00 E0 C5 04 00 00 00 00` = 0x04C5E000 | Byte offset of data block #1 (see section 3) | [H] p.191 + Fig.2 | documented |
| Unlabelled | +0x70 | 0x280 | 8 | bytes | `00 00 00 00 25 00 00 00` (value 0x2500000000) | Unknown | [H] Fig.2 faded; [D] Fig.21 decoded-text column shows a `%` at that position | unknown |
| Size of a data block | +0x78 | 0x288 | 8 | u64 LE | Fig.2 bytes `00 00 00 40 00 00 00 00` = 0x40000000; **text says 0x400000** | See section 7 (contradiction, not resolved) | [H] p.191 text and Fig.2; p.192 | documented but self-contradictory |
| Total number of data blocks | +0x80 | 0x290 | 4 (box covers 4 bytes) | u32 LE | `94 00 00 00` = 0x94 = 148 | Count of data blocks | [H] p.191 + Fig.2 | documented (4-byte width from figure box) |
| Offset to HIKBTREE1 | +0x88 | 0x298 | 8 | u64 LE | `00 DC 3B 43 25 00 00 00` = 0x25433BDC00 | HIKBTREE start | [H] p.191 + Fig.2 | documented |
| Size of HIKBTREE1 | +0x90 | 0x2A0 | 4 (box) | u32 LE | `00 60 00 00` = 0x6000 | HIKBTREE size | [H] Fig.2 label "Size of HIKBTREE1" | documented |
| Offset to HIKBTREE2 | +0x98 | 0x2A8 | 8 | u64 LE | `00 3C 3C 43 25 00 00 00` = 0x25433C3C00 | Backup HIKBTREE start. Equals HIKBTREE1 + 0x6000 in the sample | [H] Fig.2 label | documented (label); the 'backup' role is from p.194 text |
| Size of HIKBTREE2 | +0xA0 | 0x2B0 | 4 (box) | u32 LE | `00 60 00 00` = 0x6000 | | [H] Fig.2 label | documented |
| Unlabelled region | +0xA4..+0xDF | 0x2B4..0x2EF | 60 | bytes | faded values including some ending `3C 43 25`, a `60`, `01`; partly hidden under labels in the figure | Unknown; may be further offsets/sizes. I could not read these reliably | [H] Fig.2 | unknown |
| Time of system initialization | +0xE0 | 0x2F0 | 4 | u32 LE Unix seconds | bytes `37 22 77 54` = LE 0x54772237 = 1417093687 = 2014-11-27 13:08:07 if read as UTC. **[H] text prints the value as "0x37227754"**, which is the file-order byte string, not the LE value (read as an integer it would be 1999-04-25). | Time of last initialization | [H] p.191 + Fig.2; [A] reads 4 bytes LE | documented (value/order caveat) |
| Rest of sector | +0xE4..+0xEF (+ to 0xFF) | 0x2F4..0x2FF | | | zeros in Fig.2 | | [H] Fig.2 | unknown |
| Backup Master Sector location | n/a | n/a | n/a | n/a | n/a | "located next to system logs", "exactly the same data" | [H] p.190 | partly documented; offset **unknown** |

Notes:
- [D] p.67: across his six devices (5 XVR + 1 NVR) "the starting offset was always 64,041,472 (0x03D13200)" and size "16,002,048 (0xF42C00)". [D] also states the NVR's logs "began at the offset 41,472 (0xA200) regardless of its Master Sector suggesting otherwise", no explanation found. So the Master Sector log pointer is not always reliable; [A] also tries 41472 explicitly.
- [D] says nothing about data block size/count/HIKBTREE pointers; those come only from [H].
- Real image evidence needed: whether the 256 B sector is repeated verbatim at the backup location; meaning of unlabelled bytes; whether 0x210 base holds on other firmware.

---

## 2. System log area and RATS records

Log area: starts at Master Sector log offset (above). [D] p.66: "The first 2048 bytes of the log records' storage area were populated with hex values that could not be deciphered" (some resemble Unix-seconds dates); "At the end of the 2048 bytes, the actual log records began." So first RATS expected at log offset + 0x800 (statement from [D] for his images; unknown for [H]'s DVR). [H] does not mention the 2048 bytes.

Record (offsets from the 'R' of RATS):

| Field | Offset | Size | Type / endian | Example | Meaning | Source | Confidence |
|---|---|---|---|---|---|---|---|
| Signature | +0x00 | 4 | ASCII | `52 41 54 53` "RATS" | Record start | [H] p.192 + Fig.3; [D] p.66, Fig.23 | documented |
| Header variant bytes | +0x04 | 4 | bytes | [H]: `01 00 00 00`; [D]: `14 00 00 00` ("consistent in all images that were examined") | **Meaning not stated by either source.** [D]: "previous studies refer to this value as being 0x01 00 00 00 instead". Whether it is a version, a length, or flags is **unknown**. (0x14 = 20, 0x01 = 1; do not assume a length.) [A] accepts a record if the first byte after RATS is 0x14 or 0x01 and ignores the other three | [H], [D], [A] | documented (values); unknown (meaning) |
| Created time | +0x08 | 4 | u32 LE Unix seconds | `89 7C 73 63` = 0x63737C89; [D] Fig.24 labels it "2022-11-15 11:48:25 (CCTV system's Timezone)". Decoding the integer as UTC gives exactly 11:48:25, i.e. the raw value is local wall time in Unix-second form | Log creation time. Timezone: see section 6 | [H] Fig.3 ("Created time"); [D] p.66, Fig.24 | documented |
| Major type | +0x0C | 2 | u16 LE | `03 00` = Operation | [H] calls this field "Type" (Table 1: Alarm 0x01, Exception 0x02, Operation 0x03, Information 0x04); [D] calls it "Major Type" | [H] Fig.3, Table 1 p.192; [D] p.66, Fig.23 | documented |
| Minor type | +0x0E | 2 | u16 LE | `70 00` = Remote: Login | [H] has no separate field (calls what follows the type "description"); [D] splits it: "another 2 bytes for the 'Minor Type'" | [D] p.66, Fig.23-24 | documented ([D]); [H] unspecified |
| Details | +0x10 | variable | per major/minor | see below | Content depends on the major/minor combination | [D] p.66-68; [H] "Description" | partly documented |

Reconciliation of [H] vs [D]: [H] Fig.3 shows Type at C-D and "Description" starting at +0x0E; [D] shows Major at +0x0C, Minor at +0x0E, Details from +0x10. They agree on the first 14 bytes; [D]'s minor type is the first 2 bytes of [H]'s "description".

Record length: **unknown**. Neither source identifies a length field. [H] p.192: the description field "is a variable for each system log, the size of this field is also different according to each type". [A] splits the log area on the RATS byte string, so each record ends at the next RATS (or end of area). That is a tool heuristic, not a documented structure; [D] p.69 reports 19,063 `RATS` hits on one image with none a false positive after manual review, while warning "there might be false positives in other scenarios".

Details structure documented ([D] p.67, Fig.24): for Major=Operation, "The first 16 bytes of the 'Details' field were used for storing the user's name" (record +0x10..+0x1F; example `61 64 6D 69 6E 00...` "admin") and "the next 4 bytes were used for saving the user's IP address" (record +0x20..+0x23; example `C0 A8 0A 64` = 192.168.10.100, byte order = dotted order). Fig.24 shows a further nonzero byte `78` at record +0x34, unexplained. All other Details layouts: [D] p.68: "the 'Details' field for many of the mapped log types was not fully determined"; [A] contains more per-type offsets (partly parsed) that I did not transcribe.

Major/Minor values mapped in [D] Appendix B (printed p.111; 32 types). Appendix B writes the bytes in file order (e.g. "0x7000" for file bytes `70 00`, consistent with Fig.24's `70 00`), so as integers they are LE 0x0070 etc.; [H] Table 1 uses the numeric form 0x01..0x04.

| Major (bytes) | Minor (bytes) : name |
|---|---|
| 03 00 Operation | 41 00 Power On; 42 00 Local: Shutdown; 43 00 Local: Abnormal Shutdown; 50 00 Local: Login; 51 00 Local: Logout; 52 00 Local: Configure Parameters; 5C 00 Local: Initialize HDD; 6E 00 HDD Detect; 70 00 Remote: Login; 71 00 Remote: Logout; 76 00 Remote: Get Parameters; 77 00 Remote: Configure Parameters; 78 00 Remote: Get Working Status; 79 00 Remote: Alarm Arming; 7A 00 Remote: Alarm Disarming; 80 00 Remote: Playback by Time; 82 00 Remote: Initialize HDD; 86 00 Remote: Export Config File |
| 04 00 Information | A0 00 Time Sync.; A1 00 HDD Information; A2 00 S.M.A.R.T. Information; A3 00 Start Record; A4 00 Stop Record; AA 00 System Running State |
| 01 00 Alarm | 03 00 Start Motion Detection; 04 00 Stop Motion Detection; 05 00 Start Video Tampering; 06 00 Stop Video Tampering |
| 02 00 Exception | 22 00 Illegal Login; 24 00 HDD Error; 27 00 Network Disconnected; 54 00 Hik-Connect Offline Exception |

Confidence: type mapping documented ([D], one lab set, 6 devices); Details layouts mostly unknown. Corroboration: [A] maps the same four major values (0100..0400) and byte-order.

Real image evidence needed: meaning of +0x04 variants (compare 01 vs 14 across firmware), per-record length rule, the 2048-byte preamble, whether records are 4-byte aligned, behaviour at area wrap (circular?), how the log area is filled/zeroed after initialization.

---

## 3. Video Data Area and data block (IDR table)

[H] p.192-193 text: "All data blocks and sizes of video data areas are defined in the Master Sector." Data block #1 starts at the Master Sector video-area offset (0x04C5E000 in the sample); block size is the Master Sector field (see section 7). Entry-level data block offsets in HIKBTREE are consistent with absolute disk offsets (sample entry offsets end in ...C5E000, same low bits as the video-area offset), but [H] does not state the base: **partly documented**.

Block structure ([H] p.192-193, Fig.4): "A data block is divided into Video data and IDR table, the former occupies most of the data block and the latter is at the back of a data block". Fig.4 shows Video data on top and, at the bottom, "IDR table M", "IDR table M-1", ..., "IDR table 1", each box starting with `4F464E49`.

"Each record of the IDR table is recorded in the direction to decrease offset from the end of a data block. It starts with a signature 'OFNI (0x4F 46 4E 49)' and is fixed to 56 bytes for each record."

| Item | Value | Source | Confidence |
|---|---|---|---|
| Table position | at the end of the data block | [H] p.192-193 | documented |
| Record signature | `4F 46 4E 49` ("OFNI") at record start | [H] p.193, Fig.4 | documented |
| Record size | 56 bytes, fixed | [H] p.193 | documented |
| Record order | first record (IDR table 1) is at the block end; later records are at progressively lower offsets. Implied position of record k (1-based) start = block_end - 56*k (my derivation from the text plus Fig.4; not stated as a formula) | [H] p.193, Fig.4 | partly documented |
| Per-record content | "index, channel, and timestamp of an IDR picture" | [H] p.193 | documented (list only) |
| Field offsets inside the 56-byte record (index, channel, timestamp, frame position, reserved) | not given. [H] has no figure of a record. Timestamp format (width, endianness, epoch) **unknown** | [H] | unknown |
| Relation to HIKBTREE | "Through the comparison of the IDR table's timestamps as it stored in data block entries, it can be verified the time of the IDR pictures and channel." | [H] p.193 | documented |
| Mixed content in one block | If recording was paused or the channel changed, other video data is stored in the same block regardless; different data is separated by comparing IDR-table timestamps with the entry times | [H] p.193, p.195 | documented |
| Whether the first byte of video data coincides with the block start | not stated | | unknown |

Real image evidence needed: hex dump of a full IDR record to assign offsets for index/channel/timestamp; whether the table region is pre-zeroed or 0xFF where unused; the position of the block's last used byte; what separates the video region from the table region.

---

## 4. HIKBTREE

[H] p.194 text: "The HIKBTREE consists of a number of sections including a header, page list, page number, and footer." "The backup HIKBTREE is located after the former one." Master Sector gives two offsets and sizes (section 1). In the sample, offsets inside the HIKBTREE are absolute disk offsets (header "offset to footer" 0x25433C2C00 lies inside HIKBTREE1 = 0x25433BDC00..0x25433C3C00); [H] does not state that explicitly: partly documented.

Sample geometry (my arithmetic on [H] Fig.2 and Fig.5; the HIKBTREE1 base is 0x25433BDC00): header at +0x0000, page list at +0x1000 (0x25433BEC00), page #1 at +0x2000 (0x25433BFC00), example "page #X" 0x25433C1C00 = +0x4000, footer 0x25433C2C00 = +0x5000, HIKBTREE2 = +0x6000 (matches Master Sector). Observation, unexplained: page list says total pages = 2, but the geometry has room for three 4 KB pages (+0x2000, +0x3000, +0x4000) before the footer, and the "page #X" example points at the third slot. The paper's samples may come from different moments; **unknown**.

### 4.1 Header (struct = HIKBTREE start) ([H] Fig.5(a), p.194)

| Field | Offset | Size | Type | Example | Meaning | Confidence |
|---|---|---|---|---|---|---|
| Signature | +0x00 | 8 | ASCII | `48 49 4B 42 54 52 45 45` "HIKBTREE" | | documented |
| Zeros | +0x08 | 8 | | 00 | | partly documented |
| Version-like string (unlabelled, faded) | +0x10 | 14 | ASCII | "HIK.2010.11.09" | unknown | partly documented |
| Unlabelled | +0x24 / +0x28 | 4 / 4 | u32 | faded 0x10 / 0x02 | unknown | unknown |
| Created time | +0x2C | 4 | u32 LE Unix s | `3B 22 77 54` = 0x5477223B = 2014-11-27 13:08:11 UTC (4 s after the Master Sector init time in the same sample) | Header creation time | documented (label); timezone see section 6 |
| Offset to Footer | +0x30 | 8 | u64 LE | `00 2C 3C 43 25 00 00 00` = 0x25433C2C00 | | documented |
| Duplicate of footer offset (faded, unlabelled) | +0x38 | 8 | | same bytes | unknown | unknown |
| Offset to Page List | +0x40 | 8 | u64 LE | `00 EC 3B 43 25..` = 0x25433BEC00 | | documented |
| Offset to Page #1 | +0x48 | 8 | u64 LE | `00 FC 3B 43 25..` = 0x25433BFC00 | | documented |
| Faded values at +0x50 (partly hidden) and +0x58 (`94 00..`, equal to the block count 0x94) | | | | | unknown | unknown |

### 4.2 Page list ([H] Fig.5(b))

| Field | Offset (from page list start) | Size | Example | Confidence |
|---|---|---|---|---|
| Total number of pages | +0x00 | 4 | `02 00 00 00` | documented |
| Unlabelled | +0x04 | 4 | faded `C0 00 00 00` | unknown |
| Offset to Page #1 | +0x08 | 8 | 0x25433BFC00 | documented |
| Offset to Page #X (further entries) | stride unknown (figure elides rows; the example row shows 8 bytes `00 1C 3C 43 25 00 00 00` followed by 8 zero bytes, so the stride could be 8 or 16) | 8 | 0x25433C1C00 | partly documented |
| Following the first page offset in the figure: "Offset to the 1st data block in page #X" `00 E0 C5 04 10 00 00 00` (= 0x1004C5E000), channel byte `02`, times `13 04 7D 54` / `10 61 7D 54` (0x547D0413 / 0x547D6110) | | | | partly documented (figure caption text hard to align with entry layout; treat as unverified) |

[H] p.194: "The Page list contains a total number of pages, offset to each page, which have information for the connection between video data and metadata". Page size: 4 KB. "Every page contains an offset to the next page ... if the page is the last page, that field is written by '0xFF' hexadecimal values." **Where in the page this next-page field sits is not shown: unknown.**

### 4.3 Footer ([H] Fig.5(c), p.194)

| Field | Offset | Size | Example | Confidence |
|---|---|---|---|---|
| Offset to the last page | +0x00 | 8 | `00 1C 3C 43 25 00 00 00` = 0x25433C1C00 | documented |
| Fill | +0x08 | 8 | `FF FF FF FF FF FF FF FF` | partly documented |

"The Footer is located in the last of the HIKBTREE and contains an offset to the last page."

### 4.4 Data block entry (48 bytes in the figure) ([H] Fig.6, p.194-195)

Fig.6(B) draws an entry as three 16-byte rows; Fig.6(a) shows three consecutive 48-byte entries, so the stride between entries appears to be 48 bytes. The paper never states "48"; a page of 4096 bytes is not a multiple of 48 (85.33), so a page header or padding must exist: **its size and the offset of the first entry within the page are unknown**.

| Field | Offset in entry | Size | Example(s) from Fig.6(a) | Meaning | Confidence |
|---|---|---|---|---|---|
| Unlabelled (white cells in Fig.6B) | +0x00 | 8 | `FF` x8 in all three entries | Unknown (could be a link/next field; not stated) | unknown |
| Existence of video data | +0x08 | 8 (cells yellow, 8 bytes) | `00` x8 (entries 1 and 2), `FF` x8 (entry 3) | [H] p.194: "0x00 hexadecimal values if the data block becomes full of video data or 0xFF ... under the condition that the data block has no video data nor recording" | documented |
| Unlabelled | +0x10 | 1 | `00` | | unknown |
| Channel ("Ch.") | +0x11 | 1 | `01`, `02`, `FF` (no-video entry; entry-3 bytes +0x10..+0x17 all FF) | Camera number assigned by the DVR; "0x01 means camera #1" | documented |
| Unlabelled | +0x12 | 6 | `00` | | unknown |
| Start/End time of record | +0x18 | 8 | entry 1: `7E 23 77 54` `37 74 77 54` (0x5477237E = 2014-11-27 13:13:34 UTC; 0x54777437 = 2014-11-27 18:57:59 UTC); entries 2 and 3: `FF FF FF 7F 00 00 00 00` | [H] p.195: "identify the start and end of the UNIX time records in UTC only when the data block is full of video data, otherwise 0xFF FF FF 7F 00 00 00 00". The split into start (first 4 bytes) then end (last 4) is my reading of the sample (first word < second word); the paper does not state the order | partly documented (order inferred) |
| Offset of the data block | +0x20 | 8 | `00 E0 C5 C4 00..` = 0xC4C5E000; `00 E0 C5 C4 01 00..` = 0x1C4C5E000; `00 E0 C5 C4 02..` = 0x2C4C5E000 | Disk offset of the data block; "In general, different data block entries have different values ... sometimes the same ... the DVR had been paused or channel had been changed during recording" | documented |
| Unknown (figure label) | +0x28 | 8 | faded `10 00..`, `20 00 00 00 02 00 00 00`, `20 00..` | [H] Fig.6B labels it "unknown" | unknown (documented as unknown) |

Sentinel `FF FF FF 7F 00 00 00 00`: as two LE u32 it is start=0x7FFFFFFF (=2038-01-19, i.e. max signed 32-bit time) and end=0. The paper only calls it the "not full" value; the numeric reading is mine.

Contradiction to flag (not resolved): Fig.6(a) labels the entry that has real times and existence 00 as "Recording", and the entry with the sentinel and existence 00 as "Recorded". The text says real times are written only when the block is full. The labelled "Recorded" entry has the sentinel; so either the labels or the text describe states differently from what a parser would assume. Real image evidence needed.

Overwrite behaviour ([H] p.197): "'Channel' is updated as the present channel and the 'Start/End time of record' is changed to 0xFF FF FF 7F 00 00 00 00" (existence flag after overwrite: not stated). Initialization: "initialization of the HIKBTREE" (p.197).

---

## 5. Video frame/NAL layout inside blocks

[H] p.192-193, Table 2, Fig.4: "Video data is encoded to H.264, so each frame is stored in a NAL ... Each frame can be distinguished by a 1 byte NAL header (Table 2), which is used in combination with 4 bytes sequence '0x00 00 00 01'." H.265: **not described**.

| Element | Bytes | Source | Confidence |
|---|---|---|---|
| NAL start | `00 00 00 01` + 1-byte NAL header | [H] p.192 | documented |
| NAL headers observed (Table 2) | SEI 0x06, AUD 0x09, non-IDR 0x61, IDR 0x65, SPS 0x67, PPS 0x68 | [H] Table 2 p.193 | documented |
| Picture index header | "In front of the NAL unit, the index of a picture is stored with one byte header '0xBA' or '0xBC', which is also used as a combination with three bytes sequence '0x00 00 01'." i.e. `00 00 01 BA` or `00 00 01 BC` | [H] p.193 | documented (form); payload unknown |
| Sequence in an IDR group (Fig.4 right) | `000001 BA ...`, `000001 BC ...`, `00000001 09 10 ...` (AUD), `00000001 67` SPS, `00000001 68` PPS, `00000001 06` SEI, `00000001 65` IDR | [H] Fig.4 | documented (as drawn) |
| Sequence in a non-IDR group (Fig.4) | `000001 BA ...`, `00000001 09 30 ...`, `00000001 61` (non-IDR) repeated, then another IDR group | [H] Fig.4 | documented (as drawn) |
| Bytes following BA/BC (length, content, index value, whether tied to a timestamp) | not given | | unknown |
| AUD payload byte `10` (IDR group) vs `30` (non-IDR group) | shown in Fig.4, not discussed | [H] Fig.4 | partly documented |
| Effect | Generic players show screen noise because of these extra headers unless 'player.exe' from the DVR is used | [H] p.193 | documented |

Unverified observation, not from a source: `00 00 01 BA` and `00 00 01 BC` coincide with MPEG program-stream start codes (pack header, program stream map). No source in this note says Hikvision uses MPEG-PS here; treat as a hypothesis to test on a real image.

Real image evidence needed: byte length and content after BA/BC; whether every frame has one; audio and H.265 framing; how a frame's end is found (next start code vs length); where per-frame timestamps live (if only in the IDR table).

---

## 6. Timestamp formats per structure

| Structure | Format | Endianness | Timezone statement | Source |
|---|---|---|---|---|
| Master Sector init time | u32 Unix seconds | LE (4 bytes; text value order caveat in section 1) | [H] p.191: "the last system initializes the UNIX time in the UTC" | [H] |
| HIKBTREE header created time | u32 Unix seconds (assumed same as other fields) | LE | not stated | [H] Fig.5 label only |
| HIKBTREE data block entry start/end | u32 pair, Unix seconds | LE | [H] p.195: "UNIX time records in UTC" | [H] |
| RATS record created time | u32 Unix seconds | LE | see conflict below | [H] Fig.3; [D] p.66 |
| IDR table timestamp | **unknown** (format, width, tz) | | | [H] only says "timestamp" |

Han vs Dragonas conflict, quoted:
- [H] p.191 (Master Sector init time): "the last system initializes the UNIX time in the UTC" and p.195 (HIKBTREE entries): "the start and end of the UNIX time records in UTC". [H] gives no timezone statement for the log "Created time" (p.192: "The value of the Created time stores the UNIX time, when a system log is generated").
- [D] p.66 (log records): "the 'Time' value gets stored in the local time zone that the CCTV system was set and not in Coordinated Universal Time (UTC), regardless of its 'UNIX seconds' format. An investigator should always remember this peculiarity. Neither previous studies nor the research conducted in this work could determine whether or not the time zone offset was stored within the HIKVISION file system." [D] Fig.24 labels the decoded log time "(CCTV system's Timezone)".
- Scope: the two sources make claims about different structures (init/HIKBTREE vs log), so they are not strictly contradictory, but [H] also does not say how it established "UTC" and [D] only addresses logs. Whether HIKBTREE and Master Sector times are truly UTC on [D]'s newer devices is untested.
- [A] has a code comment (paraphrased) saying the log date is stored in UTC and only the exported text logs are in the configured timezone, and prints the Master Sector init time labelled UTC. That contradicts [D]'s thesis text, by the same author, and is unexplained. A tool comment is weaker evidence than the thesis text.
- DST handling: not documented anywhere read. A local-time-encoded Unix value cannot disambiguate the repeated hour at a DST fall-back.
- Real image evidence needed: a DVR with a known non-UTC timezone and known DST rule, with timezone and clock changes recorded, then compare RATS time, HIKBTREE times, IDR times, and the burned-in OSD for the same event.

---

## 7. Data block size contradiction (not resolved)

Passage A, [H] Sec. 2.1 "Master Sector", printed p.191 (PDF page 3), verbatim: "the capacity of a hard disk (0x25433D6000), offset and size of the system logs (0x3D13200 and 0xF42C00), offset to the video data area (0x4C5E000), size of a data block (0x400000), total number of data blocks (0x94), offset of the HIKBTREE (0x25433BDC00), size of the HIKBTREE (0x6000), time of system initialization (0x37227754), and others."

Passage B, [H] Sec. 2.3 "Video Data Area", printed p.192 (PDF page 4), verbatim: "The size of one data block is generally 1 GB (0x40000000bytes)."

Additional evidence in the same paper: Fig. 2 (p.191) shows the "Size of a data block" field as bytes `00 00 00 40 00 00 00 00`, which as u64 LE is 0x40000000 (as printed, 0x400000 would be `00 00 40 00 ...`). [D]'s Fig. 21 (p.65) decoded-text column at absolute 0x280 row appears consistent with a 0x40 byte at 0x28B but the hex there is faded/occluded; [D] does not discuss the field. [A] does not read this field.

Implications for offsets (arithmetic only, using [H]'s own sample numbers):
- If block size = 0x400000 (4,194,304 B): block n starts at 0x04C5E000 + n*0x400000. 0x94 (148) blocks would cover 620,756,992 B, ending at about 700,833,792, far below HIKBTREE1 (0x25433BDC00 = 160,041,786,368) on a 160 GB disk, leaving about 159.3 GB unaccounted. The Fig.6 sample block offsets 0xC4C5E000, 0x1C4C5E000, 0x2C4C5E000 would be block indexes 768, 1792, 2816 (>148); the page list example 0x1004C5E000 would be index 262,144.
- If block size = 0x40000000 (1 GiB): block n starts at 0x04C5E000 + n*0x40000000; 148 blocks end at 158,993,866,752, which is 1,047,919,616 B (less than one more block) below HIKBTREE1. The Fig.6 sample offsets would be block indexes 3, 7, 11 and the page list example index 64. [H] states no reason for this.
- A parser must read the field from the Master Sector and sanity-check against (HIKBTREE offset - video offset) / count and against HIKBTREE entry offsets, not hard-code either. Real image evidence needed: a Master Sector plus HIKBTREE entries from a real disk (any size), and the actual distance between consecutive IDR-table headers or block boundaries.

---

## Corruption and consistency checks a parser can apply using only documented facts

1. Signature `HIKVISION@HANGZHOU` present in the 0x200 sector (search the sector; base 0x210 in [D]'s images). Reject otherwise; also check at the backup location only once known.
2. Master Sector log offset + log size must lie within capacity; video-area offset >= log offset + log size; HIKBTREE1 offset >= video-area offset; HIKBTREE2 offset >= HIKBTREE1 offset + size (sample: equality). [H] Fig.2.
3. Capacity must be >= HIKBTREE2 offset + size (sample: 0x25433C3C00 + 0x6000 < 0x25433D6000).
4. (HIKBTREE1 offset - video offset) should be >= block size * block count (sample passes for 1 GiB blocks; see section 7 for the other reading).
5. HIKBTREE signature `HIKBTREE` at both copies; header's footer/page-list/page-1 offsets within the HIKBTREE range; footer's last-page offset within range; page size 4 KB.
6. Page list total pages vs. page offsets present (sample shows an unexplained mismatch, so treat as a warning not a hard error).
7. Entry existence flag 0x00 or 0xFF; if 0xFF the entry should show channel 0xFF and the sentinel; start/end of real entries should satisfy start <= end.
8. Entry data block offsets should be >= video offset and equal to video offset + n*block_size for integer n < block count (check for both block-size readings and report which one holds).
9. Time-reversal tests from [H] p.197-198: IDR times earlier than HIKBTREE entry times for the same block implies the disk wrapped; times earlier than the Master Sector init time imply re-initialization. Report as indicators only.
10. RATS record: signature, a plausible time (flag values outside the disk's life), major in {1,2,3,4}, record boundaries only from the next RATS (no documented length). Note log area preamble of 2048 bytes in [D].
11. IDR table: each record begins with `OFNI`, stride 56, walking downward from the block end; stop at the first non-OFNI record.
12. NAL stream: start codes `00 00 00 01`, NAL header in {06,09,61,65,67,68}; `00 00 01 BA/BC` prefixes are expected and not corruption.
13. Treat the 0xFF-filled "next page" field as the last-page indicator only once its position is known.

## Facts needing a real image

- Base of the Master Sector (0x200 vs 0x210) and the first 16 bytes `86 21 ...`; backup Master Sector offset and the 0x8200-byte gap after the logs; all unlabelled Master Sector bytes (+0x41, +0x48, +0x60, +0x70, +0xA4..+0xDF).
- Real data block size, and whether it varies by disk size/firmware (section 7).
- Meaning of RATS bytes +0x04..+0x07 (01 vs 14), record length rule, 2048-byte log preamble, NVR logs at 0xA200, per-type Details layouts.
- IDR record (56 B) field layout and timestamp format; exact tail position within the block.
- HIKBTREE: page header size, first-entry offset, entry stride (48?), position of next-page field, page-list stride, unlabelled entry bytes (+0x00, +0x28), the "Recording/Recorded" semantics, whether times are written only on full blocks, total-pages mismatch.
- Whether all offsets are absolute disk offsets or relative to the video area/partition.
- BA/BC header payload; H.265 framing; audio.
- Timezone/DST for each timestamp field.
- Whether newer firmware (post-2015, H.265 recorders) keeps the same signatures and layouts ([H] used one DS-7204HVI-SV with a 160 GB Seagate; [D] used five XVRs and one NVR).

---

## Sources (access date 2026-10-05)

| Key | Source | URL | Read |
|---|---|---|---|
| [H] | Han, Jeong, Lee, "Analysis of the HIKVISION DVR File System", ICDF2C 2015, LNICST 157, pp.189-199, DOI 10.1007/978-3-319-25512-5_13 | https://eudl.eu/pdf/10.1007/978-3-319-25512-5_13 | Fully read (all 14 PDF pages incl. text extraction; figures 1-6, 8, 9 viewed as images; Fig.7 procedure flowchart not viewed) |
| [D] | Dragonas, E., doctoral thesis "IoT forensics", Univ. of Piraeus 2023 (DOI 10.26267/unipi_dione/3228) | https://dione.lib.unipi.gr/xmlui/bitstream/handle/unipi/15806/Dragonas_de180.pdf | Partly read: Section 5.2.3 (pp.64-70, Figs. 21, 23, 24) and Appendix B (p.111) read; other chapters not read |
| [A] | theAtropos4n6/HikvisionLogAnalyzer (README; scripts/carving_utils.py `carved_logfiles`, `parse_fs_info`, `parse_log_data`, `convert_date`; no licence per RESEARCH.md S10) | https://github.com/theAtropos4n6/HikvisionLogAnalyzer | Partly read; used only for offset cross-checks, no code copied; main script and parsing_logfile.py and per-type Details parsers not transcribed |
| Context | /Users/shikhardixit/Desktop/Nirikshan/docs/RESEARCH.md sections 3.1, 10 | local | Read for source index only |
| Not accessed | Dragonas 2023 JFS paper (DFRWS PDF returned 403 per RESEARCH.md S3); Yang 2015; Sandeepa 2018 | | not read |

Reading caveat: hex values for faded bytes in figures were transcribed from rendered images and could contain errors; values marked as labelled in a figure are higher confidence.
