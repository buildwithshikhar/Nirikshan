# AI event index, query grammar and summaries

Everything here is **triage, not identification**. Face events are face *detections*: there is no recognition, no embedding and no appearance matching anywhere in the index, the search or the summaries. All numbers in tests come from reference test data (synthetic clips), never from a real DVR.

## What gets indexed

`app/events/indexer.py::index_case(db, case_id)` reads the **stored** analytics rows of completed runs (`detections` and `motion_intervals`; no re-analysis) and writes one `ai_events` row per motion interval or per object/face box. It is idempotent: rows are upserted by `(source_kind, source_row_id)`, so event ids stay the same across reindexes, and events whose source rows were removed are deleted. `index_after_run(db, run)` is the hook to call after `runner.run_analytics` (it does nothing for failed runs).

Each event carries the class, kind (motion/objects/faces), camera (recorder channel), frame index (and end frame for motion), the nominal time inside the clip (frame index / stream fps, constant rate assumed), the detector confidence (none for motion; its peak score is stored separately), the model name and SHA-256 from the run record, the clip's bitstream and MP4 SHA-256, and the clip's byte range and extents in the acquired image. Per-frame byte offsets are not mapped; the hit says so.

### Absolute time

Absolute time comes only from the case timeline (`app/timeline/routes.py::build_case_timeline`), so the same rules apply: no default timezone, and clips the timeline cannot place (timezone unknown, DST gap, invalid or missing timestamp) have **no** UTC time; the event keeps the timeline's reason. For a placed clip:

```
utc_lo = clip_start.lo + nominal_time_s      utc_hi = clip_start.hi + nominal_time_s
```

i.e. the clip-start uncertainty bar (resolution, DST envelope, drift-corrected when a model exists) shifted by the in-clip offset. Clock drift inside one clip is not modelled. Changing a timezone assumption changes placement; reindex afterwards.

## Full-text search backends

| Database | Backend | Behaviour |
|---|---|---|
| SQLite with FTS5 | `sqlite-fts5` | virtual table `ai_events_fts` (rowid = event id), created on first use; every term is reduced to `[a-z0-9_]` and double-quoted, so user text never reaches FTS5 syntax |
| Postgres | `postgres-ilike` | one `ILIKE '%term%'` per term over `ai_events.search_text`, ANDed |
| SQLite without FTS5 | `like-fallback` | the same with `LIKE` |

The fallback has no ranking or stemming; results are ordered the same way (by UTC, then clip, then nominal time). Every response names the backend used. Tests run on SQLite (FTS5 and, by monkeypatching, the fallback); Postgres uses the ILIKE path, which is exercised by the same tests when `TEST_DATABASE_URL` points at Postgres.

## Query grammar

Deterministic, hand-written parser (`app/events/grammar.py`), offline, no LLM. `GET /api/events/grammar` returns the full list. Clauses are ANDed; repeated values of one clause are ORed.

| Clause | Example | Meaning |
|---|---|---|
| `<class>` | `person`, `cars`, `traffic light`, `vehicle`, `face`, `motion` | detection class (COCO labels, face, motion; plural accepted) |
| `camera N` / `cam N` / `channel N` / `ch N` | `camera 2` | recorder channel |
| `clip N`, `evidence N` | `clip 14` | ids |
| `kind motion\|objects\|faces` | `kind faces` | analytics kind |
| `between T and T` | `between 10:00 and 11:00` | time of day, inclusive; may cross midnight |
| `after T`, `before T` | `after 22:30` | open-ended time of day |
| `on YYYY-MM-DD` | `on 2025-06-01` | calendar date |
| `utc`, `tz <IANA>` | `tz Asia/Kolkata` | zone for time clauses |
| `confidence OP X` | `confidence>0.5` | OP is `> >= < <= = !=` |
| `placed`, `unplaceable` | `unplaceable` | placement filter |
| `"text"` | `"yolox"` | full-text terms |

Example: `person camera 2 between 10:00 and 11:00 confidence>0.5`.

Time-of-day and date clauses apply **only to placed clips**. Without `utc`/`tz`, a time of day is read as each evidence item's device-local wall clock using the examiner-entered timezone assumption (nothing is defaulted); a placed clip whose evidence has only a UTC epoch basis and no zone is excluded from such a query and listed. A hit whose uncertainty interval crosses the window edge is marked `overlaps_boundary`. The response always gives `excluded_unplaceable_clips` (and the ids) and the interpreted query. Parse errors return HTTP 422 with `{error, position, token, grammar}`.

## Summaries

`GET /api/cases/{id}/summaries?by=clip|camera` produces template sentences, labelled exactly **"automatic summary of triage detections"**:

```
Clip 12 (camera 1): 3 person detections between 5.00 s and 9.20 s of the clip; placed ones span UTC <lo> to <hi> (uncertainty bounds); 1 motion interval ...
```

Counts, first/last nominal times, the UTC span of placed events, and the number without absolute time. No generated prose beyond the template.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/api/cases/{id}/events/reindex` | examiner; custody `ai_events_indexed` with the counts |
| GET | `/api/cases/{id}/events/status` | event count, last indexed, backend |
| GET | `/api/cases/{id}/events/search?q=&limit=&offset=` | grammar above |
| GET | `/api/cases/{id}/summaries?by=clip\|camera` | template summaries |
| GET | `/api/events/grammar` | grammar help |

Every hit links to the clip video (`/api/clips/{id}/video` and `#t=<nominal s>`), the analytics run (`/api/analytics/{run_id}`), the frame index and the clip's source byte range.
