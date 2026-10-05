"""ffmpeg-generated SYNTHETIC test bitstreams (testsrc2 pattern, not real DVR footage)."""

import io
import random
import shutil
import subprocess

from app.carving import nal as N
from app.carving.carve import CarveParams, Carver


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not shutil.which("ffmpeg") and not shutil.os.path.exists(path):
        raise RuntimeError("ffmpeg is required for these tests (brew install ffmpeg)")
    return path


def gen(
    codec: str,
    *,
    profile: str | None = None,
    size="320x240",
    seconds=2,
    gop=25,
    bframes=0,
    seed_color: int = 0,
) -> bytes:
    """Annex-B elementary stream. codec: h264|h265. Deterministic for a given ffmpeg build."""
    vf = f"testsrc2=size={size}:rate=25:duration={seconds}"
    if seed_color:
        vf += f",hue=h={seed_color}"
    cmd = [ffmpeg_path(), "-nostdin", "-v", "error", "-f", "lavfi", "-i", vf, "-pix_fmt", "yuv420p"]
    if codec == "h264":
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "1",
            "-g",
            str(gop),
            "-bf",
            str(bframes),
            "-x264-params",
            "scenecut=0:repeat-headers=1",
        ]
        if profile:
            cmd += ["-profile:v", profile]
        cmd += ["-f", "h264", "-"]
    else:
        cmd += [
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-x265-params",
            f"keyint={gop}:min-keyint={gop}:scenecut=0:repeat-headers=1:log-level=error:"
            f"bframes={bframes}:frame-threads=1",
            "-f",
            "hevc",
            "-",
        ]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    assert out.startswith((b"\x00\x00\x00\x01", b"\x00\x00\x01")), "not Annex-B"
    return out


def nal_units(data: bytes):
    """Split an Annex-B buffer into (start_code_pos, nal_bytes_without_start_code)."""
    ev = [e for e in N.scan(io.BytesIO(data), len(data)) if isinstance(e, N.StartCode)]
    for i, e in enumerate(ev):
        end = ev[i + 1].run_start if i + 1 < len(ev) else len(data)
        yield e.sc_start, data[e.hdr : end]


def scrub(data: bytes) -> bytes:
    """Remove any 00 00 so random filler cannot contain start codes or zero runs."""
    return data.replace(b"\x00\x00", b"\x00\x01")


def filler(n: int, seed: int) -> bytes:
    return scrub(random.Random(seed).randbytes(n))


def carve(data: bytes, chunk: int = N.CHUNK, **kw):
    def read_at(off, n):
        return data[off : off + n]

    c = Carver(read_at, CarveParams(**kw))
    out = list(c.run(N.scan(io.BytesIO(data), len(data), chunk)))
    return (
        [x for x in out if x.__class__.__name__ == "Clip"],
        [x for x in out if x.__class__.__name__ == "Orphan"],
        c.stats,
    )
