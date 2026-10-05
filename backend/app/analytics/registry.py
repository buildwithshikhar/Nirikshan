"""Model cards. The weights are not committed; scripts/fetch_models.py downloads and verifies them.

Runtime never touches the network: a missing or checksum-mismatching model is an error that
names the fetch command.
"""

import hashlib
import os
from dataclasses import asdict, dataclass
from pathlib import Path

FETCH_COMMAND = "python scripts/fetch_models.py"

COCO_LABELS = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant "
    "stop_sign parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe "
    "backpack umbrella handbag tie suitcase frisbee skis snowboard sports_ball kite baseball_bat "
    "baseball_glove skateboard surfboard tennis_racket bottle wine_glass cup fork knife spoon "
    "bowl banana apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch "
    "potted_plant bed dining_table toilet tv laptop mouse remote keyboard cell_phone microwave "
    "oven toaster sink refrigerator book clock vase scissors teddy_bear hair_drier toothbrush"
).split()
assert len(COCO_LABELS) == 80


class ModelMissing(RuntimeError):
    """Raised when a model file is absent or fails its checksum (message is actionable)."""


@dataclass(frozen=True)
class ModelSpec:
    key: str  # objects | faces
    name: str
    version: str
    filename: str
    url: str
    sha256: str
    size_bytes: int
    licence: str
    licence_url: str
    input_size: tuple[int, int]  # (width, height)
    labels: tuple[str, ...]
    source: str
    notes: str = ""

    def card(self) -> dict:
        d = asdict(self)
        d["labels"] = list(self.labels)
        d["input_size"] = list(self.input_size)
        return d

    def short_hash(self) -> str:
        return self.sha256[:12]

    def run_info(self) -> dict:
        """The subset recorded in every run and in the custody log."""
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "sha256": self.sha256,
            "licence": self.licence,
            "licence_url": self.licence_url,
            "source_url": self.url,
            "input_size": list(self.input_size),
            "size_bytes": self.size_bytes,
        }


MODELS: dict[str, ModelSpec] = {
    "objects": ModelSpec(
        key="objects",
        name="YOLOX-Nano",
        version="0.1.1rc0 (COCO, 416x416)",
        filename="yolox_nano.onnx",
        url="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx",
        sha256="c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d",
        size_bytes=3659407,
        licence="Apache-2.0",
        licence_url="https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE",
        input_size=(416, 416),
        labels=tuple(COCO_LABELS),
        source="Megvii-BaseDetection/YOLOX (Ge et al., 2021, arXiv:2107.08430)",
        notes="Trained on COCO train2017. Output is undecoded grid predictions (decoded here).",
    ),
    "faces": ModelSpec(
        key="faces",
        name="YuNet",
        version="2023mar",
        filename="face_detection_yunet_2023mar.onnx",
        url=(
            "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
            "face_detection_yunet_2023mar.onnx"
        ),
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        size_bytes=232589,
        licence="MIT",
        licence_url=(
            "https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE"
        ),
        input_size=(640, 640),
        labels=("face",),
        source="opencv/opencv_zoo models/face_detection_yunet (YuNet, Wu et al.)",
        notes="Detection only. The landmark outputs are discarded; no embeddings, no recognition.",
    ),
}


def models_dir() -> Path:
    env = os.getenv("NIRIKSHAN_MODELS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "models"


def model_path(spec: ModelSpec) -> Path:
    return models_dir() / spec.filename


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verified_model_path(spec: ModelSpec) -> Path:
    """Path of the model file after checking its SHA-256; raises ModelMissing otherwise."""
    p = model_path(spec)
    if not p.is_file():
        raise ModelMissing(
            f"Model '{spec.name}' is not installed ({p}). Fetch it once, with network access, "
            f"using: {FETCH_COMMAND}"
        )
    got = sha256_file(p)
    if got != spec.sha256:
        raise ModelMissing(
            f"Model file {p} has SHA-256 {got}, expected {spec.sha256}. "
            f"Re-fetch it using: {FETCH_COMMAND}"
        )
    return p


def model_status() -> list[dict]:
    out = []
    for spec in MODELS.values():
        try:
            verified_model_path(spec)
            ok, err = True, ""
        except ModelMissing as e:
            ok, err = False, str(e)
        out.append({**spec.card(), "installed": ok, "path": str(model_path(spec)), "error": err})
    return out
