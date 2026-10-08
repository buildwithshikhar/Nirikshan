#!/usr/bin/env python3
"""Generate docs/THIRD_PARTY_LICENSES.md from package metadata (re-run after dependency changes).

    backend/.venv/bin/python scripts/licenses.py [--out docs/THIRD_PARTY_LICENSES.md]

Python packages: read from the interpreter that runs this script (use the backend venv, with
requirements-dev.txt installed). Production = transitive closure of backend/requirements.txt.
npm packages: read from frontend/package-lock.json (no node_modules needed); production = not
flagged `dev`. Models, datasets, fonts and system tools are the static tables below, each with its
source; the ffmpeg row also runs the local `ffmpeg -version` if present.
Copyleft, non-commercial and unknown licences are flagged at the top of the output.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|MPL|EUPL|CDDL|EPL|OSL)\b|GNU (Lesser |Affero )?General", re.I)
NONCOMM = re.compile(r"non-?commercial|\bCC-BY-NC|research use only", re.I)


def classify(lic: str) -> str:
    if not lic or lic.strip().upper() in ("UNKNOWN", "NONE"):
        return "UNKNOWN"
    if NONCOMM.search(lic):
        return "NON-COMMERCIAL"
    if COPYLEFT.search(lic):
        return "COPYLEFT"
    return "permissive"


def norm_name(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def dist_license(d: metadata.Distribution) -> str:
    m = d.metadata
    expr = m.get("License-Expression")
    if expr:
        return expr
    lic = (m.get("License") or "").strip()
    if lic and len(lic) < 80 and "\n" not in lic:
        return lic
    cls = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if "License ::" in c]
    cls = [c for c in cls if c != "OSI Approved"]
    if cls:
        return "; ".join(cls)
    return lic.split("\n")[0][:80] if lic else ""


def py_packages() -> tuple[list[tuple], list[tuple]]:
    dists = {norm_name(d.metadata["Name"]): d for d in metadata.distributions()}
    roots = []
    extras: set[str] = set()
    for line in (ROOT / "backend" / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            roots.append(norm_name(re.split(r"[\[<>=!~ ;]", line)[0]))
            for ex in re.findall(r"\[([^\]]+)\]", line):
                extras.update(e.strip() for e in ex.split(","))
    prod: set[str] = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n in prod or n not in dists:
            continue
        prod.add(n)
        for req in dists[n].requires or []:
            if "extra ==" in req and not any(f"'{e}'" in req or f'"{e}"' in req for e in extras):
                continue
            stack.append(norm_name(re.split(r"[\[<>=!~ ;(]", req.strip())[0]))
    rows_p, rows_d = [], []
    for n, d in sorted(dists.items()):
        if n in ("pip", "setuptools", "wheel"):
            continue
        lic = dist_license(d)
        row = (d.metadata["Name"], d.version, lic or "UNKNOWN", classify(lic))
        (rows_p if n in prod else rows_d).append(row)
    return rows_p, rows_d


def npm_packages() -> tuple[list[tuple], list[tuple]]:
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text())["packages"]
    prod, dev = [], []
    for key, v in sorted(lock.items()):
        if not key:
            continue
        name = key.split("node_modules/")[-1]
        lic = v.get("license") or ""
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        opt = " (optional platform binary)" if v.get("optional") else ""
        row = (name + opt, v.get("version", "?"), lic or "UNKNOWN", classify(lic))
        (dev if v.get("dev") else prod).append(row)
    return prod, dev


def table(rows: list[tuple]) -> str:
    out = ["| Package | Version | Licence | Class |", "|---|---|---|---|"]
    for n, v, lic, c in rows:
        flag = f"**{c}**" if c != "permissive" else c
        out.append(f"| {n} | {v} | {lic} | {flag} |")
    return "\n".join(out)


def ffmpeg_local() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        return "not installed on the machine that generated this file"
    out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10).stdout
    lines = out.splitlines()
    cfg = next((x for x in lines if x.startswith("configuration:")), "")
    flags = [
        f
        for f in (
            "--enable-gpl",
            "--enable-nonfree",
            "--enable-version3",
            "--enable-libx264",
            "--enable-libx265",
        )
        if f in cfg
    ]
    return f"{lines[0] if lines else '?'}; licence-relevant flags present: {', '.join(flags) or 'none'}"


STATIC = """
## ML and OCR models

| Model | Where it lives | Licence | Verified from | Notes |
|---|---|---|---|---|
| YOLOX-Nano (COCO) | fetched by `scripts/fetch_models.py`, SHA-256 pinned in `backend/app/analytics/registry.py`; baked into the backend image | Apache-2.0 | `registry.py` (`licence`, `licence_url`: Megvii-BaseDetection/YOLOX LICENSE) | Trained on COCO train2017; COCO annotations are CC BY 4.0, images carry Flickr terms. We have not assessed whether dataset terms flow into the weights. |
| YuNet 2023mar | same | MIT | `registry.py` (opencv_zoo `models/face_detection_yunet/LICENSE`) | Detection only. |
| PP-OCRv4 det/rec + PP-OCR v2.0 cls (ONNX) | bundled inside the `rapidocr-onnxruntime` 1.4.4 wheel (`rapidocr_onnxruntime/models/`) | Apache-2.0 (RapidOCR package metadata `License: Apache-2.0`; RapidOCR and PaddleOCR LICENSE files fetched 2026-10-09 are Apache License 2.0) | package metadata; upstream LICENSE files | The wheel has no separate model-licence file. The RapidOCR README says it converted PaddleOCR models and refers to a `MODEL_LICENSES.md`, which returned HTTP 404 on the main branch when fetched on 2026-10-09. The Apache-2.0 reading for the converted weights rests on the repository/package licence and PaddleOCR's Apache-2.0; it is not confirmed by a model-specific licence file. Legal review recommended before redistribution. |

