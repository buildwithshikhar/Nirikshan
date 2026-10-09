"""Device intelligence on reference (SYNTHETIC, per-paper layout) images."""

import io
import json
import random

import pytest

from app.identify import engine
from app.models import CustodyEntry
from app.validation import layouts_hikvision as K
from app.validation import layouts_honeywell as H
from app.validation.streams import StreamPool
from app.vendors import default_registry
from tests import stream2  # noqa: F401
from tests import vendor_images as V
from tests.media import filler


@pytest.fixture(scope="module")
def pool():
    return StreamPool()


@pytest.fixture(scope="module")
def honeywell_img(pool):
    img, _clips, _ = H.build_image(H._chunks([pool.get("h264_base_320")], [True]))
    return bytes(img)


@pytest.fixture(scope="module")
def hik_img(pool):
    img, _clips, _ = K.build_image(random.Random(1), [K._blk(0, pool.get("h264_base_320"), 1)])
    return img


def ident(data: bytes) -> dict:
    return engine.identify(io.BytesIO(data), len(data))


def sig(res, vendor, name):
    p = next(p for p in res["parsers"] if p["vendor"] == vendor)
    return next(s for s in p["signatures"] if s["name"] == name)


def test_honeywell_model_and_device_id_from_documented_offsets(honeywell_img):
    r = ident(honeywell_img)
    assert r["manufacturer"]["value"] == "Honeywell"
    assert r["manufacturer"]["status"] == "identified"
    assert r["device"]["model"] == {
        "value": "HN350802xx",
        "status": "parsed",
        "source": r["device"]["model"]["source"],
        "offset": 0x4468,
        "note": r["device"]["model"]["note"],
    }
    assert "honeywell-fields.md 1.3" in r["device"]["model"]["source"]
    assert r["device"]["device_id"]["value"] == "B011003AWFNRZEFKV"
    fw = r["device"]["firmware"]
    assert fw["status"] == "unknown" and fw["value"] is None and "screenshot" in fw["note"]
    assert r["routing"]["engine"].startswith("Honeywell parser first")
    probe = sig(r, "Honeywell", "honeywell_machine_data")
    assert probe["matched"] and probe["offsets"] == [34 * 512]


def test_hikvision_has_no_model_or_firmware_only_a_version_like_string(hik_img):
    r = ident(hik_img)
    assert r["manufacturer"]["value"] == "Hikvision"
    assert r["device"]["model"]["status"] == "unknown"
    assert r["device"]["firmware"]["status"] == "unknown"
    v = r["device"]["filesystem_version_like_string"]
    assert v["value"] == "HIK.2011.03.08" and v["status"] == "unknown"
    assert v["offset"] == 0x210 + 0x20 and "not used as firmware" in v["note"]
    assert sig(r, "Hikvision", "hik_master_any")["matched"]


def test_non_matching_signatures_say_why(honeywell_img):
    r = ident(honeywell_img)
    s = sig(r, "Hikvision", "hik_btree")
    assert not s["matched"] and s["reason"] == "pattern not present in the image"
    p = sig(r, "Hikvision", "hik_master_0x200")
    assert not p["matched"] and "do not satisfy" in p["reason"] and p["bytes_seen_hex"]


def test_rejected_candidates_are_reported_with_offsets():
    data = V.dahua(frames=5, bad_trailer=True)
    r = ident(data)
    s = sig(r, "Dahua", "dahua_dhav_frame")
    assert not s["matched"] and s["candidates"] == 5 and s["rejected"] == 5
    assert "structural validation" in s["reason"]
    assert s["rejected_offsets_sample"][0] == data.find(b"DHAV")
    assert r["manufacturer"]["status"] == "unknown"
    assert r["routing"]["engine"] == "generic carving only"


def test_unknown_device_routes_to_generic_carving():
    r = ident(filler(1 << 18, 3))
    assert r["manufacturer"]["value"] is None and r["manufacturer"]["status"] == "unknown"
    assert "no documented signature" in r["manufacturer"]["note"]
    assert r["device"]["model"]["status"] == "unknown"
    assert r["routing"]["engine"] == "generic carving only"
    assert "CP Plus" in r["not_identifiable"]["vendors"]
    assert all(p["confidence"] == "none" for p in r["parsers"])


@pytest.mark.parametrize("name", ["hik", "honeywell", "dahua", "noise"])
def test_matches_agree_with_the_analysis_registry(name, hik_img, honeywell_img):
    data = {
        "hik": hik_img,
        "honeywell": honeywell_img,
        "dahua": V.dahua(frames=5),
        "noise": filler(1 << 16, 9),
    }[name]
    reg = default_registry().identify(io.BytesIO(data), len(data))
    got = ident(data)["matches"]
    assert [(m.vendor, m.confidence) for m in reg] == [(m["vendor"], m["confidence"]) for m in got]


def test_never_above_medium(hik_img, honeywell_img):
    for data in (hik_img, honeywell_img, V.dahua(frames=9)):
        assert {p["confidence"] for p in ident(data)["parsers"]} <= {"none", "low", "medium"}


def test_api_identification_is_stored_custody_logged_and_cached(
    client, session, tmp_path, honeywell_img
):
    p = tmp_path / "hw.img"
    p.write_bytes(honeywell_img)
    c = client.post("/api/cases", json={"case_number": "ID-1", "title": "ident"}).json()
    ev = client.post(
        f"/api/cases/{c['id']}/evidence",
        json={"source_path": str(p), "label": "hw", "write_blocker": "yes"},
    ).json()
    r1 = client.get(f"/api/evidence/{ev['id']}/identification").json()
    assert r1["cached"] is False and r1["manufacturer"]["value"] == "Honeywell"
    r2 = client.get(f"/api/evidence/{ev['id']}/identification").json()
    assert r2["cached"] is True and r2["stored_id"] == r1["stored_id"]
    r3 = client.get(f"/api/evidence/{ev['id']}/identification?refresh=true").json()
    assert r3["cached"] is False and r3["stored_id"] != r1["stored_id"]
    logged = session.query(CustodyEntry).filter_by(action="device_identified").all()
    assert len(logged) == 2
    assert json.loads(logged[0].details_json)["manufacturer"] == "Honeywell"
    assert client.get("/api/evidence/9999/identification").status_code == 404
