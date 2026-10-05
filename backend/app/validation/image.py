"""SYNTHETIC image builder with ground truth.

Every image starts with a banner marking it synthetic. Placement is tracked piece by piece so the
truth (which image bytes belong to which clip NAL units, and whether they survived) is computed
from the finished image by direct byte comparison, not from intentions.
"""

import hashlib
import random
from dataclasses import dataclass, field

from app.validation.streams import Stream

BANNER = (
    b"NIRIKSHAN SYNTHETIC TEST IMAGE - NOT REAL DVR DATA - generated for pipeline validation. "
).ljust(256, b" ")
LAYOUT_RAW = "raw: generic elementary-stream placement (no vendor structures)"


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
    def __init__(self, rng: random.Random, layout: str = LAYOUT_RAW):
        self.rng = rng
        self.buf = bytearray(BANNER)
        self.clips: dict[str, TruthClip] = {}
        self.layout = layout
        self.notes: list[str] = []

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
        s = len(self.buf)
        self.buf += t.stream.data[a:b]
        t.pieces.append(Piece(s, len(self.buf), a, cid))
        return s, len(self.buf)

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
