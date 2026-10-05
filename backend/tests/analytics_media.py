"""SYNTHETIC clips for analytics tests (a static noise texture with moving blocks)."""

import subprocess

import numpy as np

from app.carving.export import tool


def encode_gray_frames(frames: np.ndarray, out_path, fps: int = 25, crf: int = 23) -> None:
    """frames: (n, h, w) uint8 -> H.264 MP4 (yuv420p)."""
    n, h, w = frames.shape
    cmd = [tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray"]
    cmd += ["-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast"]
    cmd += ["-crf", str(crf), "-threads", "1", "-pix_fmt", "yuv420p", "-g", "25", str(out_path)]
    subprocess.run(cmd, input=frames.tobytes(), check=True, capture_output=True)


def motion_clip(
    out_path,
    segments: list[tuple[int, int]],
    n_frames: int = 100,
    size: tuple[int, int] = (320, 240),
    block: int = 40,
    speed: int = 5,
    seed: int = 0,
    crf: int = 23,
    noise: float = 1.5,
) -> list[tuple[int, int]]:
    """Static textured background; a bright block is visible and moving only inside each
    (first_frame, last_frame) segment. Returns the ground-truth segments."""
    w, h = size
    rng = np.random.default_rng(seed)
    bg = rng.integers(60, 120, size=(h, w)).astype(np.float32)
    frames = np.empty((n_frames, h, w), dtype=np.uint8)
    for f in range(n_frames):
        img = bg + rng.normal(0, noise, size=(h, w)).astype(np.float32)
        for a, b in segments:
            if a <= f <= b:
                x = (10 + (f - a) * speed) % max(1, w - block)
                y = h // 2 - block // 2
                img[y : y + block, x : x + block] = 230
        frames[f] = np.clip(img, 0, 255).astype(np.uint8)
    encode_gray_frames(frames, out_path, crf=crf)
    return segments


def interval_overlap_scores(
    truth: list[tuple[int, int]], found: list[tuple[int, int]], iou_min: float = 0.5
) -> tuple[int, int, int]:
    """Greedy one-to-one matching of frame intervals by IoU. Returns (tp, fp, fn)."""
    used: set[int] = set()
    tp = 0
    for a, b in truth:
        best, best_i = 0.0, -1
        for i, (c, d) in enumerate(found):
            if i in used:
                continue
            inter = max(0, min(b, d) - max(a, c) + 1)
            union = (b - a + 1) + (d - c + 1) - inter
            iou = inter / union if union else 0.0
            if iou > best:
                best, best_i = iou, i
        if best >= iou_min:
            used.add(best_i)
            tp += 1
    return tp, len(found) - tp, len(truth) - tp
