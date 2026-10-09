"""Region map of an image: what each byte range is, as far as stored results and a bounded scan
can say.

Inputs, in precedence order (a byte gets the label of the highest-precedence interval covering
it):
  1. parser clips   (engine != generic, from the selected completed CarveRun)
  2. carved clips   (generic engine)
  3. orphans        (NAL data that could not become a clip)
  4. structures     (vendor signature hits from the run's identification, partition-table sectors)
  5. zero           (4 KiB blocks that are all zero, found by a bounded scan)
  6. unknown        (scanned, not zero, not explained by any of the above)
  7. not_scanned    (beyond the scan budget)
Clip spans are [first extent start, last extent end]; vendor headers between payload extents lie
inside them. Nothing here is a claim about file-system allocation state.
"""

import heapq
import json

from app.vendors import default_registry

BLOCK = 4096
DEFAULT_SCAN = 64 * 1024 * 1024
MAX_SCAN = 1024 * 1024 * 1024
DEFAULT_MAX_REGIONS = 2000
MAX_REGIONS = 10000
PRIORITY = {"parser_clip": 1, "carved_clip": 2, "orphan": 3, "structure": 4}


def signature_lengths() -> dict[str, int]:
    out = {}
    for p in default_registry().parsers:
        out |= {pr.name: pr.length for pr in p.probes()}
        out |= {s.name: len(s.pattern) for s in p.signatures()}
    return out


def intervals_from_run(run, clips) -> list[tuple[int, int, str, dict]]:
    out = []
    for c in clips:
        if c.kind == "orphan":
            kind = "orphan"
        else:
            kind = "carved_clip" if c.engine == "generic" else "parser_clip"
        ref = {"clip_id": c.id, "engine": c.engine, "codec": c.codec}
        if c.kind == "orphan":
            ref["reason"] = c.reason
        out.append((c.start_offset, c.end_offset, kind, ref))
    if run is not None:
        lengths = signature_lengths()
        for m in json.loads(run.vendor_json or "[]"):
            for h in m.get("evidence", []):
                n = lengths.get(h["signature"], 1)
                out.append(
                    (
                        h["offset"],
                        h["offset"] + n,
                        "structure",
                        {"vendor": m["vendor"], "signature": h["signature"], "detail": h["detail"]},
                    )
                )
    return out


def intervals_from_partitions(pt: dict) -> list[tuple[int, int, str, dict]]:
    out = []
    if pt.get("mbr"):
        out.append((0, 512, "structure", {"structure": "MBR", "source": pt["mbr"]["source"]}))
    g = pt.get("gpt")
    if g:
        ss = g["sector_size"]
        out.append((ss, 2 * ss, "structure", {"structure": "GPT header", "source": g["source"]}))
        h = g["header"]
        a = h["entries_lba"] * ss
        out.append(
            (a, a + h["entry_count"] * h["entry_size"], "structure", {"structure": "GPT entries"})
        )
    return out


def zero_blocks(f, size: int, budget: int) -> tuple[list[tuple[int, int]], int]:
    """All-zero BLOCK-aligned ranges in [0, min(size, budget)). Returns (ranges, scanned_end)."""
    end = min(size, budget)
    zeros: list[tuple[int, int]] = []
    zb = bytes(BLOCK)
    pos = 0
    step = 1 << 22
    while pos < end:
        f.seek(pos)
        data = f.read(min(step, end - pos))
        if not data:
            break
        for i in range(0, len(data), BLOCK):
            blk = data[i : i + BLOCK]
            if blk == zb[: len(blk)]:
                s = pos + i
                if zeros and zeros[-1][1] == s:
                    zeros[-1] = (zeros[-1][0], s + len(blk))
                else:
                    zeros.append((s, s + len(blk)))
        pos += len(data)
    return zeros, pos


def _labelled(intervals, size):
    """Non-overlapping (start, end, kind, ref) by precedence, uncovered gaps omitted."""
    pts = sorted({0, size} | {max(0, min(size, x)) for s, e, *_ in intervals for x in (s, e)})
    starts = sorted(
        (
            (max(0, s), min(size, e), PRIORITY[k], i, k, r)
            for i, (s, e, k, r) in enumerate(intervals)
            if min(size, e) > max(0, s)
        ),
        key=lambda t: t[0],
    )
    heap: list = []
    j = 0
    out = []
    for a, b in zip(pts, pts[1:], strict=False):
        while j < len(starts) and starts[j][0] <= a:
            s, e, pr, i, k, r = starts[j]
            heapq.heappush(heap, (pr, i, e, k, r))
            j += 1
        while heap and heap[0][2] <= a:  # lazy removal: ended entries are dropped at the top
            heapq.heappop(heap)
        if heap:
            _pr, _i, _e, k, r = heap[0]
            out.append((a, b, k, r))
    return out


def _merge(regs):
    out = []
    for s, e, k, r in regs:
        if out and out[-1][2] == k and out[-1][3] == r and out[-1][1] == s:
            out[-1] = (out[-1][0], e, k, r)
        else:
            out.append((s, e, k, r))
    return out


def build(intervals, size: int, zeros, scanned_end: int) -> list[tuple[int, int, str, dict]]:
    labelled = _labelled(intervals, size)
    out = []
    pos = 0

    def fill(a: int, b: int) -> None:
        cur = a
        for zs, ze in zeros:
            if ze <= cur or zs >= b:
                continue
            zs, ze = max(zs, cur), min(ze, b)
            if zs > cur:
                gap(cur, zs)
            out.append((zs, ze, "zero", {}))
            cur = ze
        if cur < b:
            gap(cur, b)

    def gap(a: int, b: int) -> None:
        if a < min(b, scanned_end):
            out.append((a, min(b, scanned_end), "unknown", {}))
        if b > max(a, scanned_end):
            out.append((max(a, scanned_end), b, "not_scanned", {}))

    for s, e, k, r in labelled:
        if s > pos:
            fill(pos, s)
        out.append((s, e, k, r))
        pos = e
    if pos < size:
        fill(pos, size)
    return _merge(out)


def summary(regs, size: int) -> dict:
    tot: dict[str, int] = {}
    cnt: dict[str, int] = {}
    for s, e, k, _ in regs:
        tot[k] = tot.get(k, 0) + e - s
        cnt[k] = cnt.get(k, 0) + 1
    return {
        k: {"bytes": tot[k], "regions": cnt[k], "fraction": round(tot[k] / size, 6) if size else 0}
        for k in sorted(tot)
    }
