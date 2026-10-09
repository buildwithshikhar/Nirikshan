"""Dahua DHAV frame parser (P4). Scope: the DHAV frame format only; DHFS on-disk structures
(superblock, indexes, block layout) are NOT parsed (not documented in the sources we read).

Source: FFmpeg libavformat/dhav.c (docs/RESEARCH.md 3.2 [S9]), read on 2026-10-05:
  frame header, little-endian: 0-3 "DHAV"; 4 type (0xf0 audio, 0xf1 other, 0xfc video non-key,
  0xfd video key); 5 subtype; 6 channel; 7 frame sub-number; 8-11 frame number u32; 12-15 frame
  length u32 (header + payload + 8-byte trailer, must be >= 24); 16-19 date u32 (bit-packed,
  see decode_date); 20-21 timestamp u16; 22 extension length; 23 checksum byte (algorithm not
  used by dhav.c: NOT verified here). Extension TLVs follow (types 0x80 width/8,height/8;
  0x81 codec id + frame rate; 0x82 u16 width/height; others skipped by size as in parse_ext).
  Payload = frame_length - 8 - bytes consumed by the header+extension. Trailer: "dhav" + u32 LE
  equal to frame_length - 8, at frame_start + frame_length - 8 (dhav.c get_duration / header
  seek-back arithmetic; derived from code, not stated in prose).
  Type 0xf1 frames only carry the first 20 header bytes in dhav.c; they are skipped here.
  Video codec ids from the demuxer: 0x1 MPEG-4, 0x3 MJPEG, 0x2/0x4/0x8 H.264, 0xc HEVC.

Inferred (not documented): payload for H.264/HEVC is Annex-B (verified per frame at parse
time and reported); frame_number increments by 1 per frame within a channel (tolerance is an
option; Rzayeva 2026 abstract reports +/-3, abstract only); the date field's timezone is NOT
assumed (no timezone field exists in the parsed header).
"""

import struct
from dataclasses import dataclass

from app.vendors.dahua import MAX_FRAME, TYPES, DahuaParser
from app.vendors.parse import (
    ParsedClip,
    ParsedField,
    ParsedOrphan,
    ParseResult,
    RawTimestamp,
    fallback,
)

SRC = "ffmpeg dhav.c (RESEARCH 3.2 S9)"
CODECS = {0x1: "mpeg4", 0x3: "mjpeg", 0x2: "h264", 0x4: "h264", 0x8: "h264", 0xC: "h265"}
EXT_SIZES = {
    0x80: 4,
    0x81: 4,
    0x82: 8,
    0x83: 4,
    0x88: 8,
    0x8C: 8,
    0x84: 4,
    0x85: 4,
    0x8B: 4,
    0x94: 4,
    0x96: 4,
    0xA0: 4,
    0xB2: 4,
    0xB4: 4,
    0x91: 8,
    0x92: 8,
    0x93: 8,
    0x95: 8,
    0x9A: 8,
    0x9B: 8,
    0xB3: 8,
}
# Version of this parser's output (bump when parse results change). Mirrored in
# app/oem/registry.json; tests/test_oem_registry.py fails if the two disagree.
PARSER_VERSION = "1.0"
OPTIONS = {
    "frame_gap_tolerance": {
        "default": 3,
        "doc": "Max frame_number jump inside a clip (delta must be 0..tol+1). Heuristic.",
    },
    "min_clip_frames": {
        "default": 1,
        "doc": "Clips with fewer video frames are reported as orphans.",
    },
    "max_frames_per_run": {
        "default": 5_000_000,
        "doc": "Safety bound on frames parsed from one image.",
    },
}


def decode_date(d: int) -> tuple[int, str]:
    """Bit-packed date as in dhav.c get_timeinfo: sec[0:6] min[6:12] hour[12:17] day[17:22]
    month[22:26] year-2000[26:32]. Returns (raw, plain wall-clock text); no timezone."""
    sec, mn, hr = d & 0x3F, (d >> 6) & 0x3F, (d >> 12) & 0x1F
    day, mon, yr = (d >> 17) & 0x1F, (d >> 22) & 0x0F, ((d >> 26) & 0x3F) + 2000
    return d, f"{yr:04d}-{mon:02d}-{day:02d} {hr:02d}:{mn:02d}:{sec:02d}"


