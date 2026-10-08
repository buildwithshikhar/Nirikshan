"""SYNTHETIC demo data, built through the public HTTP API (used by `make demo` / `make demo-data`).

Everything here is labelled SYNTHETIC: case title, evidence labels, console output. The three
images are produced by the validation harness builders (per-paper vendor layouts, not real
device images; every image starts with the 256-byte NIRIKSHAN SYNTHETIC banner). The Hikvision
and Dahua parsers are written from the same documents as these layouts, so parsing them is a
circular self-consistency check, not validation against real DVR/NVR images.

The API is reached through a tiny `Api` protocol (`call(method, path, body) -> (status, json)`),
implemented over urllib for the real server and over a TestClient in the tests.
"""

import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEMO_CASE_NUMBER = "DEMO-SYNTHETIC-001"
DEMO_CASE_TITLE = "SYNTHETIC demo case: generated test images, not real DVR data"
DEMO_EXAMINER = "Demo Examiner (SYNTHETIC)"
SEED = 20260101

# Invented device-clock numbers for the SYNTHETIC demo; not measurements of anything.
HIK_TZ = "Asia/Kolkata"
DHAV_REFERENCES = [
    ("2025-06-01 12:00:00", "2025-06-01T06:30:30Z"),
    ("2025-06-01 14:00:00", "2025-06-01T08:30:31Z"),
]


@dataclass
class DemoImage:
    key: str  # hikvision | dahua | raw
    label: str
    path: Path
    layout: str


def build_images(out_dir: Path, seed: int = SEED) -> list[DemoImage]:
    """Write the three SYNTHETIC images into out_dir (needs ffmpeg for the test streams)."""
    from app.validation import layouts_hikvision
    from app.validation.image import Builder
    from app.validation.layouts import LAYOUT_DHAV, LAYOUT_RAW
    from app.validation.streams import StreamPool, pick

    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    pool = StreamPool()

    hik = layouts_hikvision.clean_live(rng, pool, 0)

    dhav = Builder(rng, LAYOUT_DHAV)
    dhav.noise(2048)
    for i, s in enumerate(pick(rng, pool, 2, "h264")):
        dhav.clip(f"d{i}", s, channel=1 + i)
        dhav.place(f"d{i}")
        dhav.zeros(4096)

    raw = Builder(rng, LAYOUT_RAW)
    raw.zeros(2048)
    for i, s in enumerate(pick(rng, pool, 2, "h264")):
        raw.clip(f"r{i}", s)
        raw.place(f"r{i}")
        raw.zeros(4096)

    plan = [
        ("hikvision", "SYNTHETIC Hikvision per-paper layout", hik, layouts_hikvision.LAYOUT),
        ("dahua", "SYNTHETIC Dahua DHAV per-paper layout", dhav, LAYOUT_DHAV),
        ("raw", "SYNTHETIC raw H.264 image (no vendor structures)", raw, LAYOUT_RAW),
    ]
    images = []
    for key, label, builder, layout in plan:
        data, _truth = builder.build()
        path = out_dir / f"synthetic_{key}.dd"
        path.write_bytes(data)
        images.append(DemoImage(key, label, path, layout))
    return images