## Datasets (local evaluation only; not redistributed, not in git or images)

| Dataset | Used for | Licence status |
|---|---|---|
| Penn-Fudan Pedestrian | person-detection error rates (`docs/analytics/error_rates.json`) | Published for research; no licence text found in our copy; **no licence granted to us**; used locally only |
| BioID Face Database v1.2 | face-detection error rates | No licence text in the distribution (`description.txt`), per `error_rates.json`; **no licence granted**; used locally only |

Synthetic validation images are generated by our own code and contain no third-party footage.

## Fonts

| Font | Use | Licence | Status |
|---|---|---|---|
| Bitstream Vera (via ReportLab) | PDF report | Bitstream Vera licence (permissive, redistribution allowed, name restrictions on modified fonts) | Shipped inside reportlab 5.0.1 and embedded in generated PDFs; licence text taken from the package, not independently verified |
| Frontend fonts | UI | none bundled by us; system font stack assumed | verify with `frontend/src/index.css` when finalising |

## System tools

| Tool | Licence | Notes |
|---|---|---|
| ffmpeg / ffprobe | The build decides: LGPL-2.1+ for a default build, **GPL-2.0+ when built with `--enable-gpl`** (libx264, libx265, libxvid). | See the ffmpeg section below. |
| Python (CPython) 3.12 in the image | PSF licence | python:3.12-slim base |
| Debian base packages (libgl1, libglib2.0-0, libc, ...) | various incl. LGPL/GPL | standard Debian copyright files inside the image under `/usr/share/doc/*/copyright` |
| nginx (nginxinc/nginx-unprivileged) | BSD-2-Clause | frontend image |
| Node 22 (build stage only) | MIT and bundled licences | not in the final frontend image |

### ffmpeg: what we know and what it means

- Local machine used to generate this file: {ffmpeg_local}
- The backend image installs Debian's `ffmpeg` package. Captured in `docs/security/ffmpeg-debian-image.txt`: version 7.1.5-0+deb13u1, configured with `--enable-gpl`, `--enable-libx264`, `--enable-libx265`, `--enable-libxvid` (no `--enable-nonfree` in the captured line).
- **Implication, stated plainly:** that is a GPL-licensed ffmpeg. Distributing the image (for example handing it to NTRO or publishing it) means distributing GPL binaries, which carries the obligation to offer the corresponding source for those binaries (Debian provides it as a source package) and to keep the GPL licence texts. Nirikshan itself invokes ffmpeg as a **separate process** (`subprocess`, no linking), so we do not read the GPL as reaching the Nirikshan source licence, but that is a legal question; get it reviewed before external distribution.
- Nirikshan uses `ffmpeg -c copy` (no re-encode) for MP4 export and decodes for the decode test. It does not need libx264/libx265 encoders at runtime; the tests that generate H.264/H.265 test streams do. A distribution that avoids GPL would need an LGPL-only ffmpeg build without those encoders (decoders for H.264/H.265 are native LGPL code in libavcodec), which is not what the image ships. Patent licensing of H.264/H.265 is a separate matter this document does not assess.
"""


def build() -> str:
    pp, pd = py_packages()
    np_, nd = npm_packages()
    allrows = [("python/prod", r) for r in pp] + [("python/dev", r) for r in pd]
    allrows += [("npm/prod", r) for r in np_] + [("npm/dev", r) for r in nd]
    flagged = [(w, r) for w, r in allrows if r[3] != "permissive"]
    out = [
        "# Third-Party Licences",
        "",
        f"*Generated by `scripts/licenses.py` on {date.today().isoformat()} using Python "
        f"{sys.version.split()[0]}. Do not edit by hand; re-run after dependency changes. "
        "Licence strings come from package metadata and are not legal advice; where a package "
        "declares nothing it is listed UNKNOWN, not guessed.*",
        "",
        "## Flags (read first)",
        "",
        "- **ffmpeg in the image is a GPL build** (`--enable-gpl`, libx264, libx265): see the ffmpeg "
        "section.",
        "- **MPL-2.0 (weak copyleft)** appears in the npm dev tree (`lightningcss`, build-time CSS "
        "tooling and its platform binaries); it is not part of the production frontend image, which "
        "ships only built static files and nginx.",
        "- **psycopg / psycopg-binary are LGPL-3.0** (Postgres driver, imported unmodified as a "
        "separate library; it is in requirements.txt so it ships in the backend image). "
        "**certifi and tqdm are MPL-2.0** (file-level copyleft, unmodified).",
        "- **Datasets without a licence grant** (Penn-Fudan, BioID) are used for local evaluation "
        "only and are not redistributed.",
        "- **PP-OCR model licence** rests on package metadata; no model-specific licence file "
        "was found (details below).",
    ]
    if flagged:
        out += ["", "Package-level flags found by the classifier:", ""]
        out += [f"- {w}: {r[0]} {r[1]}: {r[2]} ({r[3]})" for w, r in flagged]
    out += [
        "",
        "## Python packages: production (closure of backend/requirements.txt)",
        "",
        table(pp),
        "",
        "## Python packages: development/test only",
        "",
        table(pd),
        "",
        "## npm packages: production (frontend/package-lock.json, not flagged dev)",
        "",
        table(np_),
        "",
        "## npm packages: development/build only",
        "",
        table(nd),
    ]
    out.append(STATIC.replace("{ffmpeg_local}", ffmpeg_local()))
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "THIRD_PARTY_LICENSES.md")
    a = ap.parse_args()
    a.out.write_text(build())
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
