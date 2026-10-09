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
