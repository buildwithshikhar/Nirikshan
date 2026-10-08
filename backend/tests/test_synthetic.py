import json

from sqlalchemy import select

from app import synthetic
from app.models import CustodyEntry
from app.validation.image import BANNER


def test_banner_constant_matches_the_harness_banner():
    assert synthetic.BANNER == BANNER and len(synthetic.BANNER) == 256


def test_detection_requires_the_full_banner(tmp_path):
    ok = tmp_path / "a.dd"
    ok.write_bytes(BANNER + b"\x00" * 100)
    assert synthetic.is_synthetic_image(ok)
    half = tmp_path / "b.dd"
    half.write_bytes(BANNER[:128] + b"X" * 200)
    assert not synthetic.is_synthetic_image(half)
    shifted = tmp_path / "c.dd"
    shifted.write_bytes(b"\x00" + BANNER)
    assert not synthetic.is_synthetic_image(shifted)
    short = tmp_path / "d.dd"
    short.write_bytes(b"NIRIKSHAN SYNTHETIC")
    assert not synthetic.is_synthetic_image(short)
    assert not synthetic.is_synthetic_image(tmp_path / "missing.dd")


def test_acquired_evidence_is_flagged_from_the_banner(client, tmp_path, session):
    case = client.post("/api/cases", json={"case_number": "SYN-1", "title": "s"}).json()
    synth, real = tmp_path / "synth.dd", tmp_path / "other.dd"
    synth.write_bytes(BANNER + bytes(range(256)) * 20)
    real.write_bytes(bytes(range(256)) * 20)
    out = {}
    for name, p in (("synth", synth), ("other", real)):
        r = client.post(
            f"/api/cases/{case['id']}/evidence",
            json={"source_path": str(p), "label": name, "write_blocker": "yes"},
        )
        assert r.status_code == 201, r.text
        out[name] = r.json()
    assert out["synth"]["synthetic"] is True and out["other"]["synthetic"] is False
    listed = {
        e["label"]: e["synthetic"] for e in client.get(f"/api/cases/{case['id']}/evidence").json()
    }
    assert listed == {"synth": True, "other": False}
    entry = session.scalars(
        select(CustodyEntry).where(
            CustodyEntry.action == "evidence_acquired",
            CustodyEntry.evidence_id == out["synth"]["id"],
        )
    ).one()
    assert json.loads(entry.details_json)["synthetic_banner"] is True
