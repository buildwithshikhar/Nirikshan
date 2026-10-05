"""Honeywell identification. Source: docs/RESEARCH.md section 3.4 (arXiv 2605.07430 [S5]).

Documented for ONE model (HN35080200, H.264 only). Custom 20-byte header before each NAL:
byte 0 frame type (0x82 IDR / 0x02 non-IDR), bytes 1-3 `80 01 00`, 4-7 resolution, 8-11 NAL
length, 12-19 Unix time in microseconds, followed by `00 00 00 01` + NAL header. The paper's
integer byte order is not stated in what we read, so length and time are accepted in either
order. The "Machine Data" sector 34 (offset 0x4400) holds device ID / model strings
(e.g. HN350802xx). The paper's tools repository has no licence: nothing was copied.
"""

import re
import struct

from app.vendors.base import Match, Probe, Scope, Signature, VendorParser

MACHINE_OFFSET = 34 * 512
US_MIN, US_MAX = (
    946_684_800 * 10**6,
    4_102_444_800 * 10**6,
)  # 2000-01-01 .. 2100-01-01 in microseconds
_MODEL = re.compile(rb"HN\d{4,}")


def _header(read, off: int) -> str | None:
    start = off - 1
    if start < 0:
        return None
    h = read(start, 25)
    if len(h) < 25 or h[0] not in (0x82, 0x02) or h[20:24] != b"\x00\x00\x00\x01":
        return None
    nal_hdr = h[24]
    if nal_hdr & 0x80 or (nal_hdr & 0x1F) not in (1, 5, 6, 7, 8, 9):
        return None
    lens = {struct.unpack_from("<I", h, 8)[0], struct.unpack_from(">I", h, 8)[0]}
    if not any(1 <= n <= 16 * 1024 * 1024 for n in lens):
        return None
    ts = {struct.unpack_from("<Q", h, 12)[0], struct.unpack_from(">Q", h, 12)[0]}
    if not any(US_MIN <= t <= US_MAX for t in ts):
        return None
    kind = "IDR" if h[0] == 0x82 else "non-IDR"
    return f"custom header at {start}: {kind}, plausible length and timestamp"


def _machine(b: bytes) -> str | None:
    m = _MODEL.search(b)
    return f"Machine Data string {m.group().decode()} at sector 34" if m else None


class HoneywellParser(VendorParser):
    vendor = "Honeywell"
    tier = "B"
    sources = ("RESEARCH 3.4: arXiv 2605.07430 [S5]",)

    def probes(self):
        return [Probe("honeywell_machine_data", MACHINE_OFFSET, 512, _machine)]

    def signatures(self):
        return [Signature("honeywell_custom_header", b"\x80\x01\x00", _header)]

    def identify(self, scope: Scope) -> Match:
        headers = scope.counts.get("honeywell_custom_header", 0)
        machine = scope.counts.get("honeywell_machine_data", 0)
        if not headers and not machine:
            return self.empty_match()
        conf = "medium" if headers >= 3 and machine else "low"
        evidence = scope.hits.get("honeywell_machine_data", []) + scope.hits.get(
            "honeywell_custom_header", []
        )
        notes = [
            "Documented for a single model (HN35080200) and H.264 only; H.265 layout unknown.",
            "Header byte order of length/time is not stated in the source; accepted either way.",
        ]
        return Match(
            self.vendor,
            self.tier,
            conf,
            evidence[:40],
            self.own_counts(scope),
            list(self.sources),
            notes,
        )
