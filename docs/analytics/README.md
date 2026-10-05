# Analytics (P6): triage, not identification

Motion detection, object detection and face detection for exported clips. CPU only, offline.
Every result is a **lead for an examiner to review**. Each result, DB row, API response, UI row and
custody-log entry carries the label `triage, not identification`.

**Nothing in this document or in the code was validated on real DVR footage.** Error rates below
come from public benchmark images or from synthetic clips and are labelled as such. They will not
transfer to low-resolution, highly compressed DVR footage (see Limits).

## Scope and non-scope

- Detection only: a box, a class name and a confidence. There are no embeddings, no landmarks
  (the YuNet landmark outputs are discarded), no identity, no recognition and no matching code.
  A test asserts that outputs, API payloads and DB columns contain no such fields.
- Absence of a detection is not evidence of absence.
- Frame indices are positions in the decoded output of the exported MP4. Times are **nominal**
  (frame index / stream frame rate); they are not recording times.

## Models

Weights are not committed. `python scripts/fetch_models.py` downloads them into `backend/models/`
(gitignored) and verifies SHA-256. The application never uses the network; a missing or
checksum-mismatching model fails with an actionable error (HTTP 503 naming the fetch command).
Only permissive licences (Apache-2.0, MIT) are used. Ultralytics YOLOv5/8/11 (AGPL-3.0) are
deliberately not used.

