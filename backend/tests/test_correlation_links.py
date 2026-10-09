"""Correlation: topology, floor plan, external logs, link suggestions and decisions.

Reference test data only. Links use time, topology and class; nothing else (asserted below)."""

import ast
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.correlation import links, service
from app.custody import verify_chain
from app.models import CustodyEntry
from tests import stream3  # noqa: F401
from tests.events_support import add_clip, add_detections, new_case, set_tz

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TOPO = {
    "nodes": [
        {"id": "cam1", "label": "Gate", "channel": 1, "x": 0, "y": 0},
        {"id": "cam2", "label": "Lobby", "channel": 2, "x": 10, "y": 0},
        {"id": "cam3", "label": "Stairs", "channel": 3, "x": 10, "y": 8},
    ],
    "edges": [{"a": "cam1", "b": "cam2", "max_transit_s": 30}, {"a": "cam2", "b": "cam3"}],
    "coordinate_units": "metres (rough)",
}
CSV = (
    "timestamp,door,event,card\n"
    "2025-06-01 10:00:15,Lobby,granted,1234\n"
    "2025-06-01 99:00:00,Lobby,granted,1234\n"
    "2025-06-01 11:00:00,Roof,denied,9\n"
)


@pytest.fixture
def world(client, image, session):
    c, (ev,) = new_case(client, image, number="CO-1")
    set_tz(client, ev["id"])
    a = add_clip(session, c["id"], ev["id"], 1, (2025, 6, 1, 10, 0, 0))
    b = add_clip(session, c["id"], ev["id"], 2, (2025, 6, 1, 10, 0, 20))
    k = add_clip(session, c["id"], ev["id"], 3, (2025, 6, 1, 10, 0, 0))
    add_detections(
        session,
        a,
        "objects",
        [(125, 5.0, "person", 0.9), (126, 5.04, "person", 0.8), (130, 5.2, "car", 0.5)],
    )
    add_detections(session, b, "objects", [(50, 2.0, "person", 0.8)])
    add_detections(session, k, "objects", [(75, 3.0, "person", 0.7)])
    assert client.post(f"/api/cases/{c['id']}/events/reindex").status_code == 200
    return c, a, b, k


def put_topo(client, c, body=TOPO):
    return client.put(f"/api/cases/{c['id']}/correlation/topology", json=body)


def gen(client, c, **kw):
    return client.post(
        f"/api/cases/{c['id']}/correlation/links/generate", json={"window_s": 10, **kw}
    )


def test_topology_validation_and_custody(client, world, session):
    c, *_ = world
    assert client.get(f"/api/cases/{c['id']}/correlation/topology").json()["defined"] is False
    bad = {**TOPO, "edges": [{"a": "cam1", "b": "nope"}]}
    assert put_topo(client, c, bad).status_code == 422
    dup = {**TOPO, "nodes": TOPO["nodes"] + [{"id": "cam9", "channel": 1}]}
    assert "one node" in put_topo(client, c, dup).json()["detail"]
    loop = {**TOPO, "edges": [{"a": "cam1", "b": "cam1"}]}
    assert put_topo(client, c, loop).status_code == 422
    r = put_topo(client, c)
    assert r.status_code == 200 and r.json()["defined"] and len(r.json()["edges"]) == 2
    log = [e for e in session.scalars(select(CustodyEntry)) if e.action == "camera_topology_set"]
    assert len(log) == 1 and json.loads(log[0].details_json)["after"]["nodes"][0]["id"] == "cam1"


def test_generate_requires_topology(client, world):
    c, *_ = world
    assert gen(client, c).status_code == 409


