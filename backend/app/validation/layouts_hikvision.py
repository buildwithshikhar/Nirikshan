"""SYNTHETIC Hikvision image builder: "per-paper layout, not a real device image".

Built ONLY from fields documented in docs/parsers/hikvision-fields.md (cited "fields s<N>"):
Master Sector, backup Master Sector, system-log area with RATS records, HIKBTREE (header, page
list, pages, footer, 48-byte data-block entries), data blocks holding raw Annex-B H.264 and a tail
IDR table. Every byte the document marks unknown is 0x00 (or the figure's FF where the figure shows
FF in an unlabelled cell) and is marked below. Because the parser is written from the same document,
parsing this layout is a CIRCULAR check (self-consistency), not validation against real devices.

Choices the document leaves open, made here and visible to the parser as inferences:
  * block size field: 0x80000 (small, to keep images a few MiB; the real value is the s7 conflict)
  * Master Sector signature at absolute 0x210 by default (Dragonas); 0x200 selectable
  * backup Master Sector placed 0x200 bytes after the log area (location undocumented, s1)
  * page-list slot stride 8, first entry at page+0x10, two pages (undocumented, s4.2/s4.4)
  * IDR table: one 56-byte record per IDR picture, 'OFNI' + 52 zero bytes (field layout unknown, s3)
  * no 00 00 01 BA/BC prefix headers (their payload is unknown, s5)
"""

import random
import struct
from collections.abc import Callable

from app.validation.image import BANNER, Builder
from app.validation.scenarios import pick
from app.validation.streams import Stream, StreamPool

LAYOUT = (
    "hikvision-fs: per-paper layout (Han 2015 + Dragonas 2023 via docs/parsers/hikvision-fields.md;"
    " Master Sector, HIKBTREE, RATS logs, data blocks), not a real device image"
)
SIG = b"HIKVISION@HANGZHOU"
BLOCK = 0x80000
LOG_OFF, LOG_SIZE = 0x1000, 0x4000
VIDEO_OFF = 0x8000
BT_SIZE = 0x6000
INIT_T = 1417093687  # fields s1 sample value (raw seconds; no timezone meaning here)
T0 = 1417100000
SENTINEL = bytes.fromhex("FFFFFF7F00000000")


def master_sector(
    base: int, capacity: int, block_count: int, block_size: int, hik1: int, hik2: int
) -> bytes:
    """256-byte Master Sector starting at the signature (struct offsets, fields s1)."""
    s = bytearray(0x100)
    s[: len(SIG)] = SIG
    s[0x20:0x2E] = b"HIK.2011.03.08"  # version-like string, meaning unknown
    struct.pack_into("<Q", s, 0x38, capacity)
    struct.pack_into("<Q", s, 0x50, LOG_OFF)
    struct.pack_into("<Q", s, 0x58, LOG_SIZE)
    struct.pack_into("<Q", s, 0x68, VIDEO_OFF)
    struct.pack_into("<Q", s, 0x78, block_size)
    struct.pack_into("<I", s, 0x80, block_count)
    struct.pack_into("<QI", s, 0x88, hik1, BT_SIZE)
    struct.pack_into("<QI", s, 0x98, hik2, BT_SIZE)
    struct.pack_into("<I", s, 0xE0, INIT_T)
    # unlabelled bytes (+0x41, +0x48, +0x60, +0x70, +0xA4..0xDF, +0xE4..) stay 0x00: unknown
    return bytes(s)


def rats(
    variant: bytes, t: int, major: int, minor: int, user: str, ip: str, n: int = 0x40
) -> bytes:
    """RATS record (fields s2): sig, variant, time, major, minor, Details. Length is NOT a
    documented field; records are laid out back to back, `n` bytes each (unknown tail = 0)."""
    r = bytearray(n)
    r[:4] = b"RATS"
    r[4:8] = variant
    struct.pack_into("<IHH", r, 8, t, major, minor)
    if major == 3:  # Operation Details: 16-byte user name + 4-byte IP (Dragonas p.67)
        r[0x10 : 0x10 + len(user)] = user.encode()
        r[0x20:0x24] = bytes(int(x) for x in ip.split("."))
    return bytes(r)


