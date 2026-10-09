# Security Review and Threat Model

*Status: engineering self-review of the code at the commit this file was written against (2026-10-09). It is not an independent penetration test and not an accreditation. Statements cite the code that implements them; "absent" means we found no implementation, not that the risk is acceptable.*

Scope: the FastAPI backend (`backend/app`), the React frontend, the packaging in `backend/Dockerfile`, `frontend/Dockerfile`, `deploy/nginx.conf` and `docker-compose.offline.yml` (see [OFFLINE_DEPLOYMENT.md](OFFLINE_DEPLOYMENT.md)). Dependency audit results are in [security/audit-pip.txt](security/audit-pip.txt) and [security/audit-npm.txt](security/audit-npm.txt), summarised in section 5.

## 1. Assets, actors, trust boundaries

**Assets**

| Asset | Where | Why it matters |
|---|---|---|
| Acquired evidence images (mode 0444 copies) | `<data>/cases/<id>/evidence/` | Integrity is the product; hashes are re-checked on every read (`evidence.open_verified`) |
| Exported clips (MP4, bitstreams) | `<data>/cases/<id>/clips/` | Derived evidence; hash recorded at carve time and re-checked before analytics |
| Custody log and audit log | DB tables `custody_entries`, `audit_log` | Hash-chained, Ed25519-signed (custody); append-only by DB trigger |
| Custody signing key | `$NIRIKSHAN_KEY_DIR/custody_ed25519.pem` | Whoever holds it can forge custody entries (`signing.py`) |
| Source evidence (original disks/images) | `NIRIKSHAN_EVIDENCE_ROOTS`, optional block devices | Must never be written (`O_RDONLY|O_NOFOLLOW` in `evidence.open_source_readonly`) |
| Analytics models | `NIRIKSHAN_MODELS_DIR` | Wrong weights would silently change triage output; SHA-256 pinned in `analytics/registry.py` |

**Actors**

| Actor | Assumed capability |
|---|---|
| Authorised examiner | Uses the UI/API legitimately |
| Another person on the same network/host | Can reach the API port; **can act as any examiner** (section 2.1) |
| Malicious or careless insider with API access | Can create cases, acquire any file under an evidence root, trigger heavy analysis |
| Host administrator / DB owner / holder of the key directory | Outside what the application can defend against; the design aims at *detection*, not prevention |
| Supplier of an evidence image | The image is untrusted input to parsers and ffmpeg |
| Supply chain (PyPI, npm, GitHub model URLs, Debian) | Can deliver altered code or weights |

**Trust boundaries**

1. Browser to API (HTTP, no authentication, no TLS in this repo).
2. API to filesystem: evidence roots (read-only intent), data directory (read/write), key directory (read/write, separate).
3. API to subprocess: `ffmpeg`/`ffprobe` invoked with argument lists (`carving/export.py`), no shell.
4. Evidence image bytes to the parsers/carver/ffmpeg: untrusted input.
5. Build time to run time: the only network use is `scripts/fetch_models.py` and package installation; the application does not download anything at runtime (a test blocks sockets during analytics).

## 2. Findings

Legend: **Present** = mitigation implemented and tested in this repo; **Partial** = implemented with a stated gap; **Absent** = not implemented.

### 2.1 Examiner identity is an attestation, not authentication
`routes.examiner_name` takes the `X-Examiner` header; any non-empty value is accepted. Only `POST` calls require it. **`GET` endpoints (cases, evidence, custody, clips, video, audit, system) require nothing.** Anyone who can reach the port can read every case and can create, acquire, analyse and verify as any named examiner; the custody log will faithfully record the false name, and the Ed25519 signature proves only that *this installation* wrote the entry.
- Status: **Absent** (documented limit since P1).
- Next step: an authentication and authorisation decision from the operator (OIDC/mTLS/reverse-proxy SSO, per-examiner accounts, roles, and binding the signed examiner field to the authenticated principal). Until then deploy on a single-user workstation or behind an authenticating proxy, bound to loopback (`docker-compose.offline.yml` does this).

