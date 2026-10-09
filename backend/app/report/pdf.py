"""Render ReportData (build.build_report_data) to a court-style PDF.

Every statement is either a value read from the data, a fixed sentence about what the tool does
or does not do, or a documented limitation. Nothing legal is asserted.
"""

from __future__ import annotations

import re

from app.analytics import TRIAGE_LABEL
from app.report import pdfkit as K
from app.report.build import DISCLAIMER_CLOCK, NOMINAL_NOTE, clip_text
from app.synthetic import ORIGIN_DISCLOSURE, ORIGIN_HEADLINE, TIER_LIMIT

W = 182 * K.mm
SECTION_NAMES = [
    "COVER",
    "1. EVIDENCE",
    "2. CUSTODY CHAIN VERIFICATION",
    "3. CARVE RUNS",
    "4. TIMESTAMPS",
    "5. ANALYTICS",
    "6. LIMITATIONS",
    "7. COLOPHON AND HOW TO VERIFY THIS REPORT",
]


def _fmt_bytes(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def _none(v, dash: str = "none recorded") -> str:
    return dash if v in (None, "", [], {}) else str(v)


def render(data: dict) -> tuple[bytes, int, int]:
    """Returns (pdf bytes, page count, characters replaced by the font sanitizer)."""
    cover = data["cover"]
    footer = (
        f"Case {cover['case_number']} (id {cover['case_id']}) | report content hash "
        f"{data['content_hash'][:16]} | Nirikshan {cover['tool_version']}"
    )
    pdf, pages, san = K.build_pdf(
        lambda s, st: _story(data, s, st),
        title=f"Nirikshan report, case {cover['case_number']}",
        footer_left=footer,
    )
    return pdf, pages, san.replaced


# ------------------------------------------------------------------ story


def _story(data: dict, san: K.Sanitizer, st: K.Styles) -> list:
    P = lambda t, s=None: K.para(san, t, s or st.body)  # noqa: E731
    out: list = []
    out += _cover(data, san, st, P)
    out += _evidence(data, san, st, P)
    out += _custody(data, san, st, P)
    out += _runs(data, san, st, P)
    out += _timestamps(data, san, st, P)
    out += _analytics(data, san, st, P)
    out += _limitations(data, san, st, P)
    out += _colophon(data, san, st, P)
    return out


_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(\.\d+)?(Z|\+00:00)$")


def _sec(t):
    """Display a UTC timestamp to the second ('2026-10-09 06:57:26Z'); anything that is not an
    ISO UTC string is returned unchanged. Full precision stays in the custody log."""
    m = _ISO.match(str(t)) if t else None
    return f"{m.group(1)} {m.group(2)}Z" if m else t


def _precise(t):
    """Like _sec but keeps a non-zero fractional part (intervals can be sub-second)."""
    m = _ISO.match(str(t)) if t else None
    if not m:
        return t
    frac = (m.group(3) or "").rstrip("0")
    return f"{m.group(1)} {m.group(2)}{frac if frac != '.' else ''}Z"


def _interval(lo, hi):
    if lo is None or hi is None:
        return "-"
    return f"{_precise(lo)}\nto {_precise(hi)}"


def _origin_block(data, P, st):
    """Data origin (when the case holds generated reference images) and the Tier B limit.
    Always printed on the cover: neither can be switched off."""
    ev = data["evidence"]
    n_ref = sum(1 for e in ev if e.get("reference_data"))
    out = []
    if n_ref:
        out.append(
            P(
                f"DATA ORIGIN: {ORIGIN_HEADLINE}. {n_ref} of {len(ev)} evidence item(s) in this "
                f"case carry the generated-image marker. {ORIGIN_DISCLOSURE}",
                st.cell_b,
            )
        )
    out.append(P(TIER_LIMIT, st.cell_b))
    return out


def _cover(data, san, st, P):
    c, g = data["cover"], data["generated"]
    ver = data["custody"]["verification"]
    story = [
        P("Nirikshan forensic DVR/NVR analysis report", st.title),
        P("COVER", st.h2),
        K.kv_table(
            san,
            st,
            [
                ("Case ID", c["case_id"]),
                ("Case number", c["case_number"]),
                ("Title", c["title"]),
                ("Description", _none(c["description"])),
                ("Examiner (case creator)", c["case_examiner"]),
                ("Case created (UTC)", c["case_created_at"]),
                ("Nirikshan version", c["tool_version"]),
                ("ffmpeg version", c["ffmpeg_version"]),
                ("Custody signing key id", c["signing_key_id"]),
                ("Report generated (UTC)", g["generated_at"]),
                (
                    "NTP status at generation",
                    g["ntp_status"]
                    + (
                        "  (clock synchronization could not be determined)"
                        if g["ntp_status"] == "unknown"
                        else ""
                    ),
                ),
                ("Report content hash", data["content_hash"]),
                ("Custody chain at generation", "VALID" if ver["ok"] else "FAILED"),
            ],
        ),  # fmt: skip
        K.Spacer(1, 6),
        *_origin_block(data, P, st),
        K.Spacer(1, 4),
        P(DISCLAIMER_CLOCK, st.note),
        K.Spacer(1, 4),
        P(
            "Report content hash = SHA-256 of the canonical JSON of the data this report is "
            "rendered from, excluding the generation time and NTP status. Two reports of the "
            "same database state have the same content hash.",
            st.note,
        ),
        K.Spacer(1, 4),
        P(
            "This report states what the tool recorded and computed. It makes no legal "
            "assertion. All validation behind it is on reference test data, i.e. synthetic "
            "images (see section 6).",
            st.note,
        ),
    ]
    return story


def _evidence(data, san, st, P):
    story = [P("1. EVIDENCE", st.h1)]
    if not data["evidence"]:
        return story + [P("No evidence has been acquired in this case.")]
    rows = []
    for e in data["evidence"]:
        rows.append(
            [
                e["id"],
                f"{e['label']}\nsource: {e['source_path']} ({e['source_type']})",
                f"MD5 {e['md5']}\nSHA-256\n{e['sha256'][:32]}\n{e['sha256'][32:]}",
                f"{_fmt_bytes(e['size_bytes'])} bytes",
                f"acquired {_sec(e['acquired_at'])}\nby {e['examiner']}\nstatus {e['status']}",
                f"{e['write_blocker_attested']} ({e['write_blocker_note']})",
                f"{e['last_verify_result']}"
                + (f" at {_sec(e['last_verified_at'])}" if e["last_verified_at"] else ""),
            ]
        )
    story.append(
        K.table(
            san, st,
            ["ID", "Label and source", "Hashes of the acquired image", "Size", "Acquisition",
             "Write blocker", "Last verified"],
            rows,
            [8 * K.mm, 33 * K.mm, 49 * K.mm, 16 * K.mm, 30 * K.mm, 28 * K.mm, 18 * K.mm],
        )
    )  # fmt: skip
    story += [
        K.Spacer(1, 4),
        P(
            "Hashes are those recorded at acquisition. The evidence images were NOT re-hashed "
            "while this report was generated; 'last verification' is the result of the most "
            "recent verify action stored in the database. Write blocker values are the "
            "examiner's attestation, not verified by the tool.",
            st.note,
        ),
    ]
    return story


def _custody(data, san, st, P):
    cu = data["custody"]
    v = cu["verification"]
    ok = v["ok"]
    banner = K.Table(
        [[P(f"CUSTODY CHAIN: {'VALID' if ok else 'FAILED'}", st.banner)]], colWidths=[W]
    )
    banner.setStyle(
        K.TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1),
                 K.colors.HexColor("#d6f0d6" if ok else "#f6c8c8")),
                ("BOX", (0, 0), (-1, -1), 1.2, K.colors.HexColor("#1b6e1b" if ok else "#9b1c1c")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )  # fmt: skip
    story = [
        P("2. CUSTODY CHAIN VERIFICATION", st.h1),
        banner,
        K.Spacer(1, 4),
        K.kv_table(
            san, st,
            [
                ("Verification", "re-run at report generation time (sequence, hash links, "
                 "recomputed hashes, Ed25519 signatures)"),
                ("Entries verified", v["entries"]),
                ("head_hash", v["head_hash"]),
                ("Signing key id", v["key_id"]),
                ("Public key (Ed25519, hex)", cu["public_key_hex"]),
                ("Failures", "none" if ok else f"{len(v['failures'])} (listed below)"),
            ],
        ),
        K.Spacer(1, 3),
        P(
            "RECORD THIS head_hash OUTSIDE THIS SYSTEM (for example in a signed hand-written "
            "note or a separate register). Deleting the newest custody entries leaves a shorter "
            "chain that still verifies; only an external record of head_hash and the entry "
            "count reveals that. The head_hash shown is the one BEFORE the report_generated "
            "entry for this report was appended; that entry then becomes the new head.",
            st.body,
        ),
    ]  # fmt: skip
    if not ok:
        story.append(
            K.table(
                san,
                st,
                ["Entry seq", "Failure reason"],
                [[f["seq"], f["reason"]] for f in v["failures"]],
                [24 * K.mm, 158 * K.mm],
            )  # fmt: skip
        )
    story.append(
        P("Custody log (times to the second, entry hashes as 16-character prefixes)", st.h2)
    )
    rows = [
        [
            r["seq"], _sec(r["timestamp_utc"]), r["action"], r["examiner"],
            _none(r["evidence_id"], "-"), r["ntp_status"], r["entry_hash"][:16],
        ]
        for r in cu["entry_rows"]
    ]  # fmt: skip
    story.append(
        K.table(
            san, st, ["Seq", "Time (UTC)", "Action", "Examiner", "Evid.", "NTP", "entry_hash"],
            rows,
            [10 * K.mm, 34 * K.mm, 36 * K.mm, 40 * K.mm, 10 * K.mm, 20 * K.mm, 32 * K.mm],
        )
    )  # fmt: skip
    story.append(
        P(
            "The API audit trail (every request, with the examiner attestation) is stored "
            "separately and is not part of this report.",
            st.note,
        )
    )
    return story


