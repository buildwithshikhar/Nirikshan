"""SYNTHETIC Honeywell layout: per-paper layout, not a real device image.

Built ONLY from fields the field doc (docs/parsers/honeywell-fields.md, section numbers below)
records as documented/partly documented from arXiv:2605.07430. Parser-vs-this-layout results are
a circular check (both come from the same document), not validation against a device.

Deliberate simplifications (the real device is far larger than a test image):
  * The real Video Data starts at partition-relative 0x80000000 (abs 0x80005000, field doc 2.6),
    i.e. > 2 GiB in. Here the video chunks start at abs VIDEO_ABS (about 4 MiB) and the Channel
    Index points at them; the Partition 1 header still carries the documented Video Data Offset,
    which therefore lies beyond this image. The parser treats that as a truncated/compact image.
  * Unknown bytes are zero: Protective MBR, bytes the field doc marks unknown, Record State, Fixed
    Value, Partition 2, the secondary GPT and the primary header's alternate LBA (all zero or
    omitted). Sector 0 holds the SYNTHETIC banner instead of an MBR (unknown in the paper).
  * Padding after the end-of-channel delimiter is 0x00: P says a dummy value is stored but not
    which (field doc 3.1).
  * The custom-header length is written as the whole access-unit span following the header
    (start codes included); P does not state its semantic (field doc 3). SPS/PPS/IDR sit under one
    0x82 header as in P's Fig. 8 (field doc 3).
  * No channel byte exists in the custom header (field doc 4); the channel id lives only in the
    Channel Index entry written for each "indexed" chunk. Deleted chunks (expiration, field doc
    2.7) have no index entry.
"""

import random
import struct
import uuid
import zlib
from collections.abc import Callable

from app.validation.image import BANNER, Builder
from app.validation.layouts import access_units
from app.validation.streams import Stream, StreamPool, pick

LAYOUT = (
    "honeywell: per-paper layout (field doc docs/parsers/honeywell-fields.md, arXiv 2605.07430), "
    "not a real device image"
)
SECTOR = 512
P1_ABS = 40 * SECTOR  # field doc 1.1: Partition 1 starts at LBA 40
PAGE = 0x1000  # field doc 2.0 (derived unit)
VIDEO_ABS = 0x410000  # compact placement, see module docstring
BASE_US = 1_750_000_000_000_000  # arbitrary synthetic instant; no timezone meaning
FRAME_US = 40_000
PAD_BYTE = 0x00  # unknown in the paper


def _gpt(total_lba: int) -> bytes:
    """Sectors 0-33: banner, standard GPT header (sector 1) and 128-entry array (sectors 2-33).
    GPT field layout is UEFI standard; the paper prints no GPT bytes (field doc 1.2)."""
    out = bytearray(34 * SECTOR)
    out[: len(BANNER)] = BANNER
    arr = bytearray(128 * 128)
    p1_last = total_lba - 1
    for i, (first, last, name) in enumerate(
        ((40, p1_last, "Partition 1"), (p1_last + 1, p1_last + 20_971_520, "Partition 2"))
    ):
        e = uuid.UUID(int=0x11 + i).bytes_le + uuid.UUID(int=0x2200 + i).bytes_le
        e += struct.pack("<QQQ", first, last, 0) + name.encode("utf-16-le").ljust(72, b"\x00")
        arr[i * 128 : (i + 1) * 128] = e
    h = bytearray(92)
    # alternate LBA is 0: the paper places the secondary header at sector 32 of the final 2 GB
    # region and does not show this field (field doc 1.5)
    struct.pack_into(
        "<8sIIIIQQQQ16sQIII",
        h,
        0,
        b"EFI PART",
        0x00010000,
        92,
        0,
        0,
        1,
        0,
        40,
        total_lba - 1,
        uuid.UUID(int=0x99).bytes_le,
        2,
        128,
        128,
        zlib.crc32(bytes(arr)) & 0xFFFFFFFF,
    )
    struct.pack_into("<I", h, 16, zlib.crc32(bytes(h)) & 0xFFFFFFFF)
    out[SECTOR : SECTOR + 92] = h
    out[2 * SECTOR : 2 * SECTOR + len(arr)] = arr
    return bytes(out)


def _machine_data() -> bytes:
    """Sector 34 (field doc 1.3, Fig. 3): the two grey strings, device ID, model."""
    s = bytearray(SECTOR)
    s[0x00:0x10] = b"sn private disk\x00"
    s[0x20:0x23] = b"2.2"
    s[0x40:0x51] = b"B011003AWFNRZEFKV"
    s[0x68:0x72] = b"HN350802xx"
    return bytes(s)


def custom_header(key: bool, w: int, h: int, length: int, ts_us: int) -> bytes:
    """20 bytes: flag, 80 01 00, u16 w, u16 h, u32 length, u64 time (all LE; field doc 3)."""
    return (
        bytes([0x82 if key else 0x02]) + b"\x80\x01\x00" + struct.pack("<HHIQ", w, h, length, ts_us)
    )


def chunk(stream: Stream, a: int, b: int, t0_us: int) -> tuple[bytes, list[tuple[int, int, int]]]:
    """One per-channel chunk (field doc 2.6/3): headers + access units, 20-zero delimiter,
    padding to 4 KiB. Returns (bytes, [(offset_in_chunk, payload_len, stream_start)])."""
    w, h = (int(x) for x in stream.variant.size.split("x"))
    out, pieces = bytearray(), []
    for i, au in enumerate(access_units(stream, a, b)):
        s, e = au[0].start, au[-1].end
        key = any(n.irap for n in au)
        out += custom_header(key, w, h, e - s, t0_us + i * FRAME_US)
        pieces.append((len(out), e - s, s))
        out += stream.data[s:e]
    out += bytes(20)
    out += bytes([PAD_BYTE]) * (-len(out) % PAGE)
    return bytes(out), pieces


