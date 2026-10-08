"""P7 report tests. All data is SYNTHETIC; nothing here is validated on a real device."""

import hashlib
import json
import socket
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import custody
from app.analytics import TRIAGE_LABEL
from app.models import CustodyEntry
from app.report import pdf as report_pdf
from app.report.build import build_report_data, reassembler_false_accept
from app.report.models import Report
from app.triggers import drop_triggers
from tests.report_support import GEN, NTP, flat, make_case, pages, pdf_text


def has(text, phrase):
    return flat(phrase) in flat(text)


@pytest.fixture
def built(client, session, image):
    return make_case(client, session, image)


def render_text(session, case_id, gen=GEN):
    data = build_report_data(session, case_id, gen, NTP)
    pdf, n, _ = report_pdf.render(data)
    return data, pdf, n, pdf_text(pdf)


def test_report_contains_required_sections_and_values(session, built):
    data, pdf, n, t = render_text(session, built["case"])
    f = flat(t)
    for name in report_pdf.SECTION_NAMES:
        assert name in t
    ev = built["ev"]
    assert ev["md5"] in f and ev["sha256"] in f
    assert has(t, "examiner attestation, not verified by the tool")
    assert has(t, "CUSTODY CHAIN: VALID")
    assert data["custody"]["verification"]["head_hash"] in f
    assert data["custody"]["verification"]["key_id"] in t
    assert has(t, "RECORD THIS head_hash OUTSIDE THIS SYSTEM")
    assert has(t, "BEFORE the report_generated")
    assert has(t, "R-1") and has(t, "report test") and has(t, "Insp. Test")
    assert has(t, "2026-01-02T03:04:05") and has(t, "NTP status at generation")
    assert has(t, "unknown")
    assert has(t, "ONLY content")
    # runs: vendor tier/confidence, options, conflicts, crosscheck, clips
    assert has(t, "Tier B") and has(t, "medium") and has(t, "block_size_conflict_in_source")
    assert has(t, "block_size_mode") and has(t, "join_gap") and has(t, "generic_scope")
    assert has(t, "DISAGREEMENTS 1")
    assert has(t, "not recording time")
    assert flat("00" * 32) in f and flat("64" * 32) in f  # bitstream / MP4 hashes of clip 1
    assert has(t, "block_size_mode")


def test_failed_decodes_and_orphans_listed(session, built):
    _, _, _, t = render_text(session, built["case"])
    assert has(t, "FAILED DECODES, EXPORT FAILURES AND ORPHANS")
    assert has(t, "decode_errors") and has(t, "error while decoding MB 3 4")
    assert has(t, "no IRAP picture before the range ended")


def test_unplaceable_clips_never_in_placed_timeline(client, session, image):
    ids = make_case(client, session, image, tz=None, failed=False)
    _, _, _, t = render_text(session, ids["case"])
    placed = t.split("PLACED TIMELINE")[1].split("UNPLACEABLE CLIPS")[0]
    unplace = t.split("UNPLACEABLE CLIPS")[1].split("5. ANALYTICS")[0]
    for cid in ids["clips"]:
        assert not has(placed, f"clip {cid}")
        assert has(unplace, f"clip {cid}")
    assert has(unplace, "timezone") and has(unplace, "never defaulted")
    assert has(placed, "No clip could be placed")


def test_placed_with_assumption_shows_notes_and_both_intervals(session, built):
    _, _, _, t = render_text(session, built["case"])
    assert has(t, "read from DVR menu") and has(t, "Asia/Kolkata") and has(t, "device_local")
    placed = t.split("PLACED TIMELINE")[1].split("UNPLACEABLE CLIPS")[0]
    for cid in built["clips"]:
        assert has(placed, f"clip {cid}")
    assert has(placed, "none (no drift model)")
    assert has(placed, "unix seconds")
    unplace = t.split("UNPLACEABLE CLIPS")[1].split("5. ANALYTICS")[0]
    assert has(unplace, f"clip {built['failed_clip']}") and has(unplace, "no metadata timestamp")
    assert not any(has(unplace, f"clip {c}") for c in built["clips"])


