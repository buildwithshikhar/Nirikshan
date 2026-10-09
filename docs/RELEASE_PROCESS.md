# Release process

1. Work on a branch or locally; run the backend suite (`cd backend && python -m pytest`), `ruff check`, and the frontend `npm run lint`, `tsc -b`, `npm run build`.
2. Push to `main`. CI (`.github/workflows`) runs the backend suite, the report check and the frontend gates; wait for it to be green.
3. Both hosts redeploy from `main`: the Docker host (`git pull && docker compose -f docker-compose.prod.yml -p nirikshan-prod up -d --build`) and the static frontend host (Vercel redeploys on push when connected).
4. Run the smoke test against each deployed backend: `NIRIKSHAN_SMOKE_USERNAME=... NIRIKSHAN_SMOKE_PASSWORD=... python scripts/smoke_test.py --base-url https://HOST`. It checks `/healthz`, login, case list, report generation and download, the custody chain, and logout.
5. Rollback: redeploy the previous commit (`git checkout <previous-sha>` then the same `up -d --build`; on Vercel, promote the previous deployment). The schema version must match the database: a release that bumps `SCHEMA_VERSION` cannot be rolled back onto the newer database without restoring a backup (see docs/DEPLOYMENT.md, Backup).