def build_image(
    chunks: list[dict], *, tail: int = 8192
) -> tuple[bytearray, dict, list[tuple[int, int]]]:
    """chunks: dicts with id, stream, a, b, indexed (bool), channel (int id for the Channel Index).
    Returns (image, clips for Builder.from_layout, [(chunk_start, data_end)] per chunk)."""
    body, clips, spans, entries = bytearray(), {}, [], []
    for k, c in enumerate(chunks):
        a, b = c.get("a", 0), c.get("b", len(c["stream"].data))
        t0 = BASE_US + k * 600_000_000  # ten minutes apart
        data, pieces = chunk(c["stream"], a, b, t0)
        start = VIDEO_ABS + len(body)
        body += data
        clips[c["id"]] = (
            c["stream"],
            [(start + o, start + o + n, ss) for o, n, ss in pieces],
            {"expected": "recover", "state": "live" if c["indexed"] else "deleted"},
        )
        spans.append((start, start + pieces[-1][0] + pieces[-1][1]))
        if c["indexed"]:
            entries.append((c["channel"], len(data) // PAGE, t0 // 1_000_000, start))
    body += bytes(tail)
    total = VIDEO_ABS + len(body)
    img = bytearray(total)
    img[: 34 * SECTOR] = _gpt(total // SECTOR)
    img[34 * SECTOR : 35 * SECTOR] = _machine_data()
    # Partition 1 header (field doc 2.1): documented Video Data Offset (0x80000000 / 4 KiB), the
    # other three fields use plausible values; bytes 0x04-0x07 etc. zero (unknown).
    struct.pack_into("<I", img, P1_ABS + 0x00, 0x80000000 // PAGE)
    struct.pack_into("<I", img, P1_ABS + 0x08, 0x80000000 // PAGE + 0x10)
    struct.pack_into("<I", img, P1_ABS + 0x10, 0x01BB33D1 - 0x10)
    struct.pack_into("<I", img, P1_ABS + 0x18, 0x01BB33D1)
    if entries:  # Block Group Index entry 0 (field doc 2.1): time at +4, group number at +0x0C
        t_min = min(e[2] for e in entries)
        img[P1_ABS + 0x40 + 4 : P1_ABS + 0x40 + 8] = struct.pack("<I", t_min)
        img[P1_ABS + 0x40 + 0x0C] = 1
    for i, (ch, pages, t, start) in enumerate(entries):
        # Video Block List (field doc 2.2): +4 time, +0x0C block number, +0x0D group number
        o = P1_ABS + 0x40000 + 16 * i
        img[o + 4 : o + 8] = struct.pack("<I", t)
        img[o + 0x0C], img[o + 0x0D] = i, 1
        # Channel Index (field doc 2.3): id, stream type 0x00, length and start in 4 KiB units
        o = P1_ABS + 0x400000 + 16 * i
        img[o] = ch
        img[o + 2 : o + 4] = struct.pack("<H", pages)
        img[o + 4 : o + 8] = struct.pack("<I", t)
        img[o + 8 : o + 12] = struct.pack("<I", (start - P1_ABS) // PAGE)
    img[VIDEO_ABS:] = body
    return img, clips, spans


def _h264(rng: random.Random, pool: StreamPool, n: int) -> list[Stream]:
    return pick(rng, pool, n, "h264")


def _chunks(streams: list[Stream], indexed: list[bool]) -> list[dict]:
    return [
        {"id": f"c{i}", "stream": s, "indexed": ix, "channel": i + 1}
        for i, (s, ix) in enumerate(zip(streams, indexed, strict=True))
    ]


NOTE = "Honeywell per-paper layout: no channel byte in the header; channel only via Channel Index"


def clean_live(rng: random.Random, pool: StreamPool, _i: int) -> Builder:
    img, clips, _ = build_image(_chunks(_h264(rng, pool, 3), [True] * 3))
    return Builder.from_layout(rng, LAYOUT, bytes(img), clips, [NOTE])


def deleted_intact_zero(rng: random.Random, pool: StreamPool, _i: int) -> Builder:
    """Video intact, Channel Index entries removed for deleted clips (field doc 2.7)."""
    img, clips, _ = build_image(_chunks(_h264(rng, pool, 3), [True, False, False]))
    return Builder.from_layout(rng, LAYOUT, bytes(img), clips, [NOTE, "index entries removed"])


def partial_overwrite_zero(rng: random.Random, pool: StreamPool, _i: int) -> Builder:
    streams = _h264(rng, pool, 2)
    img, clips, spans = build_image(_chunks(streams, [True, False]))
    s, e = spans[1]
    frac = rng.choice([0.2, 0.4, 0.6])
    where = rng.choice(["head", "middle", "tail"])
    length = int((e - s) * frac)
    start = {"head": 0, "middle": (e - s - length) // 2, "tail": e - s - length}[where]
    img[s + start : s + start + length] = bytes(length)
    return Builder.from_layout(
        rng, LAYOUT, bytes(img), clips, [NOTE, f"zero overwrite of {where} {frac:.0%}"]
    )


SCENARIOS: dict[str, Callable[[random.Random, StreamPool, int], Builder]] = {
    "clean_live": clean_live,
    "deleted_intact_zero": deleted_intact_zero,
    "partial_overwrite_zero": partial_overwrite_zero,
}
