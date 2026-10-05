"""Honeywell NVR structured parser (P4). Scope: ONE model (HN350802xx, 8 channels), H.264 only.

Every layout fact below comes from docs/parsers/honeywell-fields.md ("field doc"), which records
the tables and figures of Yoon and Hwang, arXiv:2605.07430 (RESEARCH 3.4 [S5]). Section numbers
in comments refer to the field doc. The paper's tools repository has NO licence: nothing was
fetched or copied from it, and constants it alone showed are not used.

Status tags (see app/vendors/parse.py):
  parsed   - read directly from bytes at a position/width the field doc marks documented.
  inferred - our reading: a derived unit (4 KiB pages), standard GPT layout (the paper prints no
             GPT bytes), a heuristic, or a semantic the paper does not state.
  unknown  - present on disk, meaning or width undocumented; reported but never interpreted.

Not parsed (field doc says unknown / not analysed): Protective MBR, secondary GPT (it lives at
sector 32 of a final 2 GB region on the real device, 1.5), Partition 2, Fixed Value (2.5), the
"None" gap, the Record Index status bytes, header bytes 0x20-0x3F and 0x4000+, H.265, audio or
metadata frames. No checksum is documented for any Honeywell structure except the standard GPT
CRC32s (which the paper only mentions): none is claimed or verified for Partition 1 or the
custom header.

Memory is bounded: the image is never read whole. Structures are read at their offsets; the video
scan walks 1 MiB windows and reads one frame at a time (at most `max_frame_bytes`).
"""

import struct
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.vendors.honeywell import HoneywellParser
from app.vendors.parse import (
    ParsedClip,
    ParsedField,
    ParsedOrphan,
    ParseResult,
    RawTimestamp,
    fallback,
)

SRC = "field doc"
SECTOR = 512  # 1.0: sector size is never discussed by P; 512 is implied by "40 sectors ~ 20 KB"
MACHINE_ABS = 34 * SECTOR  # 1.2/1.3: Machine Data at sector 34
DEVICE_ID_ABS, MODEL_ABS = 0x4440, 0x4468  # 1.3 (Fig. 3)
P1_LBA = 40  # 1.1: Partition 1 starts at sector 40
P1_ABS = P1_LBA * SECTOR  # 0x5000
PAGE = 0x1000  # 2.0: 4 KiB unit of size/offset fields (DERIVED by the field doc, not stated by P)
VIDEO_DATA_REL = 0x80000000  # 2.1/2.6: Video Data Offset value in all of P's figures
BLOCK_LIST_REL = 0x40000  # 2.2 (Fig. 5a row labels disagree: "0x4000.."; text says 0x40000)
CHANNEL_LIST_REL = 0x400000  # 2.3
RECORD_STATE_REL = 0x40000000  # 2.4
RECORD_SUBREGION = 0x20000  # 2.4
BGI_REL = 0x40  # 2.1 Block Group Index entries (16 B each)
CH_HDR = 20  # 3: custom header size
MAGIC = b"\x80\x01\x00"  # 3: header bytes 1-3, "fixed", meaning unknown
FLAGS = {0x82: "IDR", 0x02: "non-IDR"}  # 3: header byte 0
H264_NAL_TYPES = (1, 5, 6, 7, 8, 9)  # same set as the identification parser
DELIM = bytes(20)  # 3.1: End of Channel Data
STREAM_TYPES = {0x00: "main", 0x20: "sub"}  # 2.3
WINDOW = 1 << 20
MAX_REASONS = 20

OPTIONS = {
    "time_basis_label": {
        "default": "unspecified",
        "doc": "unspecified | utc | local. ONLY annotates RawTimestamp.tz_basis with the "
        "examiner's label. The paper never states UTC or local (field doc 5); nothing is "
        "converted.",
    },
    "max_time_gap_seconds": {
        "default": 5.0,
        "doc": "A clip is split when the custom-header time jumps forward by more than this "
        "or goes backward. Heuristic (inferred); the paper documents no gap rule.",
    },
    "max_frame_bytes": {
        "default": 16 * 1024 * 1024,
        "doc": "Largest header length value accepted (also bounds per-frame memory).",
    },
    "ts_plausible_min_s": {
        "default": 946_684_800,
        "doc": "Earliest plausible header time (Unix seconds), default 2000-01-01.",
    },
    "ts_plausible_max_s": {
        "default": 4_102_444_800,
        "doc": "Latest plausible header time (Unix seconds), default 2100-01-01.",
    },
    "min_clip_frames": {
        "default": 1,
        "doc": "Clips with fewer frames are reported as orphans.",
    },
    "max_frames": {"default": 5_000_000, "doc": "Safety bound on frames parsed from one image."},
    "max_clips": {"default": 100_000, "doc": "Clip list cap; truncation is a warning."},
    "max_index_entries": {
        "default": 4096,
        "doc": "Entries read from each of Block Group Index, Video Block List, Channel Index.",
    },
    "record_state_channels": {
        "default": 8,
        "doc": "Record State subregions inspected (the model has 8 channels, field doc 2.4).",
    },
    "video_scan": {
        "default": "auto",
        "doc": "auto: scan from the Video Data Offset when the Partition 1 header validates and "
        "lies inside the image, else the whole image. whole_image: always scan everything.",
    },
}