def _kv_rows(pairs):
    return [[k, v] for k, v in pairs]


def _clip_table(san, st, P, clips, total):
    story = []
    cols = ["ID", "Engine", "Codec / ch.", "Offsets (start-end)", "Size", "Decode",
            "Nominal", "Frames"]  # fmt: skip
    w = [10, 30, 18, 52, 22, 20, 17, 13]
    rows = []
    style = []
    for i, c in enumerate(clips):
        r0 = 1 + 2 * i
        rows.append(
            [
                c["id"], c["engine"],
                f"{c['codec']} / {_none(c['channel'], '-')}",
                f"{c['start_offset']} - {c['end_offset']}"
                + (f"\n({c['extent_count']} extents, reassembled)" if c["reassembled"]
                   else (f"\n({c['extent_count']} extents)" if c["extent_count"] > 1 else "")),
                _fmt_bytes(c["size_bytes"]), c["decode_status"],
                _none(None if c["duration_s_nominal"] is None
                      else f"{c['duration_s_nominal']:.2f} s", "-"),
                _none(c["frames"], "-"),
            ]
        )  # fmt: skip
        rows.append(
            [
                K.para(
                    san,
                    f"bitstream SHA-256 {c['bitstream_sha256'] or 'none'}   |   "
                    f"MP4 SHA-256 {c['mp4_sha256'] or 'none'}",
                    st.cell,
                ),
                "", "", "", "", "", "", "",
            ]
        )  # fmt: skip
        style.append(("SPAN", (0, r0 + 1), (-1, r0 + 1)))
    story.append(K.table(san, st, cols, rows, [x * K.mm for x in w], extra=style))
    if total > len(clips):
        story.append(
            P(f"Table truncated: {len(clips)} of {total} clips shown; all are in the database.",
              st.note)
        )  # fmt: skip
    story.append(P(NOMINAL_NOTE, st.note))
    return story


