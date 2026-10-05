"""Object and face DETECTION on CPU with ONNX Runtime.

Detection only: boxes, a class name and a confidence. No embeddings, no landmarks, no identity,
no matching of any kind. Every result carries the label "triage, not identification".
Deterministic: single-threaded CPUExecutionProvider, fixed pre/post-processing, no randomness.
"""

import threading
from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image

from app.analytics import TRIAGE_LABEL
from app.analytics.frames import nominal_time, probe, read_frames
from app.analytics.registry import MODELS, ModelSpec, verified_model_path

_SESSIONS: dict[str, object] = {}
_LOCK = threading.Lock()


def get_session(spec: ModelSpec):
    """Cached CPU-only ONNX session; verifies the model checksum first (raises ModelMissing)."""
    import onnxruntime as ort

    path = verified_model_path(spec)
    with _LOCK:
        key = f"{spec.key}:{spec.sha256}"
        if key not in _SESSIONS:
            so = ort.SessionOptions()
            so.intra_op_num_threads = 1
            so.inter_op_num_threads = 1
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            _SESSIONS[key] = ort.InferenceSession(
                str(path), sess_options=so, providers=["CPUExecutionProvider"]
            )
        return _SESSIONS[key]


@dataclass(frozen=True)
class DetectParams:
    stride: int = 25  # analyse every n-th decoded frame
    conf_threshold: float = 0.30
    nms_iou: float = 0.45
    max_samples: int | None = 200
    max_per_frame: int = 100

    def validate(self) -> "DetectParams":
        if not (1 <= self.stride <= 100000):
            raise ValueError("stride must be >= 1")
        if not (0.0 < self.conf_threshold < 1.0):
            raise ValueError("conf_threshold must be in (0, 1)")
        if not (0.0 < self.nms_iou <= 1.0):
            raise ValueError("nms_iou must be in (0, 1]")
        if self.max_samples is not None and self.max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def letterbox(rgb: np.ndarray, size: tuple[int, int], pad_value: int) -> tuple[np.ndarray, float]:
    """Resize keeping aspect (top-left aligned), pad to size. Returns (HxWx3 uint8, scale)."""
    tw, th = size
    h, w = rgb.shape[:2]
    r = min(tw / w, th / h)
    nw, nh = max(1, int(round(w * r))), max(1, int(round(h * r)))
    img = Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR)
    out = np.full((th, tw, 3), pad_value, dtype=np.uint8)
    out[:nh, :nw] = np.asarray(img)
    return out, r


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """Greedy NMS (stable order: score desc, then index asc). boxes are x1,y1,x2,y2."""
    order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), i))
    keep: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order:
        i = order.pop(0)
        keep.append(i)
        rest = []
        for j in order:
            xx1, yy1 = max(boxes[i, 0], boxes[j, 0]), max(boxes[i, 1], boxes[j, 1])
            xx2, yy2 = min(boxes[i, 2], boxes[j, 2]), min(boxes[i, 3], boxes[j, 3])
            inter = max(0.0, xx2 - xx1) * max(0.0, yy2 - yy1)
            union = areas[i] + areas[j] - inter
            if union <= 0 or inter / union <= iou_thr:
                rest.append(j)
        order = rest
    return keep


def _det(box, score: float, name: str) -> dict:
    return {
        "label": TRIAGE_LABEL,
        "class_name": name,
        "confidence": round(float(score), 4),
        "bbox": [round(float(v), 1) for v in box],
    }