def decode_us(raw: int) -> str:
    """Plain epoch arithmetic, no timezone: 1970-01-01 + raw microseconds."""
    try:
        return (datetime(1970, 1, 1) + timedelta(microseconds=raw)).isoformat(sep=" ")
    except OverflowError:
        return ""


def decode_s(raw: int) -> str:
    try:
        return (datetime(1970, 1, 1) + timedelta(seconds=raw)).isoformat(sep=" ")
    except OverflowError:
        return ""


def _ascii(b: bytes) -> str | None:
    t = b.split(b"\x00", 1)[0]
    if t and all(0x20 <= c < 0x7F for c in t):
        return t.decode("ascii")
    return None


@dataclass
class Frame:
    off: int
    length: int
    key: bool
    width: int
    height: int
    ts_us: int
    ts_off: int
    nal_type: int
    boundary: str  # header | delimiter | eof

    @property
    def payload(self) -> tuple[int, int]:
        return self.off + CH_HDR, self.off + CH_HDR + self.length


class _Ctx:
    """Shared state for one parse: reader, options, counters."""

    def __init__(self, f, size: int, opts: dict):
        self.f, self.size, self.opts = f, size, opts
        self.fields: list[ParsedField] = []
        self.warnings: list[str] = []
        self.incons: list[str] = []
        self.stats: dict = {}
        self.reasons: dict[str, int] = {}
        self.stamps: list[RawTimestamp] = []

    def read(self, off: int, n: int) -> bytes:
        if off < 0 or n <= 0:
            return b""
        self.f.seek(off)
        return self.f.read(n)

    def add(self, name, value, status, source="", note=""):
        self.fields.append(ParsedField(name, value, status, source, note))

    def reason(self, why: str) -> None:
        if why in self.reasons or len(self.reasons) < MAX_REASONS:
            self.reasons[why] = self.reasons.get(why, 0) + 1

    def plausible_s(self, s: int) -> bool:
        return self.opts["ts_plausible_min_s"] <= s <= self.opts["ts_plausible_max_s"]


# ---- start sectors -----------------------------------------------------------------------------


def parse_gpt(c: _Ctx) -> dict | None:
    """Standard GPT (UEFI). P prints no GPT bytes (field doc 1.2), so every GPT field is
    `inferred`. Returns {'p1': (first, last), ...} or None when unreadable."""
    std = "GPT std (UEFI); P prints no GPT bytes (field doc 1.2)"
    if c.size < 34 * SECTOR:
        c.warnings.append("image shorter than 34 sectors: start sectors not parsed")
        return None
    h = c.read(SECTOR, 92)
    if len(h) < 92 or h[:8] != b"EFI PART":
        c.incons.append("GPT header signature 'EFI PART' missing at sector 1")
        c.add("gpt_header", None, "unknown", std, "signature missing: GPT not parsed")
        return None
    (_, rev, hsize, crc, _r, my, alt, first_u, last_u, guid, ent_lba, n_ent, ent_size, ent_crc) = (
        struct.unpack_from("<8sIIIIQQQQ16sQIII", h, 0)
    )
    ok = True
    if not 92 <= hsize <= SECTOR:
        c.incons.append(f"GPT header size {hsize} out of range")
        ok = False
    else:
        full = bytearray(c.read(SECTOR, hsize))
        full[16:20] = b"\x00\x00\x00\x00"
        if zlib.crc32(bytes(full)) & 0xFFFFFFFF != crc:
            c.incons.append("GPT header CRC32 mismatch (standard GPT check)")
            ok = False
    c.add(
        "gpt_header",
        {
            "revision": f"0x{rev:08x}",
            "my_lba": my,
            "alternate_lba": alt,
            "first_usable_lba": first_u,
            "last_usable_lba": last_u,
            "disk_guid": str(uuid.UUID(bytes_le=guid)),
            "entries_lba": ent_lba,
            "entries": n_ent,
            "entry_size": ent_size,
            "header_crc32_ok": ok,
        },
        "inferred",
        std,
        "alternate_lba is NOT used: P places the secondary header at sector 32 of the final "
        "2 GB region, not at the last LBA (field doc 1.5)",
    )
    if ent_size < 128 or ent_size % 8 or not 1 <= n_ent <= 1024 or ent_lba * SECTOR >= c.size:
        c.incons.append("GPT partition entry array parameters implausible")
        return None
    arr_len = n_ent * ent_size
    arr = c.read(ent_lba * SECTOR, arr_len)
    if len(arr) < arr_len:
        c.incons.append("GPT partition entry array truncated by the image end")
        return None
    if zlib.crc32(arr) & 0xFFFFFFFF != ent_crc:
        c.incons.append("GPT partition entry array CRC32 mismatch (standard GPT check)")
    parts = []
    for i in range(min(n_ent, 8)):  # P shows two partitions; the entry count is unknown (1.2)
        e = arr[i * ent_size : (i + 1) * ent_size]
        if e[:16] == bytes(16):
            continue
        first, last = struct.unpack_from("<QQ", e, 32)
        parts.append(
            {
                "index": i,
                "type_guid": str(uuid.UUID(bytes_le=e[:16])),
                "first_lba": first,
                "last_lba": last,
            }
        )
    if not parts:
        c.incons.append("GPT has no used partition entry")
        return None
    c.add("gpt_partitions", parts, "inferred", std, "first 8 entries inspected")
    p1 = parts[0]
    c.add(
        "partition1_first_lba",
        p1["first_lba"],
        "inferred",
        f"{SRC} 1.1 (documented value 40) + GPT std entry layout",
        "value read from the GPT entry; the 40 is documented, the entry layout is standard GPT",
    )
    if p1["first_lba"] != P1_LBA:
        c.incons.append(f"Partition 1 first LBA {p1['first_lba']} != documented {P1_LBA}")
    return {"p1": (p1["first_lba"], p1["last_lba"])}


