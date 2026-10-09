# Cross-camera correlation (suggestions only)

Correlation proposes **candidate links** between observations on different cameras. Every link is a *suggestion* (label: "suggestion: time/topology/class rule match, triage, not identification") until an analyst accepts or rejects it. There is **no appearance-based matching of any kind**: no pixels, boxes, colours, face data, embeddings or re-identification. The rule code (`app/correlation/links.py`) receives an `Observation` with exactly five fields (opaque key, camera node, detection class, UTC lower and upper bound); `tests/test_correlation_links.py` asserts this by inspecting the dataclass and the AST of the rule and plumbing modules.

All test data is reference test data; nothing has been validated on a real site or device.

## Camera topology

`PUT /api/cases/{id}/correlation/topology` stores the examiner-defined layout (current version in `camera_topologies`; every change writes custody `camera_topology_set` with before/after).

- `nodes`: `{id, label, evidence_id?, channel, x?, y?}`. A node matches events of that recorder channel on that evidence item; a node without `evidence_id` matches that channel on any evidence item of the case. `x`/`y` are rough coordinates in `coordinate_units` (free text, e.g. "metres (rough)"); they are displayed but not used by the rules.
- `edges`: `{a, b, max_transit_s?}` undirected adjacency. `max_transit_s`, when set, replaces the request window for that pair.
- Validation: unique node ids, one node per (evidence, channel), edges between two different known nodes, no duplicates.

### Floor plan

`PUT /api/cases/{id}/correlation/floorplan` with a raw body and `Content-Type: image/png` or `image/jpeg`, at most 5 MiB. The body must start with the PNG/JPEG signature (415 otherwise; 413 when too large). It is stored under the data directory as `correlation/case_<id>/floorplan_<sha256>.<ext>`, recorded with its SHA-256, size and type, and logged as custody `floorplan_uploaded`. `GET` serves it back with `X-Content-SHA256` after re-hashing the stored copy (409 if it no longer matches).

## External logs

`POST /api/cases/{id}/correlation/external-logs` imports an authorised CSV (e.g. door access) as JSON:

```json
{"filename": "door_access.csv", "content": "<csv text>",
 "authorization_note": "legal authority / consent reference",
 "timezone": "Asia/Kolkata", "time_format": "%Y-%m-%d %H:%M:%S",
 "mapping": {"time": "timestamp", "event": "event", "location": "door"},
 "location_nodes": {"Lobby": "cam2"}, "delimiter": ","}
```

- `timezone` is **required** with no default, exactly like the timeline (`UTC` must be written explicitly). `time_format` must be a wall-clock format; `%z`/`%Z` are refused so the zone is stated once, explicitly.
- Local times are converted with the timeline's `localize`: a DST-gap time gets no UTC value (reason recorded); an ambiguous (fall-back) time keeps both candidates as one interval. Resolution follows the format (`%S` 1 s, minutes only 60 s, `%f` 1 microsecond) and is added to the upper bound.
- Rows whose time does not parse are kept, unplaced, with the reason. The full raw row is stored verbatim.
- The file is stored as `extlog_<sha256>.csv`; the import is logged as custody `external_log_imported` with the SHA-256, size, mapping, timezone, format, authorisation note and row counts. Limits: 5 MiB, 100 000 rows.

## Link rules

`POST /api/cases/{id}/correlation/links/generate` with `{window_s, require_same_class=true, segment_gap_s=2, include_external_logs=true}`. Requires a topology with at least one edge (409 otherwise).

1. Placed events of the index are grouped per (clip, class) into segments of consecutive detections no more than `segment_gap_s` apart (time and class only). Unplaced events have no absolute time and are skipped; the response counts them.
2. Two segments on different cameras are a candidate when **all** fire:
   - `time_window`: the smallest possible separation of the two UTC uncertainty intervals is within the window (edge `max_transit_s` if set, otherwise `window_s`);
   - `adjacency`: the cameras are joined by a topology edge;
   - `same_class`: both segments have the same class (can be switched off; then this rule is simply not listed).
3. An external log entry with a mapped node links to a segment on the same node or an adjacent one (`external_log_location`) when `time_window` fires. No class rule applies to log entries.

Each link stores snapshots of both ends (camera, clip, class, event ids, times, video link), the rules that fired with their details, an explanation sentence, and the min/max separation. Regenerating updates and prunes only links still in `suggested` state; accepted/rejected links are never changed by regeneration. Custody: `correlation_links_generated`.

`POST /api/correlation/links/{id}/decision` with `{decision: accept|reject, note}` (note required) records the analyst decision and writes custody `correlation_link_decided` with before/after and the link snapshot. A decision can be changed later; each change is logged.

## Endpoints

| Method | Path |
|---|---|
| GET/PUT | `/api/cases/{id}/correlation/topology` |
| GET/PUT | `/api/cases/{id}/correlation/floorplan` |
| GET/POST | `/api/cases/{id}/correlation/external-logs` |
| GET | `/api/correlation/external-logs/{log_id}` (entries) |
| POST | `/api/cases/{id}/correlation/links/generate` |
| GET | `/api/cases/{id}/correlation/links?status=` |
| POST | `/api/correlation/links/{link_id}/decision` |
