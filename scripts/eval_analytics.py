#!/usr/bin/env python3
"""Measure precision/recall of the analytics models and write docs/analytics/error_rates.json.

Run from backend/ with the backend venv:  python ../scripts/eval_analytics.py
Datasets (not committed; backend/data/public/ is gitignored):
  PennFudanPed.zip  https://www.cis.upenn.edu/~jshi/ped_html/PennFudanPed.zip   (persons)
  BioID.zip         https://www.bioid.com/uploads/BioID-FaceDatabase-V1.2.zip   (faces)
Every number is labelled with its dataset; the motion numbers are SYNTHETIC.
"""

import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analytics import detect, frames, motion  # noqa: E402
from app.analytics.registry import MODELS  # noqa: E402
from app.carving.export import tool  # noqa: E402
from tests.analytics_media import interval_overlap_scores, motion_clip  # noqa: E402

DATA = ROOT / "backend" / "data" / "public"
OBJ_THRESHOLDS = [0.3, 0.5, 0.7]
FACE_THRESHOLDS = [0.5, 0.7, 0.9]
SYN = "synthetic, not representative of DVR footage"
PUBLIC = "public benchmark, not DVR footage; will not transfer to DVR footage"
TMP = Path(tempfile.mkdtemp(prefix="nk_eval_"))


def wilson(k: int, n: int, z: float = 1.96) -> list[float | None]:
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def bootstrap(per_image: np.ndarray, iters: int = 1000, seed: int = 0) -> dict:
    """per_image: (n, 3) of tp, fp, fn. Percentile 95% CI by resampling images."""
    rng = np.random.default_rng(seed)
    n = len(per_image)
    ps, rs = [], []
    for _ in range(iters):
        s = per_image[rng.integers(0, n, n)].sum(0)
        ps.append(s[0] / (s[0] + s[1]) if s[0] + s[1] else np.nan)
        rs.append(s[0] / (s[0] + s[2]) if s[0] + s[2] else np.nan)

    def ci(a):
        return [round(float(np.nanpercentile(a, q)), 4) for q in (2.5, 97.5)]

    return {"precision_ci_bootstrap": ci(ps), "recall_ci_bootstrap": ci(rs)}


def summarise(per_image: list[tuple[int, int, int]]) -> dict:
    a = np.array(per_image)
    tp, fp, fn = (int(x) for x in a.sum(0))
    out = {
        "n_images": len(per_image),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "precision_ci_wilson": wilson(tp, tp + fp),
        "recall_ci_wilson": wilson(tp, tp + fn),
    }
    out.update(bootstrap(a))
    return out


def iou(a, b) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def match_iou(gt: list, dets: list[dict]) -> tuple[int, int, int]:
    used: set[int] = set()
    tp = 0
    for d in sorted(dets, key=lambda d: -d["confidence"]):
        best, bi = 0.5, -1
        for i, g in enumerate(gt):
            if i not in used and iou(d["bbox"], g) >= best:
                best, bi = iou(d["bbox"], g), i
        if bi >= 0:
            used.add(bi)
            tp += 1
    return tp, len(dets) - tp, len(gt) - tp


def match_eyes(eyes: list, dets: list[dict]) -> tuple[int, int, int]:
    """BioID has one annotated face per image and only eye points: a detection is correct when
    its box contains both eyes and its width is 1.2-4.0 x the inter-eye distance."""
    (lx, ly), (rx, ry) = eyes
    eye_d = math.hypot(lx - rx, ly - ry)
    ok = False
    tp = fp = 0
    for d in sorted(dets, key=lambda d: -d["confidence"]):
        x1, y1, x2, y2 = d["bbox"]
        inside = all(x1 <= x <= x2 and y1 <= y <= y2 for x, y in eyes)
        if inside and 1.2 <= (x2 - x1) / eye_d <= 4.0 and not ok:
            ok = True
            tp += 1
        else:
            fp += 1
    return tp, fp, 0 if ok else 1


