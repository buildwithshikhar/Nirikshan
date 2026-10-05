"""Hikvision identification. Signatures: docs/RESEARCH.md 3.1 (Han 2015 [S1], Dragonas [S2]).

Documented on one 2015-era DVR (Han) and six 2022-23 devices (Dragonas); newer firmware and
H.265 layouts are unverified, so the maximum confidence is `medium`.
"""

from app.vendors.base import Match, Probe, Scope, Signature, VendorParser

MASTER = b"HIKVISION@HANGZHOU"  # Master Sector signature, documented at offset 0x200
MASTER_OFFSET = 0x200
# RATS log record header: Han saw 52 41 54 53 01 00 00 00, Dragonas 52 41 54 53 14 00 00 00
RATS_FOLLOWERS = (b"\x01\x00\x00\x00", b"\x14\x00\x00\x00")


def _master_probe(b: bytes) -> str | None:
    return "Master Sector signature at the documented offset 0x200" if b == MASTER else None


def _master_any(_read, off: int) -> str | None:
    where = (
        "at documented offset 0x200" if off == MASTER_OFFSET else "at another offset (backup copy?)"
    )
    return f"HIKVISION@HANGZHOU {where}"


def _rats(read, off: int) -> str | None:
    nxt = read(off + 4, 4)
    return f"RATS log record header ({nxt.hex()})" if nxt in RATS_FOLLOWERS else None


class HikvisionParser(VendorParser):
    vendor = "Hikvision"
    tier = "B"
    sources = ("RESEARCH 3.1: Han 2015 [S1]", "RESEARCH 3.1: Dragonas thesis [S2]")

    def probes(self):
        return [Probe("hik_master_0x200", MASTER_OFFSET, len(MASTER), _master_probe)]

    def signatures(self):
        return [
            Signature("hik_master_any", MASTER, _master_any),
            Signature("hik_btree", b"HIKBTREE"),
            Signature("hik_rats_log", b"RATS", _rats),
        ]

    def identify(self, scope: Scope) -> Match:
        c = self.own_counts(scope)
        if not c.get("hik_master_0x200") and not any(
            c.get(k) for k in ("hik_master_any", "hik_btree", "hik_rats_log")
        ):
            return self.empty_match()
        evidence = [h for k in sorted(scope.hits) if k.startswith("hik_") for h in scope.hits[k]]
        kinds = sum(1 for k in ("hik_master_any", "hik_btree", "hik_rats_log") if c.get(k))
        conf = "medium" if c.get("hik_master_0x200") or kinds >= 2 else "low"
        notes = [
            "Documented on a 2015 DVR and six 2022-23 devices; newer firmware unverified.",
            "Filesystem structures (HIKBTREE, IDR table) are not parsed in P2; carving is generic.",
        ]
        return Match(
            self.vendor, self.tier, conf, evidence[:40], dict(c), list(self.sources), notes
        )
