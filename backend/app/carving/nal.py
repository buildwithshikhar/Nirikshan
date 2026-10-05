"""Streaming Annex-B start-code scanner (bounded memory, chunk-boundary safe) and NAL header decode.

Header layouts, checked against FFmpeg master (libavcodec/h2645_parse.c, hevc/hevc.h) on 2026-10-05:
  * H.264 NAL header, 1 byte: forbidden_zero_bit(1) nal_ref_idc(2) nal_unit_type(5).
    Types used here: 1 non-IDR slice, 5 IDR slice, 6 SEI, 7 SPS, 8 PPS, 9 AUD, 10/11 end of
    sequence/stream, 12 filler.
  * H.265 NAL header, 2 bytes: forbidden_zero_bit(1) nal_unit_type(6) nuh_layer_id(6)
    nuh_temporal_id_plus1(3). So type = (b0 >> 1) & 0x3F, layer = ((b0 & 1) << 5) | (b1 >> 3),
    temporal_id_plus1 = b1 & 7 and must be >= 1 (hevc_parse_nal_header: get_bits1, get_bits(6),
    get_bits(6), get_bits(3)-1 with temporal_id < 0 rejected).
    IRAP types 16..23 (BLA 16-18, IDR_W_RADL 19, IDR_N_LP 20, CRA 21, reserved 22-23);
    VPS 32, SPS 33, PPS 34, AUD 35, EOS 36, EOB 37, FD 38, prefix SEI 39, suffix SEI 40.
  * Inside a NAL unit the byte sequences 00 00 00, 00 00 01 and 00 00 02 cannot occur
    (emulation prevention, 00 00 03). The carver relies on this to detect where a NAL ends
    (trailing zeros / zero-filled gaps); the tests assert it on ffmpeg-generated streams. The ITU
    text itself was not available to us (docs/RESEARCH.md section 5), only FFmpeg's parser.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

CHUNK = 4 * 1024 * 1024
HEAD = 16  # bytes after the start code handed to the carver (header + leading slice fields)

# start code with its leading zero run, or a run of >=3 zeros that is NOT followed by 0x01
_RE = re.compile(rb"\x00\x00+\x01|\x00\x00\x00+")


@dataclass(frozen=True)
class StartCode:
    run_start: int  # first byte of the zero run in front of the 01 (previous NAL ends here)
    sc_start: int  # first byte of the 3- or 4-byte start code (this NAL starts here)
    hdr: int  # offset of the NAL header byte
    head: bytes  # up to HEAD bytes starting at the NAL header


@dataclass(frozen=True)
class ZeroRun:
    pos: int  # run of >=3 zero bytes not followed by 01: the current NAL ended here


@dataclass(frozen=True)
class Eof:
    size: int


def scan(f: BinaryIO, size: int, chunk: int = CHUNK) -> Iterator[StartCode | ZeroRun | Eof]:
    """Yield start codes / zero runs in file order. Memory is O(chunk), not O(image).

    `chunk` is a parameter so tests can use tiny chunks to exercise boundary handling.
    """
    pos = 0
    carry, carry_base = b"", 0
    while True:
        f.seek(pos)
        data = f.read(chunk)
        pos += len(data)
        eof = not data or pos >= size
        buf, base = carry + data, carry_base
        keep = None
        for m in _RE.finditer(buf):
            s, e = m.span()
            if buf[e - 1] == 1:
                if not eof and e + HEAD > len(buf):
                    keep = s  # need more bytes after the start code; re-scan from here
                    break
                if e >= len(buf):
                    continue  # start code at EOF with no header byte
                run_len = e - s - 1
                yield StartCode(
                    base + s, base + e - (4 if run_len >= 3 else 3), base + e, buf[e : e + HEAD]
                )
            else:
                yield ZeroRun(base + s)
        if eof:
            break
        if keep is None:
            tz = 0
            while tz < 3 and tz < len(buf) and buf[-1 - tz] == 0:
                tz += 1
            keep = len(buf) - tz
        carry, carry_base = buf[keep:], base + keep
    yield Eof(size)


# ---- header decode -------------------------------------------------------------------------

H264_OK_TYPES = {1, 5, 6, 7, 8, 9, 10, 11, 12}
H265_OK_TYPES = set(range(0, 10)) | set(range(16, 22)) | set(range(32, 41))


def h264_type(b0: int) -> int | None:
    return None if b0 & 0x80 else b0 & 0x1F


def h265_header(b0: int, b1: int) -> tuple[int, int, int] | None:
    """(type, layer_id, temporal_id_plus1) or None if the header is invalid."""
    if b0 & 0x80:
        return None
    tid = b1 & 7
    if tid == 0:
        return None
    return (b0 >> 1) & 0x3F, ((b0 & 1) << 5) | (b1 >> 3), tid


def classify_param(head: bytes) -> tuple[str, str] | None:
    """Return (codec, 'vps'|'sps'|'pps') if the header is a parameter set, else None.

    The two codecs' parameter-set header bytes are disjoint: H.264 needs nal_ref_idc != 0.
    """
    if not head:
        return None
    b0 = head[0]
    t = h264_type(b0)
    if t in (7, 8) and b0 & 0x60:
        return "h264", "sps" if t == 7 else "pps"
    if len(head) > 1:
        h = h265_header(b0, head[1])
        if h and h[1] == 0 and h[0] in (32, 33, 34):
            return "h265", {32: "vps", 33: "sps", 34: "pps"}[h[0]]
    return None
