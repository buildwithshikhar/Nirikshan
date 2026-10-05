"""Vendor-parser plugin interface and the shared single-pass signature scan.

A parser contributes (a) fixed-offset probes, (b) byte signatures with an optional structural
validator, and (c) an `identify()` that turns the hits into a Match. Only signatures documented in
docs/RESEARCH.md may be used. Confidence reflects the support tier: no vendor is Tier A, so
`high` is never produced; the best possible result is `medium` (documented signature structurally
validated, not yet confirmed on a real image of our own).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import BinaryIO

CHUNK = 4 * 1024 * 1024
MAX_EVIDENCE = 20  # evidence offsets kept per signature (the total count is always reported)
TIERS = ("B", "C")  # Tier A requires validation on real images (none yet)
CONFIDENCE_ORDER = {"none": 0, "low": 1, "medium": 2}


@dataclass(frozen=True)
class Hit:
    signature: str
    offset: int
    detail: str


@dataclass
class Scope:
    """What the shared scan found, handed to each parser's identify()."""

    size: int
    hits: dict[str, list[Hit]] = field(default_factory=dict)  # kept evidence per signature
    counts: dict[str, int] = field(default_factory=dict)  # total validated hits per signature


@dataclass
class Match:
    vendor: str
    tier: str
    confidence: str  # none | low | medium
    evidence: list[Hit] = field(default_factory=list)
    signature_counts: dict[str, int] = field(default_factory=dict)
    basis: list[str] = field(default_factory=list)  # docs/RESEARCH.md sources
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CarveHints:
    """Optional per-vendor hints for the carver (unused by the generic P2 carver)."""

    max_pad: int | None = None


ReadAt = Callable[[int, int], bytes]
Validator = Callable[[ReadAt, int], str | None]


@dataclass(frozen=True)
class Signature:
    name: str
    pattern: bytes
    validate: Validator | None = None  # (read_at, absolute offset of pattern) -> detail or None


@dataclass(frozen=True)
class Probe:
    name: str
    offset: int
    length: int
    check: Callable[[bytes], str | None]


class VendorParser:
    vendor: str = ""
    tier: str = "C"
    sources: tuple[str, ...] = ()

    def probes(self) -> list[Probe]:
        return []

    def signatures(self) -> list[Signature]:
        return []

    def identify(self, scope: Scope) -> Match:  # pragma: no cover - interface
        raise NotImplementedError

    def enumerate(self, f: BinaryIO, size: int) -> list:
        """Optional structured enumeration (P4). P2 parsers do not parse filesystems."""
        return []

    # P4: structured parsing. `options_schema` documents every option (name -> default/doc);
    # `parse` must never raise and returns None when the parser has no structured parse.
    options_schema: dict = {}

    def parse(self, f: BinaryIO, size: int, options: dict | None = None):
        return None

    def carve_hints(self) -> CarveHints:
        return CarveHints()

    def own_counts(self, scope: Scope) -> dict[str, int]:
        """Validated-hit counts for this parser's own probes/signatures only."""
        names = {p.name for p in self.probes()} | {s.name for s in self.signatures()}
        return {k: v for k, v in scope.counts.items() if k in names}

    def empty_match(self, notes: list[str] | None = None) -> Match:
        return Match(self.vendor, self.tier, "none", basis=list(self.sources), notes=notes or [])


def scan_image(f: BinaryIO, size: int, parsers: list[VendorParser], chunk: int = CHUNK) -> Scope:
    """One streaming pass over the image for all parsers' signatures, plus fixed-offset probes."""
    scope = Scope(size)

    def add(sig: str, off: int, detail: str) -> None:
        scope.counts[sig] = scope.counts.get(sig, 0) + 1
        kept = scope.hits.setdefault(sig, [])
        if len(kept) < MAX_EVIDENCE:
            kept.append(Hit(sig, off, detail))

    def read_at(off: int, n: int) -> bytes:
        f.seek(off)
        return f.read(n)

    for parser in parsers:
        for pr in parser.probes():
            if pr.offset + 1 <= size:
                detail = pr.check(read_at(pr.offset, pr.length))
                if detail:
                    add(pr.name, pr.offset, detail)
    sigs = [s for p in parsers for s in p.signatures()]
    if not sigs:
        return scope
    keep = max(len(s.pattern) for s in sigs) - 1
    pos, tail = 0, b""
    while pos < size:
        f.seek(pos)
        data = f.read(chunk)
        if not data:
            break
        buf, base = tail + data, pos - len(tail)
        for s in sigs:
            i = buf.find(s.pattern)
            while i != -1:
                if i + len(s.pattern) > len(tail):  # not already seen in the previous chunk
                    off = base + i
                    detail = "signature match" if s.validate is None else s.validate(read_at, off)
                    if detail:
                        add(s.name, off, detail)
                i = buf.find(s.pattern, i + 1)
        pos += len(data)
        tail = buf[-keep:] if keep else b""
    return scope


class ParserRegistry:
    def __init__(self, parsers: list[VendorParser]):
        self.parsers = list(parsers)

    def parser_for(self, vendor: str) -> VendorParser | None:
        return next((p for p in self.parsers if p.vendor == vendor), None)

    def identify(self, f: BinaryIO, size: int, chunk: int = CHUNK) -> list[Match]:
        """All parsers' matches with confidence > none, best first. Empty list = unknown vendor."""
        scope = scan_image(f, size, self.parsers, chunk)
        matches = [p.identify(scope) for p in self.parsers]
        matches = [m for m in matches if m.confidence != "none"]
        matches.sort(key=lambda m: -CONFIDENCE_ORDER[m.confidence])
        return matches
