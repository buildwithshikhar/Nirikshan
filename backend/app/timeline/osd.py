"""OSD (burned-in time overlay) cross-check (P5).

Samples frames from an exported clip MP4 with ffmpeg (CPU), crops the overlay ROI, reads the
text with OCR, parses the date/time and compares it with the metadata-derived wall clock at that
frame. The delta distribution is reported with a pass/fail against a stated tolerance.

Honesty rules:
  * An unreadable ROI (low contrast, OCR confidence below threshold, text that does not parse
    as a valid date/time) is reported as `unreadable`/`unparsed`; a value is never guessed.
  * An overlay whose day/month order is ambiguous (e.g. 03/09/2025) is reported `ambiguous` with
    BOTH candidates and is excluded from the delta statistics.
  * Overlays usually show whole seconds, so deltas carry about 1 s of granularity; the default
    tolerance is 2 s. The OSD shows the device wall clock, so the comparison is wall clock to
    wall clock; no timezone is needed for DHAV or device-local epoch values.
  * OCR accuracy depends on the font/resolution/compression. The measured accuracy on RENDERED
    SYNTHETIC overlays is in docs/timeline.md; it is not an accuracy claim for real DVR footage.

OCR library: rapidocr-onnxruntime (Apache-2.0; PP-OCR det/rec ONNX models bundled in the wheel,
Apache-2.0) running on onnxruntime (MIT), CPU only, fully offline. Tesseract was not available
and is not required.
"""

from __future__ import annotations

import io
import re
import statistics
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from importlib import metadata

from app.carving.export import find_tool
from app.timeline.timestamps import validate_wall_clock

DEFAULT_ROI = (0.0, 0.0, 0.6, 0.12)  # x, y, w, h as fractions of the frame: top-left strip
DEFAULT_TOLERANCE_S = 2.0
MIN_CONFIDENCE = 0.6
MIN_CONTRAST_STD = 12.0  # gray-level std dev of the ROI below which text is not attempted
MIN_READABLE = 3


class OcrUnavailable(RuntimeError):
    pass