def test_links_rules_explanations_and_decisions(client, world, session):
    c, a, b, k = world
    put_topo(client, c)
    r = gen(client, c)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] == 1 and "No appearance" in out["note"]
    assert out["inputs"]["segments"] == 4  # A person (2 dets merged), A car, B person, K person
    link = client.get(f"/api/cases/{c['id']}/correlation/links").json()["links"][0]
    assert {link["a"]["clip_id"], link["b"]["clip_id"]} == {a.id, b.id}
    assert [x["rule"] for x in link["rules"]] == ["time_window", "adjacency", "same_class"]
    assert "30 s window (edge max_transit_s)" in link["rules"][0]["detail"]
    assert link["status"] == "suggested" and "suggestion" in link["label"]
    assert link["explanation"].startswith("Suggested because time separation")
    # A person 10:00:05-06.04, B person 10:00:22-23 (Asia/Kolkata, 1 s resolution)
    assert link["gap_s_min"] == pytest.approx(15.96) and link["gap_s_max"] == pytest.approx(18)
    seg = link["a"] if link["a"]["clip_id"] == a.id else link["b"]
    assert len(seg["event_ids"]) == 2 and seg["links"]["video_at"].endswith("#t=5.000")
    # class rule off: car in A also links to B's person
    assert gen(client, c, require_same_class=False).json()["candidates"] == 2
    gen(client, c)  # back to same-class: the car link (still suggested) is dropped
    links_ = client.get(f"/api/cases/{c['id']}/correlation/links").json()["links"]
    assert len(links_) == 1
    lid = links_[0]["id"]
    assert (
        client.post(
            f"/api/correlation/links/{lid}/decision", json={"decision": "accept", "note": ""}
        ).status_code
        == 422
    )
    d = client.post(
        f"/api/correlation/links/{lid}/decision",
        json={"decision": "accept", "note": "analyst reviewed both clips"},
    ).json()
    assert d["status"] == "accepted" and d["decided_by"] == "Insp. Test"
    # regenerating with a tiny window keeps the decided link
    out = gen(client, c, window_s=0.001).json()
    assert out["decided_links_kept"] == 1
    assert (
        client.get(f"/api/cases/{c['id']}/correlation/links", params={"status": "accepted"}).json()[
            "links"
        ][0]["id"]
        == lid
    )
    d = client.post(
        f"/api/correlation/links/{lid}/decision",
        json={"decision": "reject", "note": "changed my mind"},
    ).json()
    assert d["status"] == "rejected"
    acts = [
        e for e in session.scalars(select(CustodyEntry)) if e.action == "correlation_link_decided"
    ]
    assert [json.loads(e.details_json)["after"] for e in acts] == ["accepted", "rejected"]
    assert json.loads(acts[1].details_json)["before"] == "accepted"
    assert verify_chain(session, c["id"])["ok"]
    assert (
        client.post(
            "/api/correlation/links/999/decision", json={"decision": "accept", "note": "x"}
        ).status_code
        == 404
    )


def test_unplaced_events_are_not_linked(client, image, session):
    c, (ev,) = new_case(client, image, number="CO-2")  # no timezone assumption
    a = add_clip(session, c["id"], ev["id"], 1, (2025, 6, 1, 10, 0, 0))
    b = add_clip(session, c["id"], ev["id"], 2, (2025, 6, 1, 10, 0, 0))
    add_detections(session, a, "objects", [(1, 0.0, "person", 0.9)])
    add_detections(session, b, "objects", [(1, 0.0, "person", 0.9)])
    client.post(f"/api/cases/{c['id']}/events/reindex")
    put_topo(client, c)
    out = gen(client, c).json()
    assert out["candidates"] == 0 and out["inputs"]["unplaceable_events"] == 2


def test_external_log_import_parse_custody_and_links(client, world, session, tmp_path):
    c, a, b, k = world
    put_topo(client, c)
    body = {
        "filename": "door_access.csv",
        "content": CSV,
        "authorization_note": "Section 91 CrPC notice ref 12/2025",
        "timezone": "Asia/Kolkata",
        "time_format": "%Y-%m-%d %H:%M:%S",
        "mapping": {"time": "timestamp", "event": "event", "location": "door"},
        "location_nodes": {"Lobby": "cam2"},
    }
    url = f"/api/cases/{c['id']}/correlation/external-logs"
    for missing in ("timezone", "authorization_note", "time_format"):
        assert (
            client.post(url, json={k_: v for k_, v in body.items() if k_ != missing}).status_code
            == 422
        )
    assert client.post(url, json={**body, "timezone": ""}).status_code == 422
    assert client.post(url, json={**body, "timezone": "Mars/Base"}).status_code == 422
    assert client.post(url, json={**body, "time_format": "%Y-%m-%dT%H:%M:%S%z"}).status_code == 422
    bad_map = {**body, "mapping": {"time": "when"}}
    assert "not in CSV header" in client.post(url, json=bad_map).json()["detail"]
    assert client.post(url, json={**body, "location_nodes": {"Lobby": "camX"}}).status_code == 422
    r = client.post(url, json=body)
    assert r.status_code == 201, r.text
    log = r.json()
    assert log["sha256"] == hashlib.sha256(CSV.encode()).hexdigest()
    assert log["row_count"] == 3 and log["rows_unplaced"] == 1 and log["resolution_s"] == 1.0
    detail = client.get(f"/api/correlation/external-logs/{log['id']}").json()
    e1, e2, e3 = detail["entries"]
    assert e1["utc_lo"] == "2025-06-01T04:30:15.000000Z" and e1["node_id"] == "cam2"
    assert e1["raw"]["card"] == "1234"
    assert e2["utc_lo"] is None and "does not match format" in e2["unplaced_reason"]
    assert e3["node_id"] is None  # Roof is not mapped to a camera
    stored = [
        e for e in session.scalars(select(CustodyEntry)) if e.action == "external_log_imported"
    ]
    assert len(stored) == 1 and json.loads(stored[0].details_json)["sha256"] == log["sha256"]
    assert client.get(url).json()[0]["id"] == log["id"]
    out = gen(client, c).json()
    assert out["inputs"]["external"] == {
        "entries": 3,
        "unplaced_entries": 1,
        "entries_without_node": 1,
    }
    ext_links = [
        x
        for x in client.get(f"/api/cases/{c['id']}/correlation/links").json()["links"]
        if "external_log_entry" in (x["a"]["type"], x["b"]["type"])
    ]
    # door entry at 10:00:15 on cam2: B's person (same node, 10 s window), A's person and A's
    # car (adjacent cam1, edge window 30 s; no class rule for log entries); K on cam3 is 11 s
    # away (> 10 s window)
    assert len(ext_links) == 3
    rules = {r["rule"] for x in ext_links for r in x["rules"]}
    assert rules == {"time_window", "external_log_location"}


