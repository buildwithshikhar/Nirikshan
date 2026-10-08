"""DRAFT certificate under Section 63(4) of the Bharatiya Sakshya Adhiniyam, 2023.

This is a drafting aid. It pre-fills only facts the tool recorded (image hashes, acquisition
data, tool version, custody chain state) and leaves everything a person must state, and every
signature, blank. It never asserts that the result satisfies Section 63(4) or that anything is
admissible. The structure follows the Schedule certificate (Part A: person in charge; Part B:
expert) as reproduced by third-party sites; the official gazette text could NOT be retrieved
by us (see docs/legal/BSA-63-4-notes.md for exactly what was and was not confirmed).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import __version__, custody
from app.models import Case, Evidence
from app.report import pdfkit as K

BANNER = (
    "DRAFT for examiner and legal review, not legal advice. "
    "Nirikshan does not assert that this satisfies Section 63(4)."
)
UNCONFIRMED = [
    "The official Gazette / India Code text of the Schedule could not be retrieved; this "
    "layout follows third-party reproductions and may differ in wording, order or fields.",
    "Which Schedule fields are mandatory is not confirmed.",
    "Who must sign Part A and Part B in a given case is a legal question not settled here; "
    "the Supreme Court reportedly held that Part B need not be signed only by a Section 79A "
    "notified examiner (reported at SCC Online, 2026), and left the scope of expert "
    "certification open. Confirm with counsel.",
    "Where the hash value must appear (Part A, Part B or both) differs between sources; both "
    "parts carry the hash line below so the examiner can delete what is not needed.",
    "Nirikshan did not and cannot confirm that its recorded hashes, acquisition steps or "
    "custody log meet any court's expectation.",
]


def certificate_data(db: Session, case_id: int, evidence_id: int, generated_at: str) -> dict:
    case = db.get(Case, case_id)
    ev = db.get(Evidence, evidence_id)
    if case is None or ev is None or ev.case_id != case_id:
        raise LookupError("case or evidence not found")
    ver = custody.verify_chain(db, case_id)
    return {
        "generated_at": generated_at,
        "tool_version": __version__,
        "case": {"id": case.id, "number": case.case_number, "title": case.title},
        "evidence": {
            "id": ev.id,
            "label": ev.label,
            "source_path": ev.source_path,
            "source_type": ev.source_type,
            "status": ev.status,
            "size_bytes": ev.size_bytes,
            "md5": ev.md5,
            "sha256": ev.sha256,
            "examiner": ev.examiner,
            "acquired_at": ev.acquired_at,
            "write_blocker": ev.write_blocker,
            "last_verified_at": ev.last_verified_at,
            "last_verify_ok": ev.last_verify_ok,
        },
        "custody": {"ok": ver["ok"], "entries": ver["entries"], "head_hash": ver["head_hash"]},
    }


BLANK = "______________________________"


def _hash_block(d: dict) -> list[tuple[str, str]]:
    e = d["evidence"]
    return [
        ("MD5 (tool-recorded)", e["md5"] or "not recorded"),
        ("SHA-256 (tool-recorded)", e["sha256"] or "not recorded"),
        ("Algorithms (tick)", "[ ] SHA1   [x] SHA256   [x] MD5   [ ] Other ________"),
        (
            "Hashed object",
            "forensic image file of the storage medium of the device above, as "
            f"acquired by Nirikshan ({e['size_bytes']:,} bytes)",
        ),
    ]


def render_certificate(d: dict) -> tuple[bytes, int]:
    def story(san: K.Sanitizer, st: K.Styles) -> list:
        P = lambda t, s=None: K.para(san, t, s or st.body)  # noqa: E731
        e, c = d["evidence"], d["case"]
        s: list = [
            P("Draft certificate under Section 63(4), Bharatiya Sakshya Adhiniyam, 2023", st.title),
            P(BANNER, st.banner),
            K.Spacer(1, 5),
            P("What this document is", st.h2),
            P(
                "A drafting aid produced by software. It contains facts the software recorded and "
                "blank fields for statements that only a person can make. It is not a certificate "
                "until a qualified person completes, reviews and signs it, and Nirikshan makes no "
                "statement about whether it would be accepted by any court.",
                st.body,
            ),
            P("Unconfirmed points (read before use)", st.h2),
            *[P(f"{i}. {t}", st.small) for i, t in enumerate(UNCONFIRMED, 1)],
            P(
                f"Draft generated (UTC): {d['generated_at']}. Nirikshan {d['tool_version']}. "
                f"Case {c['number']} (id {c['id']}), evidence {e['id']}.",
                st.note,
            ),
            P(
                "PART A: to be completed and signed by the person in charge of the computer or "
                "communication device, or of the management of the relevant activities",
                st.h1,
            ),
            K.kv_table(
                san,
                st,
                [
                    ("Name", BLANK),
                    ("Son/daughter/spouse of", BLANK),
                    ("Residing / employed at", BLANK),
                    (
                        "Source of the record (tick)",
                        "[ ] Computer  [ ] Storage media  [ ] DVR  [ ] Mobile  [ ] Flash drive  "
                        "[ ] CD/DVD  [ ] Server  [ ] Cloud  [ ] Other",
                    ),
                    ("Make and model", BLANK + "   (not known to Nirikshan; examiner to complete)"),
                    ("Colour", BLANK),
                    ("Serial number", BLANK + "   (not known to Nirikshan; examiner to complete)"),
                    ("IMEI / UIN / UID / MAC / Cloud ID", BLANK),
                    ("Other identifying information", BLANK),
                    (
                        "Item as labelled in the case",
                        f"{e['label']} (source {e['source_path']}, type {e['source_type']})",
                    ),
                    (
                        "Record identified",
                        "Forensic image of the storage medium of the device, "
                        f"acquired {e['acquired_at']} (UTC) by {e['examiner']}; examiner's "
                        f"write-blocker attestation: {e['write_blocker']} (examiner attestation, "
                        "not verified by the tool)",
                    ),
                    *_hash_block(d),
                    ("Manner of production (examiner to state)", BLANK + BLANK),
                    ("Statements on the Section 63(2) conditions (person to state)", BLANK + BLANK),
                    ("Date (DD/MM/YYYY), time (IST, 24 h), place", BLANK),
                    ("Signature", BLANK),
                ],
                w0=58 * K.mm,
            ),  # fmt: skip
            K.PageBreak(),
            P("PART B: to be completed and signed by the expert", st.h1),
            K.kv_table(
                san,
                st,
                [
                    ("Name", BLANK),
                    ("Son/daughter/spouse of", BLANK),
                    ("Residing / employed at", BLANK),
                    ("Qualification and expertise (expert to state)", BLANK + BLANK),
                    *_hash_block(d),
                    (
                        "Expert's statement",
                        "(To be written by the expert. Nirikshan generates no "
                        "opinion, conclusion or certification for the expert.)",
                    ),
                    ("Date (DD/MM/YYYY), time (IST, 24 h), place", BLANK),
                    ("Signature", BLANK),
                ],
                w0=58 * K.mm,
            ),  # fmt: skip
            K.Spacer(1, 8),
            P("Tool-recorded facts, for the signatories to adopt, correct or discard", st.h2),
            K.kv_table(
                san,
                st,
                [
                    ("Image size", f"{e['size_bytes']:,} bytes"),
                    ("Acquisition status", e["status"]),
                    (
                        "Last verification of the image hashes",
                        {-1: "never verified after acquisition", 0: "FAILED", 1: "passed"}.get(
                            e["last_verify_ok"], "unknown"
                        )
                        + (f" at {e['last_verified_at']}" if e["last_verified_at"] else ""),
                    ),
                    (
                        "Custody chain at draft time",
                        ("VALID" if d["custody"]["ok"] else "FAILED")
                        + f", {d['custody']['entries']} entries, head_hash "
                        f"{d['custody']['head_hash']}",
                    ),
                    (
                        "Tool",
                        f"Nirikshan {d['tool_version']} (hash algorithms: MD5 and SHA-256, "
                        "computed in one pass at acquisition)",
                    ),
                ],
                w0=58 * K.mm,
            ),  # fmt: skip
            K.Spacer(1, 6),
            P(
                "Nirikshan's validation is on synthetic images only. The hash values above "
                "identify "
                "a file; they do not by themselves state anything about the content, origin or "
                "legal status of the record.",
                st.note,
            ),
        ]
        return s

    pdf, pages, _ = K.build_pdf(
        story,
        title=f"DRAFT Section 63(4) certificate, case {d['case']['number']}",
        footer_left=f"DRAFT certificate | case {d['case']['number']} | evidence "
        f"{d['evidence']['id']} | SHA-256 {d['evidence']['sha256'][:16]}",
        banner=BANNER,
    )
    return pdf, pages
