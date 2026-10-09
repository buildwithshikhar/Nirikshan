# Acquisition: resumable copy, bad-sector map, native-export ingest

*Round D stream 2a. Code: `backend/app/acquire/`. Tests: `backend/tests/test_acquire_resumable.py`, `backend/tests/test_acquire_native.py`. Everything here is tested on files and on an injected faulty reader; **block-device acquisition remains opt-in (`NIRIKSHAN_ALLOW_BLOCK_DEVICES=1`) and is unverified on real disks.***

The single-pass path (`POST /api/cases/{id}/evidence`, `app/evidence.py`) is unchanged: it hashes while copying, aborts on any read error and needs no checkpoint. The paths below are additions.

## 1. Resumable acquisition

`POST /api/cases/{case_id}/acquisitions` `{source_path, label, write_blocker, chunk_size?, retries?}` copies the source in chunks (default 4 MiB, 64 KiB to 64 MiB, a multiple of 512).

**Why per-chunk digests.** Python's `hashlib` state cannot be serialised, so a whole-file hash cannot be carried across a restart. The checkpoint (`acquisition_sessions` row) therefore holds:

- `bytes_done`: committed only after the chunk has been written with `pwrite` and `fsync`ed;
- `chunk_sha256_json`: the SHA-256 of every chunk **as written** (so zero-filled where the source could not be read);
- `bad_ranges_json`: the bad-sector map (see section 2).

**Resume** (`POST /api/acquisitions/{id}/resume`, allowed only for `interrupted`/`in_progress` sessions):

1. The partial copy (`<id>.img.partial`) must exist and hold at least `bytes_done` bytes. Bytes beyond `bytes_done` were written after the last committed checkpoint and are truncated; the count goes into custody (`truncated_unconfirmed_bytes`).
2. Every checkpointed chunk of the partial copy is re-hashed and compared with its digest.
3. The source is reopened through the same allow-list and read-only open as the first pass; its type and size must match the checkpoint.
4. Spot check: the last checkpointed chunk is re-read from the source and compared with its digest (skipped when that chunk contained read errors, because a re-read of a bad sector is not expected to agree).
5. Any mismatch refuses the resume: the session and evidence become `failed`, custody gets `acquisition_resume_refused` with the reason.

**Completion.** The whole copy is re-read once; every chunk must match its checkpoint and whole-file MD5 + SHA-256 are computed in the same pass. The copy is renamed to `<id>.img`, made 0444, and `evidence_acquired` is logged with method `resumable chunked copy`, chunk count, a digest of the chunk-digest list, the number of resumes and the bad-sector summary.

**Custody actions added:** `acquisition_started`, `acquisition_interrupted`, `acquisition_resumed`, `acquisition_resume_refused`, `acquisition_failed` (existing name), `evidence_acquired` (existing name, extra fields).

**Limits (stated, not hidden):**

- The resume spot check re-reads one chunk. A source changed in an earlier region while the acquisition was interrupted is **not** detected at resume time. Use the single-pass path when the source can be read in one go.
- There is no source-side whole-file hash for a resumed acquisition: the hashes are of the copy, and the copy is tied to the source only by the per-chunk digests computed at read time plus the spot check.
- An interruption here means a session left `interrupted` (an I/O exception, or a test hook) or `in_progress` (process killed). A copy running in another process is not detected; only one copier per session in this process is enforced.
- Acquisition runs synchronously inside the request (as the single-pass path does).

## 2. Read errors and the bad-sector map

A chunk read that raises `OSError` is retried (`retries`, default 1, max 5). If it still fails, the chunk is re-read 512 bytes at a time with the same retries; each sector that still fails is **written as zero bytes** and recorded as `[start, end, error]`; adjacent sectors with the same error are merged. A short read (fewer bytes than the source reported) is not a bad sector: it stops the copy (`interrupted`; the source changed or was truncated).

Consequences, recorded in custody (`zero_filled`, `bad_sector_bytes`, `bad_sector_map` (first 200 ranges), `hash_scope`) and in `GET /api/evidence/{id}/bad-sectors`:

