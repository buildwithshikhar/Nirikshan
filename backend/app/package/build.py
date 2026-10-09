"""Build a signed, deterministic evidence package (zip) for one case.

Deterministic where feasible: entries sorted by path, every timestamp fixed at 1980-01-01
00:00:00 (the zip epoch), fixed permissions (0444), JSON written with sorted keys, text members
deflated at level 6 and already-compressed media (PDF, MP4) stored. Given the same database
state, the same files, the same `created_at`/`ntp` and the same zlib, two builds are
byte-identical (tests/test_package_build.py). The custody entry `package_created` is appended
AFTER the build, so the manifest names the chain head it was built from.

What is NOT in a package: the evidence images themselves (they can be many GB; their MD5/SHA-256
are in evidence.json and the custody log, and the examiner hands the image over separately),
and nothing private (no keys, no passwords, no session data).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__, custody, schema, signing
from app.analytics.models import AnalyticsRun
from app.analytics.registry import MODELS
from app.approvals.models import EvidenceTransfer, ReportReview
from app.carving.export import ffmpeg_version
from app.hashing import hash_file
from app.models import CarveRun, Case, Clip, CustodyEntry, Evidence
from app.package import keys
from app.report.models import Report
from app.synthetic import ORIGIN_DEFINITION, ORIGIN_DISCLOSURE, ORIGIN_LABEL, TIER_LIMIT
from app.vendors import default_registry

FORMAT = "nirikshan-evidence-package"
FORMAT_VERSION = 1
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
STORED_SUFFIXES = (".mp4", ".pdf")
MANIFEST, SIGNATURE = "manifest.json", "manifest.sig"


def jdump(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


CSV_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection: a cell that starts with = + - @ TAB CR gets a
    leading apostrophe (OWASP guidance). Numbers are written as numbers."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(CSV_TRIGGERS) else s


def csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([csv_safe(v) for v in r])
    return buf.getvalue().encode()


@dataclass
class Member:
    path: str
    data: bytes | None = None
    source: Path | None = None

    def open(self) -> BinaryIO:
        return io.BytesIO(self.data) if self.data is not None else open(self.source, "rb")


@dataclass
class BuildResult:
    manifest: bytes
    signature: bytes
    files: list[dict]
    excluded: list[dict] = field(default_factory=list)


def _sha_of(m: Member) -> tuple[str, int]:
    if m.data is not None:
        return hashlib.sha256(m.data).hexdigest(), len(m.data)
    h = hash_file(m.source)
    return h.sha256, m.source.stat().st_size


def _custody_rows(db: Session, case_id: int) -> list[dict]:
    rows = db.scalars(
        select(CustodyEntry).where(CustodyEntry.case_id == case_id).order_by(CustodyEntry.seq)
    )
    return [
        {
            "seq": e.seq,
            "timestamp_utc": e.timestamp_utc,
            "action": e.action,
            "evidence_id": e.evidence_id,
            "examiner": e.examiner,
            "tool_version": e.tool_version,
            "ntp_status": e.ntp_status,
            "details": json.loads(e.details_json),
            "prev_hash": e.prev_hash,
            "entry_hash": e.entry_hash,
            "signature": e.signature,
            "key_id": e.key_id,
        }
        for e in rows
    ]


def _ffmpeg() -> str:
    try:
        return ffmpeg_version()
    except Exception:  # noqa: BLE001 - ffmpeg absent or broken: say so, do not fail the package
        return "not available"


def _parsers() -> list[dict]:
    return [
        {
            "vendor": p.vendor,
            "tier": p.tier,
            "implementation": type(p).__name__,
            "version": __version__,
            "version_note": "parsers are versioned with the tool (no separate parser version)",
            "sources": list(p.sources),
        }
        for p in default_registry().parsers
    ]


def _models() -> list[dict]:
    return [{**spec.run_info(), "used_for": key} for key, spec in sorted(MODELS.items())]


def _evidence(db: Session, case_id: int) -> list[Evidence]:
    return list(
        db.scalars(select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id))
    )


def collect(
    db: Session, case_id: int, *, created_at: str, ntp: str, include_clips: bool
) -> tuple[list[Member], list[dict], dict]:
    """All payload members except README/SHA256SUMS/key (added by build()), plus exclusions and
    facts for the manifest."""
    from app.report import jsonld
    from app.report.build import build_report_data
    from app.timeline import timeline as tl_mod
    from app.timeline.routes import build_case_timeline

    case = db.get(Case, case_id)
    members: list[Member] = []
    excluded: list[dict] = []
    evs = _evidence(db, case_id)

    members.append(
        Member(
            "case/case.json",
            jdump(
                {
                    "id": case.id,
                    "case_number": case.case_number,
                    "title": case.title,
                    "description": case.description,
                    "examiner": case.examiner,
                    "created_at": case.created_at,
                }
            ),
        )
    )
    ev_rows = [
        {
            "id": e.id,
            "label": e.label,
            "source_path": e.source_path,
            "source_type": e.source_type,
            "write_blocker_attestation": e.write_blocker,
            "status": e.status,
            "size_bytes": e.size_bytes,
            "md5": e.md5,
            "sha256": e.sha256,
            "acquired_by": e.examiner,
            "acquired_at": e.acquired_at,
            "last_verified_at": e.last_verified_at,
            "last_verify_ok": e.last_verify_ok,
            "synthetic_banner_detected": bool(e.synthetic),
        }
        for e in evs
    ]
    members.append(Member("case/evidence.json", jdump(ev_rows)))
    members.append(
        Member(
            "case/evidence.csv",
            csv_bytes(
                list(ev_rows[0].keys()) if ev_rows else ["id"],
                [list(r.values()) for r in ev_rows],
            ),
        )
    )
    runs = list(
        db.scalars(select(CarveRun).where(CarveRun.case_id == case_id).order_by(CarveRun.id))
    )
    members.append(
        Member(
            "case/runs.json",
            jdump(
                [
                    {
                        "id": r.id,
                        "evidence_id": r.evidence_id,
                        "status": r.status,
                        "examiner": r.examiner,
                        "params": json.loads(r.params_json),
                        "vendor_matches": json.loads(r.vendor_json),
                        "parsers": json.loads(r.parse_json),
                        "stats": json.loads(r.stats_json),
                        "tool_version": r.tool_version,
                        "ffmpeg_version": r.ffmpeg_version,
                        "started_at": r.started_at,
                        "finished_at": r.finished_at,
                        "identify_seconds": r.ident_seconds,
                        "carve_seconds": r.carve_seconds,
                        "error": r.error,
                    }
                    for r in runs
                ]
            ),
        )
    )
    clips = list(db.scalars(select(Clip).where(Clip.case_id == case_id).order_by(Clip.id)))
    clip_cols = [
        "id", "run_id", "evidence_id", "kind", "engine", "seq", "codec", "channel",
        "start_offset", "end_offset", "size_bytes", "bitstream_sha256", "mp4_sha256",
        "decode_status", "width", "height", "fps", "duration_s", "reason",
    ]  # fmt: skip
    members.append(
        Member(
            "case/clips.csv",
            csv_bytes(clip_cols, [[getattr(c, k) for k in clip_cols] for c in clips]),
        )
    )
    aruns = list(
        db.scalars(
            select(AnalyticsRun).where(AnalyticsRun.case_id == case_id).order_by(AnalyticsRun.id)
        )
    )
    members.append(
        Member(
            "case/analytics_runs.json",
            jdump(
                [
                    {
                        "id": a.id,
                        "clip_id": a.clip_id,
                        "kind": a.kind,
                        "status": a.status,
                        "label": a.label,
                        "examiner": a.examiner,
                        "params": json.loads(a.params_json),
                        "model": json.loads(a.model_json),
                        "result_count": a.result_count,
                        "frames_analysed": a.frames_analysed,
                        "mp4_sha256": a.mp4_sha256,
                        "error": a.error,
                    }
                    for a in aruns
                ]
            ),
        )
    )
    transfers = db.scalars(
        select(EvidenceTransfer)
        .where(EvidenceTransfer.case_id == case_id)
        .order_by(EvidenceTransfer.id)
    )
    members.append(
        Member(
            "case/transfers.json",
            jdump(
                [
                    {
                        "id": t.id,
                        "evidence_id": t.evidence_id,
                        "from": t.from_party,
                        "to": t.to_party,
                        "reason": t.reason,
                        "transferred_at": t.transferred_at,
                        "location": t.location,
                        "seal": t.seal,
                        "recorded_by": t.recorded_by,
                        "recorded_at": t.recorded_at,
                        "custody_seq": t.custody_seq,
                    }
                    for t in transfers
                ]
            ),
        )
    )
    tl = build_case_timeline(db, case_id, tl_mod.DEFAULT_MIN_GAP_S)
    members.append(Member("export/timeline.json", jdump(tl)))
    raw_csv = tl_mod.export_csv(tl)
    rows = list(csv.reader(io.StringIO(raw_csv)))
    members.append(Member("export/timeline.csv", csv_bytes(rows[0], rows[1:]) if rows else b""))
    members.append(Member("export/case.jsonld", jdump(jsonld.build_jsonld(db, case_id))))
    members.append(
        Member(
            "export/case_data.json",
            jdump(build_report_data(db, case_id, generated_at=created_at, ntp=ntp)),
        )
    )
    cust = _custody_rows(db, case_id)
    ver = custody.verify_chain(db, case_id)
    members.append(Member("custody/custody_log.json", jdump(cust)))
    members.append(Member("custody/custody_verification.json", jdump(ver)))
    members.append(
        Member(
            "custody/custody_public_key.json",
            jdump(
                {
                    "algorithm": "Ed25519",
                    "key_id": signing.key_id(signing.public_key()),
                    "public_key_hex": signing.public_key_hex(),
                    "note": "entry signatures sign the ASCII hex entry_hash (docs/ARCHITECTURE.md)",
                }
            ),
        )
    )
    # reports, with their review state
    reviews = {
        rv.report_id: rv
        for rv in db.scalars(select(ReportReview).where(ReportReview.case_id == case_id))
    }
    rep_rows = []
    for r in db.scalars(select(Report).where(Report.case_id == case_id).order_by(Report.id)):
        status = reviews[r.id].status if r.id in reviews else "draft"
        rep_rows.append(
            {"id": r.id, "file_name": r.file_name, "sha256": r.sha256, "review_status": status}
        )
        p = Path(r.file_path)
        if not p.is_file() or hash_file(p).sha256 != r.sha256:
            excluded.append(
                {"path": f"reports/{r.file_name}", "reason": "stored file missing or hash mismatch"}
            )
            continue
        members.append(Member(f"reports/{r.file_name}", source=p))
    members.append(Member("reports/reports.json", jdump(rep_rows)))
    # clips
    for c in clips:
        if c.kind != "clip" or not c.mp4_path:
            continue
        p = Path(c.mp4_path)
        arc = f"clips/evidence{c.evidence_id}/run{c.run_id}/clip{c.id}_{p.name}"
        if not include_clips:
            continue
        if not p.is_file() or hash_file(p).sha256 != c.mp4_sha256:
            excluded.append({"path": arc, "reason": "exported MP4 missing or hash mismatch"})
            continue
        members.append(Member(arc, source=p))
    facts = {
        "case": {"id": case.id, "case_number": case.case_number, "title": case.title},
        "custody": {
            "head_hash": ver["head_hash"],
            "entries": ver["entries"],
            "chain_ok": ver["ok"],
            "key_id": ver["key_id"],
            "note": "chain head BEFORE the package_created entry for this package was appended",
        },
        "data_origin": {
            "label": ORIGIN_LABEL,
            "definition": ORIGIN_DEFINITION,
            "disclosure": ORIGIN_DISCLOSURE,
            "tier_limit": TIER_LIMIT,
            "evidence_with_synthetic_banner": [e.id for e in evs if e.synthetic],
            "evidence_without_banner": [e.id for e in evs if not e.synthetic],
            "statement": (
                "Evidence items listed with the synthetic banner are generated reference test "
                "images, not captured from a physical DVR. The absence of the banner does not "
                "show that an image is real. No vendor is supported above Tier B and nothing in "
                "this package has been validated on a real device."
            ),
        },
    }
    return members, excluded, facts


README = """NIRIKSHAN EVIDENCE PACKAGE
==========================

