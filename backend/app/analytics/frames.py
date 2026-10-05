"""Frame access through ffmpeg raw pipes (no OpenCV).

Frame indices are positions in the decoded output order of the exported MP4. Times derived from
them are NOMINAL (index / stream frame rate); they are not recording times.
"""

import json
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from app.carving.export import tool


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float  # nominal stream frame rate
    fps_text: str
    nb_frames: int | None


def probe(path: str | Path) -> VideoInfo:
    out = subprocess.run(
        [
            tool("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    streams = json.loads(out.stdout or "{}").get("streams") or []
    if out.returncode != 0 or not streams:
        raise ValueError(f"ffprobe could not read a video stream: {out.stderr.strip()[:200]}")
    s = streams[0]
    try:
        fps = float(Fraction(s.get("r_frame_rate", "25/1")))
    except (ZeroDivisionError, ValueError):
        fps = 0.0
    if fps <= 0:
        fps = 25.0
    nb = s.get("nb_frames")
    return VideoInfo(
        int(s["width"]),
        int(s["height"]),
        fps,
        s.get("r_frame_rate", ""),
        int(nb) if nb and str(nb).isdigit() else None,
    )


def read_frames(
    path: str | Path,
    *,
    stride: int = 1,
    pix_fmt: str = "gray",
    size: tuple[int, int] | None = None,
    max_samples: int | None = None,
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (frame_index, array) for every `stride`-th decoded frame.

    gray -> (h, w) uint8; rgb24 -> (h, w, 3) uint8. `size` = (w, h) rescales (bilinear).
    """
    if stride < 1:
        raise ValueError("stride must be >= 1")
    info = probe(path)
    w, h = size if size else (info.width, info.height)
    vf = f"select=not(mod(n\\,{stride}))"
    if size:
        vf += f",scale={w}:{h}:flags=bilinear"
    cmd = [tool("ffmpeg"), "-nostdin", "-v", "error", "-threads", "1", "-i", str(path), "-vf", vf]
    cmd += ["-fps_mode", "passthrough"]
    if max_samples:
        cmd += ["-frames:v", str(max_samples)]
    cmd += ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-"]
    channels = 1 if pix_fmt == "gray" else 3
    nbytes = w * h * channels
    shape = (h, w) if channels == 1 else (h, w, 3)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    k = 0
    try:
        while True:
            buf = proc.stdout.read(nbytes)
            if len(buf) < nbytes:
                break
            yield k * stride, np.frombuffer(buf, dtype=np.uint8).reshape(shape)
            k += 1
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def nominal_time(frame_index: int, fps: float) -> float:
    """Nominal seconds from the start of the clip at the stream frame rate (not wall-clock)."""
    return round(frame_index / fps, 6)
