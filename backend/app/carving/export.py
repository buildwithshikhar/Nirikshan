"""Clip export: carved bytes -> raw bitstream (hashed) -> MP4 with `-c copy` (never re-encoded),
then a decode test and ffprobe. Failures are returned, never hidden.

Durations come from the elementary stream's frame rate (ffmpeg assumes 25 fps when the stream
carries no timing information); they are NOT wall-clock recording durations.
"""

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

COPY_CHUNK = 4 * 1024 * 1024
FFMPEG_TIMEOUT = 300


class FfmpegMissing(RuntimeError):
    pass


FALLBACK_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


def find_tool(name: str) -> str | None:
    """PATH first, then standard Homebrew/system dirs (IDE-launched processes often lack them)."""
    found = shutil.which(name)
    if found:
        return found
    for d in FALLBACK_DIRS:
        cand = Path(d) / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def tool(name: str) -> str:
    path = find_tool(name)
    if path is None:
        raise FfmpegMissing(f"{name} not found on PATH (brew install ffmpeg)")
    return path


def ffmpeg_version() -> str:
    out = subprocess.run([tool("ffmpeg"), "-version"], capture_output=True, text=True, timeout=10)
    return out.stdout.splitlines()[0] if out.stdout else "unknown"


@dataclass
class ExportResult:
    bitstream_sha256: str
    bitstream_bytes: int
    mp4_path: str = ""
    mp4_sha256: str = ""
    decode_status: str = "export_failed"  # ok | decode_errors | export_failed
    decode_errors: list[str] = field(default_factory=list)
    error: str = ""
    width: int | None = None
    height: int | None = None
    fps: str = ""
    duration_s: float | None = None
    codec_name: str = ""
    packets: int | None = None


def write_bitstream(f: BinaryIO, extents: list[list[int]], dest: Path) -> tuple[str, int]:
    """Concatenate extents into dest, streaming; returns (sha256, bytes)."""
    h, total = hashlib.sha256(), 0
    with open(dest, "wb") as out:
        for s, e in extents:
            f.seek(s)
            left = e - s
            while left > 0:
                chunk = f.read(min(COPY_CHUNK, left))
                if not chunk:
                    raise OSError("short read while exporting clip")
                out.write(chunk)
                h.update(chunk)
                total += len(chunk)
                left -= len(chunk)
    return h.hexdigest(), total


def _lines(text: str, limit: int = 20) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()][:limit]


def export_clip(
    f: BinaryIO, extents: list[list[int]], codec: str, out_dir: Path, name: str
) -> ExportResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, mp4 = out_dir / f"{name}.{codec}", out_dir / f"{name}.mp4"
    sha, size = write_bitstream(f, extents, raw)
    res = ExportResult(bitstream_sha256=sha, bitstream_bytes=size)
    fmt = "h264" if codec == "h264" else "hevc"
    cmd = [
        tool("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-f",
        fmt,
        "-i",
        str(raw),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
    ]
    if codec == "h265":
        cmd += ["-tag:v", "hvc1"]
    try:
        mux = subprocess.run(
            cmd + [str(mp4)], capture_output=True, text=True, timeout=FFMPEG_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        res.error = "ffmpeg mux timed out"
        raw.unlink(missing_ok=True)
        return res
    if mux.returncode != 0 or not mp4.exists() or mp4.stat().st_size == 0:
        res.error = "; ".join(_lines(mux.stderr, 5)) or f"ffmpeg exited {mux.returncode}"
        mp4.unlink(missing_ok=True)
        return res
    # Decode test on the carved bitstream itself: a container's timestamp guesses (e.g. B-frame
    # DTS from a raw stream) are not data damage and must not mask or fake decode errors.
    dec = subprocess.run(
        [tool("ffmpeg"), "-nostdin", "-v", "error", "-f", fmt, "-i", str(raw), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT,
    )
    raw.unlink(missing_ok=True)
    res.decode_errors = _lines(dec.stderr)
    res.decode_status = "ok" if dec.returncode == 0 and not res.decode_errors else "decode_errors"
    probe = subprocess.run(
        [
            tool("ffprobe"),
            "-v",
            "error",
            "-count_packets",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,nb_read_packets:format=duration",
            "-of",
            "json",
            str(mp4),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        info = json.loads(probe.stdout)
        st = (info.get("streams") or [{}])[0]
        res.width, res.height = st.get("width"), st.get("height")
        res.fps, res.codec_name = st.get("r_frame_rate", ""), st.get("codec_name", "")
        res.packets = int(st["nb_read_packets"]) if st.get("nb_read_packets") else None
        dur = info.get("format", {}).get("duration")
        res.duration_s = float(dur) if dur else None
    except (ValueError, KeyError):
        res.decode_errors.append("ffprobe returned no usable stream information")
        res.decode_status = "decode_errors"
    res.mp4_path = str(mp4)
    with open(mp4, "rb") as fh:
        d = hashlib.sha256()
        while chunk := fh.read(COPY_CHUNK):
            d.update(chunk)
    res.mp4_sha256 = d.hexdigest()
    return res
