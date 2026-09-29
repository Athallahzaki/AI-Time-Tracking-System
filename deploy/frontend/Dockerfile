# Frontend Vue (Vite) -> static bundle, disajikan oleh Nginx yang sekaligus
# menjadi reverse proxy ke backend (/api) dan MediaMTX (/hls, /whep).
# Build context = ROOT repo. Ignore file: deploy/frontend/Dockerfile.dockerignore

ARG NODE_VERSION=22
ARG NGINX_VERSION=1.27

# ---------------------------------------------------------------------------
# Stage 1: build
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS build

WORKDIR /src

COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

COPY frontend/ ./

# useDetectionStream.ts memakai VITE_API_URL untuk SSE. Tanpa ini, di luar port
# 5173 frontend menembak http://localhost:8000 — yaitu localhost milik BROWSER,
# bukan server. Di balik Nginx cukup path relatif.
ARG VITE_API_URL=/api/detections/stream
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime (nginx)
# ---------------------------------------------------------------------------
FROM nginx:${NGINX_VERSION}-alpine AS runtime

# Template diproses envsubst oleh entrypoint image nginx saat container start
# -> /etc/nginx/conf.d/default.conf. Hanya variabel di NGINX_ENVSUBST_FILTER
# yang disubstitusi, sehingga variabel nginx ($host, $uri, ...) aman.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/frontend/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/frontend/nginx/templates/ /etc/nginx/templates/
COPY deploy/frontend/nginx/snippets/ /etc/nginx/snippets/

COPY --from=build /src/dist /usr/share/nginx/html

# Folder video demo dimount dari host (frontend/public/videos), tidak di-bake
# ke image. Direktori kosong ini hanya supaya /videos/ tidak 404 aneh.
RUN mkdir -p /usr/share/nginx/html/videos

ENV NGINX_ENVSUBST_FILTER="^(BACKEND_UPSTREAM|MEDIAMTX_HLS_UPSTREAM|MEDIAMTX_WHEP_UPSTREAM|BACKEND_API_KEY|NGINX_RESOLVER|CLIENT_MAX_BODY_SIZE)$" \
    BACKEND_UPSTREAM=http://backend:8000 \
    MEDIAMTX_HLS_UPSTREAM=http://mediamtx:8888 \
    MEDIAMTX_WHEP_UPSTREAM=http://mediamtx:8889 \
    BACKEND_API_KEY= \
    NGINX_RESOLVER=127.0.0.11 \
    CLIENT_MAX_BODY_SIZE=25m

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