def ocr_library_info() -> dict:
    """OCR library/version/licence for the record (never fails when the package is missing)."""

    def ver(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "not installed"

    return {
        "library": "rapidocr-onnxruntime",
        "version": ver("rapidocr-onnxruntime"),
        "licence": "Apache-2.0",
        "models": "PP-OCR detection+recognition ONNX models bundled in the wheel (Apache-2.0)",
        "runtime": f"onnxruntime {ver('onnxruntime')} (MIT), CPU",
        "offline": True,
    }


_ENGINE = None


def rapid_engine() -> Callable:
    """Lazy RapidOCR wrapper: callable(gray PIL image) -> (text, mean confidence)."""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:  # pragma: no cover - environment problem, reported actionably
        raise OcrUnavailable(
            "OSD OCR needs the pip package 'rapidocr-onnxruntime' (Apache-2.0, bundles its "
            "models, offline): pip install rapidocr-onnxruntime==1.4.4"
        ) from exc
    ocr = RapidOCR()

    def run(img) -> tuple[str, float]:
        arr = np.array(img.convert("RGB"))
        result, _ = ocr(arr)
        if not result:
            return "", 0.0
        text = " ".join(r[1] for r in result)
        conf = sum(float(r[2]) for r in result) / len(result)
        return text, conf

    _ENGINE = run
    return run


@dataclass
class OverlayParse:
    status: str  # ok | ambiguous | unparsed
    wall: datetime | None = None
    candidates: list[datetime] = field(default_factory=list)
    fmt: str = ""
    note: str = ""


_YMD = re.compile(r"(\d{4})([-/.])(\d{2})\2(\d{2})\s*(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)?")
_XY = re.compile(r"(\d{2})([-/.])(\d{2})\2(\d{4})\s*(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)?")


def _hour(h: int, ampm: str | None) -> int | None:
    if ampm is None:
        return h
    if not 1 <= h <= 12:
        return None
    return (h % 12) + (12 if ampm == "PM" else 0)


def _mk(y, mo, d, h, mi, s) -> datetime | None:
    try:
        validate_wall_clock(y, mo, d, h, mi, s)
    except ValueError:
        return None
    return datetime(y, mo, d, h, mi, s)


def parse_overlay_text(text: str) -> OverlayParse:
    """Parse OCR text. Formats: YYYY-MM-DD HH:MM:SS, DD-MM-YYYY, MM/DD/YYYY (ambiguity is
    reported, never resolved), 12 h with AM/PM. OCR often drops the space between date and time,
    so whitespace is optional there."""
    t = text.upper()
    m = _YMD.search(t)
    if m:
        y, mo, d, h, mi, s = (int(m.group(i)) for i in (1, 3, 4, 5, 6, 7))
        hh = _hour(h, m.group(8))
        dt = _mk(y, mo, d, hh, mi, s) if hh is not None else None
        if dt is None:
            return OverlayParse("unparsed", note="matched YYYY-MM-DD but values are not valid")
        return OverlayParse(
            "ok", dt, [dt], "YYYY-MM-DD HH:MM:SS" + (" AM/PM" if m.group(8) else "")
        )
    m = _XY.search(t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        h, mi, s = int(m.group(5)), int(m.group(6)), int(m.group(7))
        hh = _hour(h, m.group(8))
        if hh is None:
            return OverlayParse("unparsed", note="12-hour clock with hour outside 1-12")
        dmy, mdy = _mk(y, b, a, hh, mi, s), _mk(y, a, b, hh, mi, s)
        suffix = " AM/PM" if m.group(8) else ""
        if dmy and mdy and dmy != mdy:
            return OverlayParse(
                "ambiguous",
                None,
                [dmy, mdy],
                "DD-MM-YYYY or MM/DD/YYYY" + suffix,
                "day/month order cannot be determined from the overlay; not guessed",
            )
        dt = dmy or mdy
        if dt is None:
            return OverlayParse("unparsed", note="matched ##/##/#### but values are not valid")
        fmt = "DD-MM-YYYY" if dmy else "MM/DD/YYYY"
        return OverlayParse("ok", dt, [dt], fmt + " HH:MM:SS" + suffix)
    return OverlayParse("unparsed", note="no date/time pattern found")


@dataclass
class OsdReading:
    t_s: float  # sample position in the clip (s)
    status: str  # ok | ambiguous | unreadable | unparsed
    text: str = ""
    confidence: float = 0.0
    reason: str = ""
    wall: datetime | None = None
    candidates: list[datetime] = field(default_factory=list)
    fmt: str = ""
    delta_s: float | None = None

    def to_dict(self) -> dict:
        return {
            "t_s": round(self.t_s, 3),
            "status": self.status,
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "osd_wall": self.wall.isoformat(sep=" ") if self.wall else None,
            "candidates": [c.isoformat(sep=" ") for c in self.candidates],
            "format": self.fmt,
            "delta_s": self.delta_s,
        }


def preprocess(img):
    """Gray, upscale to >= 64 px high, pad. Returns (processed image, contrast std dev)."""
    from PIL import Image, ImageOps, ImageStat

    g = img.convert("L")
    contrast = ImageStat.Stat(g).stddev[0]
    if g.height < 64:
        k = 64 / g.height
        g = g.resize((max(1, round(g.width * k)), 64), Image.LANCZOS)
    g = ImageOps.expand(g, border=12, fill=int(ImageStat.Stat(g).median[0]))
    return g, contrast


def read_overlay(img, t_s: float, engine: Callable | None = None) -> OsdReading:
    """OCR one cropped ROI image. Never raises on bad images; low quality is `unreadable`."""
    proc, contrast = preprocess(img)
    if contrast < MIN_CONTRAST_STD:
        return OsdReading(
            t_s, "unreadable", reason=f"low contrast (std {contrast:.1f} < {MIN_CONTRAST_STD})"
        )
    text, conf = (engine or rapid_engine())(proc)
    if not text.strip():
        return OsdReading(t_s, "unreadable", "", conf, "OCR found no text")
    if conf < MIN_CONFIDENCE:
        return OsdReading(
            t_s, "unreadable", text, conf, f"OCR confidence {conf:.2f} < {MIN_CONFIDENCE}"
        )
    p = parse_overlay_text(text)
    if p.status == "unparsed":
        return OsdReading(t_s, "unparsed", text, conf, p.note)
    return OsdReading(t_s, p.status, text, conf, p.note, p.wall, p.candidates, p.fmt)


def crop_roi(img, roi: tuple[float, float, float, float]):
    x, y, w, h = roi
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
        raise ValueError("roi must be fractions (x, y, w, h) within the frame")
    W, H = img.size
    box = (int(x * W), int(y * H), min(W, int((x + w) * W) + 1), min(H, int((y + h) * H) + 1))
    return img.crop(box)


def probe_duration(mp4: str, ffprobe: str | None = None) -> float:
    exe = ffprobe or find_tool("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe not found (install ffmpeg)")
    out = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        return float(out.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"ffprobe could not read the duration: {out.stderr.strip()}") from exc


def grab_frame(mp4: str, t_s: float, ffmpeg: str | None = None):
    """One decoded frame at ~t_s (accurate seek) as a PIL image, or None."""
    from PIL import Image

    exe = ffmpeg or find_tool("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found (install ffmpeg)")
    out = subprocess.run(
        [exe, "-nostdin", "-v", "error", "-ss", f"{t_s:.3f}", "-i", mp4, "-frames:v", "1",
         "-f", "image2pipe", "-c:v", "png", "-"],
        capture_output=True,
        timeout=60,
    )  # fmt: skip
    if out.returncode != 0 or not out.stdout:
        return None
    return Image.open(io.BytesIO(out.stdout)).convert("RGB")


def summarize(
    readings: list[OsdReading],
    tolerance_s: float = DEFAULT_TOLERANCE_S,
    min_readable: int = MIN_READABLE,
) -> dict:
    """Delta distribution + verdict. delta = OSD wall clock - metadata wall clock (seconds)."""
    counts = {k: sum(r.status == k for r in readings) for k in ("ok", "ambiguous")}
    counts["unreadable"] = sum(r.status in ("unreadable", "unparsed") for r in readings)
    deltas = [r.delta_s for r in readings if r.status == "ok" and r.delta_s is not None]
    out: dict = {
        "samples": len(readings),
        "readable": len(deltas),
        "ambiguous": counts["ambiguous"],
        "unreadable": counts["unreadable"],
        "tolerance_s": tolerance_s,
        "min_readable": min_readable,
        "median_delta_s": None,
        "mad_s": None,
        "min_delta_s": None,
        "max_delta_s": None,
        "outliers": [],
    }
    if not deltas:
        out["status"] = "unreadable" if readings else "no_samples"
        return out
    med = statistics.median(deltas)
    mad = statistics.median(abs(d - med) for d in deltas)
    thr = max(3 * 1.4826 * mad, 1.0)
    out.update(
        median_delta_s=med,
        mad_s=mad,
        min_delta_s=min(deltas),
        max_delta_s=max(deltas),
        outliers=[
            {"t_s": round(r.t_s, 3), "delta_s": r.delta_s}
            for r in readings
            if r.status == "ok" and r.delta_s is not None and abs(r.delta_s - med) > thr
        ],
    )
    if len(deltas) < min_readable:
        out["status"] = "unreadable"
        out["reason"] = f"only {len(deltas)} readable sample(s); need {min_readable}"
    elif all(abs(d) <= tolerance_s for d in deltas):
        out["status"] = "pass"
    elif abs(med) > tolerance_s:
        out["status"] = "fail"
    else:
        out["status"] = "inconclusive"
        out["reason"] = "median within tolerance but some samples are outside it"
    return out


def check_clip(
    mp4: str,
    start_wall: datetime | None,
    *,
    roi: tuple[float, float, float, float] = DEFAULT_ROI,
    n_samples: int = 8,
    tolerance_s: float = DEFAULT_TOLERANCE_S,
    duration_s: float | None = None,
    engine: Callable | None = None,
    min_readable: int = MIN_READABLE,
) -> dict:
    """Run the OSD cross-check on an exported clip.

    `start_wall` is the metadata wall clock at the clip start (naive, device wall clock) or None
    when it cannot be derived (e.g. timezone unknown for a UTC-basis epoch); readings are then
    still returned but no delta/verdict is produced."""
    if not 1 <= n_samples <= 60:
        raise ValueError("n_samples must be 1-60")
    dur = duration_s if duration_s else probe_duration(mp4)
    times = [dur * (0.05 + 0.9 * i / max(1, n_samples - 1)) for i in range(n_samples)]
    if n_samples == 1:
        times = [dur * 0.5]
    readings: list[OsdReading] = []
    for t in times:
        frame = grab_frame(mp4, t)
        if frame is None:
            readings.append(OsdReading(t, "unreadable", reason="frame could not be decoded"))
            continue
        r = read_overlay(crop_roi(frame, roi), t, engine)
        if r.status == "ok" and start_wall is not None and r.wall is not None:
            r.delta_s = (r.wall - (start_wall + timedelta(seconds=t))).total_seconds()
        readings.append(r)
    out = {
        "ocr": ocr_library_info(),
        "roi": list(roi),
        "tolerance_s": tolerance_s,
        "duration_s": dur,
        "metadata_start_wall": start_wall.isoformat(sep=" ") if start_wall else None,
        "comparison_available": start_wall is not None,
        "readings": [r.to_dict() for r in readings],
        "caveats": [
            "OSD shows whole seconds: deltas carry ~1 s granularity",
            "frame time is the requested seek position (accurate seek), not a decoded pts",
            "wall-clock comparison; OSD may be rendered by the DVR from its own clock, so "
            "agreement does not prove the clock was correct",
        ],
    }
    if start_wall is None:
        out["summary"] = {
            **summarize(readings, tolerance_s, min_readable),
            "status": "no_reference",
            "reason": "metadata wall clock for the clip start could not be derived "
            "(see timestamp flags); readings are not compared",
        }
    else:
        out["summary"] = summarize(readings, tolerance_s, min_readable)
    return out
