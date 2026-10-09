# Authentication, roles and case access

Round D, stream 1. Code: `backend/app/auth/` (users, sessions, policy), `backend/app/approvals/`
(two-person report approval, transfers), `backend/app/keystore.py` (keys at rest). Tests:
`backend/tests/test_auth_core.py`, `test_auth_policy.py`, `test_approvals_reports.py`,
`test_keystore_passphrase.py`.

## What this protects, and what it does not

**Protects**
- Every API route requires a logged-in local user, except `GET /health`, `GET /api/signing-key`,
  `GET /api/package-key` (public halves of the signing keys) and `POST /api/auth/login`.
- A user sees and acts only on cases they are a member of (Admin sees the case list and manages
  membership; see "Admin and membership"). Every case-scoped object (evidence, clips, carve runs,
  analytics runs, jobs, reports, packages, timeline, custody, transfers, performance) is resolved
  to its case before the route runs.
- Roles limit what a member may do (matrix below). The two-person rule for final reports is
  enforced on user ids, not on names.
- Custody entries, audit rows, carve runs, analytics runs and jobs record the authenticated
  principal as `Display Name (username)` instead of a free-text header.
- Password guessing is throttled per client address and per account (limits below).

**Does not protect**
- **Local accounts only.** No SSO, LDAP, OIDC, smart cards, MFA or client certificates.
- **No TLS.** The application speaks plain HTTP. Tokens and passwords (and an optional package
  passphrase) cross the network in clear unless a TLS-terminating reverse proxy is put in front
  (`deploy/nginx.conf` does not terminate TLS today). Bind to loopback or a trusted segment.
- **The database is not encrypted.** Users, password hashes, session hashes, cases, custody and
  audit rows sit in SQLite/Postgres in clear unless the deployment encrypts the volume (see
  "Disk encryption"). A database reader cannot replay a session (only SHA-256 of the token is
  stored) and cannot recover passwords cheaply (scrypt), but can read every case record.
- **A same-host attacker with filesystem access defeats it**: anyone who can run code as the
  service user, read the database file, or read the signing key (unless passphrase-protected,
  and even then while the server runs the key is in process memory) can bypass every check
  here. Authentication guards the HTTP API, nothing else.
- Isolated workers run as the same OS user (docs/workers.md).
- The audit log does not store client addresses (`audit_log` has no column for it; that table
  is shared and was not changed in this stream). Session rows record the login address.
- `NIRIKSHAN_DEV_HEADER_AUTH=1` turns all of the above into an unauthenticated attestation (next
  section). It must never be set in casework.

## Identity source

1. `Authorization: Bearer <token>` on any method.
2. The `nirikshan_session` cookie (HttpOnly, `SameSite=Strict`, `Path=/api`, `Secure` when
   `NIRIKSHAN_COOKIE_SECURE=1`) on **GET/HEAD only**, so `<video src>` and PDF downloads work in a
   browser while a cross-site form cannot perform a mutation with the cookie (CSRF). Logout also
   accepts the cookie.
3. Only with `NIRIKSHAN_DEV_HEADER_AUTH=1` (default **off**): with no token, the `X-Examiner`
   header is accepted as an **unauthenticated attestation** (the pre-Round-D behaviour). Such dev
   principals bypass case membership and roles, but are refused for user management, membership
   changes, report approval/rejection/finalisation and `GET /api/auth/me`. The test suite sets the
   flag so the pre-auth tests keep running; `tests/test_auth_*.py` switch it off per test.
4. Otherwise 401. A presented token that is invalid, expired or revoked is always 401; it never
   falls back to (3).

## Accounts, passwords, sessions

- Bootstrap: `python -m app.cli create-admin <username> [--display-name ...]` prompts for the
  password twice; it refuses once any active admin exists. There is no default account and no
  default password anywhere in the code.
- Usernames: 3-64 characters `[a-z0-9._-]`, case-folded. Accounts are never deleted (custody
  entries name them); `PATCH /api/users/{id}` with `active=false` deactivates and revokes every
  session. The last active admin cannot be demoted or deactivated.