| | Objects | Faces |
|---|---|---|
| Name / version | YOLOX-Nano, release 0.1.1rc0 (COCO) | YuNet, 2023mar |
| Source | https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx | https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx |
| Licence | Apache-2.0 (`LICENSE` in https://github.com/Megvii-BaseDetection/YOLOX) | MIT (`models/face_detection_yunet/LICENSE` in https://github.com/opencv/opencv_zoo, Copyright (c) 2020 Shiqi Yu) |
| File size | 3,659,407 bytes | 232,589 bytes |
| SHA-256 | `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| Input | 416x416, BGR, 0-255 float, letterbox pad 114 | 640x640, BGR, 0-255 float, letterbox pad 0 |
| Labels | 80 COCO classes (list in `backend/app/analytics/registry.py`) | `face` |

Runtime packages (CPU): numpy 2.2.6, onnxruntime 1.23.2 (MIT), Pillow 12.3.0; ffmpeg/ffprobe for
decoding. No OpenCV, torch or tensorflow.

## Method

- **Motion** (`app/analytics/motion.py`): ffmpeg decodes every `stride`-th frame to gray at
  `width` pixels; box blur (`blur`); absolute difference to a background model (`bg_alpha` 1.0 =
  previous sample, otherwise running average); pixels above `threshold` count as changed; a sample
  is "moving" when changed pixels >= `min_area`; consecutive moving samples (gaps up to
  `merge_gap`) form an interval with peak and mean score (fraction of pixels changed). Defaults:
  stride 2, width 160, blur 1, threshold 25, min_area 24, bg_alpha 1.0, merge_gap 2.
  Motion means pixels changed (lighting, noise and compression artefacts count too).
- **Objects / faces** (`app/analytics/detect.py`): ffmpeg decodes every `stride`-th frame (default
  25) to RGB; letterbox resize; one ONNX inference; box decoding and class-aware (objects) or
  single-class (faces) NMS in numpy. Defaults: confidence 0.30 objects / 0.50 faces, NMS IoU 0.45.
- Each run is stored (`analytics_runs`, `detections`, `motion_intervals`) with model name, version,
  licence and SHA-256, parameters, tool versions (Nirikshan, ffmpeg, onnxruntime, numpy), the error
  rates at that time, and the clip's `bitstream_sha256` and `mp4_sha256`. The MP4 is re-hashed
  before analysis; a mismatch refuses the run (HTTP 409). A signed custody entry `analytics_run`
  records the same hashes, model hashes and parameters.

## Determinism

ONNX Runtime uses `CPUExecutionProvider` with one intra-op and one inter-op thread and sequential
execution; pre/post-processing is fixed; NMS breaks ties by score then index. Tests repeat runs
and require identical output (same input, same parameters, same machine and library versions).
Bit-identical results across different CPU architectures or onnxruntime versions are not claimed.

## Runtime budget (measured on the development machine, Apple Silicon Mac, CPU)

| Step | ms per analysed 352x288 frame |
|---|---|
| YOLOX-Nano objects | ~33 |
| YuNet faces | ~30 |
| Motion (stride 1, 160 px) | ~6 |

Tests assert generous bounds (1500 ms for models, 500 ms for motion) and print the measured value
on failure. Default stride 25 means about 1 analysed frame per second at 25 fps.

## Error rates

Source of truth: `docs/analytics/error_rates.json` (copied to `backend/app/analytics/error_rates.json`
and attached to every run). Regenerate with `python ../scripts/eval_analytics.py` from `backend/`
(about 40 minutes on a loaded laptop). Matching: IoU >= 0.5, greedy by confidence. Intervals: Wilson
95% on counts (assumes independent detections, which is optimistic) and an image-level bootstrap
(1000 resamples, seed 0, preferable). "352x288_crf30" means each image was downscaled to fit 352x288
and encoded with x264 CRF 30, then decoded through the same pipeline.

Datasets (kept outside git in `backend/data/public/`, gitignored):

- **Penn-Fudan Pedestrian Database** (Wang et al., "Object Detection Combining Recognition and
  Segmentation", ACCV 2007), 170 images, 423 annotated pedestrians, 53 MB,
  https://www.cis.upenn.edu/~jshi/ped_html/ . No licence grant is stated; its readme.txt says
  copyright is retained by the authors and the works may not be reposted. It is used locally for
  evaluation only and not redistributed. Class evaluated: `person` only. Very small or heavily
  occluded pedestrians are not annotated, so some "false positives" are real people: precision
  here is understated.
- **BioID Face Database v1.2** (Jesorsky, Kirchberg, Frischholz, 2001), 1521 grey 384x286
  images, 125 MB, https://www.bioid.com/facedb/ . No licence text is included in the distribution
  (`description.txt` says it is published for face-detection research). Used locally, not
  redistributed. It has only eye positions, so a detection counts as correct when its box contains
  both eyes and is 1.2-4.0 times the inter-eye distance wide (not IoU 0.5). It is frontal, single
  face, well lit and easy: near-perfect numbers say little about CCTV.
- **Motion**: 30 synthetic clips per condition (noise texture, 40x40 block moving at 5 px/frame,
  1-3 segments), interval match when frame-IoU >= 0.5. Label: `synthetic, not representative of DVR
  footage`.

Classes other than `person` (for example `car`) and faces other than frontal were **not measured**;
the UI says so for each such class.

### Objects (YOLOX-Nano, class `person`, Penn-Fudan, IoU 0.5; public benchmark, not DVR footage)

| Condition | Conf. thr. | n | TP | FP | FN | Precision (Wilson 95%) | Recall (Wilson 95%) | Bootstrap 95% P / R |
|---|---|---|---|---|---|---|---|---|
| original | 0.3 | 170 | 415 | 189 | 8 | 68.7% (64.9%-72.3%) | 98.1% (96.3%-99.0%) | 64.0%-73.2% / 96.6%-99.3% |
| original | 0.5 | 170 | 413 | 116 | 10 | 78.1% (74.4%-81.4%) | 97.6% (95.7%-98.7%) | 73.1%-82.5% / 96.1%-99.0% |
| original | 0.7 | 170 | 398 | 54 | 25 | 88.0% (84.7%-90.7%) | 94.1% (91.4%-96.0%) | 84.4%-91.2% / 91.4%-96.4% |
| 352x288_crf30 | 0.3 | 170 | 408 | 147 | 15 | 73.5% (69.7%-77.0%) | 96.5% (94.2%-97.8%) | 69.2%-77.9% / 94.3%-98.3% |
| 352x288_crf30 | 0.5 | 170 | 396 | 80 | 27 | 83.2% (79.6%-86.3%) | 93.6% (90.9%-95.6%) | 79.1%-86.7% / 91.1%-96.2% |
| 352x288_crf30 | 0.7 | 170 | 358 | 22 | 65 | 94.2% (91.4%-96.2%) | 84.6% (80.9%-87.8%) | 91.4%-96.6% / 80.5%-88.5% |

### Faces (YuNet, BioID, eye-containment rule; public benchmark, not DVR footage)

| Condition | Conf. thr. | n | TP | FP | FN | Precision (Wilson 95%) | Recall (Wilson 95%) | Bootstrap 95% P / R |
|---|---|---|---|---|---|---|---|---|
| original | 0.5 | 1521 | 1521 | 2 | 0 | 99.9% (99.5%-100.0%) | 100.0% (99.8%-100.0%) | 99.7%-100.0% / 100.0%-100.0% |
| original | 0.7 | 1521 | 1521 | 2 | 0 | 99.9% (99.5%-100.0%) | 100.0% (99.8%-100.0%) | 99.7%-100.0% / 100.0%-100.0% |
| original | 0.9 | 1521 | 1519 | 1 | 2 | 99.9% (99.6%-100.0%) | 99.9% (99.5%-100.0%) | 99.8%-100.0% / 99.7%-100.0% |
| 352x288_crf30 | 0.5 | 1521 | 1521 | 8 | 0 | 99.5% (99.0%-99.7%) | 100.0% (99.8%-100.0%) | 99.1%-99.8% / 100.0%-100.0% |
| 352x288_crf30 | 0.7 | 1521 | 1520 | 2 | 1 | 99.9% (99.5%-100.0%) | 99.9% (99.6%-100.0%) | 99.7%-100.0% / 99.8%-100.0% |
| 352x288_crf30 | 0.9 | 1521 | 1493 | 0 | 28 | 100.0% (99.7%-100.0%) | 98.2% (97.4%-98.7%) | 100.0%-100.0% / 97.4%-98.8% |

### Motion (synthetic clips, interval IoU >= 0.5; synthetic, not representative of DVR footage)

| Condition | n clips | TP | FP | FN | Precision (Wilson 95%) | Recall (Wilson 95%) |
|---|---|---|---|---|---|---|
| 320x240_crf23 | 30 | 50 | 0 | 0 | 100.0% (92.9%-100.0%) | 100.0% (92.9%-100.0%) |
| 352x288_crf33 | 30 | 52 | 0 | 0 | 100.0% (93.1%-100.0%) | 100.0% (93.1%-100.0%) |

Reading the numbers: at the default object threshold (0.30) roughly one in three person boxes on
Penn-Fudan is a false positive (partly unannotated people), at 0.70 precision rises and recall
falls, and compression to 352x288 CRF 30 costs recall at high thresholds (84.6% at 0.7 vs 94.1%).
Face detection on BioID is near-perfect for frontal faces; the 352x288 CRF 30 variant loses recall
mostly at confidence 0.9. The synthetic motion result (perfect) only shows the code works on clean
synthetic blocks.

## Limits

- DVR footage is typically low resolution (CIF/D1), highly compressed, interlaced or noisy, with
  small distant subjects, infrared night scenes and fisheye or wide angles. None of the data above
  has those properties; public-data error rates will not transfer. The 352x288 CRF 30 rows are a
  rough stress test, not a model of any DVR.
- Motion detection by differencing reacts to illumination changes, auto-exposure, IR switching,
  compression artefacts and encoder keyframe pulses. Synthetic motion numbers do not cover these.
- Sampling at stride > 1 can miss short events (a person crossing between sampled frames).
- Exported clips may contain decode errors or concealed frames; detections on such frames are less
  reliable and the clip's decode status should be read first.
- Clips whose bitstream was carved heuristically (reassembled fragments, unknown vendor) inherit
  those caveats; analytics do not change a clip's tier.
- Model licences cover the weights as published; the training data licences (COCO, WIDER FACE) were
  not audited here.

**Triage statement.** These outputs prioritise material for human review. They do not establish
that a person, object or event is present or absent, and they must not be reported as
identifications. No analytics method here has been validated on real DVR footage.
