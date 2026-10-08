"""Draft s63(4) certificate and JSON-LD export tests (SYNTHETIC data)."""

import io
import json
import re

import pytest
from pypdf import PdfReader

from app.report.certificate import BANNER
from tests.report_support import flat, make_case, pdf_text


@pytest.fixture
def built(client, session, image):
    return make_case(client, session, image)


def cert(client, built):
    r = client.get(
        f"/api/cases/{built['case']}/certificate-draft", params={"evidence_id": built["evidence"]}
    )
    assert r.status_code == 200, r.text
    return r


def test_certificate_banner_on_every_page_and_fields(client, built):
    r = cert(client, built)
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-nirikshan-draft"] == "true"
    pages = PdfReader(io.BytesIO(r.content)).pages
    assert len(pages) >= 2
    for p in pages:
        assert flat(BANNER) in flat(p.extract_text())
    t = pdf_text(r.content)
    f = flat(t)
    ev = built["ev"]
    assert ev["md5"] in f and ev["sha256"] in f
    for field in (
        "PART A",
        "PART B",
        "Make and model",
        "Serial number",
        "IMEI / UIN / UID / MAC",
        "Signature",
        "SHA256",
        "MD5",
        "DVR",
        "synthetic HDD",
        "Insp. Test",
    ):
        assert flat(field) in f, field
    assert "Unconfirmed points" in t and "could not be retrieved" in t.replace("\n", " ")


def test_certificate_never_claims_compliance_or_admissibility(client, built):
    t = " ".join(pdf_text(cert(client, built).content).split())
    banner = " ".join(BANNER.split())
    rest = t.replace(banner, "")
    for bad in (
        "complies with",
        "is compliant",
        "is admissible",
        "will be admissible",
        "satisfies Section",
        "legally valid",
        "meets the requirements",
        "certified by Nirikshan",
    ):
        assert bad.lower() not in rest.lower(), bad
    for sentence in re.split(r"(?<=[.!?])\s+", rest):
        if re.search(r"admissib|complian|satisf|legally", sentence, re.I):
            assert re.search(r"\bnot\b|\bno\b|cannot|makes no|unconfirmed", sentence, re.I), (
                sentence
            )


def test_certificate_errors(client, built):
    base = f"/api/cases/{built['case']}/certificate-draft"
    assert client.get(base).status_code == 422
    assert client.get(base, params={"evidence_id": 999}).status_code == 404
    assert (
        client.get("/api/cases/999/certificate-draft", params={"evidence_id": 1}).status_code == 404
    )


def test_jsonld_valid_context_and_hashes_match_db(client, session, built):
    from app.models import Clip, Evidence

    r = client.get(f"/api/cases/{built['case']}/export.jsonld")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/ld+json")
    doc = json.loads(r.text)
    assert "@context" in doc and "@graph" in doc
    assert doc["@context"]["uco-types"].startswith("https://ontology.unifiedcyberontology.org/")
    nodes = {n["@id"]: n for n in doc["@graph"]}
    case = next(n for n in doc["@graph"] if n["@type"] == "nk:Case")
    assert "NOT CASE-conformant" in case["nk:conformance"]
    assert case["nk:custodyVerification"]["nk:ok"] is True
    ev = session.get(Evidence, built["evidence"])
    en = next(n for n in doc["@graph"] if n["@type"] == "nk:EvidenceImage")
    hashes = {
        h["uco-types:hashMethod"]["@value"]: h["uco-types:hashValue"]["@value"]
        for h in en["nk:contentData"]["uco-observable:hash"]
    }
    assert hashes == {"MD5": ev.md5, "SHA256": ev.sha256}
    clips = [n for n in doc["@graph"] if n["@type"] == "nk:Clip"]
    assert len(clips) == len(built["clips"]) + 1  # plus the decode_errors clip
    for n in clips:
        row = session.get(Clip, int(n["@id"].rsplit(":", 1)[1]))
        if row.bitstream_sha256:
            h = n["nk:bitstreamContentData"]["uco-observable:hash"][0]
            assert h["uco-types:hashValue"]["@value"] == row.bitstream_sha256
        if row.mp4_sha256:
            h = n["nk:mp4ContentData"]["uco-observable:hash"][0]
            assert h["uco-types:hashValue"]["@value"] == row.mp4_sha256
    cust = [n for n in doc["@graph"] if n["@type"] == "nk:CustodyEntry"]
    assert [c["nk:seq"] for c in cust] == list(range(1, len(cust) + 1))
    assert all(len(c["nk:entryHash"]) == 64 and c["nk:signature"] for c in cust)
    assert len(nodes) == len(doc["@graph"]), "@id values are unique"


def test_jsonld_deterministic_stable_ids(client, built):
    a = client.get(f"/api/cases/{built['case']}/export.jsonld").text
    b = client.get(f"/api/cases/{built['case']}/export.jsonld").text
    assert a == b
    ids = [n["@id"] for n in json.loads(a)["@graph"]]
    assert all(i.startswith("urn:nirikshan:") for i in ids)
    assert client.get("/api/cases/999/export.jsonld").status_code == 404