def parse_machine_data(c: _Ctx) -> None:
    """1.3: sector 34. Device ID and model are documented; the two grey strings are not."""
    if c.size < MACHINE_ABS + SECTOR:
        c.warnings.append("image ends before sector 34: Machine Data not parsed")
        return
    sec = c.read(MACHINE_ABS, SECTOR)
    if sec == bytes(SECTOR):
        c.incons.append("Machine Data sector 34 is all zero (absent or wiped)")
        c.add("machine_data", None, "unknown", f"{SRC} 1.3", "sector 34 all zero")
        return
    dev = _ascii(sec[DEVICE_ID_ABS - MACHINE_ABS : DEVICE_ID_ABS - MACHINE_ABS + 0x28])
    model = _ascii(sec[MODEL_ABS - MACHINE_ABS : MODEL_ABS - MACHINE_ABS + 0x18])
    if dev is None or model is None:
        c.incons.append(
            "Machine Data device ID/model are not printable ASCII at the documented offsets"
        )
    if dev is not None:
        c.add("device_id", dev, "parsed", f"{SRC} 1.3 (0x4440, ASCII, NUL padded)")
    if model is not None:
        c.add(
            "model",
            model,
            "parsed",
            f"{SRC} 1.3 (0x4468)",
            "the paper's UI shows 'HN350802xx' literally; do not match on 'HN35080200'",
        )
        if not model.startswith("HN"):
            c.warnings.append(
                f"model string {model!r} does not start with 'HN' (documented for one model)"
            )
    for name, o, n in (
        ("machine_data_string_0x4400", 0x4400, 16),
        ("machine_data_string_0x4420", 0x4420, 3),
    ):
        raw = sec[o - MACHINE_ABS : o - MACHINE_ABS + n]
        c.add(
            name,
            _ascii(raw) or raw.hex(),
            "unknown",
            f"{SRC} 1.3",
            "shown by Fig. 3, meaning not stated",
        )


# ---- Partition 1 structures --------------------------------------------------------------------


