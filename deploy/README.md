# Deployment (Docker Compose)

Semua berkas deployment tinggal di folder ini. Build context tetap root repo
(`..`), tetapi Dockerfile, ignore file, dan konfigurasi nginx tidak disebar ke
`frontend/` atau `backend/`.

```
deploy/
├── docker-compose.yml          # MAIN compose: frontend + backend (+ profile mediamtx, demo)
├── .env.example                # semua variabel; salin ke .env
├── backend/
│   ├── Dockerfile              # python:3.11-slim, uvicorn 1 worker, user non-root
│   └── Dockerfile.dockerignore # whitelist backend/ + contracts/
├── frontend/
│   ├── Dockerfile              # node build -> nginx:alpine
│   ├── Dockerfile.dockerignore # whitelist frontend/ + nginx conf
│   └── nginx/
│       ├── nginx.conf
│       ├── templates/default.conf.template   # envsubst saat start
│       └── snippets/{proxy-common,security-headers}.conf
├── fake-engine/
│   ├── Dockerfile              # engine/tools/fake_engine, tanpa GPU
│   └── Dockerfile.dockerignore
└── mediamtx/                   # relay CCTV (dipakai main compose & standalone)
    ├── mediamtx.yml
    ├── docker-compose.mediamtx.yml  # standalone, untuk mode dev (run_demo.py)
    ├── .env.mediamtx.example
    ├── start-mediamtx.{sh,ps1}
    └── README.md
```

`Dockerfile.dockerignore` adalah ignore file per-Dockerfile milik BuildKit
(default sejak Docker 23). Jadi tidak perlu `.dockerignore` di root repo.

## Topologi

```
browser ──:80──> frontend (nginx) ──/api/*──────────> backend:8000 ──TCP──> engine:8765
                                  ├─/hls/*  ──> mediamtx:8888
                                  ├─/whep/* ──> mediamtx:8889   (media WebRTC: UDP 8189 langsung)
                                  └─/videos/* ─> frontend/public/videos (mount read-only)
```

Hanya port 80 yang dibuka ke jaringan. Backend dipublish ke `127.0.0.1:8000`
untuk debugging saja.

## Mulai cepat

```bash
cd deploy
cp .env.example .env        # sesuaikan
docker compose up -d --build
docker compose ps
docker compose logs -f backend
```

Dashboard: `http://<ip-server>/`. API docs: `http://<ip-server>/docs`.

### Profile

| Perintah | Isi |
|---|---|
| `docker compose up -d` | frontend + backend. Engine asli di host. |
| `docker compose --profile mediamtx up -d` | + MediaMTX (isi `CAM01_SOURCE`). |
| `docker compose --profile demo up -d` | + fake engine. Set `ENGINE_HOST=fake-engine` di `.env`. |

Profile bisa digabung: `--profile mediamtx --profile demo`.

## Engine asli (GPU)

Engine D-FINE belum dikontainerkan: butuh CUDA, weights, dan akses kamera,
dan itu keputusan terpisah. Backend di container menjangkaunya lewat
`host.docker.internal`, jadi engine **harus listen di 0.0.0.0**:

```bash
python -m engine.runtime --config engine/config/dfine-m.yaml --tcp 0.0.0.0:8765
```

Dengan `--tcp 127.0.0.1:8765` (default lama) backend di container akan
reconnect selamanya. Di Linux, pastikan firewall mengizinkan bridge Docker ke
port 8765. Jangan buka 8765 ke LAN — protokol engine tidak punya autentikasi.

Catatan `source_uri` di `cameras.yaml` dibaca oleh **engine** (di host),
bukan oleh backend, jadi path relatif seperti `frontend/public/videos/...`
tetap relatif ke direktori kerja engine.

## Konfigurasi kamera & policy

`backend/configs/` di-mount read-only ke container. Pilih berkas lewat
`CAMERAS_CONFIG_FILE` / `POLICY_CONFIG_FILE` di `.env`, edit, lalu:

```bash
docker compose restart backend
```

`stream_url` yang benar di balik nginx: `/whep/<path>/whep`,
`/hls/<path>/index.m3u8`, atau `/videos/<file>.mp4`. Jangan pakai
`http://localhost:8889/...` — itu localhost milik browser, bukan server.

## Data

SQLite backend ada di volume `ai-time-tracking-backend-data` (`/data/backend.db`).

```bash
# backup
docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('/data/backend.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
docker compose cp backend:/data/backup.db ./backend-backup.db
```

`docker compose down -v` **menghapus** volume ini beserta seluruh event
kehadiran. Pakai `down` tanpa `-v`.

## API key

Kalau `BACKEND_API_KEY` diisi, nginx menyuntikkan `X-API-Key` ke setiap
request `/api`. Artinya kunci ini melindungi port backend langsung, **bukan**
dashboard — siapa pun yang bisa membuka port 80 tetap bisa mengubah data.
Autentikasi pengguna masih pekerjaan terbuka; sampai itu ada, batasi akses
port 80 (`HTTP_BIND`, firewall, VPN).

## Update

```bash
git pull
cd deploy
docker compose build
docker compose up -d
```

`VITE_API_URL` di-bake saat build frontend; mengubahnya butuh rebuild.
Perubahan nginx template cukup `docker compose up -d --build frontend`.