> Unreadable source ranges were replaced by zero bytes in the copy. MD5/SHA-256 cover the zero-filled copy, not the source medium.

Report authors must repeat this sentence for any evidence item with a non-empty map. For evidence acquired by the single-pass path the endpoint returns an empty map with method `single-pass acquisition` (that path aborts on any read error, so there is nothing to map).

**How it is tested.** `READER_FACTORY` is the only read path; the tests replace it with a reader that raises `EIO` for chosen offsets (permanent, or failing once then succeeding). Tests check the exact zero-filled ranges, that the copy equals the source with those ranges zeroed, that the recorded SHA-256 is the zero-filled copy's (and differs from the source's), that a transient error is absorbed by a retry, and that with `retries=0` it becomes a mapped sector. No real failing disk was used.

## 3. Logical acquisition of standard exports (native-export ingest)

`POST /api/cases/{case_id}/native-exports` `{source_path, label, write_blocker?}` acquires the file with the resumable copier, then runs `ffprobe -show_format -show_streams` **on the stored copy** and stores (table `native_exports`): container (`format_name`, long name, duration, bit rate, stream count, FFmpeg probe score), per-stream codec/profile/size/pixel format/frame rates/sample rate/channels, and container tags. `GET /api/evidence/{id}/native-export` returns it.

- **No vendor claim.** Tags are stored as found and labelled "container metadata as stored in the file; not a vendor identification". The custody entry `native_export_probed` says `vendor_claim: none`.
- **Recognised** means ffprobe found an audio or video stream with a probe score above 50. Score 50 is an extension-only match; the stored copy is named `<id>.img`, which FFmpeg maps to an image demuxer, so random bytes otherwise "probe" as a video. Raw H.264/H.265 elementary streams score 51 and are accepted; their duration is unknown (no container timing).
- A file ffprobe cannot describe stays acquired (it is evidence) with `probe_status: unrecognised` and the ffprobe error.
- Tested with ffmpeg-generated MP4, MKV, AVI (MPEG-4 Part 2), MPEG-TS and raw H.264 files. **No real vendor export file was tested.** Proprietary export packages (e.g. those described in `docs/oem-registry.md`) are described only if ffprobe recognises them.
- Analysis of exported clips (carving, timeline) is not changed by this ingest; a native export can still be analysed like any image.

## 4. E01 / EWF ingest: deferred

`GET /api/acquisition/ewf` and the `ewf` entry of `GET /api/acquisition/capabilities` return `{"available": false, "reason": ...}`. Licence evaluation: libewf and its Python binding pyewf (PyPI `libewf-python`) are **LGPL-3.0-or-later**. That is adoptable as an unmodified, dynamically linked library, as this project already does for psycopg (LGPL-3.0). The licence is not the blocker. It is deferred because (a) it would be a new dependency in `requirements.txt`, a shared file this stream may not edit; (b) it needs a native libewf build in the backend image; (c) no E01 test image can be produced in this environment (no `ewfacquire`), so the ingest could not be tested and would be a stub. Workaround: convert with `ewfexport` to raw outside Nirikshan and acquire the raw file; that conversion is outside Nirikshan's custody. Recorded in `docs/ROUND_D_DEFERRED.md`.

## 5. API summary

| Method | Path | Notes |
|---|---|---|
| GET | `/api/acquisition/capabilities` | resumable, bad-sector map, native ingest (ffprobe present?), ewf (unavailable), block device (opt-in, unverified) |
| POST | `/api/cases/{id}/acquisitions` | resumable acquisition; 403 outside evidence roots, 400 bad parameters |
| GET | `/api/cases/{id}/acquisitions` | sessions of a case |
| GET | `/api/acquisitions/{id}` | session, checkpoint progress, bad-sector map, evidence hashes |
| POST | `/api/acquisitions/{id}/resume` | 409 when refused or not resumable |
| GET | `/api/evidence/{id}/bad-sectors` | map + hash-scope statement |
| POST | `/api/cases/{id}/native-exports` | 503 without ffprobe |
| GET | `/api/evidence/{id}/native-export` | `available:false` for non-export evidence |
| GET | `/api/acquisition/ewf` | `available:false` + reason |
