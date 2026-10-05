"""Vendor-agnostic H.264/H.265 carving: group Annex-B NAL units into decodable clips.

A clip starts at an IRAP picture (H.264 IDR / H.265 BLA, IDR, CRA) that is accompanied by
parameter sets (SPS+PPS, plus VPS for H.265) and runs while NAL units stay plausible and
contiguous. Everything that cannot be turned into a clip is reported as an orphan, never dropped
silently. Streaming: one pass over scanner events, state is O(current clip).

Heuristics and their limits (see docs/ARCHITECTURE.md):
  * NAL end = next start code, or the start of a zero run (trailing_zero_8bits / zero-filled gap).
    Random (non-zero) garbage between a clip's NAL units cannot be told apart from payload, so it
    is absorbed into the previous NAL; the decode test in export flags the damage.
  * H.264 only: slice frame_num continuity (delta 0 or 1) detects splices of foreign data into a
    clip. H.265 has no equivalent check here (needs POC/DPB logic) and a gap break there is final.
  * Optional H.264 fragment reassembly joins runs across a gap of up to `join_gap` bytes when
    the next slice continues frame_num and uses a known PPS. It is a heuristic, off by default.
"""

import hashlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

from app.carving import nal as N
from app.carving.bits import (
    H264Sps,
    parse_h264_pps_id,
    parse_h264_slice,
    parse_h264_sps,
    parse_h265_pps_id,
    parse_h265_slice_pps_id,
    validate_h264_pps,
    validate_h264_sps,
    validate_h265_pps,
    validate_h265_sps,
    validate_h265_vps,
)


@dataclass
class CarveParams:
    max_pad: int = 64  # max zero padding / gap between consecutive NAL units inside a clip
    max_nal: int = 16 * 1024 * 1024
    h264_continuity: bool = True
    validate_params: bool = True  # syntax-check SPS/PPS/VPS before starting a clip
    join_gap: int = 0  # >0 enables H.264 fragment reassembly across gaps up to this many bytes


@dataclass
class Clip:
    codec: str
    extents: list[list[int]]
    nal_count: int = 0
    irap_count: int = 0
    vcl_count: int = 0
    reassembled: bool = False
    end_reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def start(self) -> int:
        return self.extents[0][0]

    @property
    def end(self) -> int:
        return self.extents[-1][1]

    @property
    def size(self) -> int:
        return sum(e - s for s, e in self.extents)


@dataclass
class Orphan:
    codec: str
    start: int
    end: int
    nal_count: int
    reason: str


@dataclass
class _Nal:
    start: int
    end: int
    hdr: int
    head: bytes


@dataclass
class _Item:
    """Non-VCL NAL held back until we know whether it opens or continues a clip."""

    start: int
    end: int
    head: bytes
    param: tuple[str, str] | None  # (codec, 'vps'|'sps'|'pps')
    digest: str = ""


@dataclass
class _Active:
    clip: Clip
    ident: frozenset
    sps: H264Sps | None = None
    pps_ids: set = field(default_factory=set)
    last_fn: int | None = None


ReadAt = Callable[[int, int], bytes]
MAX_PEND = 64


