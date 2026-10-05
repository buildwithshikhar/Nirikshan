import io
import json
import subprocess
from collections import Counter

import pytest

from app.carving import nal as N
from app.carving.export import FfmpegMissing, export_clip, ffmpeg_version, tool
from tests.media import carve, filler, nal_units

CODECS = ["h264_baseline", "h264_main_b", "h264_high", "h265_main"]


def _export(data, tmp_path, codec, name="c", extents=None):
    ex = extents or [[0, len(data)]]
    return export_clip(io.BytesIO(data), ex, codec, tmp_path, name)


def _vcl(data, codec):
    out = Counter()
    for _, nal in nal_units(data):
        t = nal[0] & 0x1F if codec == "h264" else (nal[0] >> 1) & 0x3F
        if (codec == "h264" and t in (1, 5)) or (codec == "h265" and t < 32):
            out[bytes(nal).rstrip(b"\x00")] += 1
    return out


def _extract(mp4, codec, tmp_path):
    bsf, fmt = ("h264_mp4toannexb", "h264") if codec == "h264" else ("hevc_mp4toannexb", "hevc")
    out = tmp_path / f"back.{fmt}"
    subprocess.run(
        [
            tool("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            mp4,
            "-c",
            "copy",
            "-bsf:v",
            bsf,
            "-f",
            fmt,
            str(out),
        ],
        check=True,
    )
    return out.read_bytes()


def test_ffmpeg_tools_present():
    assert "ffmpeg version" in ffmpeg_version()
    assert tool("ffprobe")


def test_missing_ffmpeg_is_a_clear_error(monkeypatch):
    from app.carving import export

    monkeypatch.setattr(export.shutil, "which", lambda _: None)
    monkeypatch.setattr(export, "FALLBACK_DIRS", ())
    with pytest.raises(FfmpegMissing, match="brew install ffmpeg"):
        export.tool("ffmpeg")


@pytest.mark.parametrize("name", CODECS)
def test_clean_clip_exports_to_playable_mp4_via_ffprobe(streams, tmp_path, name):
    data = streams[name]
    codec = name.split("_")[0]
    r = _export(data, tmp_path, codec)
    assert r.decode_status == "ok" and r.decode_errors == [] and r.error == ""
    assert r.codec_name == ("h264" if codec == "h264" else "hevc")
    assert (r.width, r.height) == ((352, 288) if name == "h264_high" else (320, 240))
    assert r.duration_s == pytest.approx(2.0, abs=0.15) and r.fps == "25/1" and r.packets == 50
    probe = json.loads(
        subprocess.run(
            [
                tool("ffprobe"),
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames",
                "-of",
                "json",
                r.mp4_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert int(probe["streams"][0]["nb_read_frames"]) == 50
    import hashlib

    assert r.mp4_sha256 == hashlib.sha256(open(r.mp4_path, "rb").read()).hexdigest()
    assert r.bitstream_sha256 == hashlib.sha256(data).hexdigest() and r.bitstream_bytes == len(data)
    assert not list(tmp_path.glob("c.h26*")), "raw intermediate must be removed"


@pytest.mark.parametrize("name", CODECS)
def test_export_is_stream_copy_not_a_re_encode(streams, tmp_path, name):
    """Every slice NAL in the MP4 is byte-identical to the carved input."""
    data = streams[name]
    codec = name.split("_")[0]
    r = _export(data, tmp_path, codec)
    assert _vcl(_extract(r.mp4_path, codec, tmp_path), codec) == _vcl(data, codec)


def test_exported_clip_from_noise_matches_original_bytes(streams, tmp_path):
    data = streams["h264_baseline"]
    img = filler(50_000, 1) + b"\x00" * 4096 + data + b"\x00" * 4096 + filler(9000, 2)
    clips, _, _ = carve(img)
    c = clips[0]
    r = export_clip(io.BytesIO(img), c.extents, c.codec, tmp_path, "noise")
    import hashlib

    assert r.bitstream_sha256 == hashlib.sha256(data).hexdigest() and r.decode_status == "ok"


def test_damaged_clip_is_listed_with_decode_errors_not_hidden(streams, tmp_path):
    data = bytearray(streams["h264_baseline"])
    data[5000:5600] = filler(600, 5)
    clips, _, _ = carve(bytes(data))
    r = export_clip(io.BytesIO(bytes(data)), clips[0].extents, "h264", tmp_path, "bad")
    assert r.decode_status == "decode_errors" and r.decode_errors
    assert r.mp4_path  # still playable up to the damage; flagged for the examiner


def test_unmuxable_input_reports_export_failed(tmp_path):
    junk = b"\x00\x00\x00\x01\x67" + filler(40, 3)
    r = _export(junk, tmp_path, "h264")
    assert r.decode_status in ("export_failed", "decode_errors")
    assert r.decode_status == "export_failed" and r.error and r.mp4_path == ""
    assert not (tmp_path / "c.mp4").exists()


def test_reassembled_extents_export_joined(streams, tmp_path):
    data = streams["h264_baseline"]
    p = [s for s, n in nal_units(data) if n[0] & 0x1F == 1][5]
    img = data[:p] + b"\x00" * 50_000 + data[p:]
    clips, _, _ = carve(img, join_gap=100_000)
    r = export_clip(io.BytesIO(img), clips[0].extents, "h264", tmp_path, "joined")
    assert r.decode_status == "ok" and r.bitstream_bytes == len(data)


def test_scan_events_unchanged_by_export_module_import():
    assert N.HEAD == 16
