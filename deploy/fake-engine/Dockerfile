# Fake engine (engine/tools/fake_engine) — memutar skenario protokol tanpa
# kamera, GPU, atau model. Dipakai lewat profile `demo` di docker-compose.yml
# untuk menguji frontend+backend end-to-end. BUKAN engine produksi.
# Build context = ROOT repo. Ignore file: deploy/fake-engine/Dockerfile.dockerignore

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN pip install "PyYAML>=6,<7"

# Hanya paket yang dibutuhkan fake_engine: engine/api (outbox) + tools/fake_engine.
COPY engine/__init__.py        /app/engine/__init__.py
COPY engine/api/               /app/engine/api/
COPY engine/tools/__init__.py  /app/engine/tools/__init__.py
COPY engine/tools/fake_engine/ /app/engine/tools/fake_engine/

RUN useradd --system --uid 10002 --home-dir /app --shell /usr/sbin/nologin engine
USER engine

ENV FAKE_SCENARIO=happy-path \
    FAKE_SPEED=1 \
    FAKE_LISTEN=0.0.0.0:8765

EXPOSE 8765

CMD ["sh", "-c", "exec python -m engine.tools.fake_engine --scenario \"$FAKE_SCENARIO\" --tcp \"$FAKE_LISTEN\" --speed \"$FAKE_SPEED\" --loop -v"]