- Password policy: 12-1024 characters, not equal to the username (length over composition, in
  the spirit of NIST SP 800-63B). No breach-list check (offline tool, no list bundled).
- Hash: `scrypt$<log2N>$<r>$<p>$<salt>$<key>` with N = 2^15, r = 8, p = 1, 16-byte random salt
  per hash, 32-byte key (Python `hashlib.scrypt`, OpenSSL). Comparison with
  `hmac.compare_digest`. Measured cost: 66.5 ms per hash on an Apple M1 (macOS 27). Unknown
  usernames run a dummy verification so timing does not reveal which usernames exist.
  `NIRIKSHAN_PASSWORD_SCRYPT_LOG2N` lowers the cost for the test suite only (minimum 10).
- Tokens: `nrk_` + 32 random bytes (urlsafe base64), returned once by `POST /api/auth/login`;
  the database stores only SHA-256(token).
- Expiry: absolute `NIRIKSHAN_SESSION_HOURS` (default 8 h) and idle
  `NIRIKSHAN_SESSION_IDLE_MINUTES` (default 30 min). `POST /api/auth/logout` revokes the session;
  a password change revokes the user's other sessions; an admin password reset or deactivation
  revokes all of them. Role changes take effect on the next request (the role is read from the
  users table every time).

## Login throttling and lockout

| Limit | Default | Storage | Variable |
|---|---|---|---|
| Failed logins per client address | 20 per 900 s sliding window, then 429 + `Retry-After` | in memory, at most 10 000 addresses (least recently failed evicted), per process, reset on restart | `NIRIKSHAN_LOGIN_ADDR_MAX_FAILURES`, `NIRIKSHAN_LOGIN_ADDR_WINDOW_S` |
| Consecutive failures per account | 5, then locked for 900 s; a correct password during the lock also fails | `users.failed_logins`, `users.locked_until` | `NIRIKSHAN_LOGIN_USER_MAX_FAILURES`, `NIRIKSHAN_LOGIN_USER_LOCK_S` |

Wrong password, unknown user, locked and deactivated accounts all get the same 401 body. An admin
can unlock early (`POST /api/users/{id}/unlock`). Behind a reverse proxy every request comes
from the proxy's address: set `NIRIKSHAN_TRUST_X_FORWARDED_FOR=1` only when that proxy appends
the client address to `X-Forwarded-For` (the last hop is used). The per-account lock means an
attacker who knows a username can lock that account out (denial of service); that is the usual
trade-off and is why admins can unlock.

## Roles and permissions

| Action | Admin | Examiner | Reviewer | Read-only |
|---|---|---|---|---|
| Manage users, unlock, reset passwords | yes | - | - | - |
| List cases | all cases | member cases | member cases | member cases |
| Read case metadata and member list | any case | member | member | member |
| Add/remove case members | any case | - | - | - |
| Create a case (creator becomes a member) | yes | yes | - | - |
| Read case contents (evidence, custody, runs, clips, video, timeline, analytics, reports, packages, transfers, jobs, performance) | member | member | member | member |
| Acquire, verify, analyse, jobs, analytics, OSD, time assumptions/references/model, generate report, request approval, build package, record transfer, enter manual baseline | member | member | - | - |
| Approve / reject a report | member, not author or requester | - | member, not author or requester | - |
| Finalise an approved report | member | member | member | - |
| Audit log | all | `?case_id=` of a member case | same | same |

How it is enforced: one global FastAPI dependency (`app.auth.policy.authorize`) runs before
every route. It picks the rule for the matched route template (explicit table, or the default
for case-scoped templates: GET = read, anything else = write), resolves every case-scoped path
parameter to its case, then checks membership and role. A route with no rule is refused (fail
closed), and `tests/test_auth_policy.py::test_every_route_has_an_access_rule` fails the build if
a newly added route has none. The cross-case test enumerates every registered route.

**404, not 403, for cases you are not a member of.** A missing object and an object in a case
you are not a member of produce the same status and body (e.g. `{"detail": "Evidence not
found"}`), so ids cannot be probed to learn that a case exists. A member whose role is not
allowed gets 403, because they already know the case exists. A path that names objects from two
different cases is refused with 404. Body fields that name objects (batch `evidence_ids`, job
`depends_on`) are checked against the path's case the same way.

