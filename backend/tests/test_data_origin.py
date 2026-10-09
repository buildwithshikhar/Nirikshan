"""Data-origin wording: the UI, report and demo state what the data is and the Tier B limit.

"Reference test data" is the headline for generated images (validation documents call them
synthetic). Wording may change; the caveats must not weaken: every report states the Tier limit and
the validation statement, and a report of a case with generated images states the data origin.
"""

import re
from pathlib import Path

from sqlalchemy import select

from app import demo_data
from app import synthetic as S
from app.models import Evidence
from app.report import pdf as report_pdf
from app.report.build import build_report_data
from tests.report_support import GEN, NTP, flat, make_case, pdf_text

TS = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "dataOrigin.ts").read_text()


def ts_const(name: str) -> str:
    m = re.search(rf"export const {name} =\s*\n?\s*'([^']*)'", TS)
    assert m, name
    return m.group(1)


def render(session, case_id):
    data = build_report_data(session, case_id, GEN, NTP)
    return pdf_text(report_pdf.render(data)[0])


def has(text, phrase):
    return flat(phrase) in flat(text)


def test_backend_and_frontend_wording_are_identical():
    assert ts_const("ORIGIN_LABEL") == S.ORIGIN_LABEL
    assert ts_const("ORIGIN_DEFINITION") == S.ORIGIN_DEFINITION
    assert ts_const("ORIGIN_DISCLOSURE") == S.ORIGIN_DISCLOSURE
    assert ts_const("TIER_LIMIT") == S.TIER_LIMIT


def test_wording_is_accurate_about_the_sources_and_keeps_the_disclosure():
    assert "published research" in S.ORIGIN_DEFINITION and "ground truth" in S.ORIGIN_DEFINITION
    assert (
        "vendor specification" not in S.ORIGIN_DEFINITION
    )  # vendors publish none for these formats
    assert "Not captured from a physical DVR" in S.ORIGIN_DISCLOSURE
    assert "Tier B" in S.TIER_LIMIT and "real device" in S.TIER_LIMIT


def test_machine_marker_inside_images_is_unchanged():
    assert b"SYNTHETIC" in S.BANNER and b"NOT REAL DVR DATA" in S.BANNER


def test_system_endpoint_exposes_the_wording(client):
    d = client.get("/api/system").json()["data_origin"]
    assert d["label"] == S.ORIGIN_LABEL and d["tier_limit"] == S.TIER_LIMIT


def test_report_for_a_case_with_reference_images_states_origin_and_tier_limit(
    client, session, image
):
    built = make_case(client, session, image)
    for e in session.scalars(select(Evidence)):
        e.synthetic = True
    session.commit()
    text = render(session, built["case"])
    assert has(text, "DATA ORIGIN: " + S.ORIGIN_HEADLINE)
    assert has(text, S.ORIGIN_DISCLOSURE) and has(text, S.TIER_LIMIT)


def test_report_without_reference_images_makes_no_origin_claim_but_keeps_every_limit(
    client, session, image
):
    built = make_case(client, session, image, number="R-2")
    text = render(session, built["case"])
    assert not has(text, "DATA ORIGIN")  # never claims reference data for other images
    assert has(text, S.TIER_LIMIT)
    for phrase in (
        "no vendor is above Tier B",
        "circular",
        "which has not been done",
        "All validation of this tool was done on SYNTHETIC images",
    ):
        assert has(text, phrase), phrase


def test_demo_labels_state_the_origin():
    assert "Reference test data" in demo_data.DEMO_CASE_TITLE
    assert "not captured from a physical DVR" in demo_data.DEMO_CASE_TITLE
    assert demo_data.DEMO_CASE_NUMBER.startswith("DEMO-REFERENCE")
