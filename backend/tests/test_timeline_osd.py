import random
import subprocess
from datetime import datetime, timedelta

import pytest

from app.timeline import osd as O
from tests.media import ffmpeg_path


def _need_ocr():
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError as exc:  # fail, never skip, with an actionable message
        pytest.fail(
            f"OSD tests need the OCR stack ({exc}): pip install rapidocr-onnxruntime==1.4.4 "
            "(brings numpy, Pillow, onnxruntime)"
        )


@pytest.fixture(scope="module", autouse=True)
def _stack():
    _need_ocr()
    O.rapid_engine()  # load models once


def fmt_text(dt: datetime, style: str) -> str:
    if style == "ymd":
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if style == "dmy":
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    if style == "mdy":
        return dt.strftime("%m/%d/%Y %H:%M:%S")
    if style == "ymd12":
        return dt.strftime("%Y-%m-%d %I:%M:%S %p")
    raise AssertionError(style)


def render_frame(text, rng, size=(640, 360), font_px=22, contrast=1.0, blur=0.0):
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    w, h = size
    base = Image.new("RGB", size, (30, 60, 40))
    d = ImageDraw.Draw(base)
    for _ in range(25):  # scene clutter below the overlay strip
        x0, y0 = rng.randrange(0, w), rng.randrange(int(h * 0.2), h)
        d.rectangle(
            [x0, y0, x0 + rng.randrange(10, 120), y0 + rng.randrange(10, 80)],
            fill=tuple(rng.randrange(20, 200) for _ in range(3)),
        )
    font = ImageFont.load_default(size=font_px)
    bg, fg = 25, int(25 + 215 * contrast)
    d.rectangle([0, 0, int(w * 0.6), int(h * 0.12)], fill=(bg, bg, bg))
    d.text((10, int(h * 0.12 / 2 - font_px / 2)), text, fill=(fg, fg, fg), font=font)
    if blur:
        base = base.filter(ImageFilter.GaussianBlur(blur))
    return base


def test_parse_formats_and_ambiguity():
    p = O.parse_overlay_text("CAM 01 2025-10-2602:30:15")
    assert p.status == "ok" and p.wall == datetime(2025, 10, 26, 2, 30, 15)
    p = O.parse_overlay_text("26-10-2025 14:05:59")
    assert p.status == "ok" and p.wall == datetime(2025, 10, 26, 14, 5, 59) and "DD-MM" in p.fmt
    p = O.parse_overlay_text("10/26/2025 14:05:59")
    assert p.status == "ok" and p.wall == datetime(2025, 10, 26, 14, 5, 59) and "MM/DD" in p.fmt
    p = O.parse_overlay_text("03/09/2025 02:30:00")
    assert p.status == "ambiguous" and p.wall is None
    assert p.candidates == [datetime(2025, 9, 3, 2, 30), datetime(2025, 3, 9, 2, 30)]
    assert O.parse_overlay_text("05/05/2025 01:02:03").status == "ok"  # same either way
    p = O.parse_overlay_text("2025-03-09 02:30:00 PM")
    assert p.wall == datetime(2025, 3, 9, 14, 30)
    assert O.parse_overlay_text("2025-03-09 12:30:00 AM").wall == datetime(2025, 3, 9, 0, 30)
    assert O.parse_overlay_text("2025-03-09 12:30:00 PM").wall == datetime(2025, 3, 9, 12, 30)
    assert O.parse_overlay_text("2025-03-09 13:30:00 PM").status == "unparsed"
    assert O.parse_overlay_text("2025-13-09 10:00:00").status == "unparsed"
    assert O.parse_overlay_text("2023-02-29 10:00:00").status == "unparsed"
    assert O.parse_overlay_text("hello").status == "unparsed"


def test_summary_statistics_and_verdicts():
    def rd(ds):
        return [O.OsdReading(float(i), "ok", delta_s=d) for i, d in enumerate(ds)]

    s = O.summarize(rd([0, -1, 0, -1, 0, -1]), 2.0)
    assert s["status"] == "pass" and s["median_delta_s"] == -0.5 and s["mad_s"] == 0.5
    s = O.summarize(rd([30, 31, 30, 29, 30]), 2.0)
    assert s["status"] == "fail" and s["median_delta_s"] == 30
    s = O.summarize(rd([0, 0, 0, 0, 0, 0, 55]), 2.0)
    assert s["status"] == "inconclusive" and s["outliers"] == [{"t_s": 6.0, "delta_s": 55}]
    s = O.summarize(rd([0, 1]), 2.0)
    assert s["status"] == "unreadable" and "need 3" in s["reason"]
    assert O.summarize([O.OsdReading(0, "unreadable")], 2.0)["status"] == "unreadable"


