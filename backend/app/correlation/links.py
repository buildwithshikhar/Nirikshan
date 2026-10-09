"""Link rules. Pure functions over `Observation`, which carries ONLY an opaque key, a camera
(topology node id), a detection class and a UTC uncertainty interval. Nothing else reaches this
module: no pixels, no boxes, no confidence, no embeddings, no appearance of any kind
(tests/test_correlation_links.py asserts this by inspecting the dataclass and this file's AST).

Rules (all must fire for an event-event link):
  time_window  the smallest possible gap between the two uncertainty intervals is <= the window
               (the edge's max_transit_s when the examiner set one, else the request window)
  adjacency    the two cameras are distinct and joined by an edge of the examiner topology
  same_class   both observations have the same detection class (skippable by the request)
External log entries (class 'external_log') link to an event when the entry's mapped node is
the event's camera or adjacent to it (rule external_log_location) and time_window fires.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

EXTERNAL = "external_log"


@dataclass(frozen=True)
class Observation:
    key: str
    camera: str
    class_name: str
    utc_lo: datetime
    utc_hi: datetime


@dataclass(frozen=True)
class Candidate:
    a: str
    b: str
    gap_s_min: float
    gap_s_max: float
    rules: tuple[tuple[str, str], ...]

    def explanation(self) -> str:
        return "Suggested because " + "; ".join(d for _, d in self.rules) + "."


def gap_bounds(a: Observation, b: Observation) -> tuple[float, float]:
    """(min, max) possible separation in seconds between two uncertainty intervals."""
    mn = max(0.0, (b.utc_lo - a.utc_hi).total_seconds(), (a.utc_lo - b.utc_hi).total_seconds())
    mx = max((b.utc_hi - a.utc_lo).total_seconds(), (a.utc_hi - b.utc_lo).total_seconds())
    return mn, mx


def adjacency(edges: list[dict]) -> dict[str, dict[str, float | None]]:
    adj: dict[str, dict[str, float | None]] = {}
    for e in edges:
        w = e.get("max_transit_s")
        adj.setdefault(e["a"], {})[e["b"]] = w
        adj.setdefault(e["b"], {})[e["a"]] = w
    return adj


def candidates(
    obs: list[Observation],
    adj: dict[str, dict[str, float | None]],
    window_s: float,
    require_same_class: bool = True,
) -> list[Candidate]:
    windows = [w for nb in adj.values() for w in nb.values() if w is not None]
    reach = max([window_s, *windows])
    ordered = sorted(obs, key=lambda o: (o.utc_lo, o.key))
    out: list[Candidate] = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if (b.utc_lo - a.utc_hi).total_seconds() > reach:
                break
            ext = (a.class_name == EXTERNAL) + (b.class_name == EXTERNAL)
            if ext == 2:
                continue
            rules: list[tuple[str, str]] = []
            if ext:
                if a.camera == b.camera:
                    rules.append(
                        ("external_log_location", f"log entry location maps to camera {a.camera}")
                    )
                elif b.camera in adj.get(a.camera, {}):
                    loc, cam = (
                        (a.camera, b.camera) if a.class_name == EXTERNAL else (b.camera, a.camera)
                    )
                    rules.append(
                        (
                            "external_log_location",
                            f"log entry location {loc} is adjacent to camera {cam}",
                        )
                    )
                else:
                    continue
                w = adj.get(a.camera, {}).get(b.camera) if a.camera != b.camera else None
            else:
                if a.camera == b.camera or b.camera not in adj.get(a.camera, {}):
                    continue
                rules.append(
                    (
                        "adjacency",
                        f"cameras {a.camera} and {b.camera} are adjacent in the examiner topology",
                    )
                )
                if a.class_name == b.class_name:
                    rules.append(("same_class", f"both are '{a.class_name}' detections"))
                elif require_same_class:
                    continue
                w = adj[a.camera][b.camera]
            win = window_s if w is None else w
            mn, mx = gap_bounds(a, b)
            if mn > win:
                continue
            src = "edge max_transit_s" if w is not None else "request window"
            rules.insert(
                0,
                (
                    "time_window",
                    f"time separation {mn:.3f}-{mx:.3f} s is within the {win:g} s window ({src})",
                ),
            )
            k1, k2 = sorted((a.key, b.key))
            out.append(Candidate(k1, k2, mn, mx, tuple(rules)))
    return out
