# Honeywell structured parser

Code: `backend/app/vendors/honeywell_fs.py` (`HoneywellFsParser`, subclass of the identification
parser). Synthetic layout: `backend/app/validation/layouts_honeywell.py`. Tests:
`backend/tests/test_honeywell_parser.py`. Byte-level source of truth: `docs/parsers/honeywell-fields.md`
(the "field doc"), which records Yoon and Hwang, arXiv:2605.07430. Tier stays **B**.

## Scope and limits

- ONE model (HN350802xx per the paper's screenshot and bytes), 8 channels, H.264 only. Nothing is
  verified on a second model or firmware.
- H.265: the header layout is unknown. Candidates whose NAL header byte is not an H.264 type are
  counted and reported in a warning; they are not parsed and no clip is exported for them.
- Not parsed (the paper is silent or did not analyse them): Protective MBR, the secondary GPT
  (at sector 32 of the final 2 GB region per the paper, field doc 1.5), Partition 2 (ext4), Fixed
  Value, the gap before Video Data, Record State status bytes, header bytes 0x20-0x3F and 0x4000+,
  audio/metadata frames.
- The paper's public tools repository has **no licence**. Nothing was fetched or copied; the parser
  is written from the facts recorded in the field doc only, and constants that only that
  repository showed are not used.
- **Circular check, not validation.** The synthetic layout the tests and the validation scenarios
  use is built from the same field doc as the parser. Passing them shows the parser matches our
  reading of the paper and survives corruption; it does not show the parser works on a real
  device image. No real Honeywell image has been examined.

## What is parsed, inferred, unknown

| Item | Status | Basis |
|---|---|---|
| Device ID (0x4440) and model (0x4468) strings in sector 34 | parsed | field doc 1.3 |
| The two unlabelled strings at 0x4400 and 0x4420 | unknown (value shown, not interpreted) | 1.3 |
| GPT header, entry array, CRC32s, Partition 1 first/last LBA | inferred | standard UEFI GPT; the paper prints no GPT bytes (1.2). First LBA is compared with the documented 40 |
| Partition 1 header: Video Data Offset, Next Video Offset, Available/Total memory | inferred | documented positions and values; the 4 KiB unit is the field doc's DERIVED reading (2.0/2.1) |
| Block Group Index: start time (+4, u32 LE), group number (+0x0C) | parsed | 2.1; bytes +0..3, +8..11, +0x0D..0x0F not reported |
| Video Block List: reserved, time, block and group numbers | parsed | 2.2; +8..11 and +14..15 unknown; list start partly documented |
| Channel Index: channel id, stream type | parsed values; the mapping chunk to entry is inferred | 2.3; start/length use the derived 4 KiB unit; +12..15 unknown; id base and camera mapping not stated |
| Record State: count byte and time anchors | inferred | 2.4; anchor array offset 0x14 and 1-based numbering are derived; status bytes unknown |
| Custom header: flag byte (0x82/0x02), u64 LE microsecond time | parsed | 3 |
| Custom header: `80 01 00` | present and checked; its meaning is **unknown** | 3 |
| Custom header: width, height, length | layout parsed; tagged inferred (endianness derived; length semantic not stated) | 3 |
| 20-zero-byte end-of-channel delimiter | parsed | 3.1; zeroed/overwritten data is indistinguishable from it |
| Padding value after the delimiter | unknown (observed values listed only) | 3.1 |
| Clip boundaries (key frame start, time continuity, delimiter) | inferred | heuristic; option `max_time_gap_seconds` |
| Channel of a clip | inferred from a surviving Channel Index entry, else `None` | the header has no channel field (4) |
| Timezone | unknown | 5 |
| Checksums | none documented, none verified (only the standard GPT CRC32s are checked) | 7 |

## Clips

A clip starts at a 0x82 frame, continues while each header validates (flag, `80 01 00`, start code
at +20, plausible resolution/length/time, H.264 NAL type) and its length lands exactly on the next
header, the 20-zero delimiter or the image end, and the payload holds no run of 20 zero bytes. It
splits on a time reversal, a forward jump over `max_time_gap_seconds`, a resolution change, the
delimiter, or an invalid next header. Extents are the NAL bytes after each 20-byte header; headers
are excluded. Non-key frames with no preceding 0x82 frame become orphans. A frame count is the
number of custom headers (SPS/PPS/IDR sit under one 0x82 header in the paper's Fig. 8). If no
consistent chain is found the result is `fallback` and the generic carver stands alone.

Timestamps are raw: the u64 value, its byte offset, format `unix microseconds (u64 LE)`, a plain
epoch-arithmetic decode with no zone suffix and `tz_basis = "not assumed"`. Option
`time_basis_label` (`unspecified` default, `utc`, `local`) only changes the `tz_basis` text to
"<label> (examiner label via option; source silent)". The paper never states UTC or local; the
field doc notes only that every wall-clock string quoted in the paper equals the UTC rendering of
the stored value, which cannot tell a UTC-set device from authors who rendered UTC.

## Options

`time_basis_label`, `max_time_gap_seconds` (5.0), `max_frame_bytes` (16 MiB), `ts_plausible_min_s`,
`ts_plausible_max_s` (2000..2100), `min_clip_frames` (1), `max_frames` (5,000,000), `max_clips`
(100,000), `max_index_entries` (4096), `record_state_channels` (8), `video_scan` (`auto`, or
`whole_image`). `auto` scans from the Video Data Offset (abs 0x80005000) when the header validates
and lies inside the image, otherwise the whole image. Memory is bounded: structures are read at
their offsets, video is scanned in 1 MiB windows and one frame (at most `max_frame_bytes`) is
read at a time; list caps are reported as warnings.

## Paper inconsistencies and how they are handled

| Inconsistency (field doc) | Handling |
|---|---|
| Device "HN35080200" in text vs "HN350802xx" on disk and in the UI (1.3) | model string reported as read; no match on the 8-digit form |
| Video Block List start 0x40000 (text) vs Fig. 5a labels 0x4000 (2.0) | 0x40000 used (text and Fig. 2 agree); tagged partly documented; real-image check needed |
| "0x08000000" in text vs 00 00 08 00 x 0x1000 = 0x80000000 (2.0) | 0x80000000 used (matches Fig. 8) |
| "frame length" really the whole chunk length (2.3) | called chunk length; never treated as one frame |
| Header is "per NAL" but SPS/PPS/IDR share one 0x82 header (3) | headers treated per access unit; the length check is neutral to whether SPS/PPS carry own headers |
| "6 bytes" of start code and NAL header vs 5 in Fig. 8 (3) | 5 bytes (00 00 00 01 + NAL header) assumed; the sixth is unexplained |
| Secondary GPT at sector 32 of a 2 GB region, not the last LBA (1.5) | not parsed; primary `alternate_lba` is reported but unused |
| Unallocated size differs by about 2 sectors between paper and the repository (1.1) | no size is hard-coded; Partition 1 bounds come from the GPT entry |
| Block Group start-time text points at 0x4C, which is the group-number byte (2.1) | time read at +4, group number at +0x0C as the figure shows |
| Fig. 11 header bytes `02 08 01 00` vs `02 80 01 00` (8) | the Fig. 8/text value `80 01 00` is required |
| Record Index "4 + 15" bytes vs a 20-byte stride in Fig. 6 (2.4) | stride 20 used; the extra bytes are unknown and unreported |
| Anchors "1-hour steps" vs day-sized jumps in the examples (2.4) | only whole-hour alignment is checked, not step size |

## Synthetic layout simplifications

The real Video Data lies more than 2 GiB into the partition. The synthetic images (about 5 MiB)
keep the documented Video Data Offset in the header but place chunks at abs 0x410000 and point the
Channel Index at them; the parser reports this as a truncated/compact image and scans for headers.
The sparse-file test exercises the real offsets (video at 0x80005000, Record State) by seeking. The
padding byte is written as 0x00 (unknown), the delimiter and header field values follow the field
doc, the length field is written as the whole access-unit span (semantic not stated by the paper),
unknown bytes are zero, and deleted clips have no Channel Index entry (the paper's expiration
behaviour, 2.7).