def test_ocr_accuracy_on_rendered_overlays_is_measured_and_reported():
    """>= 100 rendered synthetic overlays with known text. The measured numbers are printed and
    documented in docs/timeline.md; thresholds below are floors, not targets tuned to pass."""
    rng = random.Random(20251026)
    styles = ["ymd", "dmy", "mdy", "ymd12"]
    n = exact = unreadable = wrong = ambiguous = 0
    unreadable_by_style: dict[str, int] = {}
    wrong_cases = []
    for i in range(100):
        style = styles[i % 4]
        dt = datetime(2024, 1, 1) + timedelta(seconds=rng.randrange(0, 700 * 86400))
        if style in ("dmy", "mdy") and dt.day <= 12:  # keep day>12 so the truth is unambiguous
            dt = dt.replace(day=rng.randrange(13, 28))
        img = render_frame(fmt_text(dt, style), rng, font_px=rng.choice([18, 22, 28]))
        r = O.read_overlay(O.crop_roi(img, O.DEFAULT_ROI), 0.0)
        n += 1
        if r.status == "ok" and r.wall == dt:
            exact += 1
        elif r.status in ("unreadable", "unparsed"):
            unreadable += 1
            unreadable_by_style[style] = unreadable_by_style.get(style, 0) + 1
        elif r.status == "ambiguous":
            ambiguous += 1
        else:
            wrong += 1
            wrong_cases.append((fmt_text(dt, style), r.text))
    print(f"\nOSD OCR synthetic: n={n} exact={exact} unreadable={unreadable} "
          f"ambiguous={ambiguous} wrong={wrong} unreadable_by_style={unreadable_by_style} "
          f"{wrong_cases[:5]}")  # fmt: skip
    assert n >= 100
    assert exact / n >= 0.80, f"exact-match accuracy {exact}/{n}"
    assert wrong / n <= 0.05, f"confidently wrong {wrong}/{n}: {wrong_cases[:5]}"


def test_degraded_overlays_are_unreadable_not_guessed():
    rng = random.Random(5)
    dt = datetime(2025, 6, 1, 10, 0, 0)
    bad = []
    for kw in (dict(contrast=0.02), dict(contrast=0.03, blur=2.0)):
        for _ in range(5):
            img = render_frame(fmt_text(dt, "ymd"), rng, **kw)
            bad.append(O.read_overlay(O.crop_roi(img, O.DEFAULT_ROI), 0.0))
    heavy = []
    for _ in range(5):  # heavy blur at normal contrast
        img = render_frame(fmt_text(dt, "ymd"), rng, blur=6.0)
        heavy.append(O.read_overlay(O.crop_roi(img, O.DEFAULT_ROI), 0.0))
    assert all(r.status in ("unreadable", "unparsed") for r in bad), [r.status for r in bad]
    assert all(r.wall is None and r.delta_s is None for r in bad + heavy)
    # heavy blur may or may not OCR; it must never produce a confidently WRONG valid time
    assert all(r.status != "ok" or r.wall == dt for r in heavy), [(r.status, r.text) for r in heavy]


def test_ocr_unavailable_message_is_actionable(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("rapidocr_onnxruntime"):
            raise ImportError("blocked")
        return real(name, *a, **k)

    monkeypatch.setattr(O, "_ENGINE", None)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(O.OcrUnavailable, match="pip install rapidocr-onnxruntime"):
        O.rapid_engine()


def test_library_info_records_version_and_licence():
    info = O.ocr_library_info()
    assert info["library"] == "rapidocr-onnxruntime" and info["licence"] == "Apache-2.0"
    assert info["version"] != "not installed" and "MIT" in info["runtime"]


def make_overlay_clip(path, start: datetime, seconds=6, fps=10, size=(640, 360)):
    """Encode a synthetic MP4 whose overlay shows start + floor(t) (1 Hz clock)."""
    rng = random.Random(1)
    proc = subprocess.Popen(
        [ffmpeg_path(), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-crf", "18", str(path)],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    cache = {}
    for f in range(seconds * fps):
        sec = f // fps
        if sec not in cache:
            cache[sec] = render_frame(
                fmt_text(start + timedelta(seconds=sec), "ymd"), rng
            ).tobytes()
        proc.stdin.write(cache[sec])
    proc.stdin.close()
    assert proc.wait() == 0


def test_check_clip_end_to_end_pass_and_fail(tmp_path):
    start = datetime(2025, 6, 1, 10, 0, 0)
    mp4 = tmp_path / "c.mp4"
    make_overlay_clip(mp4, start)
    ok = O.check_clip(str(mp4), start, n_samples=6, duration_s=6.0)
    assert ok["summary"]["status"] == "pass", ok["summary"]
    assert ok["summary"]["readable"] >= 5 and ok["ocr"]["licence"] == "Apache-2.0"
    assert all(-1.5 <= r["delta_s"] <= 0.5 for r in ok["readings"] if r["delta_s"] is not None)
    # metadata says the clip starts 30 s earlier than the overlay: delta ~ +30 s -> fail
    bad = O.check_clip(str(mp4), start - timedelta(seconds=30), n_samples=6, duration_s=6.0)
    assert bad["summary"]["status"] == "fail" and 28 <= bad["summary"]["median_delta_s"] <= 31
    none = O.check_clip(str(mp4), None, n_samples=3, duration_s=6.0)
    assert none["summary"]["status"] == "no_reference" and not none["comparison_available"]
    with pytest.raises(ValueError):
        O.check_clip(str(mp4), start, roi=(0.5, 0.5, 0.9, 0.9), n_samples=0)
    with pytest.raises(ValueError):
        O.crop_roi(render_frame("x", random.Random(0)), (0.9, 0.0, 0.0, 0.5))