def degrade(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    """Downscale to fit 352x288 (aspect kept) + x264 crf 30, then decode like the pipeline."""
    h, w = rgb.shape[:2]
    r = min(352 / w, 288 / h)
    nw, nh = int(w * r) // 2 * 2, int(h * r) // 2 * 2
    src, dst = TMP / "in.png", TMP / "out.mp4"
    Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR).save(src)
    subprocess.run(
        [
            tool("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-c:v",
            "libx264",
        ]
        + [
            "-preset",
            "medium",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            str(dst),
        ],
        check=True,
    )
    frame = next(frames.read_frames(dst, pix_fmt="rgb24"))[1]
    return frame.copy(), nw / w


def eval_objects() -> dict:
    root = DATA / "PennFudanPed"
    names = sorted(p.stem for p in (root / "PNGImages").glob("*.png"))
    low = min(OBJ_THRESHOLDS)
    p = detect.DetectParams(conf_threshold=low)
    sess = detect.get_session(MODELS["objects"])
    acc = {(c, t): [] for c in ("original", "352x288_crf30") for t in OBJ_THRESHOLDS}
    for n in names:
        rgb = np.asarray(Image.open(root / "PNGImages" / f"{n}.png").convert("RGB"))
        txt = (root / "Annotation" / f"{n}.txt").read_text()
        gt = [
            [float(v) for v in m.groups()]
            for m in re.finditer(r": \((\d+), (\d+)\) - \((\d+), (\d+)\)", txt)
        ]
        for cond in ("original", "352x288_crf30"):
            img, r = (rgb, 1.0) if cond == "original" else degrade(rgb)
            g = [[v * r for v in b] for b in gt]
            dets = [
                d for d in detect.detect_objects_frame(img, p, sess) if d["class_name"] == "person"
            ]
            for t in OBJ_THRESHOLDS:
                acc[(cond, t)].append(match_iou(g, [d for d in dets if d["confidence"] >= t]))
    return {
        "model": MODELS["objects"].run_info(),
        "measured_classes": ["person"],
        "unmeasured_note": "Other COCO classes (e.g. car) were NOT measured; treat as unknown.",
        "configs": [
            {
                "dataset": "Penn-Fudan Pedestrian Database (Wang et al., 2007), person class",
                "dataset_url": "https://www.cis.upenn.edu/~jshi/ped_html/",
                "dataset_licence": (
                    "No licence grant stated; readme.txt: copyright retained by authors, works "
                    "may not be reposted. Used locally for evaluation, not redistributed"
                ),
                "label": PUBLIC,
                "condition": cond,
                "class": "person",
                "iou_threshold": 0.5,
                "confidence_threshold": t,
                "nms_iou": p.nms_iou,
                **summarise(acc[(cond, t)]),
            }
            for cond in ("original", "352x288_crf30")
            for t in OBJ_THRESHOLDS
        ],
    }


def eval_faces() -> dict:
    root = DATA / "bioid"
    names = sorted(p.stem for p in root.glob("*.pgm"))
    p = detect.DetectParams(conf_threshold=min(FACE_THRESHOLDS))
    sess = detect.get_session(MODELS["faces"])
    acc = {(c, t): [] for c in ("original", "352x288_crf30") for t in FACE_THRESHOLDS}
    for n in names:
        rgb = np.asarray(Image.open(root / f"{n}.pgm").convert("RGB"))
        v = [float(x) for x in (root / f"{n}.eye").read_text().splitlines()[1].split()]
        for cond in ("original", "352x288_crf30"):
            img, r = (rgb, 1.0) if cond == "original" else degrade(rgb)
            eyes = [(v[0] * r, v[1] * r), (v[2] * r, v[3] * r)]
            dets = detect.detect_faces_frame(img, p, sess)
            for t in FACE_THRESHOLDS:
                acc[(cond, t)].append(match_eyes(eyes, [d for d in dets if d["confidence"] >= t]))
    return {
        "model": MODELS["faces"].run_info(),
        "measured_classes": ["face"],
        "unmeasured_note": (
            "BioID is frontal, single-face, 384x286 grey images. Profile, occluded, small or "
            "multiple faces were NOT measured. Matching uses eye-containment (BioID has no boxes), "
            "not IoU 0.5. Unannotated extra faces would count as false positives."
        ),
        "configs": [
            {
                "dataset": "BioID Face Database v1.2 (Jesorsky et al., 2001), 1521 images",
                "dataset_url": "https://www.bioid.com/facedb/",
                "dataset_licence": "No licence text in the distribution (description.txt); "
                "published for face-detection research; used locally, not redistributed",
                "label": PUBLIC,
                "condition": cond,
                "match_rule": "box contains both annotated eye points, width 1.2-4.0x eye distance",
                "confidence_threshold": t,
                "nms_iou": p.nms_iou,
                **summarise(acc[(cond, t)]),
            }
            for cond in ("original", "352x288_crf30")
            for t in FACE_THRESHOLDS
        ],
    }


def eval_motion() -> dict:
    rng = np.random.default_rng(12345)
    cfgs = []
    for cond, size, crf in (
        ("320x240_crf23", (320, 240), 23),
        ("352x288_crf33", (352, 288), 33),
    ):
        per = []
        for i in range(30):
            segs, t = [], int(rng.integers(5, 15))
            for _ in range(int(rng.integers(1, 4))):
                ln = int(rng.integers(10, 30))
                if t + ln > 95:
                    break
                segs.append((t, t + ln))
                t += ln + int(rng.integers(15, 25))
            f = TMP / "m.mp4"
            gt = motion_clip(f, segs, size=size, crf=crf, seed=i)
            r = motion.analyse_motion(f)
            found = [(x["start_frame"], x["end_frame"]) for x in r["intervals"]]
            per.append(interval_overlap_scores(gt, found))
        cfgs.append(
            {
                "dataset": "30 synthetic clips (noise texture, 40x40 block at 5 px/frame)",
                "label": SYN,
                "condition": cond,
                "match_rule": "interval frame-IoU >= 0.5",
                **summarise(per),
            }
        )
    return {
        "model": None,
        "measured_classes": [],
        "measured_params": motion.MotionParams().to_dict(),
        "unmeasured_note": "Motion = changed pixels only. Lighting changes, noise and compression "
        "artefacts on real DVR footage were NOT measured.",
        "configs": cfgs,
    }


def main() -> None:
    out = {
        "label": "triage, not identification",
        "generated_by": "scripts/eval_analytics.py",
        "statement": (
            "Nothing here was validated on real DVR footage. Public-benchmark numbers will not "
            "transfer to low-resolution, highly compressed DVR footage; synthetic numbers are not "
            "representative either."
        ),
        "entries": {
            "objects": eval_objects(),
            "faces": eval_faces(),
            "motion": eval_motion(),
        },
    }
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    (ROOT / "docs" / "analytics" / "error_rates.json").write_text(text)
    (ROOT / "backend" / "app" / "analytics" / "error_rates.json").write_text(text)
    for k, e in out["entries"].items():
        for c in e["configs"]:
            print(
                k,
                c["condition"],
                c.get("confidence_threshold", ""),
                "P",
                c["precision"],
                c["precision_ci_wilson"],
                "R",
                c["recall"],
                c["recall_ci_wilson"],
                c["n_images"],
            )


if __name__ == "__main__":
    main()