def _runs(data, san, st, P):
    story = [P("3. CARVE RUNS", st.h1)]
    if not data["runs"]:
        return story + [P("No carve run exists for this case.")]
    for r in data["runs"]:
        story.append(P(f"Run {r['id']} (evidence {r['evidence_id']}), status {r['status']}", st.h2))
        story.append(
            K.kv_table(
                san,
                st,
                [
                    ("Run by", r["examiner"]),
                    ("Started / finished (UTC)", f"{r['started_at']} / {_none(r['finished_at'])}"),
                    ("Tool / ffmpeg", f"{r['tool_version']} / {r['ffmpeg_version']}"),
                    ("Error", _none(r["error"])),
                    (
                        "Counts",
                        "; ".join(
                            f"{k}={v}"
                            for k, v in r["stats"]
                            if k
                            in (
                                "clips",
                                "orphans",
                                "ok",
                                "decode_errors",
                                "export_failed",
                                "bytes_scanned",
                            )
                        ),
                    ),
                ],
            )  # fmt: skip
        )
        story.append(P("Options and parameters used", st.h2))
        story.append(
            K.table(
                san, st, ["Name", "Value"], r["params"] or [["(none)", ""]], [70 * K.mm, 112 * K.mm]
            )  # fmt: skip
        )
        story.append(P("Vendor identification", st.h2))
        if r["vendor_matches"]:
            rows = [
                [
                    m["vendor"], f"Tier {m['tier']}", m["confidence"],
                    "; ".join(m["notes"]) or "none",
                    "; ".join(f"{k}={v}" for k, v in m["signature_counts"]),
                ]
                for m in r["vendor_matches"]
            ]  # fmt: skip
            story.append(
                K.table(
                    san,
                    st,
                    ["Vendor", "Tier", "Confidence", "Caveats / notes", "Signature hits"],
                    rows,
                    [26 * K.mm, 14 * K.mm, 20 * K.mm, 82 * K.mm, 40 * K.mm],
                )  # fmt: skip
            )
            story.append(
                P("Confidence is bounded by the tier: the tool never reports 'high' because no "
                  "vendor is validated on real device images.", st.note)
            )  # fmt: skip
        else:
            story.append(P("No vendor signature matched: generic carving only."))
        for p in r["parsers"]:
            story += _parser(p, san, st, P)
        cc = r["clip_field_counts"]
        story.append(
            P(f"Clip-level parser fields across this run: parsed {cc['parsed']}, inferred "
              f"{cc['inferred']}, unknown {cc['unknown']}.", st.small)
        )  # fmt: skip
        story.append(P(f"Carved clips ({r['clips_total']})", st.h2))
        if r["clips"]:
            story += _clip_table(san, st, P, r["clips"], r["clips_total"])
        else:
            story.append(P("No clips were carved in this run."))
        story.append(P("FAILED DECODES, EXPORT FAILURES AND ORPHANS", st.h2))
        if r["failed"]:
            rows = [
                [f["id"], f["engine"], f["decode_status"],
                 clip_text("; ".join([x for x in [f["error"], *f["decode_errors"]] if x]) or "-",
                           500),
                 f"{f['start_offset']} - {f['end_offset']}"]
                for f in r["failed"]
            ]  # fmt: skip
            story.append(
                K.table(
                    san,
                    st,
                    ["Clip", "Engine", "Status", "Error / decoder messages", "Offsets"],
                    rows,
                    [12 * K.mm, 28 * K.mm, 24 * K.mm, 82 * K.mm, 36 * K.mm],
                )  # fmt: skip
            )
            story.append(
                P(f"{r['failed_total']} clip(s) did not export or decode cleanly. They are "
                  "listed, not hidden; do not rely on their video.", st.note)
            )  # fmt: skip
        else:
            story.append(P("No failed decode or export failure in this run."))
        if r["orphans"]:
            rows = [
                [o["id"], o["engine"], _none(o["channel"], "-"),
                 f"{o['start_offset']} - {o['end_offset']}", _fmt_bytes(o["size_bytes"]),
                 o["reason"]]
                for o in r["orphans"]
            ]  # fmt: skip
            story.append(
                K.table(san, st, ["Orphan", "Engine", "Ch.", "Offsets", "Size", "Why orphaned"],
                        rows, [14 * K.mm, 26 * K.mm, 10 * K.mm, 44 * K.mm, 22 * K.mm, 66 * K.mm])
            )  # fmt: skip
            if r["orphans_total"] > len(r["orphans"]):
                story.append(P(f"Truncated: {len(r['orphans'])} of {r['orphans_total']} orphans "
                               "shown.", st.note))  # fmt: skip
        else:
            story.append(P("No orphan ranges in this run."))
    return story