def test_analytics_label_model_hashes_and_error_rates(session, built):
    _, _, _, t = render_text(session, built["case"])
    f = flat(t)
    assert has(t, f"Result label: {TRIAGE_LABEL}")
    m = built["model"]
    assert m["sha256"] in f and m["name"] in t and m["licence"] in t
    assert has(t, "Measured error rates and their data source")
    assert has(t, "public benchmark") or "synthetic" in t.lower()
    assert has(t, "NOT an identification")


def test_limitations_page(session, built):
    _, _, _, t = render_text(session, built["case"])
    lim = t.split("6. LIMITATIONS")[1].split("7. COLOPHON")[0].replace("\n", " ")
    assert has(lim, "SYNTHETIC") and has(lim, "circular") and has(lim, "no vendor is above Tier B")
    assert has(lim, "no validation on real devices")
    assert has(lim, "does not prove the bytes are the original")
    assert has(lim, "falsely accepted 35 of 297") and has(lim, "11.8%")
    assert has(lim, "asserts nothing legal")


def test_reassembler_rate_read_from_file_and_missing_file_is_unknown(tmp_path):
    ok = reassembler_false_accept()
    assert ok["available"] and (ok["k"], ok["n"]) == (35, 297)
    bad = reassembler_false_accept(tmp_path / "nope.json")
    assert not bad["available"] and "nope.json" in bad["reason"]


def test_colophon_library_font_and_latin_only(session, built):
    _, _, _, t = render_text(session, built["case"])
    c = t.split("7. COLOPHON")[1].replace("\n", " ")
    assert has(c, "ReportLab") and has(c, "BSD-3-Clause") and has(c, "Bitstream Vera")
    assert has(c, "Latin only") and has(c, "no network access")


def test_unrenderable_characters_are_flagged_not_dropped(client, session, image):
    ids = make_case(client, session, image)
    client.put(
        f"/api/evidence/{ids['evidence']}/time-assumption",
        json={"timezone": "Asia/Kolkata", "epoch_basis": "device_local", "notes": "menu 中"},
    )
    data, pdf, _, t = render_text(session, ids["case"])
    assert has(t, "[U+4E2D]")
    _, _, replaced = report_pdf.render(data)
    assert replaced >= 1


def test_determinism_and_only_generated_at_differs(session, built):
    d1, p1, _, t1 = render_text(session, built["case"])
    _, p2, _, _ = render_text(session, built["case"])
    assert p1 == p2 and hashlib.sha256(p1).digest() == hashlib.sha256(p2).digest()
    gen2 = "2027-05-06T07:08:09.000000+00:00"
    d3, p3, _, t3 = render_text(session, built["case"], gen2)
    assert p3 != p1 and d1["content_hash"] == d3["content_hash"]
    a, b = t1.splitlines(), t3.splitlines()
    diff = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
    assert len(a) == len(b) and diff
    assert all("2026-01-02T03:04:05" in x and "2027-05-06T07:08:09" in y for x, y in diff)


def test_page_count_sanity(client, session, image):
    small = make_case(client, session, image, n_clips=1, failed=False)
    _, _, n_small, _ = render_text(session, small["case"])
    assert 5 <= n_small <= 14
    big = make_case(client, session, image, n_clips=150, number="R-2")
    assert big["case"]
    _, pdf, n_big, _ = render_text(session, big["case"])
    assert n_big > n_small and n_big <= 60 and pages(pdf) == n_big


