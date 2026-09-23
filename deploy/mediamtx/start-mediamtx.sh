#!/usr/bin/env sh
set -eu

DEPLOY_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$DEPLOY_DIR/.env.mediamtx"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.mediamtx.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker tidak ditemukan. Instal dan jalankan Docker terlebih dahulu." >&2
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  cp "$DEPLOY_DIR/.env.mediamtx.example" "$ENV_FILE"
  echo "deploy/mediamtx/.env.mediamtx telah dibuat. Isi CAM01_SOURCE, lalu jalankan script ini lagi." >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
sleep 3
python "$DEPLOY_DIR/../../scripts/check_mediamtx.py"