def test_external_log_dst_gap_and_ambiguous(client, world):
    c, *_ = world
    csv_ = "t,where\n2025-03-30 01:30,Gate\n2025-10-26 01:30,Gate\n"
    r = client.post(
        f"/api/cases/{c['id']}/correlation/external-logs",
        json={
            "filename": "x.csv",
            "content": csv_,
            "authorization_note": "consent form 7",
            "timezone": "Europe/London",
            "time_format": "%Y-%m-%d %H:%M",
            "mapping": {"time": "t", "location": "where"},
        },
    ).json()
    assert r["resolution_s"] == 60.0 and r["rows_unplaced"] == 1
    gap, amb = client.get(f"/api/correlation/external-logs/{r['id']}").json()["entries"]
    assert "DST gap" in gap["unplaced_reason"] and gap["utc_lo"] is None
    assert amb["flags"] == "dst_ambiguous"
    assert amb["utc_lo"] == "2025-10-26T00:30:00.000000Z"  # BST candidate
    assert amb["utc_hi"] == "2025-10-26T01:31:00.000000Z"  # GMT candidate + 60 s resolution


def test_floorplan_upload_checks_and_serve(client, world, session):
    c, *_ = world
    url = f"/api/cases/{c['id']}/correlation/floorplan"
    assert client.get(url).status_code == 404
    h = {"Content-Type": "image/gif"}
    assert client.put(url, content=b"GIF89a", headers=h).status_code == 415
    assert (
        client.put(url, content=b"notapng", headers={"Content-Type": "image/png"}).status_code
        == 415
    )
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024)
    assert client.put(url, content=big, headers={"Content-Type": "image/png"}).status_code == 413
    r = client.put(url, content=PNG, headers={"Content-Type": "image/png"})
    assert r.status_code == 200 and r.json()["sha256"] == hashlib.sha256(PNG).hexdigest()
    g = client.get(url)
    assert g.content == PNG and g.headers["content-type"] == "image/png"
    assert g.headers["x-content-sha256"] == r.json()["sha256"]
    topo = client.get(f"/api/cases/{c['id']}/correlation/topology").json()
    assert topo["floorplan"]["size_bytes"] == len(PNG)
    assert any(e.action == "floorplan_uploaded" for e in session.scalars(select(CustodyEntry)))
    # tampering with the stored copy is detected on serve
    from app.correlation.models import CameraTopology

    t = session.scalars(select(CameraTopology)).first()
    Path(t.floorplan_path).write_bytes(PNG + b"x")
    assert client.get(url).status_code == 409


# ------------------------------------------------- no appearance-based matching, by construction

ALLOWED_FIELDS = {"key", "camera", "class_name", "utc_lo", "utc_hi"}
FORBIDDEN = {
    "x1",
    "y1",
    "x2",
    "y2",
    "bbox",
    "confidence",
    "embedding",
    "embeddings",
    "pixels",
    "frame",
    "frames",
    "image",
    "mp4_path",
    "descriptor",
    "feature",
    "features",
    "appearance",
    "histogram",
    "color",
    "colour",
    "face_id",
    "reid",
}


def _names(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
    return out


def test_link_inputs_are_only_time_topology_and_class():
    assert {f.name for f in dataclasses.fields(links.Observation)} == ALLOWED_FIELDS
    tree = ast.parse(Path(links.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in ("a", "b", "o"):  # Observation variables in links.py
                assert node.attr in ALLOWED_FIELDS | {"total_seconds"}, node.attr
    assert not (_names(links.__file__) & FORBIDDEN)
    # the plumbing that builds Observations from the index reads no box/appearance fields either
    assert not (_names(service.__file__) & FORBIDDEN)


def test_link_rules_pure_function():
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    o = links.Observation
    obs = [
        o("a", "n1", "person", t0, t0 + timedelta(seconds=1)),
        o("b", "n2", "person", t0 + timedelta(seconds=5), t0 + timedelta(seconds=6)),
        o("c", "n3", "person", t0 + timedelta(seconds=5), t0 + timedelta(seconds=6)),
        o("d", "n2", "car", t0, t0 + timedelta(seconds=1)),
    ]
    adj = links.adjacency([{"a": "n1", "b": "n2"}])
    found = links.candidates(obs, adj, window_s=4)
    assert [(c.a, c.b) for c in found] == [("a", "b")]
    assert found[0].gap_s_min == 4 and found[0].gap_s_max == 6
    assert links.candidates(obs, adj, window_s=3.9) == []
