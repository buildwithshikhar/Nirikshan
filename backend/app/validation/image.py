"""SYNTHETIC image builder with ground truth.

Every image starts with a banner marking it synthetic. Placement is tracked piece by piece so the
truth (which image bytes belong to which clip NAL units, and whether they survived) is computed
from the finished image by direct byte comparison, not from intentions.
"""

import hashlib
import random
from dataclasses import dataclass, field

from app.validation.layouts import LAYOUT_DHAV, LAYOUT_RAW, wrap_stream
from app.validation.streams import Stream

BANNER = (
    b"NIRIKSHAN SYNTHETIC TEST IMAGE - NOT REAL DVR DATA - generated for pipeline validation. "
).ljust(256, b" ")

CURRENT_LAYOUT = LAYOUT_RAW  # set by the harness per trial


def noise(rng: random.Random, n: int) -> bytes:
    """Random bytes with no 00 00 pair: cannot contain start codes or zero runs."""
    return rng.randbytes(n).replace(b"\x00\x00", b"\x00\x01")


@dataclass
class Piece:
    img_start: int
    img_end: int
    stream_start: int
    clip: str


@dataclass
class TruthClip:
    id: str
    stream: Stream
    expected: str  # recover | none (a deliberately destroyed clip)
    channel: int = 0
    state: str = "live"
    pieces: list[Piece] = field(default_factory=list)