class Carver:
    def __init__(self, read_at: ReadAt, params: CarveParams | None = None):
        self.read_at = read_at
        self.p = params or CarveParams()
        self.active: _Active | None = None
        self.pend: list[_Item] = []
        self.orphan: Orphan | None = None
        self.last_end = 0  # end of the last NAL seen (committed or pending)
        self.last_valid_end = 0  # end of the last NAL with a valid header (stray junk excluded)
        self.stats = {
            "nal_units": 0,
            "stray_nal_units": 0,
            "oversize_nal_units": 0,
            "tolerated_invalid_nal_units": 0,
            "join_candidates": 0,
            "join_accepted": 0,
        }
        # (end of the clip's last NAL, start of the candidate NAL, accepted): for validation
        self.join_log: list[tuple[int, int, bool]] = []

    # ---- driver ---------------------------------------------------------------------------
    def run(self, events: Iterable) -> Iterator[Clip | Orphan]:
        pending: N.StartCode | None = None
        for ev in events:
            if isinstance(ev, N.StartCode):
                if pending is not None and ev.run_start > pending.hdr:
                    yield from self._handle(self._nal(pending, ev.run_start))
                pending = ev
            elif isinstance(ev, N.ZeroRun):
                if pending is not None and ev.pos > pending.hdr:
                    yield from self._handle(self._nal(pending, ev.pos))
                    pending = None
            elif pending is not None and ev.size > pending.hdr:  # Eof
                tail = self.read_at(max(pending.hdr, ev.size - 2), 2)  # <3 zeros: not a ZeroRun
                end = ev.size - (len(tail) - len(tail.rstrip(b"\x00")))
                yield from self._handle(self._nal(pending, max(end, pending.hdr + 1)))
                pending = None
        yield from self._close_active("end of image")
        yield from self._flush_orphan()

    @staticmethod
    def _nal(sc: N.StartCode, end: int) -> _Nal:
        return _Nal(sc.sc_start, end, sc.hdr, sc.head)

    # ---- small helpers --------------------------------------------------------------------
    def _nal_bytes(self, start: int, end: int) -> bytes:
        """NAL unit bytes (header onwards, capped) for a start-code-prefixed span."""
        raw = self.read_at(start, min(end - start, 520))
        return raw[raw.find(b"\x01") + 1 :]

    def _item(self, n: _Nal, param) -> _Item:
        digest = hashlib.sha256(self._nal_bytes(n.start, n.end)).hexdigest() if param else ""
        return _Item(n.start, n.end, n.head, param, digest)

    def _close_active(self, reason: str) -> Iterator[Clip]:
        if self.active is not None:
            clip = self.active.clip
            clip.end_reason = reason
            self.active = None
            yield clip

    def _flush_orphan(self) -> Iterator[Orphan]:
        if self.orphan is not None:
            o, self.orphan = self.orphan, None
            yield o

    def _add_orphan(self, n: _Nal, codec: str, reason: str) -> Iterator[Orphan]:
        o = self.orphan
        if o is not None and (n.start - o.end > self.p.max_pad or o.reason != reason):
            yield from self._flush_orphan()
            o = None
        if o is None:
            self.orphan = Orphan(codec, n.start, n.end, 1, reason)
        else:
            o.end, o.nal_count = n.end, o.nal_count + 1

    @staticmethod
    def _kind(codec: str, head: bytes) -> tuple[str, int | None]:
        """('vcl'|'param'|'other'|'invalid', nal_type) interpreting head as `codec`."""
        if codec == "h264":
            t = N.h264_type(head[0])
            if t is None or t not in N.H264_OK_TYPES:
                return "invalid", None
            return ("vcl" if t in (1, 5) else "param" if t in (7, 8) else "other"), t
        h = N.h265_header(head[0], head[1] if len(head) > 1 else 0)
        if h is None or h[1] != 0 or h[0] not in N.H265_OK_TYPES:
            return "invalid", None
        t = h[0]
        return ("vcl" if t < 32 else "param" if t in (32, 33, 34) else "other"), t

    def _pps_ids(self, codec: str, items) -> set[int]:
        out = set()
        for it in items:
            if it.param and it.param == (codec, "pps"):
                raw = self._nal_bytes(it.start, it.end)
                pid = parse_h264_pps_id(raw) if codec == "h264" else parse_h265_pps_id(raw)
                if pid is not None:
                    out.add(pid)
        return out

    @staticmethod
    def _slice_pps(codec: str, sl) -> int:
        return sl.pps_id if codec == "h264" else sl

    @staticmethod
    def _is_irap(codec: str, t: int) -> bool:
        return t == 5 if codec == "h264" else 16 <= t <= 21

    @staticmethod
    def _slice(codec: str, t: int, n: _Nal, sps: H264Sps | None):
        """Parsed slice fields, or None when the header is implausible."""
        if codec == "h264":
            s = parse_h264_slice(n.head, sps)
            if s is None or (t == 5 and s.slice_type not in (2, 4, 7, 9)):
                return None
            return s
        return parse_h265_slice_pps_id(n.head, t)

    # ---- state machine --------------------------------------------------------------------
    def _handle(self, n: _Nal) -> Iterator[Clip | Orphan]:
        self.stats["nal_units"] += 1
        if n.end - n.start > self.p.max_nal:
            self.stats["oversize_nal_units"] += 1
            self.last_end = self.last_valid_end = n.end
            yield from self._close_active("oversize NAL unit")
            self.pend = []
            return
        if self.active is not None and self._stray_header(n):
            # Vendor headers are not emulation-escaped: their fields can contain 00 00 01. An
            # invalid NAL header close behind valid data is junk inside the gap, not a clip end.
            self.stats["tolerated_invalid_nal_units"] += 1
            self.last_end = n.end
            return
        gap = n.start - self.last_valid_end
        self.last_end = self.last_valid_end = n.end
        if self.active is not None:
            yield from self._active(n, gap)
        else:
            yield from self._idle(n, gap)

    def _stray_header(self, n: _Nal) -> bool:
        kind, _ = self._kind(self.active.clip.codec, n.head)
        if kind != "invalid" or n.start - self.last_valid_end > self.p.max_pad:
            return False
        return N.classify_param(n.head) is None  # another codec's parameter set starts a new clip

    def _break(self, n: _Nal, gap: int, reason: str) -> Iterator[Clip | Orphan]:
        yield from self._close_active(reason)
        yield from self._idle(n, gap)

    def _active(self, n: _Nal, gap: int) -> Iterator[Clip | Orphan]:
        a = self.active
        codec = a.clip.codec
        kind, t = self._kind(codec, n.head)
        joined = False
        if gap > self.p.max_pad:
            candidate = bool(self.p.join_gap) and gap <= self.p.join_gap and kind == "vcl"
            ok = candidate and self._continues(a, n)
            if candidate and codec == "h264":
                self.stats["join_candidates"] += 1
                self.stats["join_accepted"] += int(ok)
                if len(self.join_log) < 10000:
                    self.join_log.append((a.clip.extents[-1][1], n.start, ok))
            if ok:
                joined = True
            else:
                self.pend = []
                yield from self._break(n, gap, f"gap of {gap} bytes")
                return
        if kind == "invalid":
            self.pend = []
            yield from self._break(n, gap, "invalid NAL header")
            return
        if kind != "vcl":
            param = N.classify_param(n.head) if kind == "param" else None
            self.pend = (self.pend + [self._item(n, param)])[-MAX_PEND:]
            return
        sl = self._slice(codec, t, n, a.sps)
        if sl is None:
            self.pend = []
            yield from self._break(n, gap, "implausible slice header")
            return
        irap = self._is_irap(codec, t)
        known = a.pps_ids | self._pps_ids(codec, self.pend)
        if known and self._slice_pps(codec, sl) not in known:
            self.pend = []
            yield from self._break(n, gap, "slice references a PPS not seen in the clip")
            return
        if codec == "h264" and self.p.h264_continuity and not irap and not joined:
            if a.last_fn is not None and sl.frame_num is not None:
                if (sl.frame_num - a.last_fn) % (1 << a.sps.log2_max_frame_num) not in (0, 1):
                    self.pend = []
                    yield from self._break(n, gap, "frame_num discontinuity (possible splice)")
                    return
        if irap and any(p.param for p in self.pend):
            ident = frozenset((p.param[1], p.digest) for p in self.pend if p.param)
            if ident != a.ident:
                yield from self._close_active("parameter sets changed")
                yield from self._idle(n, gap)  # self.pend still holds the new group
                return
        a.pps_ids |= self._pps_ids(codec, self.pend)
        for it in self.pend:  # commit held-back items (repeated headers, SEI, ...)
            self._extend(a, it.start, it.end)
            a.clip.nal_count += 1
        self.pend = []
        if joined:
            a.clip.extents.append([n.start, n.end])
            a.clip.reassembled = True
            a.clip.notes.append(f"joined across a {gap}-byte gap at offset {n.start} (heuristic)")
        else:
            self._extend(a, n.start, n.end)
        a.clip.nal_count += 1
        a.clip.vcl_count += 1
        a.clip.irap_count += int(irap)
        if codec == "h264" and sl.frame_num is not None:
            a.last_fn = sl.frame_num

    @staticmethod
    def _extend(a: _Active, s: int, e: int) -> None:
        a.clip.extents[-1][1] = max(a.clip.extents[-1][1], e)  # padding <= max_pad stays inside

    def _continues(self, a: _Active, n: _Nal) -> bool:
        """H.264 fragment-join test: a P/B slice, known PPS, frame_num continuing the clip."""
        if a.clip.codec != "h264" or a.sps is None or a.last_fn is None:
            return False
        s = parse_h264_slice(n.head, a.sps)
        if s is None or s.frame_num is None or s.pps_id not in a.pps_ids:
            return False
        return (s.frame_num - a.last_fn) % (1 << a.sps.log2_max_frame_num) in (0, 1)

    def _idle(self, n: _Nal, gap: int) -> Iterator[Clip | Orphan]:
        if self.pend and gap > self.p.max_pad:
            self.pend = []
        kinds = {c: self._kind(c, n.head) for c in ("h264", "h265")}
        valid = {c: k for c, k in kinds.items() if k[0] != "invalid"}
        if not valid:
            self.stats["stray_nal_units"] += 1
            self.pend = []
            return
        for codec, (kind, t) in valid.items():
            if kind == "vcl" and self._try_start(n, codec, t):
                yield from self._flush_orphan()
                return
        if any(k != "vcl" for k, _ in valid.values()):
            # e.g. an H.264 SEI also parses as an H.265 slice: keep it as a possible header NAL
            yield from self._flush_orphan()
            self.pend = (self.pend + [self._item(n, N.classify_param(n.head))])[-MAX_PEND:]
            return
        reason = "slices without a preceding IRAP + parameter sets (continuation fragment)"
        if any(self._is_irap(c, t) for c, (_, t) in valid.items()):
            reason = "IRAP picture without parameter sets"
        self.pend = []
        yield from self._add_orphan(n, next(iter(valid)), reason)

    def _group_valid(self, codec: str, items) -> bool:
        """SPS/PPS(/VPS) of the group parse with in-range fields and reference each other."""
        raw = {k: [] for k in ("vps", "sps", "pps")}
        for it in items:
            if it.param:
                raw[it.param[1]].append(self._nal_bytes(it.start, it.end))
        if codec == "h264":
            sps = [validate_h264_sps(b) for b in raw["sps"]]
            if not sps or any(s is None for s in sps):
                return False
            ids = {s.sps_id for s in sps}
            return all(validate_h264_pps(b, ids) is not None for b in raw["pps"])
        vps = [validate_h265_vps(b) for b in raw["vps"]]
        if not vps or any(v is None for v in vps):
            return False
        sps = [validate_h265_sps(b, set(vps)) for b in raw["sps"]]
        if not sps or any(s is None for s in sps):
            return False
        return all(validate_h265_pps(b, set(sps)) is not None for b in raw["pps"])

    def _try_start(self, n: _Nal, codec: str, t: int) -> bool:
        if not self._is_irap(codec, t):
            return False
        have = {p.param[1] for p in self.pend if p.param and p.param[0] == codec}
        if not ({"sps", "pps"} | ({"vps"} if codec == "h265" else set())) <= have:
            return False
        if self._slice(codec, t, n, None) is None:
            return False
        idx = next(i for i, p in enumerate(self.pend) if p.param and p.param[0] == codec)
        while (
            idx > 0
            and self.pend[idx - 1].param is None
            and self._kind(codec, self.pend[idx - 1].head)[0] == "other"
        ):
            idx -= 1  # AUD/SEI directly in front of the parameter sets belong to the clip
        items = [p for p in self.pend[idx:] if p.param is None or p.param[0] == codec]
        if self.p.validate_params and not self._group_valid(codec, items):
            return False
        sps = None
        if codec == "h264":
            for p in items:
                if p.param == ("h264", "sps"):
                    sps = parse_h264_sps(self._nal_bytes(p.start, p.end))
                    break
        pps_ids = self._pps_ids(codec, items)
        sl0 = self._slice(codec, t, n, None)
        if pps_ids and self._slice_pps(codec, sl0) not in pps_ids:
            return False  # the IRAP slice does not reference any PPS that came with it
        clip = Clip(codec, [[items[0].start, items[0].end]], nal_count=len(items))
        a = _Active(clip, frozenset((p.param[1], p.digest) for p in items if p.param), sps, pps_ids)
        for it in items[1:]:
            self._extend(a, it.start, it.end)
        self._extend(a, n.start, n.end)
        clip.nal_count += 1
        clip.vcl_count = clip.irap_count = 1
        sl = self._slice(codec, t, n, sps)
        if codec == "h264" and sl is not None and sl.frame_num is not None:
            a.last_fn = sl.frame_num
        self.active, self.pend = a, []
        return True