Case: {case_number} (id {case_id})    Created (UTC): {created_at}    By: {created_by}
Tool version: {tool_version}

This package was written by Nirikshan. It is signed with an Ed25519 key whose id is
{key_id}. The signature proves that whoever held that key produced manifest.json; it does
not by itself prove who that was. Compare the key id with the one recorded outside this
package (case file, lab register, GET /api/package-key at the issuing lab).

The evidence images are NOT inside the package; their MD5/SHA-256 are in case/evidence.json
and in the custody log. Data origin: see "data_origin" in manifest.json.

OFFLINE VERIFICATION
1. With Nirikshan installed (no database or network needed):
     python -m app.cli verify-package <this file> --expect-key-id {key_id}
   It checks the signature and every file hash and names any file that fails.
2. Without Nirikshan (OpenSSL 3 and coreutils), after unzipping:
     openssl pkeyutl -verify -pubin -inkey package_public_key.pem -rawin \\
         -in manifest.json -sigfile manifest.sig
     sha256sum -c SHA256SUMS
   Then confirm that every file listed in manifest.json "files" is present and that no other
   file was added (manifest.json and manifest.sig themselves are not listed).
3. Record the custody head_hash in manifest.json ("custody"."head_hash") against the
   value recorded at the lab; custody/custody_log.json holds every signed entry.