def _parser(p, san, st, P):
    c = p["image_field_counts"]
    story = [
        P(f"Parser {p['parser']} ({p['vendor']}, Tier {p['tier']}): status {p['status']}", st.h2),
        P(f"Image-level fields: parsed {c['parsed']}, inferred {c['inferred']}, "
          f"unknown {c['unknown']}. A field is 'parsed' only when read directly from bytes the "
          "public source documents; 'inferred' and 'unknown' fields are not facts about the "
          "device.", st.small),
    ]  # fmt: skip
    if p["options"]:
        story.append(K.table(san, st, ["Parser option (value used)", "Value"], p["options"],
                             [70 * K.mm, 112 * K.mm]))  # fmt: skip
    story.append(P("OPEN SOURCE CONFLICTS (exposed, not resolved)", st.h2))
    rows = [[x["name"], x["status"], x["value"]] for x in p["open_source_conflicts"]]
    rows += [["documented conflict", "-", t] for t in p["documented_source_conflicts"]]
    if rows:
        story.append(K.table(san, st, ["Name", "Status", "Content"], rows,
                             [42 * K.mm, 16 * K.mm, 124 * K.mm]))  # fmt: skip
    else:
        story.append(P("No conflict fields were emitted by this parser for this run."))
    cc = p["crosscheck"]
    story.append(
        P(f"Cross-check against the generic carver: parser clips {_none(cc['parser_clips'], '-')}"
          f", generic clips {_none(cc['generic_clips'], '-')}, DISAGREEMENTS "
          f"{cc['disagreements']}"
          + (" (" + "; ".join(f"{k}: {n}" for k, n in cc["by_kind"]) + ")"
             if cc["by_kind"] else "") + ".", st.body)
    )  # fmt: skip
    if p["inconsistencies"]:
        story.append(P("Parser inconsistencies: " + " | ".join(p["inconsistencies"]), st.small))
    if p["warnings"]:
        story.append(P("Parser warnings: " + " | ".join(p["warnings"]), st.small))
    return story


