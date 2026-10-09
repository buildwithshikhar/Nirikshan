# Round D log (resume point for a fresh session)

Format: newest entry last. Each entry: what landed (commit), what ran, what is unverified, what is next.

## 2026-10-09 Step -1
- Repo clean and in sync with origin/main (b68098a), CI green, Docker up, 32 GB free.
- Wrote `PS_GAP_ANALYSIS.md`, `ROUND_D_PLAN.md`, `ROUND_D_UI_MAP.md`.
- Next: Wave 1 streams 1 and 2 in worktrees (max 2 at a time), then stream 3.

## Stream 2 merged (acquisition, identification, explorer, recovery, OEM registry)
- Fast-forwarded from worktree branch; wired in `main.py`; SCHEMA_VERSION 9. SQLite suite: 554 passed, 1 skipped.
- Deferred: E01 ingest, firmware identification, signature checks on exports (see ROUND_D_DEFERRED.md). Recoverability agreement is weak (Pearson 0.44) and is documented as such.
- Worktree branch deleted after the merge (`git branch -d`, confirmed merged).
- Pending: Streams 1 and 3 running; API.md / SECURITY_REVIEW / CHANGELOG / tier tables updated at the end.

## Stream 3 merged (events, correlation, validation center)
- Cherry-picked 4 commits (docs conflict in ROUND_D_DEFERRED.md resolved by keeping both sections); wired in `main.py`; SCHEMA_VERSION 10. SQLite suite with both streams: 600 passed, 1 skipped.
- Worktree branch `worktree-agent-a4135574fc8433f29` deleted with `-D` after `git cherry` showed its code commits present (the fourth differs only by the conflict resolution; code dirs diff empty).
- Pending: optional `index_after_run` hook in `analytics/routes.py` (after Stream 1 lands, to avoid conflicting edits). Stream 1 still running.

## Stream 1 merged; Wave 1 gates (2026-10-09)
- Stream 1 (auth/RBAC, approvals/transfers, packages, workers/chains/batches, performance, key passphrase) cherry-picked with conflicts in `main.py`, `schema.py` and `ROUND_D_DEFERRED.md` resolved by keeping both sides; SCHEMA_VERSION 11. Worktree branch deleted with `-D` after the merged suite (692 tests = 491 + 63 + 46 + 92) passed.
- Added `POLICY` rules for the 18 stream 2/3 routes that had no case-scoped path parameter (reference data = any authenticated user; validation re-run = admin or examiner) and resolvers for acquisition session, external log and correlation link ids. Added the auto-index hook after analytics runs (with a test).
- `make demo` and the Playwright config set `NIRIKSHAN_DEV_HEADER_AUTH=1` because the UI still uses the X-Examiner header until Part 2 builds login.
- Ran: SQLite suite 693 passed + 1 skipped (694 collected); Postgres 16 suite (this repo's compose db, then `docker compose down`, no `-v`): 691 passed, 2 failed (SQLite-specific expectations in the new event tests), fixed and re-run 25/25 for that file on both databases; Playwright 30/30; `make validate` thresholds PASS, digest unchanged (`ba75170e...`); `make demo` seeded and custody verified; `pip-audit` clean, no new dependencies.
- Unverified: Postgres full-suite rerun after the 2-test fix (only that file re-run); Linux resource limits; real-device behaviour of anything.
- Next: Part 2 (frontend from `ROUND_D_UI_MAP.md`).