@dataclass
class Frame:
    off: int
    length: int
    type: int
    subtype: int
    channel: int
    subnum: int
    number: int
    date: int
    ts16: int
    payload: tuple[int, int]
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    ext_mismatch: bool = False
    annexb: bool | None = None


def parse_ext(ext: bytes) -> tuple[dict, int]:
    """Return (info, consumed). Unknown TLV types stop parsing like dhav.c (skip rest)."""
    info: dict = {}
    i = 0
    n = len(ext)
    while i < n:
        t = ext[i]
        size = EXT_SIZES.get(t)
        if size is None:
            return info, n  # dhav.c: skip rest of the extension
        if i + size > n:
            return info, n
        if t == 0x80:
            info["width"], info["height"] = 8 * ext[i + 2], 8 * ext[i + 3]
        elif t == 0x81:
            info["codec_id"], info["fps"] = ext[i + 2], ext[i + 3]
        elif t == 0x82:
            info["width"], info["height"] = struct.unpack_from("<HH", ext, i + 4)
        i += size
    return info, i


def read_frame(read, off: int, size: int, why: list) -> Frame | None:
    """Parse and validate one frame at `off`; append a reason to `why` when rejected."""
    h = read(off, 24)
    if len(h) < 24:
        why.append("truncated header")
        return None
    if h[:4] != b"DHAV":
        why.append("wrong magic")
        return None
    t = h[4]
    if t not in TYPES:
        why.append(f"unknown frame type 0x{t:02x}")
        return None
    subtype, channel, subnum = h[5], h[6], h[7]
    number, length, date = struct.unpack_from("<III", h, 8)
    if not 24 <= length <= MAX_FRAME or off + length > size:
        why.append(f"frame length {length} out of range or beyond the image")
        return None
    tr = read(off + length - 8, 8)
    if len(tr) < 8 or tr[:4] != b"dhav" or struct.unpack("<I", tr[4:])[0] != length - 8:
        why.append("trailer missing or length mismatch")
        return None
    if t == 0xF1:
        return Frame(off, length, t, subtype, channel, subnum, number, date, 0, (off, off))
    ts16, ext_len = struct.unpack_from("<H", h, 20)[0], h[22]
    ext = read(off + 24, ext_len)
    info, consumed = parse_ext(ext)
    mismatch = consumed != ext_len
    p0 = off + 24 + consumed  # as dhav.c: payload follows what parse_ext consumed
    p1 = off + length - 8
    if p0 > p1:
        why.append("extension overruns the frame")
        return None
    fr = Frame(
        off,
        length,
        t,
        subtype,
        channel,
        subnum,
        number,
        date,
        ts16,
        (p0, p1),
        CODECS.get(info.get("codec_id")) if "codec_id" in info else None,
        info.get("width"),
        info.get("height"),
        info.get("fps"),
        mismatch,
    )
    head = read(p0, 4)
    fr.annexb = head[:3] == b"\x00\x00\x01" or head == b"\x00\x00\x00\x01"
    return fr


def iter_frames(f, size: int, stats: dict, reasons: dict, max_frames: int):
    """Yield valid frames in file order; follow chains (next frame at off+length), rescan after
    breaks. Rejection reasons are counted (bounded dict)."""

    def read(o, n):
        f.seek(o)
        return f.read(n)

    pos, win = 0, 1 << 20
    yielded = 0
    while pos < size and yielded < max_frames:
        buf = read(pos, win)
        if not buf:
            break
        i = buf.find(b"DHAV")
        if i < 0:
            pos += max(1, len(buf) - 3)
            continue
        off = pos + i
        why: list = []
        fr = read_frame(read, off, size, why)
        if fr is None:
            reasons[why[0]] = reasons.get(why[0], 0) + 1
            stats["rejected_candidates"] = stats.get("rejected_candidates", 0) + 1
            pos = off + 1
            continue
        while fr is not None and yielded < max_frames:  # chain: contiguous frames
            yield fr
            yielded += 1
            nxt = fr.off + fr.length
            why = []
            fr = read_frame(read, nxt, size, why) if nxt + 24 <= size else None
            if fr is None and nxt < size and why and why[0] != "wrong magic":
                reasons[why[0]] = reasons.get(why[0], 0) + 1  # a plain run end is not an error
            pos = nxt
        # chain ended (non-DHAV bytes): continue scanning from pos
        yield None  # run boundary marker