def _ts_cell(rec):
    if not rec:
        return "no record"
    return (f"raw {rec['raw']} ({rec['field']}, {rec['format']}, offset {rec['offset']})\n"
            f"as stored: {_none(rec['wall_clock_as_stored'], 'n/a')}")  # fmt: skip


def _timestamps(data, san, st, P):
    ts = data["timestamps"]
    story = [P("4. TIMESTAMPS", st.h1)]
    story.append(
        P("Clock readings stored by a recorder are not facts about real time. Timezone and "
          "epoch basis are examiner assumptions; none is defaulted. Raw values are shown "
          "exactly as read.", st.note)
    )  # fmt: skip
    story.append(P("Timezone assumption per evidence", st.h2))
    if not ts["evidence"]:
        story.append(P("No evidence in this case."))
    for e in ts["evidence"]:
        pairs = [
            ("Evidence", f"{e['evidence_id']} ({e['label']})"),
            ("Timezone status", e["tz_status"]),
            ("Assumed timezone", _none(e["timezone"], "NONE (unknown)")),
            ("Epoch basis", _none(e["epoch_basis"], "NONE (unknown)")),
            ("Basis of the assumption", _none(e["evidence_kind"], "n/a")),
            ("Evidence notes (examiner)", _none(e["notes"], "none recorded")),
            ("Entered by / at", f"{_none(e['set_by'], 'n/a')} / {_none(e['updated_at'], 'n/a')}"),
        ]
        story.append(K.kv_table(san, st, pairs))
        story.append(K.Spacer(1, 3))
        if e["references"]:
            story.append(
                K.table(san, st, ["Ref", "Device clock reading (no zone)", "True time UTC",
                                  "Method", "Uncert. (s)", "Notes"],
                        [[r["id"], r["device_time_raw"], r["true_time_utc"], r["method"],
                          r["reading_uncertainty_s"], r["notes"]] for r in e["references"]],
                        [10 * K.mm, 36 * K.mm, 40 * K.mm, 26 * K.mm, 14 * K.mm, 56 * K.mm])
            )  # fmt: skip
        else:
            story.append(P("Reference observations: none recorded.", st.small))
        m = e["model"]
        if m:
            story.append(
                P(
                    f"Drift model {m['id']}: method {m['method']}, n={m['n']}, offset "
                    f"{m['offset_s']:.3f} s (95% CI {m['offset_ci_s'][0]:.3f} to "
                    f"{m['offset_ci_s'][1]:.3f}), drift {m['drift_ppm']:.2f} ppm"
                    + (" (ASSUMED zero, not measured)" if m["drift_assumed_zero"] else "")
                    + f", usable={m['usable']}. Assumptions: "
                    + (" | ".join(m["assumptions"]) or "none")
                    + ". Warnings: " + (" | ".join(m["warnings"]) or "none") + ".",
                    st.small,
                )
            )  # fmt: skip
        else:
            story.append(P("Drift model: none fitted; no corrected intervals exist.", st.small))
    story.append(P("PLACED TIMELINE", st.h2))
    if ts["placed"]:
        rows = []
        for p in ts["placed"]:
            s = p["start_record"] or {}
            rows.append(
                [
                    p["order"], f"clip {p['clip_id']}",
                    f"ev {p['evidence_id']} / ch {_none(p['channel'], '-')}",
                    _ts_cell(p["start_record"]),
                    (f"{_none(s.get('assumed_timezone'), 'n/a')} "
                     f"({_none(s.get('epoch_basis'), 'n/a')})"),
                    _interval(s.get("utc_lo"), s.get("utc_hi")),
                    ("none (no drift model)" if not s.get("corrected_utc_lo")
                     else _interval(s.get("corrected_utc_lo"), s.get("corrected_utc_hi"))),
                    ", ".join(p["flags"]) or "-",
                ]
            )  # fmt: skip
        story.append(
            K.table(san, st, ["#", "Clip", "Source", "Raw start timestamp", "Zone (basis)",
                              "UTC uncorrected", "UTC corrected", "Flags"], rows,
                    [x * K.mm for x in [7, 11, 16, 36, 20, 34, 36, 22]])
        )  # fmt: skip
        story.append(
            P(f"Order rule: {ts['tie_break']}. The order is a presentation order, not a claim "
              "about which event came first when uncertainty intervals overlap.", st.note)
        )  # fmt: skip
        if ts["placed_total"] > len(ts["placed"]):
            story.append(P(f"Truncated: {len(ts['placed'])} of {ts['placed_total']} shown.",
                           st.note))  # fmt: skip
    else:
        story.append(P("No clip could be placed on a UTC axis."))
    story.append(P("UNPLACEABLE CLIPS (no UTC value computed, never placed)", st.h2))
    if ts["unplaceable"]:
        rows = [
            [f"clip {p['clip_id']}", f"ev {p['evidence_id']} / ch {_none(p['channel'], '-')}",
             p["reason"], _ts_cell(p["start_record"])]
            for p in ts["unplaceable"]
        ]  # fmt: skip
        story.append(
            K.table(
                san,
                st,
                ["Clip", "Source", "Reason it is unplaceable", "Raw value (as stored, no zone)"],
                rows,
                [14 * K.mm, 24 * K.mm, 84 * K.mm, 60 * K.mm],
            )  # fmt: skip
        )
        if ts["unplaceable_total"] > len(ts["unplaceable"]):
            story.append(P(f"Truncated: {len(ts['unplaceable'])} of {ts['unplaceable_total']} "
                           "shown.", st.note))  # fmt: skip
    else:
        story.append(P("None: every clip with a metadata timestamp could be placed."))
    story.append(
        P(f"Gaps reported: {ts['gaps_total']}; overlaps reported: {ts['overlaps_total']} (full "
          "lists via the timeline export of the application). Flag meanings: "
          + " ".join(f"{k}: {v}" for k, v in ts["flag_help"].items()), st.small)
    )  # fmt: skip
    return story


