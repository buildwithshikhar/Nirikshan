"""Vendor layouts for SYNTHETIC images, built ONLY from fields documented in docs/RESEARCH.md.

Every layout is "per-paper layout, not a real device image". Because the parsers are written from
the same documents, parser-vs-same-layout results are a circular check, not independent validation.
"""

import struct
from datetime import datetime, timedelta

from app.validation.streams import NalInfo, Stream

LAYOUT_RAW = "raw: generic elementary-stream placement (no vendor structures)"
LAYOUT_DHAV = (
    "dahua-dhav: per-paper layout (FFmpeg dhav.c DHAV frame format; DHFS not modelled), "
    "not a real device image"
)
CODEC_ID = {"h264": 0x08, "h265": 0x0C}
BASE_DATE = (2025, 6, 1, 12, 0, 0)  # arbitrary synthetic wall-clock start (no timezone meaning)


def pack_date(year, month, day, hour, minute, sec) -> int:
    return (year - 2000) << 26 | month << 22 | day << 17 | hour << 12 | minute << 6 | sec


def frame_date(number: int) -> int:
    """Synthetic wall clock: BASE_DATE plus number // 25 seconds, packed correctly."""
    t = datetime(*BASE_DATE) + timedelta(seconds=number // 25)
    return pack_date(t.year, t.month, t.day, t.hour, t.minute, t.second)


def dhav_frame(
    ftype: int,
    channel: int,
    number: int,
    payload: bytes,
    *,
    ext: bytes = b"",
    date: int | None = None,
    ts16: int = 0,
    subtype: int = 0,
    checksum: int = 0,
) -> tuple[bytes, int]:
    """DHAV frame bytes and the payload offset inside it. Header 24 bytes + ext + payload + 8."""
    hdr_len = 24 + len(ext)
    length = hdr_len + len(payload) + 8
    d = date if date is not None else frame_date(number)
    h = b"DHAV" + bytes([ftype, subtype, channel, 0]) + struct.pack("<III", number, length, d)
    h += struct.pack("<H", ts16 & 0xFFFF) + bytes([len(ext), checksum]) + ext
    return h + payload + b"dhav" + struct.pack("<I", length - 8), hdr_len


def dhav_ext(codec: str, width: int, height: int, fps: int = 25) -> bytes:
    """0x82 (u16 width/height, 8 bytes) + 0x81 (codec id + fps, 4 bytes) TLVs."""
    return (b"\x82\x00\x00\x00" + struct.pack("<HH", width, height)) + bytes(
        [0x81, 0, CODEC_ID[codec], fps]
    )


def access_units(stream: Stream, a: int, b: int) -> list[list[NalInfo]]:
    """Group NAL units starting in [a, b) into access units (non-VCL NALs + one VCL NAL)."""
    out, cur = [], []
    for n in stream.nals:
        if not (a <= n.start < b):
            continue
        cur.append(n)
        if n.vcl:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def wrap_stream(
    stream: Stream, a: int, b: int, channel: int, number0: int
) -> list[tuple[bytes, int, int, int]]:
    """Frames for stream bytes [a, b): (frame_bytes, payload_offset, payload_len, stream_start)."""
    frames = []
    v = stream.variant
    w, h = (int(x) for x in v.size.split("x"))
    for i, au in enumerate(access_units(stream, a, b)):
        s, e = au[0].start, au[-1].end
        key = any(n.irap for n in au)
        payload = stream.data[s:e]
        ext = dhav_ext(v.codec, w, h) if key else b""
        fr, off = dhav_frame(
            0xFD if key else 0xFC, channel, number0 + i, payload, ext=ext, ts16=(number0 + i) * 40
        )
        frames.append((fr, off, len(payload), s))
    return frames
