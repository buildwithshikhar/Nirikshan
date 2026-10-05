# Hikvision file-system parser (Tier B, per-paper, not validated on a real image)

Code: `backend/app/vendors/hikvision_fs.py` (`HikvisionFsParser`, subclass of the identification
parser). Synthetic layout: `backend/app/validation/layouts_hikvision.py`. Tests:
`backend/tests/test_hikvision_parser.py`. Byte-level source of truth:
[hikvision-fields.md](hikvision-fields.md) (Han 2015 and Dragonas 2023, with confidence tags);
section numbers below ("s3") refer to it.

**Circularity statement.** The test layout and the parser are both written from the same field
document. Parsing that layout therefore proves self-consistency and robustness (no crash, bounded
memory, conflicts surfaced), not that the parser reads a real Hikvision recorder. No real device
image has been examined. The tier stays B.

## What is parsed, inferred, unknown

Every `ParsedField` carries one of three tags: `parsed` (bytes read at an offset the sources
document), `inferred` (our reading or a heuristic), `unknown` (present, undocumented, not read).

| Structure | parsed | inferred | unknown (not interpreted) |
|---|---|---|---|
| Master Sector (s1) | signature, capacity, log offset/size, video offset, block-size field, block count, HIKBTREE1/2 offset+size, init time (raw u32) | which base (0x200 vs 0x210) holds the signature; capacity units; 4-byte widths from figure boxes; block size actually used | the 16 bytes before the signature, the version-like string at +0x20, +0x41, +0x48, +0x60, +0x70, +0xA4..+0xDF |
| Backup Master Sector (s1) | - | its offset (searched for after the log area; location undocumented) and identity with the primary | everything else |
| Log area / RATS (s2) | signature, header-variant bytes (01/14, values only), created time (raw), major, minor, Operation user name and IP | record boundaries (next RATS; no length field is documented), record count | meaning of the variant bytes, the 2048-byte preamble, all Details layouts other than Operation user/IP |
| HIKBTREE (s4) | signature, created time, footer / page-list / page #1 offsets, total pages, page #1 offset, footer last-page offset, entry fields (existence flag, channel, start/end u32, block offset) | page-list slot stride (8 or 16 tried), entry stride 48 (read off Fig.6), first-entry offset inside a page (chosen by plausibility), start-before-end order | header +0x24/+0x28/+0x38/+0x50/+0x58, page-list +0x04, entry +0x00 and +0x28, next-page field position, page header size |
| IDR table (s3) | the `OFNI` signature at 56-byte stride downward from the block end (count only) | that the table sits at the end of the block, used to bound the NAL scan | the entire 56-byte record content: index, channel, timestamp are NOT read |
| Video data (s5) | - | NAL framing: found by the generic Annex-B carver inside each located block range (the paper documents raw H.264 NAL units; `00 00 01 BA/BC` index headers are documented in form only) | BA/BC payload, audio, H.265 (any H.265 found is reported as an orphan, not claimed) |
| Checksums | - | - | None is documented for any structure; none is verified or claimed (`checksum` field, status unknown) |