def detect_objects_frame(rgb: np.ndarray, params: DetectParams, session=None) -> list[dict]:
    spec = MODELS["objects"]
    sess = session or get_session(spec)
    img, r = letterbox(rgb, spec.input_size, 114)
    x = np.ascontiguousarray(img[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32)[None]  # BGR
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]  # (3549, 85)
    grids, strides = [], []
    for s in (8, 16, 32):
        gw, gh = spec.input_size[0] // s, spec.input_size[1] // s
        gx, gy = np.meshgrid(np.arange(gw), np.arange(gh))
        grids.append(np.stack((gx, gy), 2).reshape(-1, 2))
        strides.append(np.full((gw * gh, 1), s))
    grid, stride = np.concatenate(grids).astype(np.float32), np.concatenate(strides)
    xy = (out[:, :2] + grid) * stride
    wh = np.exp(out[:, 2:4]) * stride
    cls = out[:, 5:]
    cid = cls.argmax(1)
    score = out[:, 4] * cls[np.arange(len(cls)), cid]
    m = score >= params.conf_threshold
    if not m.any():
        return []
    xy, wh, cid, score = xy[m], wh[m], cid[m], score[m]
    boxes = np.concatenate((xy - wh / 2, xy + wh / 2), 1) / r
    h, w = rgb.shape[:2]
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
    results = []
    for c in sorted(set(cid.tolist())):
        idx = np.where(cid == c)[0]
        for k in nms(boxes[idx], score[idx], params.nms_iou):
            results.append((float(score[idx[k]]), int(c), boxes[idx[k]]))
    results.sort(key=lambda t: (-t[0], t[1], tuple(t[2])))
    return [_det(b, s, spec.labels[c]) for s, c, b in results[: params.max_per_frame]]


def detect_faces_frame(rgb: np.ndarray, params: DetectParams, session=None) -> list[dict]:
    spec = MODELS["faces"]
    sess = session or get_session(spec)
    img, r = letterbox(rgb, spec.input_size, 0)
    x = np.ascontiguousarray(img[:, :, ::-1].transpose(2, 0, 1), dtype=np.float32)[None]  # BGR
    outs = [o[0] for o in sess.run(None, {sess.get_inputs()[0].name: x})]
    named = dict(zip([o.name for o in sess.get_outputs()], outs, strict=True))
    boxes_all, scores_all = [], []
    for stride in (8, 16, 32):
        cols = spec.input_size[0] // stride
        cls = np.clip(named[f"cls_{stride}"][:, 0], 0, 1)
        obj = np.clip(named[f"obj_{stride}"][:, 0], 0, 1)
        bb = named[f"bbox_{stride}"]
        n = len(cls)
        rr, cc = np.divmod(np.arange(n), cols)
        cx = (cc + bb[:, 0]) * stride
        cy = (rr + bb[:, 1]) * stride
        bw = np.exp(bb[:, 2]) * stride
        bh = np.exp(bb[:, 3]) * stride
        boxes_all.append(np.stack((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), 1))
        scores_all.append(np.sqrt(cls * obj))
    boxes, scores = np.concatenate(boxes_all) / r, np.concatenate(scores_all)
    m = scores >= params.conf_threshold
    if not m.any():
        return []
    boxes, scores = boxes[m], scores[m]
    h, w = rgb.shape[:2]
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
    keep = nms(boxes, scores, params.nms_iou)[: params.max_per_frame]
    return [_det(boxes[k], scores[k], "face") for k in keep]


FRAME_FUNCS = {"objects": detect_objects_frame, "faces": detect_faces_frame}


def analyse_detections(path, kind: str, params: DetectParams | None = None) -> dict:
    """Run detection on every `stride`-th frame of an exported clip."""
    if kind not in FRAME_FUNCS:
        raise ValueError(f"unknown detection kind {kind!r}")
    p = (params or DetectParams()).validate()
    spec = MODELS[kind]
    sess = get_session(spec)  # fail early (actionable) if the model is missing
    info = probe(path)
    fn = FRAME_FUNCS[kind]
    detections: list[dict] = []
    frames = 0
    for idx, rgb in read_frames(path, stride=p.stride, pix_fmt="rgb24", max_samples=p.max_samples):
        frames += 1
        for d in fn(rgb, p, sess):
            detections.append(
                {"frame_index": idx, "nominal_time_s": nominal_time(idx, info.fps), **d}
            )
    return {
        "label": TRIAGE_LABEL,
        "kind": kind,
        "params": p.to_dict(),
        "video": {"width": info.width, "height": info.height, "fps": info.fps},
        "frames_analysed": frames,
        "detections": detections,
        "time_basis": "nominal: frame_index / stream frame rate (not recording time)",
    }