class Builder:
    def __init__(self, rng: random.Random, layout: str | None = None):
        layout = layout or CURRENT_LAYOUT
        self.rng = rng
        self.frame_no: dict[str, int] = {}
        self.buf = bytearray(BANNER)
        self.clips: dict[str, TruthClip] = {}
        self.layout = layout
        self.notes: list[str] = []

    @classmethod
    def from_layout(
        cls,
        rng: random.Random,
        layout: str,
        image: bytes,
        clips: dict[str, tuple[Stream, list[tuple[int, int, int]], dict]],
        notes: list[str] | None = None,
    ) -> "Builder":
        """Wrap an image produced by a vendor-layout generator so ground truth is computed by byte
        comparison like any other image. `clips[id] = (stream, [(img_start, img_end, stream_start)],
        {"expected": "recover"|"none", "channel": int, "state": str})` where each tuple says that
        image bytes [img_start, img_end) are stream bytes starting at stream_start (the video
        payload only, never vendor headers)."""
        b = cls(rng, layout)
        b.buf = bytearray(image)
        for cid, (stream, pieces, meta) in clips.items():
            t = b.clip(
                cid,
                stream,
                meta.get("expected", "recover"),
                meta.get("channel", 0),
                meta.get("state", "live"),
            )
            t.pieces = [Piece(s, e, ss, cid) for s, e, ss in pieces]
        b.notes = notes or []
        return b

    def pos(self) -> int:
        return len(self.buf)

    def zeros(self, n: int) -> None:
        self.buf += b"\x00" * n

    def noise(self, n: int) -> None:
        self.buf += noise(self.rng, n)

    def raw(self, data: bytes) -> None:
        self.buf += data

    def clip(
        self, cid: str, stream: Stream, expected="recover", channel=0, state="live"
    ) -> TruthClip:
        return self.clips.setdefault(cid, TruthClip(cid, stream, expected, channel, state))

    def place(self, cid: str, a: int = 0, b: int | None = None) -> tuple[int, int]:
        """Append stream bytes [a, b) of clip `cid`; returns the image range."""
        t = self.clips[cid]
        b = len(t.stream.data) if b is None else b
        if self.layout == LAYOUT_DHAV:
            return self._place_dhav(t, a, b)
        s = len(self.buf)
        self.buf += t.stream.data[a:b]
        t.pieces.append(Piece(s, len(self.buf), a, cid))
        return s, len(self.buf)

    def _place_dhav(self, t: TruthClip, a: int, b: int) -> tuple[int, int]:
        n0 = self.frame_no.get(t.id, 1000)
        first = len(self.buf)
        frames = wrap_stream(t.stream, a, b, t.channel, n0)
        for fr, off, plen, sstart in frames:
            p0 = len(self.buf) + off
            self.buf += fr
            t.pieces.append(Piece(p0, p0 + plen, sstart, t.id))
        self.frame_no[t.id] = n0 + len(frames)
        return first, len(self.buf)

    def foreign(self, cid: str, at: int, length: int) -> None:
        """A newer recording of clip `cid` overwrote [at, at+length), written in this image's
        layout (raw bytes, or DHAV frames) and truncated at `length`; any shortfall is zeroed."""
        t = self.clips[cid]
        if self.layout == LAYOUT_DHAV:
            blob, rel = bytearray(), []
            for fr, off, plen, sstart in wrap_stream(
                t.stream, 0, len(t.stream.data), t.channel, 5000
            ):
                if len(blob) + len(fr) > length:
                    break
                rel.append((len(blob) + off, len(blob) + off + plen, sstart))
                blob += fr
        else:
            blob = bytearray(t.stream.data[:length])
            rel = [(0, len(blob), 0)]
        data = bytes(blob) + b"\x00" * (length - len(blob))
        self.overwrite(at, data[:length])
        t.pieces += [Piece(at + a, at + b, ss, cid) for a, b, ss in rel]

    def overwrite(self, img_start: int, data: bytes) -> None:
        self.buf[img_start : img_start + len(data)] = data

    def build(self) -> tuple[bytes, dict]:
        img = bytes(self.buf)
        return img, self.truth(img)

    # ---- ground truth ------------------------------------------------------------------------
    def truth(self, img: bytes) -> dict:
        clips = []
        for t in self.clips.values():
            nals = []
            for n in t.stream.nals:
                loc = next(
                    (
                        p
                        for p in t.pieces
                        if p.stream_start <= n.start
                        and n.end <= p.stream_start + (p.img_end - p.img_start)
                    ),
                    None,
                )
                if loc is None:
                    nals.append(
                        {
                            "gop": n.gop,
                            "vcl": n.vcl,
                            "param": n.param,
                            "irap": n.irap,
                            "img_off": None,
                            "len": n.end - n.start,
                            "intact": False,
                        }
                    )
                    continue
                off = loc.img_start + (n.start - loc.stream_start)
                intact = img[off : off + (n.end - n.start)] == t.stream.data[n.start : n.end]
                nals.append(
                    {
                        "gop": n.gop,
                        "vcl": n.vcl,
                        "param": n.param,
                        "irap": n.irap,
                        "img_off": off,
                        "len": n.end - n.start,
                        "intact": intact,
                    }
                )
            self._mark_recoverable(nals)
            clips.append(
                {
                    "id": t.id,
                    "variant": t.stream.variant.name,
                    "codec": t.stream.variant.codec,
                    "expected": t.expected,
                    "channel": t.channel,
                    "state": t.state,
                    "frames_total": t.stream.frames,
                    "frames_recoverable": sum(1 for n in nals if n["vcl"] and n["recoverable"]),
                    "source_sha256": hashlib.sha256(t.stream.data).hexdigest(),
                    "pieces": [[p.img_start, p.img_end, p.stream_start] for p in t.pieces],
                    "nals": nals,
                }
            )
        return {
            "synthetic": True,
            "marker": BANNER.decode().strip(),
            "layout": self.layout,
            "notes": self.notes,
            "size": len(img),
            "image_sha256": hashlib.sha256(img).hexdigest(),
            "clips": clips,
        }

    @staticmethod
    def _mark_recoverable(nals: list[dict]) -> None:
        """A VCL NAL is recoverable if it and everything a decoder needs before it survived:
        the GOP's parameter sets and every earlier VCL NAL of that GOP (NAL-order prefix)."""
        by_gop: dict[int, list[dict]] = {}
        for n in nals:
            by_gop.setdefault(n["gop"], []).append(n)
        for g in by_gop.values():
            params_ok = all(n["intact"] for n in g if n["param"])
            prefix_ok = params_ok
            for n in g:
                if n["vcl"]:
                    prefix_ok = prefix_ok and n["intact"]
                    n["recoverable"] = prefix_ok
                else:
                    n["recoverable"] = False