# ---- API access --------------------------------------------------------------------------------
class UrlApi:
    def __init__(self, base: str, examiner: str = DEMO_EXAMINER, timeout: float = 600.0):
        self.base, self.examiner, self.timeout = base.rstrip("/"), examiner, timeout

    def call(self, method: str, path: str, body=None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Examiner", self.examiner)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"detail": raw.decode(errors="replace")}


class ClientApi:
    """Adapter over a Starlette/FastAPI TestClient (tests)."""

    def __init__(self, client):
        self.client = client

    def call(self, method: str, path: str, body=None) -> tuple[int, object]:
        r = self.client.request(method, path, json=body, headers={"X-Examiner": DEMO_EXAMINER})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None


class DemoError(RuntimeError):
    pass


def _ok(resp: tuple[int, object], what: str, expect=(200, 201, 202)):
    status, body = resp
    if status not in expect:
        raise DemoError(f"{what} failed: HTTP {status} {body}")
    return body


def wait_job(api, job_id: int, log: Callable[[str], None], poll: float = 0.4, timeout=600.0):
    """Poll a job to a terminal state, logging each progress step (monotonic)."""
    end, last = time.time() + timeout, ("", -1.0)
    while time.time() < end:
        job = _ok(api.call("GET", f"/api/jobs/{job_id}"), f"poll job {job_id}")
        cur = (job["stage"], round(job["progress"], 2))
        if cur != last and job["active"]:
            log(f"    job {job_id}: {job['progress'] * 100:5.1f}%  {job['stage']}")
            last = cur
        if not job["active"]:
            return job
        time.sleep(poll)
    raise DemoError(f"job {job_id} did not finish within {timeout:.0f}s")


def report_available(api) -> bool:
    """True if the API exposes POST /api/cases/{id}/report (added by another stream)."""
    status, spec = api.call("GET", "/openapi.json")
    if status != 200 or not isinstance(spec, dict):
        return False
    return "post" in spec.get("paths", {}).get("/api/cases/{case_id}/report", {})


def seed(
    api,
    evidence_dir: Path,
    log: Callable[[str], None] = print,
    poll: float = 0.4,
    images: list[DemoImage] | None = None,
) -> dict:
    """Create the demo case end to end. Idempotent per case number: an existing demo case is
    reported, not duplicated. Returns a summary dict (ids, urls, skipped steps)."""
    summary: dict = {"skipped": []}
    status, cases = api.call("GET", "/api/cases")
    existing = [c for c in (cases or []) if c["case_number"] == DEMO_CASE_NUMBER]
    if existing:
        summary.update(case_id=existing[0]["id"], already_existed=True)
        log(f"Demo case {DEMO_CASE_NUMBER} already exists (id {existing[0]['id']}); not recreated.")
        return summary
    summary["already_existed"] = False

    case = _ok(
        api.call(
            "POST",
            "/api/cases",
            {
                "case_number": DEMO_CASE_NUMBER,
                "title": DEMO_CASE_TITLE,
                "description": "SYNTHETIC: generated by `make demo` from per-paper vendor layouts. "
                "Nothing here is real DVR/NVR evidence and no result validates a real device.",
            },
        ),
        "create case",
    )
    cid = case["id"]
    summary["case_id"] = cid
    log(f"[1/6] SYNTHETIC case {DEMO_CASE_NUMBER} created (id {cid})")

    log("[2/6] building 3 SYNTHETIC images (ffmpeg test patterns in per-paper layouts) ...")
    images = images or build_images(evidence_dir)
    evidence: dict[str, dict] = {}
    for img in images:
        ev = _ok(
            api.call(
                "POST",
                f"/api/cases/{cid}/evidence",
                {"source_path": str(img.path), "label": img.label, "write_blocker": "unknown"},
            ),
            f"acquire {img.key}",
        )
        if not ev.get("synthetic"):
            raise DemoError(f"{img.key}: acquired image lacks the SYNTHETIC banner flag")
        evidence[img.key] = ev
        log(
            f"      acquired #{ev['id']} {img.label} ({ev['size_bytes']:,} B, "
            f"sha256 {ev['sha256'][:12]}...)"
        )
    summary["evidence"] = {k: e["id"] for k, e in evidence.items()}

    log("[3/6] analysis jobs (progress is polled from the job API)")
    clips_by_key: dict[str, list[dict]] = {}
    for key, ev in evidence.items():
        job = _ok(api.call("POST", f"/api/evidence/{ev['id']}/jobs/analyze", {}), f"job {key}")
        log(f"    {key}: job {job['id']} submitted")
        done = wait_job(api, job["id"], log, poll)
        if done["status"] != "completed":
            raise DemoError(f"analysis job for {key} ended {done['status']}: {done['error']}")
        run = _ok(api.call("GET", f"/api/runs/{done['run_id']}"), "run")
        clips_by_key[key] = [c for c in run["clips"] if c["kind"] == "clip"]
        vendors = ", ".join(m["vendor"] for m in run["vendor_matches"]) or "unknown vendor"
        log(f"    {key}: run {run['id']} completed, {len(clips_by_key[key])} clips ({vendors})")
    summary["clips"] = {k: [c["id"] for c in v] for k, v in clips_by_key.items()}

    log("[4/6] time assumptions and reference observations (P5 endpoints)")
    _ok(
        api.call(
            "PUT",
            f"/api/evidence/{evidence['hikvision']['id']}/time-assumption",
            {
                "timezone": HIK_TZ,
                "epoch_basis": "device_local",
                "evidence_kind": "device_setting_note",
                "notes": "SYNTHETIC demo: invented note 'DVR menu UTC+05:30'; no real device.",
            },
        ),
        "hikvision assumption",
    )
    dh = evidence["dahua"]["id"]
    _ok(
        api.call(
            "PUT",
            f"/api/evidence/{dh}/time-assumption",
            {
                "timezone": HIK_TZ,
                "epoch_basis": "device_local",
                "evidence_kind": "examiner_entered",
                "notes": "SYNTHETIC demo: invented examiner assumption for the Dahua-layout image.",
            },
        ),
        "dahua assumption",
    )
    for raw, true_utc in DHAV_REFERENCES:
        _ok(
            api.call(
                "POST",
                f"/api/evidence/{dh}/time-references",
                {
                    "device_time_raw": raw,
                    "true_time_utc": true_utc,
                    "method": "other",
                    "notes": "SYNTHETIC demo: invented reference pair, not a measurement.",
                },
            ),
            "reference",
        )
    fit = _ok(api.call("POST", f"/api/evidence/{dh}/time-model/fit", {}), "fit")
    log(f"    dahua: assumption + 2 references + fitted model (usable={fit.get('usable')})")
    log(
        f"    hikvision: assumption {HIK_TZ}; raw: timezone left UNKNOWN on purpose "
        "(its clips show as unplaceable on the timeline)"
    )
    summary["unknown_timezone_evidence"] = evidence["raw"]["id"]

    log("[5/6] triage analytics on one clip (leads for review, not findings)")
    target = next((c for v in clips_by_key.values() for c in v if c.get("has_video")), None)
    summary["analytics"] = {}
    if target is None:
        summary["skipped"].append("analytics: no clip with an exported MP4")
        log("    skipped: no exported MP4")
    else:
        summary["analytics_clip_id"] = target["id"]
        for kind in ("motion", "objects", "faces"):
            status, body = api.call("POST", f"/api/clips/{target['id']}/analytics", {"kind": kind})
            if status == 201:
                summary["analytics"][kind] = body["id"]
                log(f"    {kind}: run {body['id']} ({body['result_count']} results)")
            else:
                msg = body.get("detail") if isinstance(body, dict) else body
                summary["skipped"].append(f"analytics {kind}: HTTP {status}")
                log(f"    {kind}: skipped, HTTP {status} ({msg})")

    log("[6/6] report")
    if report_available(api):
        status, body = api.call("POST", f"/api/cases/{cid}/report", {})
        if status in (200, 201, 202):
            summary["report"] = body
            log("    report generated")
        else:
            summary["skipped"].append(f"report: HTTP {status}")
            log(f"    report endpoint answered HTTP {status}: {body}")
    else:
        summary["skipped"].append("report: POST /api/cases/{id}/report is not available")
        log("    skipped: this build has no report endpoint (POST /api/cases/{id}/report)")
    return summary
