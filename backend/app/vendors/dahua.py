"""Dahua identification via DHAV frames. Source: docs/RESEARCH.md section 3.2 (FFmpeg dhav.c [S9]).

A frame is `DHAV` + type byte (0xf0 audio, 0xf1 other, 0xfc non-key video, 0xfd key video),
channel at byte 6, u32 LE frame length at bytes 12-15 (covers header + payload + 8-byte trailer),
and a trailer `dhav` + u32 LE (= frame length - 8) located at frame_start + length - 8. The
trailer relation follows dhav.c: `pos = trailer_offset - u32 + 8` (get_duration, lines ~272-284)
and `payload = frame_length - 8 - header` (read_chunk). Validation here uses that relation, so a
bare `DHAV` string (random data, text) is not enough. The DHFS on-disk structures are not
documented in what we read, so only DHAV frames are used.
"""

import struct

from app.vendors.base import Match, Probe, Scope, Signature, VendorParser

TYPES = {0xF0: "audio", 0xF1: "other", 0xFC: "video non-key", 0xFD: "video key"}
MAX_FRAME = 16 * 1024 * 1024


def _frame(read, off: int) -> str | None:
    hdr = read(off, 24)
    if len(hdr) < 24 or hdr[4] not in TYPES:
        return None
    (length,) = struct.unpack_from("<I", hdr, 12)
    if not 24 <= length <= MAX_FRAME:
        return None
    trailer = read(off + length - 8, 8)
    if (
        len(trailer) < 8
        or trailer[:4] != b"dhav"
        or struct.unpack("<I", trailer[4:])[0] != length - 8
    ):
        return None
    return f"DHAV {TYPES[hdr[4]]} frame, channel {hdr[6]}, length {length}, trailer verified"


def _file_prefix(b: bytes) -> str | None:
    return (
        "'DAHUA' file prefix (exported DAV file, not an on-disk DHFS signature)"
        if b == b"DAHUA"
        else None
    )


class DahuaParser(VendorParser):
    vendor = "Dahua"
    tier = "B"
    sources = ("RESEARCH 3.2: FFmpeg libavformat/dhav.c [S9]",)

    def probes(self):
        return [Probe("dahua_file_prefix", 0, 5, _file_prefix)]

    def signatures(self):
        return [Signature("dahua_dhav_frame", b"DHAV", _frame)]

    def identify(self, scope: Scope) -> Match:
        frames = scope.counts.get("dahua_dhav_frame", 0)
        if not frames and not scope.counts.get("dahua_file_prefix"):
            return self.empty_match()
        evidence = scope.hits.get("dahua_file_prefix", []) + scope.hits.get("dahua_dhav_frame", [])
        notes = [
            "Identified from DHAV frames (container), not DHFS disk structures (undocumented).",
            "CP Plus is NOT assumed to be Dahua-compatible; only a real image can show that.",
        ]
        return Match(
            self.vendor,
            self.tier,
            "medium" if frames >= 3 else "low",
            evidence[:40],
            self.own_counts(scope),
            list(self.sources),
            notes,
        )