def log_area(variant: bytes = b"\x14\x00\x00\x00") -> bytes:
    """Log area: 2048 undeciphered preamble bytes (0x00 here, s2) then back-to-back records."""
    recs = [
        (3, 0x70, "admin", "192.168.10.100"),  # Operation / Remote: Login
        (3, 0x50, "admin", "192.168.10.101"),  # Operation / Local: Login
        (4, 0xA3, "", ""),  # Information / Start Record
        (1, 0x03, "", ""),  # Alarm / Start Motion Detection
        (2, 0x24, "", ""),  # Exception / HDD Error
        (4, 0xA4, "", ""),  # Information / Stop Record
    ]
    out = bytearray(0x800)
    for i, (ma, mi, u, ip) in enumerate(recs):
        out += rats(variant, T0 + 60 * i, ma, mi, u, ip)
    return bytes(out).ljust(LOG_SIZE, b"\x00")


def entry(exists: bool, channel: int, start: int, end: int, block: int) -> bytes:
    """48-byte HIKBTREE data-block entry (fields s4.4). +0x00 and +0x28 are documented unknown."""
    e = bytearray(48)
    e[0:8] = b"\xff" * 8  # unlabelled; FF in all three sample entries
    e[8:16] = (b"\x00" if exists else b"\xff") * 8
    e[0x11] = channel
    if exists and start is not None:
        struct.pack_into("<II", e, 0x18, start, end)
    else:
        e[0x18:0x20] = SENTINEL
    struct.pack_into("<Q", e, 0x20, block)
    return bytes(e)


def hikbtree(base: int, entries: list[bytes], created: int = INIT_T + 4) -> bytes:
    """HIKBTREE (fields s4): header +0, page list +0x1000, pages +0x2000/+0x3000, footer +0x5000."""
    b = bytearray(BT_SIZE)
    b[:8] = b"HIKBTREE"
    b[0x10:0x1E] = b"HIK.2010.11.09"
    struct.pack_into("<I", b, 0x2C, created)
    # +0x30 footer, +0x38 duplicate of footer (unlabelled), +0x40 page list, +0x48 page #1
    struct.pack_into("<QQQQ", b, 0x30, base + 0x5000, base + 0x5000, base + 0x1000, base + 0x2000)
    per = (4096 - 0x10) // 48
    pages = [entries[i : i + per] for i in range(0, max(len(entries), 1), per)][:2]
    struct.pack_into("<I", b, 0x1000, len(pages))
    for k, pg in enumerate(pages):
        struct.pack_into("<Q", b, 0x1008 + 8 * k, base + 0x2000 + 0x1000 * k)  # slot stride 8
        for j, e in enumerate(pg):
            o = 0x2000 + 0x1000 * k + 0x10 + 48 * j  # first entry at page+0x10 (undocumented)
            b[o : o + 48] = e
    struct.pack_into("<Q", b, 0x5000, base + 0x2000 + 0x1000 * (len(pages) - 1))
    b[0x5008:0x5010] = b"\xff" * 8
    return bytes(b)


