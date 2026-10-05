"""Byte-range bookkeeping for the parser-first pipeline.

Parsers run first; the generic carver then covers only the ranges no parser clip spans, so a
partial parser never loses clips and no clip is produced twice. A parser clip's span is
[first extent start, last extent end] (vendor headers between payload extents are inside it);
overlapping spans (e.g. interleaved channels) are merged.
"""

from collections.abc import Iterable, Iterator

from app.carving import nal
from app.carving.carve import CarveParams, Carver, Clip, Orphan


def merge_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for s, e in sorted(spans):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def uncovered(covered: list[tuple[int, int]], size: int) -> list[tuple[int, int]]:
    """Complement of merged `covered` ranges within [0, size)."""
    out, pos = [], 0
    for s, e in covered:
        if s > pos:
            out.append((pos, s))
        pos = max(pos, e)
    if pos < size:
        out.append((pos, size))
    return out


def carve_ranges(f, ranges: list[tuple[int, int]], params: CarveParams) -> Iterator[Clip | Orphan]:
    """Run the generic carver over each range independently (a clip never straddles a range)."""

    def read_at(off: int, n: int) -> bytes:
        f.seek(off)
        return f.read(n)

    for start, end in ranges:
        carver = Carver(lambda o, n, end=end: read_at(o, min(n, max(0, end - o))), params)
        yield from carver.run(nal.scan(f, end, start=start))