**Admin and membership.** Admins manage accounts and memberships and can see every case's
metadata, but read or act on a case's contents only after adding themselves as a member. Every
membership change is a custody entry (`member_added` / `member_removed`) in that case's chain,
so an admin reading a case is visible in its custody log.

## Approvals and transfers

Report lifecycle: `draft -> pending_approval -> approved -> final`, or `pending_approval ->
rejected` (terminal; generate a new report). Approve/reject require a Reviewer or Admin who is
a case member, logged in as a user (not the dev header), and is neither the report's author nor
the requester (compared on user id, and on the recorded examiner string for reports created
before this module). Finalise re-hashes the stored PDF first. Every step writes a custody entry
(`report_approval_requested`, `report_approved`, `report_rejected`, `report_finalized`) and an
append-only `report_review_events` row; a `final` review row is immutable (database trigger
refuses UPDATE/DELETE). The PDF bytes are never rewritten (their SHA-256 is in the custody log):
the download carries the status in `X-Nirikshan-Report-Status` and in the file name
(`..._FINAL.pdf`), and the evidence package lists it.

Evidence transfers (`POST /api/evidence/{id}/transfers`): from, to, reason, the stated time of
the handover (ISO 8601 with a UTC offset, stored in UTC; server clock when omitted, and the entry
says which), optional location and seal number, recorded by the authenticated user. Each is a
custody entry `evidence_transferred` and an append-only `evidence_transfers` row, queryable per
evidence item and per case. A transfer record documents a physical handover the examiner
attests to; the software cannot observe the handover.

## Keys at rest

The custody signing key (`custody_ed25519`) and the package signing key (`package_ed25519`) live
in `NIRIKSHAN_KEY_DIR` (outside the data directory, 0600). By default each is an unencrypted
PKCS8 PEM, as before. Optional protection:

- `python -m app.cli protect-key [--key custody|package|all]` converts the PEM(s) to
  `<name>.key.enc`, reads the result back (same public key) and unlinks the PEM. Unlinking does
  not scrub old disk blocks, snapshots or backups: rotate the key if a plaintext copy may have
  been exposed.
- If `NIRIKSHAN_KEY_PASSPHRASE_FILE` (preferred: a 0600 file, first line used) or
  `NIRIKSHAN_KEY_PASSPHRASE` is set when no key exists yet, new keys are created protected.
- A protected key without a passphrase, or with a wrong one, fails closed: nothing is signed.
- The CLI prompts interactively (no echo) when neither variable is set and a terminal is present.
  The passphrase is never logged or stored; environment variables are visible to the same user
  (`ps eww`, `/proc/<pid>/environ`), which is why the file variant is preferred.
- `python -m app.cli key-status` prints the state of both keys.

File format (87 bytes): magic `NRKKEY01` (8), scrypt log2 N (1, default 15), r (1, 8), p (1, 1),
salt (16), AES-GCM nonce (12), AES-256-GCM ciphertext of the 32-byte raw Ed25519 private key with
its 16-byte tag (48). Key = scrypt(passphrase, salt, N, r, p, 32). The 39-byte header is the
AES-GCM associated data, so changing a parameter, the salt or the nonce fails like a changed
ciphertext. While the server runs the decrypted key is held in memory (re-deriving scrypt for
every custody entry would cost about 66 ms each).

## Disk encryption (the database and case data are not encrypted by the app)

Nirikshan does not encrypt its database, case workspaces (acquired images, clips, reports,
packages) or logs. Protect them with full-disk or volume encryption on the host:

- macOS: FileVault (System Settings > Privacy & Security > FileVault); for an external evidence
  disk, an APFS (Encrypted) volume.
- Linux: LUKS2 (`cryptsetup luksFormat`, then open and mount the data volume; for Docker put the
  named volumes on the encrypted mount).
- Windows (WSL/Docker Desktop hosts): BitLocker on the drive that holds the Docker data.

Encryption at rest protects a powered-off or stolen disk. It does not protect a running, unlocked
host from its own users.
