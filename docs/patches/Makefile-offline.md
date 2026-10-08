# Proposal: Makefile targets for the offline stack

The lead owns the `Makefile`. Proposed additions (not applied):

```make
# Offline packaging (see docs/OFFLINE_DEPLOYMENT.md). NIRIKSHAN_EVIDENCE_DIR must be set for up/down.
.PHONY: offline-build offline-models offline-save offline-up offline-down
offline-models:
	python scripts/fetch_models.py && python scripts/model_manifest.py write

offline-build:
	docker compose -f docker-compose.offline.yml build

offline-save: offline-build
	docker save nirikshan-offline-backend nirikshan-offline-frontend | gzip > nirikshan-offline-images.tar.gz
	sha256sum nirikshan-offline-images.tar.gz

offline-up:
	docker compose -f docker-compose.offline.yml -p nirikshan-offline up -d

offline-down:
	docker compose -f docker-compose.offline.yml -p nirikshan-offline down
```

`offline-down` omits `-v` on purpose: `down -v` deletes the case data and the custody signing key volumes.

Also proposed for CI: a job that runs `python scripts/licenses.py` and `python scripts/build_final_report.py --check`, failing on a diff.
