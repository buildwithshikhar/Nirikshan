"""Cross-camera / cross-evidence timeline (P5).

Each clip becomes an interval whose start and end carry uncertainty bars taken from the
timestamp records (resolution, DST ambiguity envelope) and, when a drift model exists, the
corrected interval (both are always reported; the axis uses the corrected one if present).

Rules:
  * Items whose start cannot be placed (timezone unknown, DST gap, invalid date, no metadata
    timestamp) go to `unplaceable` with the reason; they are NEVER put on the axis by default.
  * Deterministic order (tie-break rule): sort by
        (nominal start, nominal end, evidence_id, channel [None last], clip_id)
    where nominal = midpoint of the plotted uncertainty interval, compared at microsecond
    resolution. Equal nominal times therefore order by evidence, then channel, then clip id.
    The order is a presentation order, NOT a claim about which event came first when the
    uncertainty bars overlap (`ambiguous_order_with` lists such neighbours).
  * Gaps are computed per (evidence, channel): next.start - prev.end between consecutive items
    in that order. Reported when the nominal gap exceeds `min_gap_s`; `certain` is true only if
    the uncertainty bars also leave a positive gap (next.start_lo > prev.end_hi).
  * Overlaps are reported for items on different (evidence, channel) pairs, and as
    `same_channel` for items on one channel (anomaly). `certain` only if the inner bounds
    overlap (max(start_hi) < min(end_lo)).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from app.timeline.timestamps import (
    DST_GAP,
    INVALID_DATE,
    TZ_UNKNOWN,
    TimestampRecord,
    iso,
)

DEFAULT_MIN_GAP_S = 1.0
TIE_BREAK = (
    "nominal start, nominal end, evidence_id, channel (None last), clip_id; "
    "nominal = midpoint of the plotted uncertainty interval"
)


def _role(rec: TimestampRecord) -> str:
    f = rec.field.lower()
    if "first" in f or "start" in f:
        return "start"
    if "last" in f or "end" in f:
        return "end"
    return ""


def pick_start_end(
    records: list[TimestampRecord],
) -> tuple[TimestampRecord | None, TimestampRecord | None]:
    """Start/end records by field-name role; otherwise earliest/latest raw of the same format."""
    if not records:
        return None, None
    starts = [r for r in records if _role(r) == "start"]
    ends = [r for r in records if _role(r) == "end"]
    if not starts and not ends:
        same = [r for r in records if r.format == records[0].format]
        try:
            same.sort(key=lambda r: int(r.raw))  # type: ignore[call-overload]
        except (TypeError, ValueError):
            pass
        return same[0], (same[-1] if len(same) > 1 else None)
    s = min(starts, key=lambda r: int(r.raw)) if starts else None  # type: ignore[call-overload]
    e = max(ends, key=lambda r: int(r.raw)) if ends else None  # type: ignore[call-overload]
    return s, e


def _plot(rec: TimestampRecord) -> tuple[datetime, datetime] | None:
    if rec.corrected_utc_lo is not None and rec.corrected_utc_hi is not None:
        return rec.corrected_utc_lo, rec.corrected_utc_hi
    if rec.utc_lo is not None and rec.utc_hi is not None:
        return rec.utc_lo, rec.utc_hi
    return None


def unplaceable_reason(rec: TimestampRecord | None) -> str:
    if rec is None:
        return "no metadata timestamp for this clip (generic carve or parser gave none)"
    if TZ_UNKNOWN in rec.flags:
        return (
            "timezone / epoch basis unknown for this evidence: no examiner assumption entered "
            "(never defaulted)"
        )
    if DST_GAP in rec.flags:
        return (
            f"local time {rec.wall_clock_as_stored} does not exist in "
            f"{rec.assumed_timezone} (DST gap)"
        )
    if INVALID_DATE in rec.flags:
        return "timestamp is not a valid date/time: " + "; ".join(rec.notes)
    return "timestamp could not be placed: " + "; ".join(rec.notes or ["unknown reason"])


def _mid(lo: datetime, hi: datetime) -> datetime:
    return lo + (hi - lo) / 2


def _us(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds()


def build_timeline(items: list[dict], min_gap_s: float = DEFAULT_MIN_GAP_S) -> dict:
    """items: {clip_id, evidence_id, channel, engine, duration_s, records, osd, tz_status,
    drift_model_id}. Returns placed / unplaceable / gaps / overlaps (JSON-ready)."""
    placed: list[dict] = []
    unplaceable: list[dict] = []
    for it in items:
        s_rec, e_rec = pick_start_end(it.get("records", []))
        base = {
            "clip_id": it["clip_id"],
            "evidence_id": it["evidence_id"],
            "channel": it.get("channel"),
            "engine": it.get("engine", ""),
            "osd": it.get("osd"),
            "drift_model_id": it.get("drift_model_id"),
            "start_record": s_rec.to_dict() if s_rec else None,
            "end_record": e_rec.to_dict() if e_rec else None,
            "flags": sorted({f for r in (s_rec, e_rec) if r for f in r.flags}),
            "tz_status": s_rec.tz_status if s_rec else it.get("tz_status", "unknown"),
        }
        sp = _plot(s_rec) if s_rec else None
        if sp is None:
            unplaceable.append({**base, "reason": unplaceable_reason(s_rec)})
            continue
        ep = _plot(e_rec) if e_rec else None
        end_note = ""
        if ep is None:
            dur = it.get("duration_s")
            if dur:
                ep = (sp[0] + timedelta(seconds=dur), sp[1] + timedelta(seconds=dur))
                end_note = "end = start + exported media duration (not a metadata timestamp)"
            else:
                ep = sp
                end_note = "end unknown: drawn as a point at the start"
            if e_rec is not None and not _plot(e_rec):
                end_note += f"; end timestamp unplaceable: {unplaceable_reason(e_rec)}"
        placed.append(
            {
                **base,
                "start": {"lo": iso(sp[0]), "hi": iso(sp[1])},
                "end": {"lo": iso(ep[0]), "hi": iso(ep[1])},
                "end_note": end_note,
                "_s": sp,
                "_e": ep,
                "_ns": _mid(*sp),
                "_ne": _mid(*ep),
            }
        )
    placed.sort(
        key=lambda p: (
            p["_ns"],
            p["_ne"],
            p["evidence_id"],
            p["channel"] is None,
            p["channel"] if p["channel"] is not None else 0,
            p["clip_id"],
        )
    )
    for n, p in enumerate(placed, start=1):
        p["order"] = n
        p["ambiguous_order_with"] = []
    # bars that overlap at the start make the relative order uncertain (report, do not resolve)
    for i, a in enumerate(placed):
        for b in placed[i + 1 :]:
            if b["_s"][0] > a["_s"][1]:
                break
            a["ambiguous_order_with"].append(b["clip_id"])
            b["ambiguous_order_with"].append(a["clip_id"])

    gaps: list[dict] = []
    groups: dict[tuple, list[dict]] = {}
    for p in placed:
        groups.setdefault((p["evidence_id"], p["channel"]), []).append(p)
    for (ev, ch), seq in sorted(
        groups.items(), key=lambda kv: (kv[0][0], kv[0][1] is None, kv[0][1] or 0)
    ):
        for a, b in zip(seq, seq[1:], strict=False):
            nominal = _us(b["_ns"], a["_ne"])
            if nominal > min_gap_s:
                lo = _us(b["_s"][0], a["_e"][1])
                hi = _us(b["_s"][1], a["_e"][0])
                gaps.append(
                    {
                        "evidence_id": ev,
                        "channel": ch,
                        "after_clip_id": a["clip_id"],
                        "before_clip_id": b["clip_id"],
                        "from": iso(a["_ne"]),
                        "to": iso(b["_ns"]),
                        "gap_s_nominal": nominal,
                        "gap_s_min": lo,
                        "gap_s_max": hi,
                        "certain": lo > 0,
                    }
                )
    overlaps: list[dict] = []
    for i, a in enumerate(placed):
        for b in placed[i + 1 :]:
            if b["_ns"] >= a["_ne"]:
                break  # sorted by nominal start: no later item overlaps a nominally
            nom = _us(min(a["_ne"], b["_ne"]), max(a["_ns"], b["_ns"]))
            if nom <= 0:
                continue
            inner = _us(min(a["_e"][0], b["_e"][0]), max(a["_s"][1], b["_s"][1]))
            same = (a["evidence_id"], a["channel"]) == (b["evidence_id"], b["channel"])
            overlaps.append(
                {
                    "type": "same_channel" if same else "cross_channel",
                    "a_clip_id": a["clip_id"],
                    "b_clip_id": b["clip_id"],
                    "a": {"evidence_id": a["evidence_id"], "channel": a["channel"]},
                    "b": {"evidence_id": b["evidence_id"], "channel": b["channel"]},
                    "overlap_s_nominal": nom,
                    "overlap_s_certain": max(0.0, inner),
                    "certain": inner > 0,
                }
            )
    for p in placed:
        for k in ("_s", "_e", "_ns", "_ne"):
            del p[k]
    return {
        "tie_break": TIE_BREAK,
        "min_gap_s": min_gap_s,
        "placed": placed,
        "unplaceable": unplaceable,
        "gaps": gaps,
        "overlaps": overlaps,
        "counts": {
            "placed": len(placed),
            "unplaceable": len(unplaceable),
            "gaps": len(gaps),
            "overlaps": len(overlaps),
        },
    }


EXPORT_COLUMNS = [
    "clip_id", "evidence_id", "channel", "engine", "placement", "unplaceable_reason", "order",
    "tz_status", "flags", "drift_model_id",
    *[
        f"{w}_{c}"
        for w in ("start", "end")
        for c in (
            "raw", "field", "format", "offset", "wall_clock_as_stored", "assumed_timezone",
            "tz_evidence", "epoch_basis", "flags", "conflict_note", "utc_lo", "utc_hi",
            "corrected_utc_lo", "corrected_utc_hi",
        )
    ],
    "plot_start_lo", "plot_start_hi", "plot_end_lo", "plot_end_hi", "end_note",
    "osd_status", "osd_median_delta_s", "osd_mad_s", "osd_readable", "osd_tolerance_s",
    "ambiguous_order_with",
]  # fmt: skip


def _row(it: dict, placement: str) -> dict:
    row = {
        "clip_id": it["clip_id"],
        "evidence_id": it["evidence_id"],
        "channel": "" if it["channel"] is None else it["channel"],
        "engine": it["engine"],
        "placement": placement,
        "unplaceable_reason": it.get("reason", ""),
        "order": it.get("order", ""),
        "tz_status": it["tz_status"],
        "flags": ";".join(it["flags"]),
        "drift_model_id": "" if it["drift_model_id"] is None else it["drift_model_id"],
        "end_note": it.get("end_note", ""),
        "ambiguous_order_with": ";".join(str(x) for x in it.get("ambiguous_order_with", [])),
    }
    for w in ("start", "end"):
        rec = it.get(f"{w}_record") or {}
        for c in (
            "raw", "field", "format", "offset", "wall_clock_as_stored", "assumed_timezone",
            "tz_evidence", "epoch_basis", "conflict_note", "utc_lo", "utc_hi",
            "corrected_utc_lo", "corrected_utc_hi",
        ):  # fmt: skip
            v = rec.get(c)
            row[f"{w}_{c}"] = "" if v is None else v
        row[f"{w}_flags"] = ";".join(rec.get("flags", []))
        if w in it:
            row[f"plot_{w}_lo"], row[f"plot_{w}_hi"] = it[w]["lo"], it[w]["hi"]
    osd = it.get("osd") or {}
    row["osd_status"] = osd.get("status", "")
    for k, col in (
        ("median_delta_s", "osd_median_delta_s"),
        ("mad_s", "osd_mad_s"),
        ("readable", "osd_readable"),
        ("tolerance_s", "osd_tolerance_s"),
    ):
        v = osd.get(k)
        row[col] = "" if v is None else v
    return row


def export_csv(tl: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for it in tl["placed"]:
        w.writerow(_row(it, "placed"))
    for it in tl["unplaceable"]:
        w.writerow(_row(it, "unplaceable"))
    return buf.getvalue()
