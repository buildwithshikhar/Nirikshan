"""Motion detection by frame differencing / running-average background subtraction (numpy, CPU).

Frames are decoded to reduced-size gray, box-blurred, compared with a background model and
thresholded. A sampled frame is "moving" when the changed area reaches `min_area` pixels (at the
analysis size). Consecutive moving samples form an interval. Output is a TRIAGE lead: motion
means pixels changed (including lighting changes, compression artefacts and camera noise), not
that a person or object moved. Times are NOMINAL (frame index / stream fps), not recording times.
"""

from dataclasses import asdict, dataclass

import numpy as np

from app.analytics import TRIAGE_LABEL
from app.analytics.frames import nominal_time, probe, read_frames


@dataclass(frozen=True)
class MotionParams:
    stride: int = 2  # analyse every n-th decoded frame
    width: int = 160  # analysis width in pixels (height keeps the aspect ratio)
    blur: int = 1  # box-blur radius in pixels at analysis size (0 = off)
    threshold: int = 25  # per-pixel absolute difference (0-255) counted as changed
    min_area: int = 24  # changed pixels (analysis size) for a sample to count as motion
    bg_alpha: float = 1.0  # background update rate; 1.0 = difference to previous sample
    merge_gap: int = 2  # samples of stillness tolerated inside one interval
    min_samples: int = 1  # minimum moving samples for an interval
    max_samples: int | None = None

    def validate(self) -> "MotionParams":
        if not (1 <= self.stride <= 1000):
            raise ValueError("stride must be 1..1000")
        if not (16 <= self.width <= 1280):
            raise ValueError("width must be 16..1280")
        if not (0 <= self.blur <= 20):
            raise ValueError("blur must be 0..20")
        if not (1 <= self.threshold <= 255):
            raise ValueError("threshold must be 1..255")
        if self.min_area < 1:
            raise ValueError("min_area must be >= 1")
        if not (0.0 < self.bg_alpha <= 1.0):
            raise ValueError("bg_alpha must be in (0, 1]")
        if self.merge_gap < 0 or self.min_samples < 1:
            raise ValueError("merge_gap must be >= 0 and min_samples >= 1")
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def box_blur(img: np.ndarray, radius: int) -> np.ndarray:
    """Separable box blur with edge replication, float32 (deterministic, no dependencies)."""
    if radius <= 0:
        return img.astype(np.float32)
    k = 2 * radius + 1
    out = img.astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius + 1, radius)
        c = np.cumsum(np.pad(out, pad, mode="edge"), axis=axis, dtype=np.float64)
        n = out.shape[axis]
        hi = np.take(c, np.arange(k, k + n), axis=axis)
        lo = np.take(c, np.arange(0, n), axis=axis)
        out = ((hi - lo) / k).astype(np.float32)
    return out


def analyse_motion(path, params: MotionParams | None = None) -> dict:
    """Return {"samples": [...], "intervals": [...], "params", "video", "label"}."""
    p = (params or MotionParams()).validate()
    info = probe(path)
    w = p.width - p.width % 2
    h = max(2, int(round(info.height * w / info.width)))
    h -= h % 2
    bg: np.ndarray | None = None
    samples: list[tuple[int, float, bool]] = []
    for idx, frame in read_frames(
        path, stride=p.stride, pix_fmt="gray", size=(w, h), max_samples=p.max_samples
    ):
        cur = box_blur(frame, p.blur)
        if bg is None:
            bg = cur
            samples.append((idx, 0.0, False))
            continue
        changed = int((np.abs(cur - bg) >= p.threshold).sum())
        samples.append((idx, changed / cur.size, changed >= p.min_area))
        bg = cur if p.bg_alpha >= 1.0 else (1.0 - p.bg_alpha) * bg + p.bg_alpha * cur
    intervals = _intervals(samples, p, info.fps)
    return {
        "label": TRIAGE_LABEL,
        "params": p.to_dict(),
        "video": {
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "analysis_size": [w, h],
        },
        "frames_analysed": len(samples),
        "samples": [{"frame_index": i, "score": round(s, 6), "moving": m} for i, s, m in samples],
        "intervals": intervals,
        "time_basis": "nominal: frame_index / stream frame rate (not recording time)",
    }


def _intervals(samples: list[tuple[int, float, bool]], p: MotionParams, fps: float) -> list[dict]:
    out: list[dict] = []
    cur: list[tuple[int, float]] = []
    gap = 0
    for idx, score, moving in samples:
        if moving:
            cur.append((idx, score))
            gap = 0
        elif cur:
            gap += 1
            if gap > p.merge_gap:
                _close(out, cur, p, fps)
                cur, gap = [], 0
    if cur:
        _close(out, cur, p, fps)
    return out


def _close(out: list[dict], cur: list[tuple[int, float]], p: MotionParams, fps: float) -> None:
    if len(cur) < p.min_samples:
        return
    scores = [s for _, s in cur]
    start, end = cur[0][0], cur[-1][0]
    out.append(
        {
            "start_frame": start,
            "end_frame": end,
            "start_time_s": nominal_time(start, fps),
            "end_time_s": nominal_time(end, fps),
            "n_samples": len(cur),
            "score_peak": round(max(scores), 6),
            "score_mean": round(sum(scores) / len(scores), 6),
            "label": TRIAGE_LABEL,
        }
    )