### 2.2 Signing key directory
Key generation: mode 0600 file, directory 0700 (`signing._load_or_create`); refused when inside the data directory or group/world-accessible; `O_EXCL` creation. Unencrypted PKCS8 PEM (`NoEncryption`). No rotation (entries carry `key_id`, but only the current key verifies), no backup mechanism, no HSM/TPM support.
- Who can forge entries: anyone who can read the key file, and anyone who can run code as the service user (the signing happens in-process). A forged but correctly signed entry is undetectable by `verify-chain`.
- In the offline compose file the key sits on its own volume (`nirikshan_keys`) mounted only into the backend. Anyone with Docker access on the host can read it.
- Status: **Partial**. Next steps: back the key up separately and offline; record `key_id` and the public key (`GET /api/signing-key`) in the paper case file; plan rotation (accept multiple public keys during verification); consider a hardware-backed key for casework that will be contested.

### 2.3 Evidence roots and block-device gating
`config.evidence_roots()` is `NIRIKSHAN_EVIDENCE_ROOTS`; empty means every acquisition is refused (403, fail-closed, tested). The requested path is resolved (`resolve(strict=True)`), the policy is applied to the resolved path and that path is opened `O_RDONLY|O_NOFOLLOW`. Block devices require `NIRIKSHAN_ALLOW_BLOCK_DEVICES=1` (default off; the compose file sets `"0"`). The custody entry records requested and resolved paths. Verified in the offline container: `/etc/passwd` gave 403 while `/evidence/a.img` was acquired.
- Residual risk: a time-of-check/time-of-use swap by someone with write access to an evidence root (narrowed by `O_NOFOLLOW` on the final component, not eliminated).
- Evidence is copied once into the data directory; the source is never opened for writing. Software gating is not a write blocker: the physical-device case depends on the examiner's hardware blocker and the `write_blocker` attestation. Real block-device acquisition is untested (file-backed fixtures only).
- `GET /api/system` returns the configured evidence roots and the key id to any caller (information disclosure of directory names).
- Status: **Present** (policy), **Partial** (race; physical device untested). Next step: mount evidence `:ro` (done in the compose file) so the OS enforces what the code intends; keep roots narrow; restrict `/api/system` once authentication exists.

### 2.4 Custody-log tail truncation and database tampering
`custody.verify_chain` checks sequence, hash links, recomputed hashes and signatures. Deleting the newest entries leaves a valid shorter chain; only an externally recorded `head_hash` exposes that. `custody_entries` and `audit_log` have BEFORE UPDATE/DELETE triggers (and TRUNCATE on Postgres, `app/triggers.py`); a DB owner can drop the triggers, which the chain and signatures then detect for anything except tail truncation or forged-with-key entries. `python -m app.cli reset-db --yes` drops the schema (dev only) and needs only shell access to the container.
- Status: **Partial** by design. Next step: make "record `head_hash` outside the system" a mandatory step in every SOP session close (SOP-05) and in the report (the PDF report states it on the custody page and records the head_hash it was built from); consider periodically countersigning or time-stamping `head_hash` with an external authority.

### 2.5 Path traversal
- Acquisition: see 2.3. Clip serving: `GET /api/clips/{id}/video` returns `FileResponse(row.mp4_path)` where the path comes from the database row written by the backend, not from the request, so there is no request-controlled path. If an attacker can write `clips.mp4_path` (DB access) they can make the endpoint serve any file readable by the service user.
- Clip files are 0444 under `<data>/cases/...`. Case numbers are not used to build paths (numeric ids are).
- Status: **Present** for request-supplied paths. Next step: constrain `mp4_path` to the data directory at serve time (defence in depth), and add a test.

### 2.6 File serving of clips (Range)
Served by Starlette `FileResponse`, which handles `Range`. No authentication (2.1), so any reachable client can download any clip. Recorded in the audit log by the middleware (`main.audit_trail`), which records method, path, status and the (unauthenticated) examiner header, not bodies or IP addresses.
- Status: **Partial** (served correctly; access control absent). `deploy/nginx.conf` sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; no CSP, no TLS.

### 2.7 SQL injection
All database access in the application uses SQLAlchemy ORM / Core expressions with bound parameters. The DDL for triggers is static text (`app/triggers.py`). Request fields are validated by Pydantic models (`schemas.py`), several with length bounds (`case_number` 100, `title` 300, `label` 300). `description` (default empty), `source_path` and `parser_options` have no length limit.
- Status: **Present** (no string-built SQL found in a read of the app code; not fuzzed). Next step: add maximum lengths to the free-text fields; run an SQL-injection scanner in CI.

### 2.8 CORS
`CORS_ORIGINS` (default `http://localhost:5173`) lists allowed origins; methods and headers are `*`; credentials are not enabled, so cookies are not involved. The packaged stack serves UI and API from one origin through nginx, so CORS is not needed there; the compose file lists only the loopback UI origins.
- Status: **Present**. Note that `X-Examiner` is a custom header and `allow_headers=["*"]` lets any *allowed* origin send it.