Clips: one `ParsedClip` per carved H.264 clip inside a block that a HIKBTREE entry with existence
flag `00` points at. `channel` is the entry's channel byte; the field `channel_attribution` is tagged
`inferred` because [H] p.193 says a block can also hold another channel's video and the IDR-table
layout that would separate them is unknown. Raw start/end times come from the entry only when they
are not the `FF FF FF 7F 00 00 00 00` sentinel and start <= end, and are block-level, not per clip.
A block that is referenced by entries with different channels gets `channel=None`. Clips are not
emitted for blocks whose range had to be clamped, that do not sit at `video_offset + n * size`, whose
index is >= the block count, or that overlap an earlier scanned range; those produce inconsistencies
(and, for clamped ranges, orphans). Result status: `parsed` only with at least one clip and no
inconsistency; `partial` otherwise; `fallback` when no Master Sector is found or on any exception
(the generic carver's output stands either way).

Memory: the image is never read whole. Structures and blocks are read with seek/read; the log scan
uses 1 MiB windows. Caps (all options, truncation is recorded in `warnings`): RATS records, log
bytes scanned, HIKBTREE pages and entries, blocks scanned; the sample returned for RATS is
`log_sample_size` records.

## Options

| Option | Default | Effect |
|---|---|---|
| `master_sector_offset` | `auto` | `auto` tries 0x210 (Dragonas), then 0x200 (Han), then searches 0x200-0x2FF and flags an unusual offset. `0x200` / `0x210` force one base. The base found is returned as a field. |
| `block_size_mode` | `field` | `field` uses the Master Sector value read from the image; `0x400000` / `1gib` are examiner overrides. See conflict (a). |
| `time_basis_label` | `unspecified` | `utc` / `local` only rewrite the `tz_basis` label of RawTimestamps (and RATS sample items). Raw values and the plain wall-clock decode are unchanged. See conflict (b). |
| `btree_first_entry_offset` | `auto` | Offset of the first 48-byte entry in a 4 KB page (undocumented). `auto` picks the 8-byte-aligned offset in 0..0x40 with the most plausible entries. |
| `max_log_records`, `max_log_scan_bytes`, `log_sample_size`, `max_btree_entries`, `max_pages`, `max_blocks_scanned` | see `OPTIONS` | Bounds. |

## Open conflicts, exposed rather than resolved

**(a) Data-block size (s7).** [H] p.191 text says 0x400000, p.192 says "generally 1 GB
(0x40000000)", and the Fig.2 bytes decode to 0x40000000. The parser always emits the field
`block_size_conflict_in_source` (status `unknown`) quoting all three plus the value read from the
image, the mode, and the size in use, plus `block_size_used` and `block_geometry_check` (does
`count * size` fit between the video area and HIKBTREE1, evaluated for each candidate). Default
`field` trusts the image's own Master Sector value. With an override the geometry changes: block
offsets not at `video_offset + n * size` are rejected, ranges that exceed the image or HIKBTREE1 are
clamped and then emit orphans only (never clips), and overlapping ranges are skipped, each listed in
`inconsistencies`.

**(b) Timestamp basis (s6).** [H] calls Master Sector init and HIKBTREE entry times UTC; [D] says
log times are stored in the CCTV's local time zone; the same author's tool comments the opposite.
The structures differ and no single device was tested for both. Every time is returned as a raw
epoch integer with its offset, format `unix seconds (u32 LE)`, a plain decode of the integer
(not a timezone claim) and `tz_basis = "not assumed"`. The field `timestamp_basis_conflict_in_source`
documents the conflict. DST is undocumented and not handled. P5 owns normalization.

**(c) Master Sector base.** Han: sector starts at 0x200; Dragonas Fig.21: signature at 0x210. Both
are accepted; which one is used is returned, and a signature present at both is flagged.

## Known limits

* Entry location inside a page, page-list stride and the next-page field are undocumented; the
  parser infers them from plausibility (existence flag uniform 00/FF and block offset inside the
  video area) and reports them as `inferred`. A different real layout may yield no entries (the
  parser then falls back to the generic carver) or, worst case, plausible-looking wrong entries.
* Block offsets are assumed absolute disk offsets (consistent with the paper's samples, not stated).
* Per-clip channel and per-clip time are not available without the IDR-table record layout.
  Clips do not span blocks; a recording that continues in another block is a separate clip.
* Deleted/overwritten data: a cleared entry (existence FF) hides intact video from this parser; the
  generic carver still finds it and the cross-check reports it as
  `generic_clip_not_explained_by_parser`. The Fig.6 labels (Recording/Recorded) contradict the text
  on when real times are written; times may be absent or the sentinel for blocks that hold video.
* The 2048-byte log preamble is documented for Dragonas' devices only; NVR logs at 0xA200 and the
  per-type Details layouts are not handled.
* `00 00 01 BA/BC` headers are not emitted by the synthetic layout; how the generic carver treats
  them in real data is untested. H.265 and audio framing are undocumented and not parsed.
* No checksum is verified. Structure validity checks (offset ordering, ranges, signatures) are the
  only integrity tests, and they are the checks listed at the end of the field document.
