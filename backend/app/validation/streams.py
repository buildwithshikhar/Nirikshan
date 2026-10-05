"""SYNTHETIC elementary streams generated with ffmpeg (testsrc2 pattern). Not DVR footage."""

import io
import random
import subprocess
from dataclasses import dataclass, field

from app.carving import nal as N
from app.carving.export import ffmpeg_version, tool


@dataclass(frozen=True)
class Variant:
    name: str
    codec: str  # h264 | h265
    profile: str
    size: str
    seconds: int
    gop: int
    bframes: int
    hue: int


# Neighbouring clips in an image always use different variants so their parameter sets differ.
VARIANTS = (
    Variant("h264_base_320", "h264", "baseline", "320x240", 2, 12, 0, 0),
    Variant("h264_main_b_352", "h264", "main", "352x288", 2, 12, 2, 40),
    Variant("h264_high_480", "h264", "high", "480x270", 2, 10, 0, 90),
    Variant("h264_base_256", "h264", "baseline", "256x192", 3, 15, 0, 140),
    Variant("h265_main_320", "h265", "main", "320x240", 2, 12, 0, 20),
    Variant("h265_main_416", "h265", "main", "416x240", 2, 10, 0, 70),
)


@dataclass
class NalInfo:
    start: int  # offset of the start code in the stream
    end: int
    type: int
    vcl: bool
    irap: bool
    param: bool
    gop: int


@dataclass
class Stream:
    variant: Variant
    data: bytes
    nals: list[NalInfo] = field(default_factory=list)

    @property
    def frames(self) -> int:
        return sum(1 for n in self.nals if n.vcl)


def _encode(v: Variant) -> bytes:
    vf = f"testsrc2=size={v.size}:rate=25:duration={v.seconds},hue=h={v.hue}"
    cmd = [
        tool("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        vf,
        "-pix_fmt",
        "yuv420p",
    ]
    if v.codec == "h264":
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "1",
            "-g",
            str(v.gop),
            "-bf",
            str(v.bframes),
            "-profile:v",
            v.profile,
            "-x264-params",
            "scenecut=0:repeat-headers=1",
            "-f",
            "h264",
            "-",
        ]
    else:
        cmd += [
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-x265-params",
            f"keyint={v.gop}:min-keyint={v.gop}:scenecut=0:repeat-headers=1:log-level=error:"
            f"bframes={v.bframes}:frame-threads=1:pools=1",
            "-f",
            "hevc",
            "-",
        ]
    return subprocess.run(cmd, capture_output=True, check=True, timeout=120).stdout


def _nal_table(data: bytes, codec: str) -> list[NalInfo]:
    sc = [e for e in N.scan(io.BytesIO(data), len(data)) if isinstance(e, N.StartCode)]
    out: list[NalInfo] = []
    for i, e in enumerate(sc):
        end = sc[i + 1].run_start if i + 1 < len(sc) else len(data)
        b0 = data[e.hdr]
        if codec == "h264":
            t = b0 & 0x1F
            vcl, irap, param = t in (1, 5), t == 5, t in (7, 8)
        else:
            t = (b0 >> 1) & 0x3F
            vcl, irap, param = t < 32, 16 <= t <= 21, t in (32, 33, 34)
        out.append(NalInfo(e.sc_start, end, t, vcl, irap and vcl, param, 0))
    # assign GOPs: a new GOP starts at the first non-VCL NAL following a VCL NAL before an IRAP
    gop, prev_vcl = -1, True
    for n in out:
        if not n.vcl and prev_vcl:
            gop += 1
        if n.vcl and n.irap and gop < 0:
            gop = 0
        n.gop = max(gop, 0)
        prev_vcl = n.vcl
    return out


class StreamPool:
    """Generates each variant once per run; records ffmpeg version and stream hashes."""

    def __init__(self) -> None:
        self._cache: dict[str, Stream] = {}
        self.ffmpeg = ffmpeg_version()

    def get(self, name: str) -> Stream:
        if name not in self._cache:
            v = next(x for x in VARIANTS if x.name == name)
            data = _encode(v)
            self._cache[name] = Stream(v, data, _nal_table(data, v.codec))
        return self._cache[name]

    def all(self) -> list[Stream]:
        return [self.get(v.name) for v in VARIANTS]

    def by_codec(self, codec: str) -> list[Stream]:
        return [s for s in self.all() if s.variant.codec == codec]


def aux_stream(kind: str) -> bytes:
    """Negative-class media that must NOT carve as H.264/H.265: mjpeg or mpeg4 (part 2)."""
    vf = "testsrc2=size=320x240:rate=25:duration=2"
    base = [
        tool("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        vf,
        "-pix_fmt",
        "yuvj420p",
    ]
    if kind == "mjpeg":
        cmd = base + ["-c:v", "mjpeg", "-q:v", "5", "-f", "image2pipe", "-"]
    else:
        cmd = base[:-2] + [
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "mpeg4",
            "-threads",
            "1",
            "-g",
            "12",
            "-f",
            "m4v",
            "-",
        ]
    return subprocess.run(cmd, capture_output=True, check=True, timeout=120).stdout


def derived(pool: "StreamPool", name: str, hue: int) -> Stream:
    """Same encoder settings (identical parameter sets) with different picture content."""
    from dataclasses import replace

    key = f"{name}#h{hue}"
    if key not in pool._cache:
        v = replace(next(x for x in VARIANTS if x.name == name), name=key, hue=hue)
        data = _encode(v)
        pool._cache[key] = Stream(v, data, _nal_table(data, v.codec))
    return pool._cache[key]


def pick(rng: random.Random, pool: StreamPool, n: int, codec: str | None = None) -> list[Stream]:
    """n streams; neighbours always have different variants (different parameter sets)."""
    pop = pool.by_codec(codec) if codec else pool.all()
    out: list[Stream] = []
    for _ in range(n):
        choices = [s for s in pop if not out or s.variant.name != out[-1].variant.name]
        out.append(rng.choice(choices))
    return out
