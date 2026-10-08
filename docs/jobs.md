# Background analysis jobs

Analysis of a large image can take minutes, so the UI starts it as a background job and polls its
progress. The synchronous `POST /api/evidence/{id}/analyze` still exists and behaves exactly as
before (no progress, no cancel).

## API (all mutations need the `X-Examiner` header)

| Call | Result |
|---|---|
| `POST /api/evidence/{id}/jobs/analyze` (body = the same options as `/analyze`) | 202 + job. `existing: true` if an identical request is already active. 409 if the evidence is not acquired, 503 without ffmpeg |
| `GET /api/jobs/{id}` | job (poll about once per second) |
| `GET /api/cases/{id}/jobs?evidence_id=&active=` | jobs of a case, newest first |
| `POST /api/jobs/{id}/cancel` | 202 + job (`cancelling`, or `cancelled` if it was still queued); 409 if already finished |

Job fields: `id, kind, case_id, evidence_id, params, status, active, cancel_requested, progress
(0..1, never decreases), stage (text), run_id, clips_recorded, error, examiner, created_at,
started_at, finished_at`.

## State machine

```
queued --start--> running --done--> completed
   |                 |  \--error--> failed
   |cancel           |cancel
   v                 v
cancelled <------ cancelling --(next checkpoint)--> cancelled
                         \--(finished first)--> completed
restart of the application: queued | running | cancelling --> failed ("interrupted")
```

All transitions are conditional `UPDATE ... WHERE status = ...`, so a cancel request and a finishing
worker cannot overwrite each other. `active_key` (the idempotency key: SHA-256 of kind, evidence
and normalised parameters) is set only while the job is queued/running/cancelling and has a UNIQUE
constraint: one active job per identical request, any number of finished ones.

## Cancel semantics

Cancellation is cooperative. The pipeline checks `should_cancel()` between stages, before each
parser, before each generic-carving item and before each clip export. It is NOT checked inside one
ffmpeg call or inside the initial full-image hash re-verification, so a cancel can take as long as
the current step.

When a running job is cancelled:

* the run is marked `cancelled` (not `failed`, not `completed`);
* clips already exported **and recorded** stay recorded and are listed (`clips_recorded`);
* every file in the run's clip directory that no clip row records (a half-written bitstream or MP4)
  is deleted, and an empty run directory is removed: no orphan files;
* one custody entry `analysis_cancelled` is written with `run_id`, `partial: true`,
  `completed_clip_ids`, `orphans_recorded`, `unrecorded_files_removed`. No `carve_completed` entry is
  written. The custody chain verifies as usual;
* a job cancelled while still queued never creates a run; its custody entry has `run_id: null`.

## Crash safety

* Any exception in a worker marks the job `failed` with the error text, the run `failed`
  (existing `carve_failed` entry), writes an `analysis_job_failed` custody entry and removes
  unrecorded files. Failure bookkeeping swallows its own errors: nothing propagates out of a worker
  thread, and a custody write failure still leaves the job `failed`.
* On application startup (`lifespan`) every job still `queued`, `running` or `cancelling` belonged
  to the previous process: it is marked `failed` ("interrupted: the application restarted"), with a
  custody entry; any carve run left `running` is marked `failed` with a `carve_failed` entry and its
  unrecorded files removed. Nothing is resumed.

## Restart

Submitting the same request while one is active returns the existing job. After `cancelled` or
`failed` the same request creates a new job and a new run (new run number, new clip directory).
The old partial run, its recorded clips and custody entries are left untouched and are never
reused or duplicated.

## Limits

* Single process: the worker pool is a `ThreadPoolExecutor` (`NIRIKSHAN_JOB_WORKERS`, default 2).
  There is no broker, no multi-process coordination and no resume after a restart.
* The queue is in memory; queued jobs lost at restart are marked `failed`.
* No authentication: the examiner header is an attestation, as everywhere else.
* The custody log assigns sequence numbers per case without a lock across threads; two simultaneous
  writers to the same case could collide on the UNIQUE (case_id, seq) constraint. The job manager
  writes custody entries only from its own worker, but a user action in the same millisecond can
  still race (pre-existing limitation of the custody writer).
* A cancel does not interrupt the image re-verification that precedes each run.