def build_image(
    rng: random.Random,
    blocks: list[dict],
    *,
    master_base: int = 0x210,
    block_size: int = BLOCK,
    variant: bytes = b"\x14\x00\x00\x00",
    extra_empty_blocks: int = 1,
) -> tuple[bytes, dict, dict]:
    """blocks: dicts with keys stream (Stream|None), cid, channel, exists (bool), times
    ((start, end) | None -> sentinel), zero (optional (a, b) stream-byte range zeroed after
    placement). Returns (image, clips for Builder.from_layout, layout metadata)."""
    nblocks = len(blocks) + extra_empty_blocks
    hik1 = VIDEO_OFF + nblocks * block_size
    hik2 = hik1 + BT_SIZE
    size = hik2 + BT_SIZE
    img = bytearray(size)
    img[: len(BANNER)] = BANNER  # synthetic marker; bytes 0x100..0x1FF otherwise zero
    sec = master_sector(master_base, size, nblocks, block_size, hik1, hik2)
    img[master_base : master_base + 0x100] = sec
    img[LOG_OFF : LOG_OFF + LOG_SIZE] = log_area(variant)
    backup = LOG_OFF + LOG_SIZE + 0x200  # location undocumented (s1): synthetic choice
    img[backup : backup + 0x100] = sec
    ents: list[bytes] = []
    clips: dict = {}
    for i, blk in enumerate(blocks):
        bo = VIDEO_OFF + i * block_size
        s: Stream | None = blk.get("stream")
        if s is not None:
            img[bo : bo + len(s.data)] = s.data
            nidr = sum(1 for n in s.nals if n.irap)
            end = bo + block_size
            for k in range(1, nidr + 1):  # record k at block_end - 56*k (s3, partly documented)
                img[end - 56 * k : end - 56 * k + 4] = b"OFNI"  # remaining 52 bytes: unknown
            if blk.get("zero"):
                a, b2 = blk["zero"]
                img[bo + a : bo + b2] = b"\x00" * (b2 - a)
            clips[blk["cid"]] = (
                s,
                [(bo, bo + len(s.data), 0)],
                {
                    "expected": blk.get("expected", "recover"),
                    "channel": blk["channel"],
                    "state": blk.get("state", "live"),
                },
            )
        t = blk.get("times")
        ents.append(
            entry(blk["exists"], blk["channel"], t[0] if t else None, t[1] if t else None, bo)
        )
    ents.append(entry(False, 0xFF, None, None, VIDEO_OFF + len(blocks) * block_size))  # unused
    for base in (hik1, hik2):
        img[base : base + BT_SIZE] = hikbtree(base, ents)
    meta = {
        "hik1": hik1,
        "hik2": hik2,
        "block_size": block_size,
        "blocks": nblocks,
        "backup_master": backup,
        "master_base": master_base,
    }
    return bytes(img), clips, meta


def _wrap(rng, blocks, notes, **kw) -> Builder:
    img, clips, _meta = build_image(rng, blocks, **kw)
    return Builder.from_layout(rng, LAYOUT, img, clips, notes)


def _blk(i, s, ch, **kw) -> dict:
    t0 = T0 + i * 1000
    return {
        "stream": s,
        "cid": f"c{i}",
        "channel": ch,
        "exists": True,
        "times": (t0, t0 + 600),
    } | kw


def clean_live(rng, pool: StreamPool, _i):
    ss = pick(rng, pool, 3, "h264")
    blocks = [_blk(i, s, 1) for i, s in enumerate(ss)]
    blocks[-1]["times"] = None  # block still being recorded: existence 00 + sentinel (s4.4)
    return _wrap(rng, blocks, ["3 blocks, channel 1; last block times are the sentinel"])


def deleted_intact_zero(rng, pool: StreamPool, _i):
    ss = pick(rng, pool, 3, "h264")
    blocks = [_blk(i, s, 1 + i) for i, s in enumerate(ss)]
    for i in (1, 2):  # entries cleared (existence FF, channel FF, sentinel); data left intact
        blocks[i].update(exists=False, channel=0xFF, times=None, state="deleted")
    return _wrap(rng, blocks, ["blocks 1 and 2: HIKBTREE entries cleared, video bytes intact"])


def partial_overwrite_zero(rng, pool: StreamPool, _i):
    ss = pick(rng, pool, 2, "h264")
    victim = ss[1]
    cut = rng.choice([n.start for n in victim.nals[1:] if not n.param][2:-2])
    blocks = [_blk(0, ss[0], 1), _blk(1, victim, 2, state="deleted", times=None)]
    blocks[1]["zero"] = (cut, len(victim.data))  # tail of the victim zeroed in place
    return _wrap(rng, blocks, [f"victim block 1 zeroed from stream offset {cut}; entry kept"])


def multi_channel_gop(rng, pool: StreamPool, _i):
    ss = pick(rng, pool, 5, "h264")
    chans = [1, 2, 1, 3, 2]
    blocks = [_blk(i, s, ch) for i, (s, ch) in enumerate(zip(ss, chans, strict=True))]
    return _wrap(rng, blocks, [f"channels from HIKBTREE entries: {chans}"])


SCENARIOS: dict[str, Callable[[random.Random, StreamPool, int], Builder]] = {
    "clean_live": clean_live,
    "deleted_intact_zero": deleted_intact_zero,
    "partial_overwrite_zero": partial_overwrite_zero,
    "multi_channel_gop": multi_channel_gop,
}