### 2.9 Supply chain: models, OCR, packages, images
- Analytics weights are pinned by SHA-256 in `analytics/registry.py`, verified on every load (`verified_model_path`) and at fetch time (`scripts/fetch_models.py`); `scripts/model_manifest.py` produces/verifies an `sha256sum`-compatible manifest for air-gapped transfer; the backend image build fails on mismatch. The model download URLs are on GitHub (redirects to a CDN); trust is anchored in the pinned hash, which we computed from the first download (trust on first use).
- The OCR models are inside the `rapidocr-onnxruntime==1.4.4` wheel. They are covered by pip's package pin but **not** by our own checksum, and pip is not run with `--require-hashes`. Status: **Partial**.
- Python dependencies are pinned for the P5/P6 stack in `requirements.txt` but the web stack (`fastapi`, `uvicorn`, `sqlalchemy`, `psycopg`, `pyyaml`, `cryptography`) is range-pinned; `requirements.lock` is informational. Docker base images are referenced by tag, not digest. Status: **Partial**. Next step: hash-pinned lock (`pip-compile --generate-hashes`), digest-pinned base images, SBOM per release.
- The ffmpeg in the image is Debian's package: **trusted via the Debian archive signature**, a GPL build (see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)).
- Dependency audits: section 5.

### 2.10 Denial of service
- **Large or hostile images:** acquisition streams in 4 MiB chunks (bounded memory) but copies the whole image into the data directory (disk exhaustion; no quota). The carver is bounded-memory and measured at about 569 MiB/s scanning on one Mac (see ARCHITECTURE); a pathological image can still produce very many clips and ffmpeg runs.
- **Synchronous analysis:** `POST /api/evidence/{id}/analyze` and analytics run in the request thread; a long run occupies a worker and the nginx proxy timeout is set to 3600 s. Analysis can also run as a background job with progress and cooperative cancel (`/api/evidence/{id}/jobs/analyze`, docs/jobs.md); that is a convenience, not a quota: there is still no rate limiting, no per-user limits, and cancel cannot interrupt the initial image re-verification or one ffmpeg call. Treat the API as single-examiner.
- **ffmpeg on untrusted data:** carved bitstreams are muxed/decoded by ffmpeg with timeouts (`subprocess.run(..., timeout=...)` in `carving/export.py` and `analytics/frames.py`). ffmpeg parsers have a long history of memory-safety bugs; the backend container runs as an unprivileged user with all capabilities dropped and a read-only root, which limits but does not remove the impact. Status: **Partial**.
- No rate limiting, request size limit on the API itself (nginx caps request bodies at 1 MB).
- Next step: disk quotas on the data volume, concurrency limits, the job queue, and resource limits (`mem_limit`, `pids_limit`) in compose.

### 2.11 Report / PDF injection
The PDF report, the BSA 63(4) draft certificate and the JSON-LD export exist (`backend/app/report/`); they were not assessed here beyond a read of their design (ReportLab is fed through an internal text sanitiser that replaces non-Latin characters with visible `[U+XXXX]` markers; whether paragraph markup in examiner text is escaped everywhere was not verified). Risks to review: examiner-supplied free text (case title, description, labels, time-assumption notes) flowing into PDF text or JSON-LD; ReportLab paragraph markup interpretation of `<`/`&` in user text; filename and path leakage; whether a regenerated report can diverge silently from the database. The existing CSV/JSON timeline export (`timeline/routes.py`) writes user-controlled strings to CSV: spreadsheet formula injection (cells beginning with `=`, `+`, `-`, `@`) was not specifically mitigated as far as we checked. Status: CSV **Absent** (not mitigated, not verified in code), PDF/JSON-LD **partially assessed** (design read only, no fuzzing).

### 2.12 Secrets handling
No secrets are baked into images (`backend/Dockerfile` creates the key directory empty; the key is generated on first run into a volume). The database is SQLite by default; the legacy dev `docker-compose.yml` carries a fixed Postgres password (`nirikshan`) and publishes port 5433 on all interfaces, which is a development convenience only and must not be used for casework. The only environment values in the offline compose file are paths and a CORS list. Status: **Present** for the offline stack; the dev compose file is **Absent**-hardening by design.