def _analytics(data, san, st, P):
    story = [P("5. ANALYTICS", st.h1)]
    runs = data["analytics"]
    if not runs:
        return story + [P("No analytics run exists for this case.")]
    story.append(
        P("Every result below is a lead for a human examiner. It is NOT an identification of any "
          "person or object. Times are nominal (frame index / stream frame rate), not recording "
          "time.", st.note)
    )  # fmt: skip
    for a in runs:
        story.append(P(f"Analytics run {a['id']}: {a['kind']} on clip {a['clip_id']}", st.h2))
        story.append(P(f"Result label: {TRIAGE_LABEL}", st.banner))
        if a["label"] != TRIAGE_LABEL:
            story.append(P(f"WARNING: stored label differs from the required label: {a['label']}"))
        m = a["model"]
        pairs = [
            ("Status", a["status"]),
            ("Run by / started", f"{a['examiner']} / {a['started_at']}"),
            ("Clip hashes", f"bitstream SHA-256 {a['bitstream_sha256']}; "
                            f"MP4 SHA-256 {a['mp4_sha256']}"),
            ("Model", (f"{m['name']} {m['version']}; licence {m['licence']}; "
                       f"SHA-256 {m['sha256']}") if m else "none (frame-difference method, "
                                                           "no learned model)"),
            ("Parameters", "; ".join(f"{k}={v}" for k, v in a["params"])),
            ("Frames analysed / results", f"{a['frames_analysed']} / {a['result_count']}"),
            ("Tool versions", "; ".join(f"{k}={v}" for k, v in a["tool"])),
            ("Error", _none(a["error"])),
        ]  # fmt: skip
        story.append(K.kv_table(san, st, pairs))
        s = a["summary"]
        if a["kind"] == "motion":
            story.append(P(f"Motion intervals: {s.get('intervals_total', 0)}", st.small))
            if s.get("intervals"):
                story.append(
                    K.table(san, st, ["Frames", "Nominal start-end (s)", "Peak score"],
                            [[f"{i[0]}-{i[1]}", f"{i[2]:.2f} - {i[3]:.2f}", f"{i[4]:.3f}"]
                             for i in s["intervals"]], [40 * K.mm, 60 * K.mm, 40 * K.mm])
                )  # fmt: skip
        else:
            story.append(P(f"Detections: {s.get('detections_total', 0)}", st.small))
            if s.get("by_class"):
                story.append(
                    K.table(san, st, ["Class", "Count", "Max confidence", "Nominal first-last (s)"],
                            [[c[0], c[1], f"{c[2]:.3f}", f"{c[3]:.2f} - {c[4]:.2f}"]
                             for c in s["by_class"]], [40 * K.mm, 20 * K.mm, 30 * K.mm, 50 * K.mm])
                )  # fmt: skip
        er = a["error_rates"]
        story.append(P("Measured error rates and their data source", st.h2))
        if er and er["configs"]:
            rows = [
                [c.get("condition", ""), _none(c.get("class"), "-"),
                 _none(c.get("confidence_threshold"), "-"), _none(c.get("n_images"), "-"),
                 f"tp {c.get('tp')} fp {c.get('fp')} fn {c.get('fn')}",
                 f"P {c.get('precision')} R {c.get('recall')}",
                 f"{c.get('dataset')} [{c.get('label')}]"]
                for c in er["configs"]
            ]  # fmt: skip
            story.append(
                K.table(san, st, ["Condition", "Class", "Conf.", "N", "Counts", "Rates",
                                  "Data source (as recorded)"], rows,
                        [x * K.mm for x in [20, 14, 11, 11, 28, 28, 70]])
            )  # fmt: skip
            story.append(
                P(f"Run threshold equals a measured one: {er['run_threshold_measured']}; run "
                  f"parameters match the measured ones: {er['run_params_match_measured']}. "
                  f"Not measured: {er['unmeasured_note']}", st.small)
            )  # fmt: skip
        else:
            story.append(P("No measured error rates are recorded for this run: treat the "
                           "reliability as unknown."))  # fmt: skip
    return story


