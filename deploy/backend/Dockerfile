# Backend FastAPI — AI Time Tracking System.
# Build context = ROOT repo (lihat deploy/docker-compose.yml: context: ..).
# Ignore file khusus Dockerfile ini: deploy/backend/Dockerfile.dockerignore
#
# Backend meng-import `backend.*` dan `contracts.validator` (skema protokol),
# jadi keduanya disalin dengan struktur yang sama seperti di repo.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependensi dulu supaya layer ini ter-cache selama requirements tidak berubah.
# tzdata: ZoneInfo("Asia/Jakarta") di break_policy butuh database zona waktu,
# dan image slim tidak menjaminnya.
COPY backend/requirements.txt /tmp/requirements-backend.txt
COPY contracts/validator/requirements.txt /tmp/requirements-contracts.txt
RUN pip install -r /tmp/requirements-backend.txt -r /tmp/requirements-contracts.txt tzdata

# Kode aplikasi.
COPY contracts/ /app/contracts/
COPY backend/ /app/backend/

# User non-root + direktori data (SQLite) yang dimiliki user tersebut.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /data \
 && chown -R app:app /data

USER app

ENV BACKEND_DB_PATH=/data/backend.db \
    CAMERAS_CONFIG=/app/backend/configs/cameras.yaml \
    POLICY_CONFIG=/app/backend/configs/policy.yaml \
    ENGINE_HOST=host.docker.internal \
    ENGINE_PORT=8765 \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4); sys.exit(0)" || exit 1

# SATU worker saja: koneksi ke engine, view stream, dan state live disimpan
# in-process. Beberapa worker = beberapa koneksi engine yang saling rebutan
# checkpoint last_event_seq.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host \"$UVICORN_HOST\" --port \"$UVICORN_PORT\" --workers 1 --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10"]
