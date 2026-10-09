# Isolated workers, job chains, retries and batches

Code: `backend/app/workers/` (`isolate.py` runner, `entry.py` worker process, `tasks.py`
whitelisted tasks, `plan.py` validation, `pipeline.py` glue) and `backend/app/jobs/` (manager,
routes). Tests: `backend/tests/test_workers_isolation.py`, `test_jobs_chains.py`,
`test_jobs.py`. Background job basics (progress, cancel, recovery): `docs/jobs.md`.

## What runs in a worker

Background jobs (`/api/evidence/{id}/jobs/analyze`, the analytics job routes) run the compute
on untrusted bytes in a separate process:

- **analyze**: the worker re-hashes the image (must equal the recorded SHA-256), identifies the
  vendor, runs the vendor parsers and the generic carver, and returns a JSON plan (no files, no
  database). The parent validates the plan (types, every offset inside the image, ranges equal
  to what the parent computes, the hash the worker saw) and then exports clips with ffmpeg and
  stores rows and custody entries through the same code as the in-process path. Tested: an
  isolated job stores exactly the clips, hashes, parser output and cross-check of an in-process
  run on the same image.
- **analytics**: the worker runs motion/object/face detection over one exported clip and returns
  the results; the parent adds all result rows in one transaction.

The synchronous endpoints (`POST /api/evidence/{id}/analyze`, `POST /api/clips/{id}/analytics`)
still run in-process (unchanged, for compatibility); prefer the job routes.
`NIRIKSHAN_ISOLATE_JOBS=0` runs jobs in-process too (development only).

## Isolation: what is enforced, and how

| Measure | How | macOS (measured, M1) | Linux |
|---|---|---|---|
| Fresh interpreter | `python -E -s -B -m app.workers.entry` (no PYTHON* variables, no user site, no bytecode writes) | yes | yes |
| No credentials | environment rebuilt from scratch: PATH, LANG/LC_ALL, a temporary HOME/TMPDIR, NIRIKSHAN_MODELS_DIR; no DATABASE_URL, key passphrase or proxy variables | yes (tested) | yes |
| CPU time | `RLIMIT_CPU` set by the worker before it reads input | enforced (SIGXCPU, tested) | enforced (not measured here) |
| Memory | Linux: `RLIMIT_AS`. macOS does not enforce RLIMIT_AS, so the parent samples the worker's physical footprint (`proc_pid_rusage`) every 0.5 s and kills it above the limit | sampled watchdog (tested); a spike shorter than 0.5 s can pass | RLIMIT_AS (not measured here) |
| No file writes | `RLIMIT_FSIZE=0` (writes fail with EFBIG; pipes unaffected) | enforced (tested) | enforced |
| No core dumps | `RLIMIT_CORE=0` | set | set |
| Wall-clock timeout | parent kills the worker's process group (SIGKILL) | enforced (tested) | enforced |
| Network | **best effort**: the worker replaces `socket.socket`, `create_connection`, `getaddrinfo`, `gethostbyname`, `socketpair`, `fromfd` with functions that raise, before any task code runs; the task code opens no sockets | Python socket API refused (tested) | same |

Not provided: no OS network namespace, seccomp filter, sandbox profile, chroot or separate user
id. The guard does not cover native code or child processes (analytics runs ffmpeg as a child,
on a local file path). The worker runs as the same OS user as the server and can read what the
server can read, including a plaintext signing key file. So this isolation contains crashes,
hangs, runaway memory/CPU and accidental network use in parser, carver and analytics code; it is
not a security boundary against code execution through a malicious image. For a real network
guarantee deploy on an offline host or the internal-only Docker network (docs/OFFLINE_DEPLOYMENT.md).

`python -m app.cli worker-selftest [--json]` runs diagnostic tasks and prints what the current
host enforces (exit 1 if a measured guard is missing).

Limits: `NIRIKSHAN_WORKER_TIMEOUT_S` (default 3600), `NIRIKSHAN_WORKER_CPU_S` (default = the
timeout), `NIRIKSHAN_WORKER_MEM_MB` (default 4096), `NIRIKSHAN_WORKER_THREADS` (OMP threads,
default 2).

## Failure states (case stays consistent)

| Event | Job | Run | Rows/files |
|---|---|---|---|
| Worker crash (signal, non-zero exit) | failed, `WorkerCrashed: worker exited with status N ...` / `terminated by SIGXCPU (CPU time limit)` | failed, same error, custody `carve_failed` | no clips of the run (the plan phase stores nothing) |
| Worker timeout | failed, `WorkerTimeout: worker exceeded the wall-clock limit of N s` | failed | none |
| Memory limit | failed, `WorkerCrashed: worker exceeded the memory limit ...` or the RLIMIT_AS MemoryError | failed | none |
| Exception in the task | failed, `WorkerError: <type>: <message>` | failed | none |
| Invalid plan | failed, `PlanInvalid: ...` | failed | none |
| Cancel during the worker phase | cancelled (worker killed at once) | cancelled | none |
| Failure while the parent exports/stores clips (ffmpeg error, disk) | as before (docs/jobs.md): completed clips stay recorded and are listed, half-written files are removed | failed | complete clips only |

Every failure also writes a custody entry (`analysis_job_failed` / `job_failed`), and the chain
verifies afterwards (tested).

## Chains, retries, batches

- `POST /api/evidence/{id}/jobs/analyze?depends_on=<job>` and
  `POST /api/clips/{id}/jobs/analytics?depends_on=<job>`: the job waits in `queued`
  (`waiting: true`, stage "Waiting for job N") until that job completes.
- `POST /api/jobs/{id}/then/analytics {kind, params}`: analytics over every exported clip of the
  run the analyze job produces.
- When a job fails or is cancelled, every job waiting on it is cancelled, transitively, with
  `error = "dependency job N failed: ..."` and a custody entry `job_cancelled`. A dependency on a
  job that already failed is refused (409, "retry it first").
- `POST /api/jobs/{id}/retry`: only for failed or cancelled jobs. Creates a new job linked by
  `retry_of` (`attempt` + 1). Asking again returns the same retry (`existing: true`). A dependent
  retried after its dependency was retried follows the newest attempt. Analytics jobs never
  re-analyse a clip that already has a completed run with identical parameters
  (`result.skipped_existing`), so retries and repeated chains never duplicate results. An analyze
  retry creates a new run; the failed run stays recorded as failed.
- `POST /api/cases/{id}/jobs/batch {evidence_ids, analyze, analytics: [{kind, params}]}`: one
  analyze job per evidence item (duplicates removed) plus dependent analytics jobs, tagged with a
  `batch_id`; `GET /api/cases/{id}/batches/{batch_id}` summarises them, and
  `GET /api/cases/{id}/jobs?batch_id=` lists them. Evidence ids of other cases are 404.

Concurrency: the pool size is `NIRIKSHAN_JOB_WORKERS` (default 2); custody appends are serialised
in-process so concurrent jobs of one case cannot collide on the chain sequence. Single process
only (no broker): a restart fails every queued/running job, including waiting dependents, with
"interrupted" (docs/jobs.md).