def parse_p1_header(c: _Ctx, gpt: dict | None) -> tuple[bool, bool]:
    """2.1. Returns (header_valid_and_data_inside_image, header_present)."""
    if c.size < P1_ABS + 0x40:
        c.warnings.append("image ends before the Partition 1 header: not parsed")
        return False, False
    h = c.read(P1_ABS, 0x40 + 16 * c.opts["max_index_entries"])
    if h[:0x20] == bytes(0x20):
        c.incons.append("Partition 1 header fields are all zero (blank or wiped)")
        c.add("partition1_header", None, "unknown", f"{SRC} 2.1", "all zero")
        return False, False
    vdo, nxt, avail, total = (struct.unpack_from("<I", h, o)[0] for o in (0x00, 0x08, 0x10, 0x18))
    raw = {"video_data_offset": vdo, "next_video_offset": nxt, "available": avail, "total": total}
    unit_note = "4 KiB unit is the field doc's DERIVED interpretation (P never states it)"
    for k, v in raw.items():
        c.add(
            f"p1_{k}",
            {"raw_u32_le": v, "bytes_if_4k_units": v * PAGE},
            "inferred",
            f"{SRC} 2.1 (offsets 0x00/0x08/0x10/0x18, 4 stated, 8 not excluded)",
            unit_note,
        )
    valid = True
    if vdo * PAGE != VIDEO_DATA_REL:
        c.incons.append(
            f"Video Data Offset {vdo * PAGE:#x} != {VIDEO_DATA_REL:#x} seen in all of P's figures"
        )
        valid = False
    if avail > total:
        c.incons.append("Available Memory exceeds Total Allocatable Memory")
    if nxt * PAGE < vdo * PAGE:
        c.incons.append("Next Video Offset precedes the Video Data Offset")
    inside = valid and P1_ABS + vdo * PAGE < c.size
    if valid and not inside:
        c.warnings.append(
            f"Video Data Offset (abs {P1_ABS + vdo * PAGE:#x}) lies beyond the image end "
            f"({c.size}): "
            "truncated or compact image; video is located by scanning, and the partition-size "
            "checks are skipped"
        )
    elif inside and gpt:
        psize = (gpt["p1"][1] - gpt["p1"][0] + 1) * SECTOR
        if nxt * PAGE >= psize:
            c.incons.append("Next Video Offset lies beyond Partition 1")
    # Block Group Index (documented): entries at 0x40 + 16n, until the first all-zero entry
    groups, bad = [], 0
    cap = c.opts["max_index_entries"]
    for n in range(cap):
        e = h[BGI_REL + 16 * n : BGI_REL + 16 * n + 16]
        if len(e) < 16 or e == bytes(16):
            break
        t = struct.unpack_from("<I", e, 4)[0]
        if struct.unpack_from("<I", e, 0)[0] != 0 or not c.plausible_s(t):
            bad += 1
        groups.append({"start_time_s": t, "group_number": e[0x0C]})
        if len(c.stamps) < 5:
            c.stamps.append(
                RawTimestamp(
                    "block group start time",
                    P1_ABS + BGI_REL + 16 * n + 4,
                    t,
                    "unix seconds (u32 LE)",
                    decode_s(t),
                    _tz(c),
                    "Header Block Group Index (field doc 2.1); zone not stated by P",
                )
            )
    if bad:
        c.incons.append(
            f"{bad} Block Group Index entries with non-zero reserved bytes or implausible time"
        )
    c.add(
        "block_group_index",
        groups,
        "parsed",
        f"{SRC} 2.1 (+4 start time u32 LE, +0x0C group number)",
        "bytes +0..3 (zero), +8..11 and +0x0D..0x0F are unreported (unknown); the table "
        "ends at the first all-zero entry, which P does not state (inferred)",
    )
    if valid and nxt == vdo and avail == total and not groups:
        c.add(
            "format_event_candidate",
            True,
            "inferred",
            f"{SRC} 2.7/7.3 (derived from P Fig. 11b, not stated by P)",
            "next offset == video offset, available == total, no Block Group Index entries; "
            "whether Video Data is still non-empty is not checked here",
        )
    return inside, True