def _limitations(data, san, st, P):
    lim = data["limitations"]
    fa = lim["reassembler"]
    fa_txt = (
        f"The H.264 fragment reassembly heuristic (off by default; clips joined by it are "
        f"labelled) falsely accepted {fa['k']} of {fa['n']} wrong join candidates "
        f"({fa['rate'] * 100:.1f}%, 95% CI {fa['ci95'][0] * 100:.1f}-{fa['ci95'][1] * 100:.1f}%) "
        f"in the scenario {fa['scenario']} of the committed baseline ({fa['source']}); this "
        "figure is itself from synthetic images."
        if fa["available"]
        else f"The false-accept rate of the fragment reassembly heuristic could not be read: "
        f"{fa['reason']}. It must be treated as unknown here (the project documentation "
        "reports it from the committed validation baseline)."
    )
    items = [
        "All validation of this tool was done on SYNTHETIC images generated by its own "
        "harness. No result here has been validated on a real DVR/NVR image or device.",
        "Parser-versus-same-layout results are circular: the synthetic layouts and the parsers "
        "come from the same public documents. They show the code follows those documents, not "
        "that real recorders follow them.",
        "Tiers recorded in this report: "
        + (
            ", ".join("Tier " + t for t in lim["tiers_in_this_report"])
            or "none (no vendor matched)"
        )
        + f". The code defines tiers {', '.join(lim['tiers_defined_in_code'])} only; no vendor "
        "is above Tier B (Tier A requires validation on real images, which has not been done).",
        "There was no validation on real devices: no claim is made about any specific "
        "recorder model or firmware.",
        "A clean decode status ('ok') shows that ffmpeg decoded the carved bitstream without "
        "reported errors. It does not prove the bytes are the original recording, nor that the "
        "picture content is complete or unaltered.",
        fa_txt,
        "Durations are nominal (frames / stream frame rate). They are not recording times.",
        "Timezone and epoch basis are examiner assumptions where they exist; clips without one "
        "are listed as unplaceable and are never placed by default.",
        "Examiner identity is an attestation (X-Examiner header), not authentication. The "
        "custody chain detects tampering; it does not prevent it, and anyone holding the "
        "signing key could forge entries. Truncation of the newest entries is detected only by "
        "comparing with an externally recorded head_hash.",
        "Analytics output is triage, not identification, and its error rates were measured on "
        "public benchmark or synthetic data that will not transfer to DVR footage.",
        "This report asserts nothing legal. It does not state that any evidence is admissible, "
        "that any procedure complies with any law or standard, or that any certificate "
        "requirement is satisfied.",
    ]
    story = [K.PageBreak(), P("6. LIMITATIONS", st.h1)]
    for i, t in enumerate(items, 1):
        story.append(P(f"{i}. {t}", st.body))
        story.append(K.Spacer(1, 3))
    story.append(K.PageBreak())
    return story


