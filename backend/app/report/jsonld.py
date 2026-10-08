"""Case export as JSON-LD. NOT CASE-conformant, and it does not claim to be.

What was checked (public UCO ontology pages, accessed 2026-10-09, see docs/report.md): the IRIs
and datatypes of uco-types:Hash, uco-types:hashMethod (xsd:string), uco-types:hashValue
(xsd:hexBinary), uco-observable:ContentDataFacet (properties hash, sizeInBytes). Only those terms
are borrowed from UCO. Everything else uses the Nirikshan vocabulary `nk:` (urn:nirikshan:vocab:),
which is documented in the @context only as IRIs; it has no published definitions. The export is
not validated against the CASE/UCO SHACL shapes (they were not available offline) and omits
properties UCO shapes require (for example core:specVersion), so it must not be offered as CASE.

The output is deterministic: no generation time, sorted collections, @id derived from the
signing key id and database ids.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.models import Case, Clip, CustodyEntry, Evidence
from app.report.build import _custody

UCO = "https://ontology.unifiedcyberontology.org/uco/"
NK = "urn:nirikshan:vocab:"
CONTEXT = {
    "uco-observable": UCO + "observable/",
    "uco-types": UCO + "types/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "nk": NK,
}
CONFORMANCE = (
    "NOT CASE-conformant. Only uco-types:Hash/hashMethod/hashValue and "
    "uco-observable:ContentDataFacet/hash/sizeInBytes are borrowed from UCO; every other term is "
    "in the nk: vocabulary, which has no published definition. Not validated against CASE/UCO "
    "SHACL shapes."
)


def _hash(method: str, value: str) -> dict:
    return {
        "@type": "uco-types:Hash",
        "uco-types:hashMethod": {"@type": "xsd:string", "@value": method},
        "uco-types:hashValue": {"@type": "xsd:hexBinary", "@value": value},
    }


def _facet(fid: str, hashes: list[dict], size: int | None) -> dict:
    f: dict = {
        "@id": fid,
        "@type": "uco-observable:ContentDataFacet",
        "uco-observable:hash": hashes,
    }
    if size is not None:
        f["uco-observable:sizeInBytes"] = {"@type": "xsd:long", "@value": size}
    return f


def build_jsonld(db: Session, case_id: int) -> dict:
    case = db.get(Case, case_id)
    if case is None:
        raise LookupError(f"case {case_id} not found")
    cust = _custody(db, case_id)
    ver = cust["verification"]
    base = f"urn:nirikshan:{ver['key_id']}:case:{case_id}"
    graph: list[dict] = [
        {
            "@id": base,
            "@type": "nk:Case",
            "nk:caseNumber": case.case_number,
            "nk:title": case.title,
            "nk:description": case.description,
            "nk:examiner": case.examiner,
            "nk:createdAt": case.created_at,
            "nk:toolVersion": __version__,
            "nk:conformance": CONFORMANCE,
            "nk:custodyVerification": {
                "nk:ok": ver["ok"],
                "nk:entries": ver["entries"],
                "nk:headHash": ver["head_hash"],
                "nk:signingKeyId": ver["key_id"],
                "nk:signatureAlgorithm": "Ed25519",
                "nk:publicKeyHex": cust["public_key_hex"],
                "nk:failures": [
                    {"nk:seq": f["seq"], "nk:reason": f["reason"]} for f in ver["failures"]
                ],
            },
        }
    ]
    for e in db.scalars(select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id)):
        eid = f"{base}:evidence:{e.id}"
        graph.append(
            {
                "@id": eid,
                "@type": "nk:EvidenceImage",
                "nk:case": {"@id": base},
                "nk:label": e.label,
                "nk:sourcePath": e.source_path,
                "nk:sourceType": e.source_type,
                "nk:writeBlockerAttestation": e.write_blocker,
                "nk:writeBlockerNote": "examiner attestation, not verified by the tool",
                "nk:status": e.status,
                "nk:examiner": e.examiner,
                "nk:acquiredAt": e.acquired_at,
                "nk:lastVerifiedAt": e.last_verified_at,
                "nk:lastVerifyOk": e.last_verify_ok,
                "nk:contentData": _facet(
                    eid + "#content",
                    [
                        h
                        for h in (
                            _hash("MD5", e.md5) if e.md5 else None,
                            _hash("SHA256", e.sha256) if e.sha256 else None,
                        )
                        if h
                    ],
                    e.size_bytes,
                ),
            }
        )
    for c in db.scalars(
        select(Clip).where(Clip.case_id == case_id, Clip.kind == "clip").order_by(Clip.id)
    ):
        cid = f"{base}:clip:{c.id}"
        node = {
            "@id": cid,
            "@type": "nk:Clip",
            "nk:case": {"@id": base},
            "nk:evidence": {"@id": f"{base}:evidence:{c.evidence_id}"},
            "nk:carveRun": c.run_id,
            "nk:engine": c.engine,
            "nk:codec": c.codec,
            "nk:channel": c.channel,
            "nk:startOffset": c.start_offset,
            "nk:endOffset": c.end_offset,
            "nk:decodeStatus": c.decode_status,
            "nk:nominalDurationSeconds": c.duration_s,
            "nk:nominalDurationNote": "frames / stream frame rate; not recording time",
        }
        if c.bitstream_sha256:
            node["nk:bitstreamContentData"] = _facet(
                cid + "#bitstream", [_hash("SHA256", c.bitstream_sha256)], c.size_bytes
            )
        if c.mp4_sha256:
            node["nk:mp4ContentData"] = _facet(cid + "#mp4", [_hash("SHA256", c.mp4_sha256)], None)
        graph.append(node)
    for r in db.scalars(
        select(CustodyEntry).where(CustodyEntry.case_id == case_id).order_by(CustodyEntry.seq)
    ):
        graph.append(
            {
                "@id": f"{base}:custody:{r.seq}",
                "@type": "nk:CustodyEntry",
                "nk:case": {"@id": base},
                "nk:seq": r.seq,
                "nk:timestampUtc": r.timestamp_utc,
                "nk:action": r.action,
                "nk:examiner": r.examiner,
                "nk:evidenceId": r.evidence_id,
                "nk:toolVersion": r.tool_version,
                "nk:ntpStatus": r.ntp_status,
                "nk:detailsJson": r.details_json,  # canonical JSON text, hashed as stored
                "nk:prevHash": r.prev_hash,
                "nk:entryHash": r.entry_hash,
                "nk:signature": r.signature,
                "nk:signingKeyId": r.key_id,
            }
        )
    return {"@context": CONTEXT, "@graph": graph}