If the package file ends in .nrkenc it is encrypted (AES-256-GCM, scrypt-derived key); the
verifier asks for the passphrase. The byte format is in docs/package.md.
"""


def _zinfo(path: str) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(path, date_time=ZIP_EPOCH)
    zi.create_system = 3
    zi.external_attr = (0o100444 & 0xFFFF) << 16
    if path.lower().endswith(STORED_SUFFIXES):
        zi.compress_type = zipfile.ZIP_STORED
    else:
        zi.compress_type = zipfile.ZIP_DEFLATED
    return zi


def build(
    db: Session,
    case_id: int,
    out: BinaryIO,
    *,
    created_at: str,
    created_by: str,
    ntp: str,
    include_clips: bool = True,
) -> BuildResult:
    members, excluded, facts = collect(
        db, case_id, created_at=created_at, ntp=ntp, include_clips=include_clips
    )
    pub_pem = keys.public_key_pem()
    kid = keys.key_id()
    members.append(Member("package_public_key.pem", pub_pem))
    members.append(
        Member(
            "README.txt",
            README.format(
                case_number=facts["case"]["case_number"],
                case_id=case_id,
                created_at=created_at,
                created_by=created_by,
                tool_version=__version__,
                key_id=kid,
            ).encode(),
        )
    )
    members.sort(key=lambda m: m.path)
    files = []
    for m in members:
        sha, size = _sha_of(m)
        files.append({"path": m.path, "sha256": sha, "size": size})
    sums = "".join(f"{f['sha256']}  {f['path']}\n" for f in files).encode()
    members.append(Member("SHA256SUMS", sums))
    files.append(
        {"path": "SHA256SUMS", "sha256": hashlib.sha256(sums).hexdigest(), "size": len(sums)}
    )
    members.sort(key=lambda m: m.path)
    files.sort(key=lambda f: f["path"])
    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "created_at": created_at,
        "created_by": created_by,
        "ntp_status": ntp,
        "tool_version": __version__,
        "schema_version": schema.SCHEMA_VERSION,
        "ffmpeg_version": _ffmpeg(),
        "parsers": _parsers(),
        "analytics_models": _models(),
        "package_signing_key": {
            "algorithm": "Ed25519",
            "key_id": kid,
            "public_key_hex": keys.public_key_hex(),
        },
        "signature_covers": "the exact bytes of manifest.json",
        "files": files,
        "excluded": excluded,
        "include_clips": include_clips,
        **facts,
    }
    mbytes = jdump(manifest)
    sig = keys.sign(mbytes)
    sizes = {f["path"]: f["size"] for f in files}
    with zipfile.ZipFile(out, "w", compresslevel=6) as zf:
        entries = sorted(
            [*members, Member(MANIFEST, mbytes), Member(SIGNATURE, sig)], key=lambda m: m.path
        )
        for m in entries:
            big = sizes.get(m.path, 0) > (1 << 31)
            with m.open() as src, zf.open(_zinfo(m.path), "w", force_zip64=big) as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
    return BuildResult(mbytes, sig, files, excluded)
