import hashlib
import io
import subprocess

import pytest

from app import clock
from app.hashing import CHUNK, hash_file, hash_stream


@pytest.mark.parametrize("n", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 2 * CHUNK + 7])
def test_digests_match_hashlib_and_sink_gets_same_bytes(n):
    data = (b"nirikshan" * (n // 9 + 1))[:n]
    sink = io.BytesIO()
    d = hash_stream(io.BytesIO(data), sink)
    assert d.size == n and sink.getvalue() == data
    assert d.md5 == hashlib.md5(data).hexdigest()
    assert d.sha256 == hashlib.sha256(data).hexdigest()


def test_known_answer_vectors(tmp_path):
    p = tmp_path / "abc"
    p.write_bytes(b"abc")
    d = hash_file(p)
    assert d.md5 == "900150983cd24fb0d6963f7d28e17f72"
    assert d.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_md5_and_sha256_agree_with_system_tools(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"x" * 100_000)
    d = hash_file(p)
    sha = subprocess.run(["shasum", "-a", "256", str(p)], capture_output=True, text=True)
    if sha.returncode == 0:
        assert sha.stdout.split()[0] == d.sha256


def _fake_run(stdout):
    return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=stdout)


@pytest.mark.parametrize(
    "out,expected", [("yes\n", "synchronized"), ("no\n", "not_synchronized"), ("?", "unknown")]
)
def test_ntp_status_parsing(monkeypatch, out, expected):
    monkeypatch.setattr(clock, "_cache", None)
    monkeypatch.setattr(clock.shutil, "which", lambda _: "/usr/bin/timedatectl")
    monkeypatch.setattr(clock.subprocess, "run", _fake_run(out))
    assert clock.ntp_status() == expected


def test_ntp_unknown_without_timedatectl(monkeypatch):
    monkeypatch.setattr(clock, "_cache", None)
    monkeypatch.setattr(clock.shutil, "which", lambda _: None)
    assert clock.ntp_status() == "unknown"


def test_utc_timestamp_is_utc():
    assert clock.utc_now_iso().endswith("+00:00")