def _colophon(data, san, st, P):
    libs = data["cover"]["libraries"]
    return [
        P("7. COLOPHON AND HOW TO VERIFY THIS REPORT", st.h1),
        K.kv_table(
            san,
            st,
            [
                ("Report format version", data["report_format"]),
                (
                    "PDF library",
                    f"ReportLab {libs['reportlab']['version']}, licence "
                    f"{libs['reportlab']['licence']} (offline; no network access "
                    "during generation)",
                ),
                ("Font", f"{libs['font']['name']}; licence: {libs['font']['licence']}"),
                ("Character coverage", libs["font"]["scope"]),
                (
                    "Reproducibility",
                    "ReportLab invariant mode with fixed metadata: the same "
                    "data and the same generation time give byte-identical "
                    "PDF files.",
                ),
                ("Report content hash", data["content_hash"]),
                (
                    "head_hash used",
                    data["custody"]["verification"]["head_hash"]
                    + "  (before the report_generated entry)",
                ),
            ],
        ),  # fmt: skip
        K.Spacer(1, 6),
        P("How to verify", st.h2),
        P(
            "1. Compute the SHA-256 of this PDF file and compare it with the 'sha256' in the "
            "custody entry 'report_generated' (API: GET /api/cases/{id}/custody) and in the "
            "report list. A report cannot contain its own file hash.",
            st.body,
        ),
        P(
            "2. Run 'Verify chain and signatures' and compare head_hash and entry count with your "
            "external record. The report's head_hash is the chain state immediately before the "
            "report_generated entry; the entry itself records that same value as the head it "
            "was built from.",
            st.body,
        ),
        P(
            "3. Compare the hashes in section 1 with an independent hash of the acquired image "
            "(for example sha256sum), and the clip hashes in section 3 with the exported files.",
            st.body,
        ),
        P(
            "4. The downloaded report is re-hashed by the server on every download; a mismatch "
            "with the recorded hash is refused with HTTP 409.",
            st.body,
        ),
    ]