### 2.13 Logging of sensitive data
`audit_log` stores examiner string, method, path (includes numeric ids), status code, case id. It does not store request bodies or client addresses, so it can neither prove which machine acted nor leak bodies. Custody `details` hold hashes, paths, tool versions. Uvicorn's default access log prints method, path and client address to stdout (container log). Evidence content is never logged. The audit log cannot record an unauthenticated caller's identity beyond the free-text header. Status: **Partial**. Next step: log client address and authenticated principal once authentication exists; ship container logs to a write-once store.

### 2.14 Container and deployment posture (offline stack)
Measured on 2026-10-09 on Docker Desktop 29.7.2 (macOS, arm64); procedure in [OFFLINE_DEPLOYMENT.md](OFFLINE_DEPLOYMENT.md):
- backend runs as uid 10001, frontend as uid 101; root filesystems read-only; `cap_drop: [ALL]` (CapEff 0), `no-new-privileges` (NoNewPrivs 1); evidence mount read-only (write attempt: "Read-only file system"); published port bound to 127.0.0.1.
- **Backend has no route to the internet** (connect and DNS both fail) because it is only on an `internal: true` network.
- **The frontend container does have internet reachability on this host.** Docker cannot publish a port from an internal-only network (we tested), so the frontend joins a second network, and the `enable_ip_masquerade: "false"` option did not stop outbound traffic on Docker Desktop. The container only serves static files and proxies to the backend, but "no outbound at runtime" is therefore **not enforced for the frontend** on this host; use a host firewall rule, or run on a native Linux engine and verify (untested).
- Status: **Partial**.

## 3. Summary table

| # | Area | Mitigation | Recommended next step |
|---|---|---|---|
| 2.1 | Authentication | Absent | Authn/z decision; bind examiner to principal |
| 2.2 | Signing key | Partial | Offline backup, rotation plan, optional HSM |
| 2.3 | Evidence roots / block devices | Present / Partial | `:ro` mounts; hardware write blocker; test a real device |
| 2.4 | Custody truncation, DB owner | Partial | Mandatory external `head_hash`; external time-stamping |
| 2.5 | Path traversal | Present | Constrain served `mp4_path` to the data dir |
| 2.6 | Clip serving | Partial | Access control with 2.1; CSP/TLS at the proxy |
| 2.7 | SQL injection | Present (ORM) | Length limits; CI scanner |
| 2.8 | CORS | Present | Keep origin list minimal |
| 2.9 | Supply chain | Partial | Hash-pinned lock, digest-pinned bases, own checksum for OCR models, SBOM |
| 2.10 | DoS | Partial | Per-user quotas and rate limits (absent); job queue exists (bounded workers); compose resource limits |
| 2.11 | Report/CSV injection | CSV absent; PDF/JSON-LD partially assessed | Escape formula prefixes; fuzz report text handling with markup, very long and non-Latin input |
| 2.12 | Secrets | Present (offline stack) | Do not use the dev compose file for casework |
| 2.13 | Logging | Partial | Log principal and client address once authn exists |
| 2.14 | Container posture | Partial | Host firewall for the frontend network |

## 4. Deployment hardening checklist

- [ ] Run on a dedicated, single-purpose host; full-disk encryption on; physical access controlled.
- [ ] Bind only to loopback (compose default) or place behind an authenticating, TLS-terminating proxy. Never expose the API port directly.
- [ ] Add authentication in front of the API (2.1) before more than one person uses the system.
- [ ] Build the images on a connected machine; verify `sha256sum -c SHA256SUMS` for models; transfer with `docker save`; record the image IDs in the case file.
- [ ] Mount evidence `:ro`; keep `NIRIKSHAN_ALLOW_BLOCK_DEVICES=0` unless a hardware write blocker is in use and its use is attested.
- [ ] Keep the key volume separate from the data volume; back it up offline; note `key_id` in the paper file.
- [ ] After every session: `GET /api/cases/{id}/custody/verify` and write `head_hash` and entry count on the paper log, signed.
- [ ] Add a host firewall rule that drops traffic from the compose `edge` network to anything but the host (frontend container egress, section 2.14).
- [ ] Set `mem_limit`, `pids_limit` and a data-volume quota; monitor free disk.
- [ ] Re-run `pip-audit` and `npm audit` before each release; review section 5; pin `cryptography` per the audit.
- [ ] Do not use `docker-compose.yml` (dev Postgres, fixed password) for casework.
- [ ] Time: set the host clock from a trusted source and record the offset; NTP status is `unknown` on non-systemd hosts and in containers.
- [ ] Treat every evidence image as hostile input: do not run the stack on a machine that holds other sensitive data.

