# Nirikshan backend image (offline deployment). Build context = REPOSITORY ROOT:
#   docker build -f backend/Dockerfile -t nirikshan-offline-backend .
# Python 3.12-slim: the CI matrix tests 3.10 and 3.12, and all pinned wheels (onnxruntime,
# opencv, rapidocr) have 3.12 builds. No secrets are baked in: the custody signing key is
# generated at first run into the key volume (NIRIKSHAN_KEY_DIR), never into the image.

# ---- stage 1: analytics models, SHA-256 verified. Fails the build on any mismatch. -------------
# Needs network at BUILD time only. For a fully air-gapped build, build on a connected machine
# and transfer the image (docs/OFFLINE_DEPLOYMENT.md), or mount models from a read-only volume.
FROM python:3.12-slim AS models
WORKDIR /src
COPY scripts/fetch_models.py scripts/model_manifest.py scripts/
COPY backend/app/analytics/registry.py backend/app/analytics/registry.py
# registry.py is stdlib-only; stub the package markers so fetch_models.py can import it.
RUN touch backend/app/__init__.py backend/app/analytics/__init__.py \
 && mkdir -p backend/models \
 && python scripts/fetch_models.py \
 && python scripts/model_manifest.py write --dir backend/models --out backend/models/SHA256SUMS \
 && python scripts/model_manifest.py verify --dir backend/models --manifest backend/models/SHA256SUMS

# ---- stage 2: runtime --------------------------------------------------------------------------
FROM python:3.12-slim
# ffmpeg + ffprobe come from the Debian package (a GPL build, see docs/THIRD_PARTY_LICENSES.md).
# libgl1/libglib2.0-0: shared libraries needed by the opencv-python wheel that rapidocr pulls in.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && ffmpeg -version | head -1 && ffprobe -version | head -1 \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin nirikshan
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=models /src/backend/models /opt/nirikshan/models
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NIRIKSHAN_MODELS_DIR=/opt/nirikshan/models \
    NIRIKSHAN_DATA_DIR=/var/lib/nirikshan/data \
    NIRIKSHAN_KEY_DIR=/var/lib/nirikshan/keys \
    DATABASE_URL=sqlite:////var/lib/nirikshan/data/nirikshan.db
# Mount points exist and are owned by the service user so a fresh named volume inherits ownership.
RUN mkdir -p /var/lib/nirikshan/data /var/lib/nirikshan/keys /evidence /incoming \
 && chown -R nirikshan:nirikshan /var/lib/nirikshan /incoming && chmod 700 /incoming && chmod 700 /var/lib/nirikshan/keys
USER nirikshan
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
