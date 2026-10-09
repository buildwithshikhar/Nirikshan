# Evidence package and offline verification

Code: `backend/app/package/` (`build.py`, `crypto.py`, `verify.py`, `keys.py`, `routes.py`).
Tests: `backend/tests/test_package_build.py`.

## Making a package

`POST /api/cases/{case_id}/package` (case member, role Admin or Examiner), body optional:

```json
{"include_clips": true, "passphrase": "optional, 12+ characters"}
```

The response names the stored file, its SHA-256, the package key id and a ready-to-run verify
command. `GET /api/cases/{id}/packages` lists packages; `GET /api/packages/{id}/download`
re-hashes the stored file and refuses (409) if it no longer matches. After the build a custody
entry `package_created` records the file name and SHA-256, the manifest SHA-256 and signature,
the key id, the file count, exclusions, whether it is encrypted, and the custody head the
package was built from (the head before this entry).

The passphrase is sent in the request body. The application does not provide TLS: send it only
over loopback or through a TLS-terminating proxy. It is never stored or logged.

## Contents

| Path | What |
|---|---|
| `README.txt` | what the package is, offline verification steps |
| `manifest.json` | signed manifest (below) |
| `manifest.sig` | Ed25519 signature (64 raw bytes) over the exact bytes of `manifest.json` |
| `package_public_key.pem` | the package signing public key (SubjectPublicKeyInfo PEM) |
| `SHA256SUMS` | `sha256sum -c` compatible list of every other payload file |
| `case/case.json`, `case/evidence.json`, `case/evidence.csv` | case and evidence inventory (hashes, attestation of write blocker, synthetic banner flag) |
| `case/runs.json`, `case/clips.csv`, `case/analytics_runs.json`, `case/transfers.json` | acquisition/analysis records |
| `custody/custody_log.json` | every custody entry with hash, prev_hash, signature, key id |
| `custody/custody_verification.json`, `custody/custody_public_key.json` | chain verification at build time; custody public key |
| `export/case.jsonld`, `export/timeline.json`, `export/timeline.csv`, `export/case_data.json` | JSON-LD, timeline exports, the full report data model |
| `reports/report_*.pdf`, `reports/reports.json` | stored report PDFs whose hash still matches, with their review status (draft/final/...) |
| `clips/evidence<E>/run<R>/clip<C>_*.mp4` | exported clips whose hash still matches (omit with `include_clips: false`) |

Not included: the evidence images (can be many GB; their MD5/SHA-256 are in `evidence.json` and
the custody log, and the image travels separately), and nothing secret (no keys, passwords,
sessions). Files whose stored hash no longer matches are left out and listed under `excluded`
in the manifest and in the custody entry, never silently. CSV cells starting with `=`, `+`, `-`,
`@`, TAB or CR get a leading `'` (spreadsheet formula injection, OWASP guidance).

## Manifest

`manifest.json` (JSON, sorted keys, 2-space indent): `format` (`nirikshan-evidence-package`),
`format_version` (1), `created_at` (UTC), `created_by` (authenticated principal), `ntp_status`,
`tool_version`, `schema_version`, `ffmpeg_version`, `parsers` (vendor, tier, implementation,
sources; parsers are versioned with the tool), `analytics_models` (name, version, SHA-256,
licence, source), `package_signing_key` (algorithm, key id, public key hex), `case`, `custody`
(head_hash, entries, chain_ok, key_id), `data_origin` (reference-test-data wording, tier limit,
which evidence items carry the synthetic banner, and the statement that nothing has been
validated on a real device), `files` (path, sha256, size for every payload file; sorted),
`excluded`, `include_clips`. `manifest.json` and `manifest.sig` are not listed in `files`.

## Determinism

Entries are sorted by path; every entry has the zip epoch timestamp (1980-01-01 00:00:00), Unix
mode 0444, text deflated at level 6, PDF/MP4 stored. JSON uses sorted keys. Ed25519 signatures
are deterministic. Given the same database state and files, the same `created_at`/NTP status and
the same zlib, two builds are byte-identical (tested). Two packages made at different times
differ in `created_at`, in the README and in the custody head (the first package's
`package_created` entry is part of the second one's chain).

## Offline verification

```
python -m app.cli verify-package <file> --expect-key-id <key id recorded at the lab> [--json]
```

No database, network or Nirikshan key is needed. Exit code 0 = verified, 1 = a check failed
(every failing file is named), 2 = the package could not be checked (unreadable, encrypted
without a passphrase, wrong passphrase, missing manifest). Checks: zip readable, no duplicate or
unsafe names; signature over `manifest.json` with the key named in it; `package_public_key.pem`
is that key; the key id equals `--expect-key-id` when given; every listed file present with the
listed size and SHA-256; no unlisted file.

Without Nirikshan (OpenSSL 3, coreutils), after unzipping:

```
openssl pkeyutl -verify -pubin -inkey package_public_key.pem -rawin -in manifest.json -sigfile manifest.sig
sha256sum -c SHA256SUMS
```

then check that the files in `manifest.json` are exactly the files present (minus manifest.json
and manifest.sig).

**What a valid signature means.** It shows that whoever held the package key produced the
manifest, and that no listed file changed since. Anyone can re-sign a modified package with
their own key, so the key id must be compared with one recorded outside the package (paper case
file, lab register, `GET /api/package-key` at the issuing lab). Without that comparison the
verifier says so (`NOTE signing key id ...`).

## Encrypted container (`.zip.nrkenc`)

Optional, when a passphrase is given. Streamed, chunked AES-256-GCM (Python `cryptography`):

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | magic `NRKPKG01` |
| 8 | 1 | scrypt log2 N (17, i.e. N = 131072, about 128 MiB) |
| 9 | 1 | scrypt r (8) |
| 10 | 1 | scrypt p (1) |
| 11 | 16 | salt (random) |
| 27 | 7 | nonce prefix (random) |
| 34 | 4 | chunk size C, uint32 big-endian (1 MiB) |
| 38 | ... | chunks |

- key = scrypt(passphrase, salt, N, r, p, dklen = 32); measured 278 ms on an Apple M1.
- chunk i = AES-256-GCM(key, nonce_i, plaintext_i, associated data = header bytes 0..37) =
  ciphertext (same length as plaintext_i) followed by the 16-byte tag.
- nonce_i = prefix (7 bytes) || i (uint32 big-endian) || last-flag (1 byte: 0x01 for the final
  chunk, else 0x00).
- every chunk except the last carries exactly C plaintext bytes; the last carries 0..C bytes (an
  empty input is a single empty final chunk).

The counter prevents reordering, the last-flag prevents truncation and extension, and the header
as associated data prevents parameter changes. Any failure (wrong passphrase, flipped byte,
truncated file, reordered chunks, changed header) fails closed with no output treated as valid
(tested for each). The plaintext zip exists briefly in the case's package directory while the
encrypted file is written and is then unlinked, not scrubbed; use disk encryption
(docs/security/auth.md) when that matters. The verifier decrypts into a 0600 temporary file that
it deletes afterwards.

## Keys

The package key is a separate Ed25519 key (`NIRIKSHAN_KEY_DIR/package_ed25519.*`), created on
first use, stored like the custody key and optionally passphrase-protected
(`python -m app.cli protect-key --key package`, docs/security/auth.md "Keys at rest"). There is
no rotation mechanism yet: a package verifies against the key named in its own manifest, so old
packages stay verifiable if the key id is recorded.