## 5. Dependency audit results

### 5.0 Update after the upgrade (2026-10-09)
`cryptography` was upgraded 46.0.7 to **50.0.2** (the `<47` pin became `>=50.0.2,<51`) and `source-map-js` 1.2.1 to 1.2.2 (dev-only, lockfile). Re-run: `pip-audit` reports no known vulnerabilities for `requirements.txt`, `requirements-dev.txt` and the lock file; `npm audit` reports 0 vulnerabilities ([security/audit-after-upgrade.txt](security/audit-after-upgrade.txt), JSON files with `-after-upgrade`). Custody signatures created before the upgrade still verify: `backend/tests/test_signature_compat.py` verifies a chain signed with 46.0.7 (fixture generated before the upgrade) and checks that Ed25519 re-signing reproduces the stored signatures. Still not covered: OS packages and container images were never scanned; auditors only know published advisories. The findings below are the audit as first run (kept as history).

### 5.1 First audit run (2026-10-09, nothing upgraded)

Commands and raw output: [security/audit-pip.txt](security/audit-pip.txt) (+ JSON), [security/audit-npm.txt](security/audit-npm.txt) (+ JSON).

**Python (`pip-audit` 2.10.1): 4 advisory records, all in `cryptography 46.0.7`.** The same four appear for `requirements.txt` (43 packages), `requirements-dev.txt` (51) and `requirements.lock` (52). The fixed versions (48.0.1, 49.0.0, 50.0.0) are above the `cryptography>=42,<47` constraint in `requirements.txt`.

| Advisory | Severity (GitHub) | What it is | Reachable in our usage? | Recommendation |
|---|---|---|---|---|
| GHSA-m2h6-j472-rp4c / CVE-2026-69248 | medium | X.509 verifier wildcard SAN versus name constraints | No: the code imports only Ed25519 and PEM key loading (`app/signing.py`) and a cipher in the validation generator; no X.509 verification | Upgrade when the constraint is revisited |
| GHSA-jwv3-5hgf-82ww / CVE-2026-69249 | high | Exponential path building on duplicate self-signed certificates | No: no certificate path building | same |
| GHSA-g6cj-pr64-35w5 / CVE-2026-69247 | high | PKCS#7 decryption oracle | No: no PKCS#7 use | same |
| GHSA-537c-gmf6-5ccf | high (CVSS 7.5) | Wheel bundles a vulnerable OpenSSL (June 2026 advisory: CVE-2026-45447, PKCS7_verify use-after-free) | Not through our code paths (no PKCS#7/CMS); the OpenSSL library is loaded in the process | Move to cryptography >= 48.0.1 and re-run the full test suite (Ed25519 signing is the only dependency); changing `<47` needs a decision because older stored keys/signatures must still verify (they should, Ed25519 is standardised, but test it) |

**npm: production dependencies 0 vulnerabilities. Including dev dependencies: 1 high** (`source-map-js` 1.2.1 per `package-lock.json`, GHSA-68fv-2mgg-jv7q, CVSS 7.5, event-loop denial of service via crafted indexed source maps). Dev-only (reached through postcss and `@tailwindcss/node` at build time); not present in the production image (the frontend image carries only the built static files). Not reachable at runtime. Recommend `npm audit fix` in a normal dependency-update change.

**Not covered:** OS packages in the Debian/alpine layers (run an image scanner such as Trivy/Grype on a connected machine and record the result with the image digest; not done here); the ffmpeg build; the vulnerability databases are queried live, so results change daily.

### Pinned versions (from `backend/requirements.lock`, informational)

See the file for the full list; key entries: fastapi 0.143.0, cryptography 46.0.7, numpy 2.2.6, onnxruntime 1.23.2, rapidocr-onnxruntime 1.4.4, opencv-python 5.0.0.93, Pillow 12.3.0. The lock was produced on Python 3.10; the container uses Python 3.12 and resolves from `requirements.txt`, so installed patch versions in the image may differ from the lock for the unpinned web-stack packages.

## 6. What we have not done

No external penetration test; no fuzzing of the HTTP surface; no review of the frontend for XSS beyond React's default escaping and a grep that found no `dangerouslySetInnerHTML` or `innerHTML` in `frontend/src`; no threat model for the physical acquisition chain; no assessment of the unmerged report, job and demo code.