def parse_block_list(c: _Ctx) -> None:
    """2.2: 16 B entries; +0 reserved zero, +4 start time u32 LE, +0x0C block no., +0x0D group no.
    The start (0x40000 vs the Fig. 5a label 0x4000) is only partly documented."""
    base = P1_ABS + BLOCK_LIST_REL
    if c.size < base + 16:
        c.stats["block_list"] = "beyond image"
        return
    n_max = c.opts["max_index_entries"]
    buf = c.read(base, 16 * n_max)
    n = bad = 0
    times, groups = [], set()
    for i in range(len(buf) // 16):
        e = buf[16 * i : 16 * i + 16]
        if e == bytes(16):
            break
        n += 1
        t = struct.unpack_from("<I", e, 4)[0]
        if struct.unpack_from("<I", e, 0)[0] != 0 or not c.plausible_s(t):
            bad += 1
            continue
        times.append(t)
        groups.add(e[0x0D])
    c.stats["block_list"] = {
        "entries": n,
        "invalid": bad,
        "groups": sorted(groups),
        "time_range_s": [min(times), max(times)] if times else None,
    }
    if bad:
        c.incons.append(
            f"{bad} Video Block List entries with non-zero reserved bytes or implausible time"
        )
    if n >= n_max:
        c.warnings.append(f"Video Block List read capped at {n_max} entries")
    c.add(
        "video_block_list",
        c.stats["block_list"],
        "parsed",
        f"{SRC} 2.2",
        "reserved/time/block/group bytes documented; bytes +8..11 and +14..15 unknown and not "
        "reported; list start partly documented (Fig. 5a label differs)",
    )


def parse_channel_index(c: _Ctx, vdo_inside: bool) -> list[tuple[int, int, int, int]]:
    """2.3: 16 B entries; +0 channel id, +1 stream type (0x00 main / 0x20 sub), +2..3 length and
    +8..11 start in 4 KiB units (DERIVED unit), +4..7 start time u32 LE. Returns surviving entries
    as (start_abs, end_abs, channel_id, stream_type)."""
    base = P1_ABS + CHANNEL_LIST_REL
    if c.size < base + 16:
        c.stats["channel_index"] = "beyond image"
        return []
    n_max = c.opts["max_index_entries"]
    buf = c.read(base, 16 * n_max)
    out, n = [], 0
    counts = {"bad_stream_type": 0, "beyond_image": 0, "no_header_at_start": 0, "before_video": 0}
    for i in range(len(buf) // 16):
        e = buf[16 * i : 16 * i + 16]
        if e == bytes(16):
            break
        n += 1
        ch, st = e[0], e[1]
        ln, t, start = (
            struct.unpack_from("<H", e, 2)[0],
            struct.unpack_from("<I", e, 4)[0],
            struct.unpack_from("<I", e, 8)[0],
        )
        a = P1_ABS + start * PAGE
        if st not in (0x00, 0x20) or ln == 0 or not c.plausible_s(t):
            counts["bad_stream_type"] += 1
            continue
        if vdo_inside and start * PAGE < VIDEO_DATA_REL:
            counts["before_video"] += 1
            continue
        if a + CH_HDR > c.size:
            counts["beyond_image"] += 1
            continue
        h = c.read(a, 4)
        if len(h) < 4 or h[0] not in FLAGS or h[1:4] != MAGIC:
            counts["no_header_at_start"] += 1
            continue
        out.append((a, a + ln * PAGE, ch, st))
        if len(c.stamps) < 8:
            c.stamps.append(
                RawTimestamp(
                    "channel index stream start time",
                    base + 16 * i + 4,
                    t,
                    "unix seconds (u32 LE)",
                    decode_s(t),
                    _tz(c),
                    "Channel Index (field doc 2.3); zone not stated by P",
                )
            )
    c.stats["channel_index"] = {"entries": n, "usable": len(out), **counts}
    for k in ("bad_stream_type", "before_video", "beyond_image"):
        if counts[k]:
            c.incons.append(f"{counts[k]} Channel Index entries rejected: {k}")
    if n >= n_max:
        c.warnings.append(f"Channel Index read capped at {n_max} entries")
    c.add(
        "channel_index",
        c.stats["channel_index"],
        "inferred",
        f"{SRC} 2.3",
        "channel id and start time are documented; length/start are in a DERIVED 4 KiB unit; "
        "bytes +12..15 unknown; list end (first all-zero entry) not stated by P; entries "
        "without a header at their start are counted, not trusted",
    )
    return out


def parse_record_state(c: _Ctx) -> None:
    """2.4: (channels + 1) subregions of 0x20000; first byte = anchor count; Record Index = 20 B
    at +0x14 (offset derived): u32 full-hour time + undocumented status. Only the time anchors
    are read; status bytes are unknown."""
    base = P1_ABS + RECORD_STATE_REL
    out = []
    for ch in range(1, c.opts["record_state_channels"] + 1):  # 1-based: derived from P's text
        o = base + ch * RECORD_SUBREGION
        if o + 0x14 > c.size:
            break
        n = c.read(o, 1)[0]
        if n == 0:
            continue
        raw = c.read(o + 0x14, 20 * n)
        anchors = [struct.unpack_from("<I", raw, 20 * i)[0] for i in range(len(raw) // 20)]
        off_grid = sum(1 for a in anchors if a % 3600)
        out.append(
            {
                "channel_1based_derived": ch,
                "count_byte": n,
                "anchors_read": len(anchors),
                "first_s": anchors[0] if anchors else None,
                "last_s": anchors[-1] if anchors else None,
                "off_hour": off_grid,
            }
        )
        if len(anchors) != n or off_grid:
            c.incons.append(f"Record State channel {ch}: count/anchors inconsistent")
    if out:
        c.stats["record_state"] = out
        c.add(
            "record_state",
            out,
            "inferred",
            f"{SRC} 2.4",
            "anchor array offset 0x14 and 1-based channel numbering are derived; per-hour status "
            "bytes and the 20th byte are unknown and not reported",
        )


def _tz(c: _Ctx) -> str:
    lab = c.opts["time_basis_label"]
    return (
        "not assumed"
        if lab == "unspecified"
        else f"{lab} (examiner label via option; source silent)"
    )


# ---- video stream ------------------------------------------------------------------------------


def read_frame(c: _Ctx, off: int) -> Frame | None:
    """Validate the custom header at `off` (field doc 3) and that its length lands on the next
    header, the 20-zero delimiter or the image end. Records the first rejection reason."""
    o = c.opts
    h = c.read(off, CH_HDR + 5)
    if len(h) < CH_HDR + 5:
        c.reason("truncated header")
        return None
    if h[0] not in FLAGS or h[1:4] != MAGIC:
        c.reason("wrong flag byte or magic")
        return None
    w, ht, length, ts = struct.unpack_from("<HHIQ", h, 4)
    if h[20:24] != b"\x00\x00\x00\x01":
        c.reason("no Annex-B start code after the header")
        return None
    if not (0 < w <= 16384 and 0 < ht <= 16384):  # heuristic bound, not from P
        c.reason("implausible resolution")
        return None
    if not 5 <= length <= o["max_frame_bytes"]:
        c.reason("length field out of range")
        return None
    if off + CH_HDR + length > c.size:
        c.reason("length points beyond the image end")
        return None
    if not c.plausible_s(ts // 1_000_000):
        c.reason("timestamp outside plausible range")
        return None
    nal = h[24]
    if nal & 0x80 or (nal & 0x1F) not in H264_NAL_TYPES:
        c.stats["non_h264_nal_headers"] = c.stats.get("non_h264_nal_headers", 0) + 1
        c.reason("NAL header is not an H.264 type (H.265 layout unknown)")
        return None
    end = off + CH_HDR + length
    if end == c.size:
        boundary = "eof"
    else:
        nxt = c.read(end, CH_HDR)
        if nxt == DELIM:
            boundary = "delimiter"
        elif len(nxt) >= 4 and nxt[0] in FLAGS and nxt[1:4] == MAGIC:
            boundary = "header"
        else:
            c.reason("length does not land on a header, the 20-zero delimiter or the image end")
            return None
    payload = c.read(off + CH_HDR, length)
    if DELIM in payload:  # 3.1: zero runs >= 20 cannot occur in valid H.264 NAL bytes
        c.reason("payload contains a run of >= 20 zero bytes (damaged or overwritten)")
        return None
    return Frame(off, length, h[0] == 0x82, w, ht, ts, off + 12, nal & 0x1F, boundary)


def iter_frames(c: _Ctx, start: int):
    """Yield Frames in image order, and a str (reason) at the end of each contiguous run."""
    pos, yielded = start, 0
    while pos < c.size and yielded < c.opts["max_frames"]:
        b0 = max(0, pos - 1)
        buf = c.read(b0, WINDOW)
        if not buf:
            break
        i = buf.find(MAGIC)
        last = len(buf) - 3
        found = False
        while i != -1:
            hdr = b0 + i - 1
            if i >= 1 and hdr >= pos and buf[i - 1] in FLAGS:
                fr = read_frame(c, hdr)
                if fr is None:
                    c.stats["rejected_candidates"] = c.stats.get("rejected_candidates", 0) + 1
                else:
                    found = True
                    break
            i = buf.find(MAGIC, i + 1)
        if not found:
            pos = c.size if len(buf) < WINDOW else max(pos + 1, b0 + last)
            continue
        while fr is not None and yielded < c.opts["max_frames"]:
            yield fr
            yielded += 1
            nxt = fr.off + CH_HDR + fr.length
            if fr.boundary == "delimiter":
                end = nxt + len(DELIM)
                q = -(-end // PAGE) * PAGE  # next 4 KiB boundary (derived, 3.1)
                pad = c.read(end, min(q - end, PAGE))
                vals = c.stats.setdefault("padding_byte_values_observed", [])
                for v in sorted(set(pad)):
                    if v not in vals and len(vals) < 8:
                        vals.append(v)
                yield "end-of-channel delimiter or zeroed data (20 zero bytes)"
                pos = end
                break
            if fr.boundary == "eof":
                yield "end of image"
                pos = c.size
                break
            fr = read_frame(c, nxt)
            if fr is None:
                c.stats["rejected_candidates"] = c.stats.get("rejected_candidates", 0) + 1
                yield "next custom header invalid or inconsistent"
                pos = nxt + 1
                break
        else:
            pos = c.size
            yield "frame cap reached"


class HoneywellFsParser(HoneywellParser):
    """Registered (by the lead) in place of the identification-only HoneywellParser."""

    options_schema = OPTIONS

    def parse(self, f, size, options=None):
        opts = {k: v["default"] for k, v in OPTIONS.items()} | (options or {})
        try:
            return self._parse(f, size, opts, set(options or {}) - set(OPTIONS))
        except Exception as exc:  # never raise: fall back to generic carving
            return fallback(
                self.vendor,
                self.vendor,
                self.tier,
                opts,
                f"parser error ({type(exc).__name__}: {exc}); generic carving stands",
            )

    def _parse(self, f, size, opts, unknown_opts) -> ParseResult:
        if opts["time_basis_label"] not in ("unspecified", "utc", "local"):
            opts["time_basis_label"] = "unspecified"
            bad_label = True
        else:
            bad_label = False
        c = _Ctx(f, size, opts)
        if bad_label:
            c.warnings.append("time_basis_label must be unspecified|utc|local: using unspecified")
        if unknown_opts:
            c.warnings.append(f"unknown options ignored: {sorted(unknown_opts)}")
        gpt = parse_gpt(c)
        parse_machine_data(c)
        inside, present = parse_p1_header(c, gpt)
        parse_block_list(c)
        index = parse_channel_index(c, inside)
        parse_record_state(c)
        start = P1_ABS + VIDEO_DATA_REL if inside and opts["video_scan"] == "auto" else 0
        c.stats["video_scan_start"] = start

        clips: list[ParsedClip] = []
        orphans: list[ParsedOrphan] = []
        active: dict | None = None
        orphan: ParsedOrphan | None = None
        orphan_end = -1
        st = c.stats
        st.update(frames=0, key_frames=0, runs=0, clips_truncated=False, aligned_clip_starts=0)
        gap_us = int(opts["max_time_gap_seconds"] * 1_000_000)

        def ts(fr: Frame, name: str) -> RawTimestamp:
            return RawTimestamp(
                name,
                fr.ts_off,
                fr.ts_us,
                "unix microseconds (u64 LE)",
                decode_us(fr.ts_us),
                _tz(c),
                "custom header bytes 12-19 (field doc 3); zone not stated by P",
            )

        def close(why: str) -> None:
            nonlocal active
            a, active = active, None
            if a is None:
                return
            if a["frames"] < opts["min_clip_frames"]:
                orphans.append(
                    ParsedOrphan(
                        None, a["ext"][0][0], a["ext"][-1][1], a["frames"], "clip too short"
                    )
                )
                return
            if len(clips) >= opts["max_clips"]:
                st["clips_truncated"] = True
                return
            ch = _channel_of(index, a["ext"][0][0] - CH_HDR)
            clip = ParsedClip(
                "h264", a["ext"], None, a["frames"], a["keys"], True, a["w"], a["h"], end_reason=why
            )
            clip.timestamps = [a["first_ts"], a["last_ts"]]
            if ch is not None and ch != "ambiguous":
                clip.channel = ch[0]
                clip.fields.append(
                    ParsedField(
                        "channel",
                        ch[0],
                        "inferred",
                        f"{SRC} 2.3/4",
                        f"from the Channel Index entry whose chunk contains this clip (stream type "
                        f"{STREAM_TYPES.get(ch[1], ch[1])}); id base and "
                        "camera mapping are not stated by P",
                    )
                )
            else:
                note = (
                    "chunk matches more than one Channel Index entry"
                    if ch == "ambiguous"
                    else "the custom header has no channel field (field doc 4) and no surviving "
                    "Channel Index entry covers this clip"
                )
                clip.fields.append(ParsedField("channel", None, "unknown", f"{SRC} 4", note))
                clip.notes.append("channel unknown: " + note)
            clip.fields += [
                ParsedField("frame_type", "0x82 key / 0x02 non-key", "parsed", f"{SRC} 3 byte 0"),
                ParsedField(
                    "timestamp",
                    "u64 LE microseconds, raw",
                    "parsed",
                    f"{SRC} 3 bytes 12-19",
                    "LE confirmed by the field doc against P's printed value; zone unknown",
                ),
                ParsedField(
                    "resolution",
                    f"{a['w']}x{a['h']}",
                    "inferred",
                    f"{SRC} 3 bytes 4-7",
                    "layout documented, endianness derived from 1920x1080",
                ),
                ParsedField(
                    "length_semantic",
                    f"{a['frames']}/{a['frames']} lengths land on a header, delimiter or image end",
                    "inferred",
                    f"{SRC} 3",
                    "whether length counts NAL only or the whole access unit is not "
                    "stated by P; the check is semantics-neutral",
                ),
                ParsedField(
                    "clip_boundaries",
                    "key frame start; timestamp continuity; delimiter",
                    "inferred",
                    "heuristic",
                    "option max_time_gap_seconds",
                ),
            ]
            if a["first_off"] % PAGE == (P1_ABS % PAGE):
                st["aligned_clip_starts"] += 1
            clips.append(clip)

        for fr in iter_frames(c, start):
            if isinstance(fr, str):
                st["runs"] += 1
                close(fr)
                continue
            st["frames"] += 1
            st["key_frames"] += int(fr.key)
            if len(c.stamps) < 10:
                c.stamps.append(ts(fr, "frame time"))
            if active is not None:
                delta = fr.ts_us - active["last_us"]
                if delta < 0 or delta > gap_us:
                    close("timestamp reversal" if delta < 0 else "timestamp discontinuity")
                elif (fr.width, fr.height) != (active["w"], active["h"]):
                    close("resolution change")
            if active is None:
                if not fr.key:
                    if orphan is not None and fr.off == orphan_end:
                        orphan.end, orphan.frames = fr.payload[1], orphan.frames + 1
                    else:
                        orphan = ParsedOrphan(
                            None,
                            fr.payload[0],
                            fr.payload[1],
                            1,
                            "non-key frames without a preceding 0x82 key frame",
                        )
                        if len(orphans) < 10_000:
                            orphans.append(orphan)
                    orphan_end = fr.payload[1]
                    continue
                orphan = None
                active = {
                    "ext": [],
                    "frames": 0,
                    "keys": 0,
                    "w": fr.width,
                    "h": fr.height,
                    "first_ts": ts(fr, "first frame time"),
                    "first_off": fr.off,
                    "last_us": 0,
                    "last_ts": None,
                }
            active["ext"].append(list(fr.payload))
            active["frames"] += 1
            active["keys"] += int(fr.key)
            active["last_us"] = fr.ts_us
            active["last_ts"] = ts(fr, "last frame time")
        close("end of image")
        if st["clips_truncated"]:
            c.warnings.append(f"clip list capped at {opts['max_clips']}")

        if st["frames"] == 0:
            msg = "no consistent Honeywell custom-header chain found; generic carving stands"
            if st.get("non_h264_nal_headers"):
                msg += (
                    f" ({st['non_h264_nal_headers']} otherwise valid custom headers carry a "
                    "non-H.264 NAL header; the H.265 layout is undocumented and not parsed)"
                )
            return ParseResult(
                self.vendor,
                self.vendor,
                self.tier,
                "fallback",
                opts,
                c.fields,
                [],
                orphans,
                c.stamps,
                c.warnings + [msg],
                [f"{k}: {v}" for k, v in sorted(c.reasons.items())[:10]] + c.incons,
                st,
            )
        if st.get("non_h264_nal_headers"):
            c.warnings.append(
                f"{st['non_h264_nal_headers']} otherwise valid custom headers carry a non-H.264 "
                "NAL header; the H.265 layout is undocumented: neither parsed nor exported"
            )
        incons = c.incons + [
            f"{v} candidate(s) rejected: {k}" for k, v in sorted(c.reasons.items())
        ]
        if st.get("padding_byte_values_observed") is not None:
            c.add(
                "padding_byte_value",
                st["padding_byte_values_observed"],
                "unknown",
                f"{SRC} 3.1",
                "P says a dummy value fills the gap but not which; these are observed values only",
            )
        c.add(
            "custom_header",
            "flag, 80 01 00, WxH, length, u64 LE microsecond time",
            "parsed",
            f"{SRC} 3",
        )
        c.add(
            "custom_header_constant",
            "80 01 00",
            "unknown",
            f"{SRC} 3",
            "'fixed 3 byte value', meaning not stated",
        )
        c.add(
            "end_of_channel_delimiter",
            "20 x 0x00",
            "parsed",
            f"{SRC} 3.1",
            "zeroed or overwritten data is indistinguishable from the delimiter",
        )
        c.add(
            "checksum",
            "none documented",
            "unknown",
            f"{SRC} 7",
            "no checksum is documented for the custom header or Partition 1; none is verified",
        )
        c.add(
            "timezone",
            "not stated by the source",
            "unknown",
            f"{SRC} 5",
            f"examiner label via time_basis_label: {opts['time_basis_label']}",
        )
        for name in ("secondary_gpt", "partition2", "fixed_value", "h265_layout"):
            c.add(
                name,
                "not parsed",
                "unknown",
                f"{SRC} 1.5/1.4/2.5/3",
                "undocumented or not analysed",
            )
        return ParseResult(
            self.vendor,
            self.vendor,
            self.tier,
            "partial" if incons else "parsed",
            opts,
            c.fields,
            clips,
            orphans,
            c.stamps,
            c.warnings,
            incons,
            st,
        )


def _channel_of(index, off: int):
    """(channel id, stream type) of the unique Channel Index chunk covering `off`; None; or
    'ambiguous'."""
    hit = [e for e in index if e[0] <= off < e[1]]
    if not hit:
        return None
    if len({(e[2], e[3]) for e in hit}) > 1:
        return "ambiguous"
    return hit[0][2], hit[0][3]