def test_generate_endpoint_records_hash_and_head_in_custody(client, session, built, tmp_path):
    before = custody.verify_chain(session, built["case"])
    r = client.post(f"/api/cases/{built['case']}/report")
    assert r.status_code == 201, r.text
    rep = r.json()
    path = Path(session.get(Report, rep["id"]).file_path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == rep["sha256"]
    assert path.stat().st_mode & 0o222 == 0, "report is stored read-only"
    assert path.parent == tmp_path / "data" / "cases" / str(built["case"]) / "reports"
    entry = session.scalars(
        select(CustodyEntry).where(CustodyEntry.action == "report_generated")
    ).one()
    d = json.loads(entry.details_json)
    assert d["sha256"] == rep["sha256"] and d["file_name"] == rep["file_name"]
    assert d["head_hash_built_from"] == before["head_hash"] == rep["head_hash_before"]
    assert d["libraries"]["reportlab"]["version"] and d["parameters"]
    assert entry.examiner == "Insp. Test" and rep["custody_seq"] == entry.seq
    assert custody.verify_chain(session, built["case"])["ok"]
    assert flat(before["head_hash"]) in flat(pdf_text(path.read_bytes()))
    lst = client.get(f"/api/cases/{built['case']}/reports").json()
    assert [x["id"] for x in lst] == [rep["id"]]
    dl = client.get(f"/api/reports/{rep['id']}/download")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf"
    assert hashlib.sha256(dl.content).hexdigest() == rep["sha256"]


def test_generate_requires_examiner_and_case(client, built):
    r = client.post(f"/api/cases/{built['case']}/report", headers={"X-Examiner": ""})
    assert r.status_code == 400
    assert client.post("/api/cases/9999/report").status_code == 404
    assert client.get("/api/cases/9999/reports").status_code == 404
    assert client.get("/api/reports/9999/download").status_code == 404


def test_download_409_when_file_modified_or_missing(client, session, built):
    rep = client.post(f"/api/cases/{built['case']}/report").json()
    path = Path(session.get(Report, rep["id"]).file_path)
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b"x")
    r = client.get(f"/api/reports/{rep['id']}/download")
    assert r.status_code == 409 and "no longer matches" in r.json()["detail"]
    path.unlink()
    assert client.get(f"/api/reports/{rep['id']}/download").status_code == 409


def test_tampered_custody_chain_shows_failed_and_report_still_generates(client, session, built):
    drop_triggers(session)
    session.execute(text("UPDATE custody_entries SET examiner='mallory' WHERE seq=2"))
    session.commit()
    r = client.post(f"/api/cases/{built['case']}/report")
    assert r.status_code == 201
    rep = r.json()
    assert rep["chain_ok"] is False
    t = pdf_text(Path(session.get(Report, rep["id"]).file_path).read_bytes())
    assert has(t, "CUSTODY CHAIN: FAILED") and has(t, "Failure reason")
    assert has(t, "entry_hash does not match entry contents")
    assert not has(t, "CUSTODY CHAIN: VALID")


def test_no_network_during_generation(client, session, built, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    data = build_report_data(session, built["case"], GEN, NTP)
    pdf, _, _ = report_pdf.render(data)
    assert pdf.startswith(b"%PDF")


def test_footer_has_case_and_content_hash_prefix(session, built):
    data, _, _, t = render_text(session, built["case"])
    assert data["content_hash"][:16] in t and has(t, "Page 1 of") and has(t, "Case R-1")


def test_end_to_end_real_carve_hashes_match_report(client, session, streams, tmp_path):
    from app.models import Clip
    from tests.test_analyze import acquire, make_image

    case = client.post("/api/cases", json={"case_number": "E2E", "title": "e2e"}).json()
    path, _ = make_image(streams, tmp_path)
    ev = acquire(client, case, path)
    assert client.post(f"/api/evidence/{ev['id']}/analyze").status_code == 201
    rep = client.post(f"/api/cases/{case['id']}/report").json()
    t = pdf_text(Path(session.get(Report, rep["id"]).file_path).read_bytes())
    f = flat(t)
    assert ev["sha256"] in f and ev["md5"] in f
    clips = session.scalars(select(Clip).where(Clip.kind == "clip")).all()
    assert len(clips) == 2
    for c in clips:
        assert c.bitstream_sha256 in f and c.mp4_sha256 in f
    assert has(t, "ffmpeg version") and has(t, "CUSTODY CHAIN: VALID")
    assert has(t, "No vendor signature matched")