class DhavParser(DahuaParser):
    """Registered in place of the identification-only DahuaParser (same signatures/identify)."""

    options_schema = OPTIONS
    parser_version = PARSER_VERSION

    def parse(self, f, size, options=None):
        opts = {k: v["default"] for k, v in OPTIONS.items()} | (options or {})
        try:
            return self._parse(f, size, opts)
        except Exception as exc:  # never raise: fall back to generic carving
            return fallback(
                self.vendor,
                self.vendor,
                self.tier,
                opts,
                f"parser error ({type(exc).__name__}: {exc}); generic carving stands",
            )

    def _parse(self, f, size, opts) -> ParseResult:
        stats = {
            "frames": 0,
            "video_frames": 0,
            "key_frames": 0,
            "audio_frames": 0,
            "other_frames": 0,
            "runs": 0,
            "annexb_frames": 0,
            "ext_mismatch_frames": 0,
        }
        reasons: dict = {}
        clips: list[ParsedClip] = []
        orphans: list[ParsedOrphan] = []
        active: dict[int, dict] = {}
        pending_orphan: dict[int, ParsedOrphan] = {}
        stamps: list[RawTimestamp] = []

        def close(ch, why):
            a = active.pop(ch, None)
            if a is None:
                return
            if a["frames"] < opts["min_clip_frames"]:
                orphans.append(
                    ParsedOrphan(ch, a["ext"][0][0], a["ext"][-1][1], a["frames"], "clip too short")
                )
                return
            c = ParsedClip(
                a["codec"],
                a["ext"],
                ch,
                a["frames"],
                a["keys"],
                a["codec"] in ("h264", "h265"),
                a["w"],
                a["h"],
                end_reason=why,
            )
            c.timestamps = [a["first_ts"], a["last_ts"]]
            c.fields = [
                ParsedField("channel", ch, "parsed", SRC + " byte 6"),
                ParsedField("codec", a["codec"], "parsed", SRC + " ext 0x81 codec id"),
                ParsedField(
                    "frame_numbers", f"{a['fn0']}..{a['fn1']}", "parsed", SRC + " bytes 8-11"
                ),
                ParsedField(
                    "clip_boundaries",
                    "frame_number continuity + key-frame start",
                    "inferred",
                    "heuristic; tolerance option frame_gap_tolerance",
                ),
            ]
            if a["codec"] not in ("h264", "h265"):
                c.notes.append(
                    f"codec {a['codec']} is not exported (exporter handles H.264/H.265 only)"
                )
            if a["non_annexb"]:
                c.notes.append(
                    f"{a['non_annexb']} payloads do not start with an Annex-B start code"
                )
            clips.append(c)

        def stamp(fr: Frame, name: str) -> RawTimestamp:
            raw, wall = decode_date(fr.date)
            return RawTimestamp(
                name,
                fr.off + 16,
                raw,
                "DHAV date u32 LE bit-packed (dhav.c get_timeinfo)",
                wall,
                "not assumed",
                f"frame {fr.number}, ts16={fr.ts16}",
            )

        for fr in iter_frames(f, size, stats, reasons, opts["max_frames_per_run"]):
            if fr is None:
                stats["runs"] += 1
                for ch in list(active):
                    close(ch, "end of contiguous DHAV frame run")
                continue
            stats["frames"] += 1
            if len(stamps) < 5:
                stamps.append(stamp(fr, "frame date"))
            if fr.type == 0xF0:
                stats["audio_frames"] += 1
                continue
            if fr.type == 0xF1:
                stats["other_frames"] += 1
                continue
            stats["video_frames"] += 1
            stats["key_frames"] += int(fr.type == 0xFD)
            stats["annexb_frames"] += int(bool(fr.annexb))
            stats["ext_mismatch_frames"] += int(fr.ext_mismatch)
            ch = fr.channel
            a = active.get(ch)
            if a is not None:
                delta = (fr.number - a["last_fn"]) & 0xFFFFFFFF
                changed = fr.type == 0xFD and (
                    fr.codec
                    and fr.codec != a["codec"]
                    or (fr.width and (fr.width, fr.height) != (a["w"], a["h"]))
                )
                if delta > opts["frame_gap_tolerance"] + 1 or changed:
                    close(
                        ch,
                        "frame_number discontinuity" if not changed else "codec/resolution change",
                    )
                    a = None
            if a is None:
                if fr.type != 0xFD:
                    o = pending_orphan.get(ch)
                    if o is not None and fr.off - o.end <= 64 + fr.length:
                        o.end, o.frames = fr.payload[1], o.frames + 1
                    else:
                        o = ParsedOrphan(
                            ch,
                            fr.payload[0],
                            fr.payload[1],
                            1,
                            "non-key video frames without a preceding key frame",
                        )
                        pending_orphan[ch] = o
                        orphans.append(o)
                    continue
                pending_orphan.pop(ch, None)
                a = active[ch] = {
                    "codec": fr.codec or "unknown",
                    "w": fr.width,
                    "h": fr.height,
                    "ext": [],
                    "frames": 0,
                    "keys": 0,
                    "fn0": fr.number,
                    "fn1": fr.number,
                    "last_fn": fr.number,
                    "first_ts": stamp(fr, "first frame date"),
                    "last_ts": None,
                    "non_annexb": 0,
                }
            a["ext"].append(list(fr.payload))
            a["frames"] += 1
            a["keys"] += int(fr.type == 0xFD)
            a["last_fn"] = a["fn1"] = fr.number
            a["last_ts"] = stamp(fr, "last frame date")
            a["non_annexb"] += int(fr.annexb is False)
        for ch in list(active):
            close(ch, "end of image")

        if stats["frames"] == 0:
            return ParseResult(
                self.vendor,
                self.vendor,
                self.tier,
                "fallback",
                opts,
                warnings=["no valid DHAV frame chain found; generic carving stands"],
                inconsistencies=[f"{k}: {v}" for k, v in sorted(reasons.items())[:10]],
                stats=stats,
            )
        incons = [f"{k}: {v} candidate(s) rejected" for k, v in sorted(reasons.items())]
        if stats["ext_mismatch_frames"]:
            incons.append(
                f"{stats['ext_mismatch_frames']} frames: extension TLVs consumed != declared length"
            )
        fields = [
            ParsedField(
                "frame_header", "DHAV magic/type/channel/frame number/length/date", "parsed", SRC
            ),
            ParsedField(
                "frame_trailer",
                "dhav + u32 == length-8 (verified per frame)",
                "parsed",
                SRC + " (derived arithmetic)",
            ),
            ParsedField(
                "extension_tlvs",
                "0x80/0x81/0x82 and size-skipped others",
                "parsed",
                SRC + " parse_ext",
            ),
            ParsedField(
                "date",
                "raw u32 + plain wall-clock decode, no timezone",
                "parsed",
                SRC + " get_timeinfo",
                "timezone not stated in the source (local wall clock is inferred): NOT assumed",
            ),
            ParsedField(
                "payload_format",
                f"Annex-B in {stats['annexb_frames']}/{stats['video_frames']} video frames",
                "inferred",
                "FFmpeg feeds payload to H.264/HEVC decoders; checked per frame",
            ),
            ParsedField(
                "checksum_byte",
                "present at header byte 23",
                "unknown",
                SRC,
                "dhav.c skips it; algorithm undocumented, not verified",
            ),
            ParsedField(
                "subtype_byte", "present at header byte 5", "unknown", SRC, "meaning not documented"
            ),
            ParsedField(
                "dhfs_structures",
                "not parsed",
                "unknown",
                "RESEARCH 3.2",
                "DHFS layout undocumented",
            ),
        ]
        return ParseResult(
            self.vendor,
            self.vendor,
            self.tier,
            "partial" if incons else "parsed",
            opts,
            fields,
            clips,
            orphans,
            stamps,
            [],
            incons,
            stats,
        )
