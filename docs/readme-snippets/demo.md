## Demo (SYNTHETIC data only)

```
make demo
```

Starts the backend and the web UI with a throw-away data directory (`./demo-data`, demo-only
signing key), builds the case `DEMO-SYNTHETIC-001` from three generated images (Hikvision and Dahua
per-paper layouts, a raw H.264 image), runs the analysis as background jobs with progress, sets time
assumptions (one image is left with an unknown timezone on purpose), runs triage analytics and
prints the URLs. Ctrl-C stops everything. Every image, label and screen is marked SYNTHETIC: this is
generated test data, not real DVR/NVR evidence, and the demo does not validate any real device.
`make demo-data` builds the same case against a backend that is already running. Details:
[docs/demo.md](docs/demo.md); background jobs: [docs/jobs.md](docs/jobs.md); accessibility status:
[docs/accessibility.md](docs/accessibility.md).
