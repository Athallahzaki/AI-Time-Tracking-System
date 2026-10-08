# Deploy Portainer (engine di laptop via NetBird) + kotak hantu di overlay + uji A/B 4060

Tanggal: 8 Okt 2026. Dasar: repo 8 Okt + paket backend r6.

Paket kumulatif r7: isi r6 ditambah perubahan di bawah. Menggantikan semua paket sebelumnya.

## 1. Kotak hantu: satu orang tampil dengan 2-3 kotak

**Penyebab.** `ByteTrackTracker.update()` (`engine/perception/bytetrack_tracker.py`) mengembalikan track yang hilang dengan state `LOST` selama `track_buffer_seconds` (1 dtk), memakai kotak **terakhir yang membeku**. Masa tenggang ini benar untuk presensi. Tapi `_maybe_view` (`engine/runtime/camera.py`) mengirim semua track ke kanal view tanpa memeriksa state. Saat ByteTrack memberi ID baru ke orang yang sama (ID switch), kotak lama membeku sampai 1 dtk di samping kotak baru. Dua switch dalam sedetik menghasilkan tiga kotak.

**Perbaikan.** Overlay hanya mengirim track `NEW`/`TRACKED`, ditambah track `LOST` yang baru hilang ≤ 0,3 dtk (`VIEW_LOST_GRACE_SECONDS`). Pengecualian 0,3 dtk itu supaya satu frame tanpa deteksi tidak membuat kotak berkedip. Presensi tidak berubah: `_remember_live` dan assembler tetap memakai masa tenggang penuh. Frame tanpa track aktif tetap dikirim kosong, supaya browser berhenti menggambar kotak lama.

**Yang tidak diperbaiki di sini:**
- **ID switch itu sendiri.** Penyetelan tracker, atau nanti ReID.
- **Deteksi ganda dari D-FINE.** Dua kotak yang sama-sama bergerak menempel satu orang.

Kalau setelah ini masih ada kotak ganda yang *ikut bergerak*, penyebabnya salah satu dari dua itu.

## 2. Uji A/B 4060

Protokolnya ada di `docs/DEMO-REMOTE.md` §8. Empat run 15 menit di laptop saja:
- **R0:** semua perubahan run 3;
- **R1:** tanpa `-r 25`;
- **R2:** tanpa afinitas;
- **R3:** power throttling ffmpeg/mediamtx di-reset.

`scripts/summarize_gladi.py` meringkas semuanya dalam satu tabel dengan vonis. Untuk tiga gladi 8 Okt, vonisnya sama dengan bacaan manual:

```
file                         menit fps med  lambat ganti drop/s umur med   p95   p99  maks stall  vonis
8015b0e3-gladi-4060-15m.csv   14.0    6.12   55.8%     4   13.9     0.42  3.62  6.83  8.93     2  GAGAL
4c27bf36-gladi-4060-15m.csv   14.0    5.92   84.9%     6   23.3     0.63  3.23  4.22  4.45     3  GAGAL
79f4d808-gladi-4060-15m_1.cs  14.0   10.00    0.0%     0    0.0     0.04  0.07  0.09  0.10     0  LULUS
```

## 3. Deploy Portainer

Isi sama dengan paket sebelumnya:
- **Laptop:** ffmpeg, MediaMTX, dan engine.
- **Server Portainer CE:** backend dan frontend.
- **Lewat NetBird:** backend → engine :8765, dan nginx → MediaMTX laptop :8888/:8889.
- **Video:** HLS (default); WebRTC opsional lewat TCP 8189 di IP publik VPS.

Masalah compose lama yang diselesaikan:

| Masalah di compose lama | Akibat | Di compose Portainer |
|---|---|---|
| Tidak ada `env_file` | Admin tidak terbentuk, tidak bisa login, email mati | `env_file: stack.env` |
| `backend/configs` di-mount `:ro` | Ubah batas waktu gagal | `policy.yaml` di `/data`, disalin dari image saat start pertama |
| Bind mount relatif | Tidak menunjuk ke host di Portainer CE | Dihapus; config ikut image |
| `localhost` di config kamera | Engine dan browser membuka mesin yang salah | `rtsp://127.0.0.1` (dibuka engine di laptop) dan path relatif |

Perubahan dari paket sebelumnya: `start-engine.ps1` sekarang memakai `-BindIp` (alias `-NetBirdIp` tetap jalan), supaya bisa dipakai untuk uji A/B di `127.0.0.1`. Runbook menambah §8 (uji A/B), satu baris checklist afinitas, dan satu baris gejala kotak ganda.

## Daftar file

| File | Status | Isi |
|---|---|---|
| `engine/runtime/camera.py` | UBAH | Kotak hantu: konstanta, filter di `_maybe_view`, helper `_recently_seen`. |
| `deploy/docker-compose.portainer.yml` | BARU | Compose khusus Portainer: backend + frontend, `env_file: stack.env`, tanpa bind mount relatif, `policy.yaml` di volume `/data`. |
| `deploy/portainer.env.example` | BARU | Variabel untuk ditempel di UI Portainer (Advanced mode). |
| `backend/configs/cameras.remote-hls.yaml` | BARU | Kamera mode remote, video HLS (default). |
| `backend/configs/cameras.remote-webrtc.yaml` | BARU | Kamera mode remote, video WebRTC (opsional). |
| `deploy/laptop/start-mediamtx.ps1` | BARU | MediaMTX di laptop dengan config repo; `-VpsPublicIp` untuk WebRTC. |
| `deploy/laptop/start-engine.ps1` | BARU | Engine yang hanya mendengarkan di `-BindIp` (IP NetBird, atau 127.0.0.1 untuk uji A/B); afinitas opsional. |
| `deploy/laptop/firewall.ps1` | BARU | Firewall Windows: port dibuka hanya untuk IP NetBird server/VPS; `-Remove` untuk membersihkan. |
| `deploy/vps/nginx-stream-webrtc.conf` | BARU | Penerusan TCP 8189 di VPS ke laptop (hanya WebRTC). |
| `scripts/summarize_gladi.py` | BARU | Ringkasan dan vonis LULUS/GAGAL dari satu atau beberapa CSV `lag_probe`. |
| `engine/tests/test_view_overlay_states.py` | BARU | Mengunci perbaikan kotak hantu (3 tes). |
| `engine/tests/test_summarize_gladi.py` | BARU | Tes `summarize_gladi.py` (4 tes). |
| `docs/DEMO-REMOTE.md` | BARU | Runbook demo jarak jauh, termasuk §8 uji A/B 4060. |
| `deploy/.gitignore` | UBAH | Tambah `stack.env`. |

Semua file CRLF.

## Uji

- **Seluruh tes:** `pytest` (contracts + engine + backend) **658 lulus**, 7 di-skip. Tes skip memang butuh GPU atau model.
- **Tes overlay:** ketiganya **gagal di `camera.py` lama** dan lulus di yang baru.
- **`summarize_gladi.py`:** dicek pada tiga CSV gladi 8 Okt (tabel di §2), plus 4 tes sintetis.
- **Deploy:**
  - `docker compose config` valid.
  - Backend dengan env setara container: admin login 200, `/api/cameras` benar, ubah policy 200 dengan komentar utuh.
  - Skrip `.ps1` lolos parser PowerShell 7.4.
- **Belum bisa diuji di sandbox:**
  - build dan jalan di Docker atau Portainer;
  - `stack.env` di Portainer CE;
  - skrip Windows (`Get-NetIPAddress`, firewall);
  - NetBird, VPS, dan Cloudflare;
  - WebRTC TCP.

---

## Isi file

### `engine/runtime/camera.py` (UBAH, 3 tempat)

**(a)** Di bagian konstanta, tepat di bawah `DEFAULT_VIEW_FPS = 10.0`:

```python
# Track LOST masih digambar sebentar supaya satu frame tanpa deteksi tidak
# membuat kotak berkedip; lebih dari ini kotaknya hantu (posisi membeku).
VIEW_LOST_GRACE_SECONDS = 0.3
```

**(b)** Di `_maybe_view`, awal loop `for track in tracks:`, sebelum `uuid = track.attributes.get("track_uuid")`:

```python
        boxes = []
        for track in tracks:
            # Track LOST (masa tenggang track_buffer_seconds) membawa kotak
            # TERAKHIR yang membeku. Digambar selama masa tenggang penuh, ia jadi
            # kotak hantu di samping track baru orang yang sama setelah ID
            # switch -> "2-3 kotak per orang". Hanya overlay yang dipangkas;
            # presensi (_remember_live, assembler) tetap memakai masa tenggang.
            if not track.is_active and not _recently_seen(track, frame):
                continue
            uuid = track.attributes.get("track_uuid")
```

**(c)** Fungsi baru di tingkat modul, tepat di atas `def _normalized(track: Track, frame: Frame)`:

```python
def _recently_seen(track: Track, frame: Frame) -> bool:
    """LOST yang baru sekejap (< VIEW_LOST_GRACE_SECONDS) tetap digambar."""
    if track.state != TrackState.LOST:
        return False
    return (frame.timestamp - track.last_seen_timestamp) <= VIEW_LOST_GRACE_SECONDS
```

`TrackState` sudah di-import di file ini (`from ..ports.tracking import Track, TrackState`).

### `deploy/docker-compose.portainer.yml` (BARU)

Compose khusus Portainer: backend + frontend, `env_file: stack.env`, tanpa bind mount relatif, `policy.yaml` di volume `/data`.

```yaml
# =============================================================================
# AI Time Tracking System — compose untuk Portainer (server), engine di laptop
#
# Topologi demo jarak jauh (docs/DEMO-REMOTE.md):
#
#   LAPTOP (lokasi)                         SERVER (Portainer CE)
#   ffmpeg -> MediaMTX -> engine            frontend (nginx) + backend
#                ^          ^                    |            |
#                |          +---- TCP 8765 ------+------------+  backend -> engine
#                +-- HTTP 8888/8889 (HLS/WHEP) <-+  nginx -> MediaMTX laptop
#
#   Semua lintas mesin lewat NetBird. Penonton: Cloudflare -> VPS -> NetBird -> :80.
#
# Beda dengan deploy/docker-compose.yml (alur lokal, tidak diubah):
#   - Tanpa bind mount relatif. Portainer CE meng-clone repo ke dalam
#     container-nya sendiri, jadi path seperti ../backend/configs tidak
#     menunjuk ke host. Config kamera ikut image (Dockerfile meng-COPY backend/),
#     policy.yaml disalin ke volume /data saat start pertama supaya bisa diubah
#     dari halaman Pengaturan.
#   - env_file: stack.env. Variabel di UI Portainer hanya mengisi ${...} di file
#     ini; tanpa env_file, INITIAL_ADMIN_PASSWORD dan SMTP_* tidak sampai ke
#     container (admin tidak terbentuk, tidak ada yang bisa login).
#   - Tanpa MediaMTX dan fake engine: MediaMTX jalan di laptop.
#
# Portainer: Stacks -> Add stack -> Repository
#   Compose path : deploy/docker-compose.portainer.yml
#   Environment  : isi dari deploy/portainer.env.example
#   GitOps update: MATIKAN di hari demo.
#
# Tanpa Portainer (uji di server lewat CLI), dari folder deploy/:
#   cp portainer.env.example stack.env   # lalu isi
#   docker compose -f docker-compose.portainer.yml --env-file stack.env up -d --build
# =============================================================================

name: ${COMPOSE_PROJECT_NAME:-ai-time-tracking}

x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"

services:
  backend:
    build:
      context: ..
      dockerfile: deploy/backend/Dockerfile
    image: ${IMAGE_PREFIX:-ai-time-tracking}/backend:${IMAGE_TAG:-latest}
    restart: unless-stopped
    # Semua variabel stack (admin awal, SMTP, DASHBOARD_URL, AUTH_SESSION_HOURS)
    # diteruskan apa adanya. Yang di `environment:` di bawah menimpanya.
    env_file:
      - stack.env
    environment:
      TZ: ${TZ:-Asia/Jakarta}
      # IP NetBird laptop (100.x.y.z), BUKAN nama *.netbird.cloud: DNS NetBird
      # terpasang di host, container tidak bisa me-resolve-nya.
      ENGINE_HOST: ${LAPTOP_NETBIRD_IP:?isi LAPTOP_NETBIRD_IP dengan IP NetBird laptop}
      ENGINE_PORT: ${ENGINE_PORT:-8765}
      ENGINE_RECONNECT_SECONDS: ${ENGINE_RECONNECT_SECONDS:-2}
      CAMERAS_CONFIG: /app/backend/configs/${CAMERAS_CONFIG_FILE:-cameras.remote-hls.yaml}
      POLICY_CONFIG: /data/policy.yaml
      BACKEND_DB_PATH: /data/backend.db
    # Sama dengan CMD di Dockerfile, ditambah penyalinan policy.yaml awal ke
    # /data. File di image tetap jadi bawaan; perubahan dari UI tinggal di volume.
    command:
      - sh
      - -c
      - >-
        [ -f /data/policy.yaml ] || cp /app/backend/configs/policy.yaml /data/policy.yaml;
        exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
        --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10
    volumes:
      - backend-data:/data
    # Hanya untuk debugging di server. Akses normal lewat nginx (/api).
    ports:
      - "127.0.0.1:${BACKEND_PORT:-8000}:8000"
    networks: [app]
    logging: *default-logging

  frontend:
    build:
      context: ..
      dockerfile: deploy/frontend/Dockerfile
      args:
        VITE_API_URL: ${VITE_API_URL:-/api/detections/stream}
    image: ${IMAGE_PREFIX:-ai-time-tracking}/frontend:${IMAGE_TAG:-latest}
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy
    environment:
      TZ: ${TZ:-Asia/Jakarta}
      BACKEND_UPSTREAM: http://backend:8000
      # /hls/ dan /whep/ diteruskan nginx ke MediaMTX di laptop lewat NetBird.
      MEDIAMTX_HLS_UPSTREAM: http://${LAPTOP_NETBIRD_IP:?isi LAPTOP_NETBIRD_IP}:8888
      MEDIAMTX_WHEP_UPSTREAM: http://${LAPTOP_NETBIRD_IP:?isi LAPTOP_NETBIRD_IP}:8889
      BACKEND_API_KEY: ${BACKEND_API_KEY:-}
      CLIENT_MAX_BODY_SIZE: ${CLIENT_MAX_BODY_SIZE:-25m}
    ports:
      - "${HTTP_BIND:-0.0.0.0}:${HTTP_PORT:-80}:80"
    networks: [app]
    logging: *default-logging

networks:
  app:
    name: ${COMPOSE_PROJECT_NAME:-ai-time-tracking}-net

volumes:
  backend-data:
    name: ${COMPOSE_PROJECT_NAME:-ai-time-tracking}-backend-data
```

### `deploy/portainer.env.example` (BARU)

Variabel untuk ditempel di UI Portainer (Advanced mode).

```bash
# =============================================================================
# Variabel stack Portainer untuk deploy/docker-compose.portainer.yml
#
# Portainer: Stacks -> stack -> Environment variables -> "Advanced mode",
# tempel isi file ini lalu isi nilainya. Portainer menyimpannya sebagai
# stack.env, yang diteruskan ke backend lewat env_file.
#
# Uji lewat CLI: cp portainer.env.example stack.env (stack.env di-gitignore).
# JANGAN commit nilai asli (password admin, SMTP).
# =============================================================================

# --- Umum --------------------------------------------------------------------
COMPOSE_PROJECT_NAME=ai-time-tracking
IMAGE_PREFIX=ai-time-tracking
IMAGE_TAG=latest
TZ=Asia/Jakarta

# --- Laptop engine (NetBird) ------------------------------------------------
# IP NetBird laptop (100.x.y.z), lihat `netbird status` di laptop.
# Dipakai backend (engine :8765) dan nginx (MediaMTX :8888 HLS, :8889 WHEP).
LAPTOP_NETBIRD_IP=
ENGINE_PORT=8765
ENGINE_RECONNECT_SECONDS=2

# --- Kamera ------------------------------------------------------------------
# cameras.remote-hls.yaml    : HLS lewat domain (aman di jaringan mana pun)
# cameras.remote-webrtc.yaml : WebRTC, media TCP 8189 lewat IP publik VPS
CAMERAS_CONFIG_FILE=cameras.remote-hls.yaml

# --- Frontend / nginx --------------------------------------------------------
HTTP_BIND=0.0.0.0
HTTP_PORT=80
VITE_API_URL=/api/detections/stream
CLIENT_MAX_BODY_SIZE=25m

# --- Backend -----------------------------------------------------------------
BACKEND_PORT=8000
DETECTION_RETENTION_DAYS=7
BACKEND_API_KEY=

# Admin pertama, dibuat saat backend start bila username ini belum ada.
# Password minimal 8 karakter. Tanpa ini tidak ada yang bisa login.
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=
AUTH_SESSION_HOURS=8

# Alamat publik dashboard (dipakai di tautan email).
DASHBOARD_URL=https://dashboard.contoh.id

# --- Email / SMTP ------------------------------------------------------------
SMTP_ENABLED=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_TO=
SMTP_TIMEOUT_SECONDS=10
```

### `backend/configs/cameras.remote-hls.yaml` (BARU)

Kamera mode remote, video HLS (default).

```yaml
# Mode remote, video lewat HLS (docs/DEMO-REMOTE.md).
# Engine dan MediaMTX jalan di LAPTOP; backend dan frontend di server.
#
# source_uri dikirim backend ke engine (set_cameras) dan dibuka OLEH ENGINE,
# jadi 127.0.0.1 di sini berarti laptop itu sendiri. Pakai 127.0.0.1, bukan
# localhost: di Windows localhost bisa ke ::1 dulu.
#
# stream_url diputar browser lewat nginx server (/hls/ -> MediaMTX laptop).
# HLS lewat Cloudflare seperti halaman web biasa, dan overlay disinkronkan
# dengan PROGRAM-DATE-TIME dari MediaMTX (jam laptop, sama dengan engine).
cameras:
  - id: "r1"
    code: "CAM-01"
    name: "Entertainment Room"
    source_uri: "rtsp://127.0.0.1:8554/cam01"
    stream_url: "/hls/cam01/index.m3u8"
    enabled_by_default: true
    fps: 25
```

### `backend/configs/cameras.remote-webrtc.yaml` (BARU)

Kamera mode remote, video WebRTC (opsional).

```yaml
# Mode remote, video lewat WebRTC (docs/DEMO-REMOTE.md, bagian WebRTC).
# Sama dengan cameras.remote-hls.yaml, hanya stream_url yang berbeda.
#
# Signalling WHEP lewat domain (nginx server -> MediaMTX laptop :8889).
# Media lewat TCP 8189 di IP publik VPS -> NetBird -> laptop. Butuh:
#   - MediaMTX laptop dengan webrtcLocalTCPAddress :8189 dan
#     webrtcAdditionalHosts = IP publik VPS (start-mediamtx-laptop.ps1 -VpsPublicIp)
#   - penerusan TCP 8189 di VPS (deploy/vps/nginx-stream-webrtc.conf)
# Jaringan yang hanya membuka 80/443 akan memblokir 8189: kembali ke HLS.
cameras:
  - id: "r1"
    code: "CAM-01"
    name: "Entertainment Room"
    source_uri: "rtsp://127.0.0.1:8554/cam01"
    stream_url: "/whep/cam01/whep"
    enabled_by_default: true
    fps: 25
```

### `deploy/laptop/start-mediamtx.ps1` (BARU)

MediaMTX di laptop dengan config repo; `-VpsPublicIp` untuk WebRTC.

```powershell
<#
.SYNOPSIS
  MediaMTX di laptop untuk demo jarak jauh (docs/DEMO-REMOTE.md).

.DESCRIPTION
  Memakai deploy/mediamtx/mediamtx.yml dari repo (path cam01 = publisher,
  RTSP 8554, HLS 8888, WHEP 8889). Tanpa -VpsPublicIp: cukup untuk mode HLS.
  Dengan -VpsPublicIp: WebRTC juga menerima media lewat TCP 8189 dan
  mengiklankan IP publik VPS sebagai kandidat ICE (mode cameras.remote-webrtc).

.EXAMPLE
  .\deploy\laptop\start-mediamtx.ps1 -MediaMtxExe C:\Users\Athallah\Desktop\test\mediamtx.exe

.EXAMPLE
  .\deploy\laptop\start-mediamtx.ps1 -MediaMtxExe C:\tools\mediamtx.exe -VpsPublicIp 203.0.113.10
#>
param(
    [string]$MediaMtxExe = "mediamtx.exe",
    [string]$VpsPublicIp = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Config = Join-Path $RepoRoot "deploy\mediamtx\mediamtx.yml"

if (-not (Test-Path $Config)) { throw "Config MediaMTX tidak ditemukan: $Config" }
$exe = Get-Command $MediaMtxExe -ErrorAction SilentlyContinue
if (-not $exe) { throw "mediamtx.exe tidak ditemukan: $MediaMtxExe (isi -MediaMtxExe dengan path lengkap)" }

if ($VpsPublicIp) {
    # Media WebRTC lewat TCP: VPS meneruskan TCP 8189 ke laptop via NetBird.
    $env:MTX_WEBRTCLOCALTCPADDRESS = ":8189"
    $env:MTX_WEBRTCADDITIONALHOSTS = $VpsPublicIp
    Write-Host "WebRTC: TCP :8189, kandidat ICE tambahan $VpsPublicIp"
} else {
    Remove-Item Env:MTX_WEBRTCLOCALTCPADDRESS -ErrorAction SilentlyContinue
    Remove-Item Env:MTX_WEBRTCADDITIONALHOSTS -ErrorAction SilentlyContinue
    Write-Host "Mode HLS (WebRTC hanya untuk jaringan lokal)."
}

Write-Host "MediaMTX: $($exe.Source)"
Write-Host "Config  : $Config"
& $exe.Source $Config
```

### `deploy/laptop/start-engine.ps1` (BARU)

Engine yang hanya mendengarkan di `-BindIp` (IP NetBird, atau 127.0.0.1 untuk uji A/B); afinitas opsional.

```powershell
<#
.SYNOPSIS
  Engine di laptop untuk demo jarak jauh (docs/DEMO-REMOTE.md).

.DESCRIPTION
  Engine mendengarkan HANYA di IP NetBird laptop, jadi tidak terbuka di Wi-Fi
  tempat laptop berada. Backend di server yang menyambung ke sini.

  Backend belum mendukung kunci handshake engine (ENGINE_SHARED_KEY), jadi
  engine jalan tanpa kunci dan akan mencetak peringatan. Pengamannya: bind ke
  IP NetBird + ACL NetBird + firewall Windows (firewall.ps1).

  -AffinityMask opsional, mis. 0xFFFF untuk mengunci engine ke 16 thread P-core
  di laptop Intel hybrid (uji 8 Okt). Hanya berlaku bila python.exe yang
  dipakai adalah interpreter asli (env conda), bukan peluncur venv.

.EXAMPLE
  .\deploy\laptop\start-engine.ps1 -NetBirdIp 100.64.0.12

.EXAMPLE
  .\deploy\laptop\start-engine.ps1 -NetBirdIp 100.64.0.12 -Config engine/config/demo-1060.yaml -AffinityMask 0xFFFF

.EXAMPLE
  # Uji A/B (gladi A) tanpa server: hanya lag_probe di laptop yang bisa masuk.
  .\deploy\laptop\start-engine.ps1 -BindIp 127.0.0.1 -HealthSeconds 2 -AffinityMask 0xFFFF
#>
param(
    [Parameter(Mandatory = $true)][Alias("NetBirdIp")][string]$BindIp,
    [string]$Config = "engine/config/demo-4060.yaml",
    [int]$Port = 8765,
    [int]$HealthSeconds = 10,
    [string]$AffinityMask = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

if (-not (Get-NetIPAddress -IPAddress $BindIp -ErrorAction SilentlyContinue)) {
    throw "IP $BindIp tidak ada di laptop ini. Untuk IP NetBird: sudah tersambung? Cek: netbird status"
}
if (-not (Test-Path $Config)) { throw "Config engine tidak ditemukan: $Config" }

$python = (Get-Command python -ErrorAction Stop).Source
Write-Host "Python : $python"
if ($AffinityMask -and $python -match "\\Scripts\\python\.exe$") {
    Write-Warning "python.exe ini kemungkinan peluncur venv; afinitas bisa tidak mengenai engine. Pakai env conda atau cmd 'start /affinity'."
}

$engineArgs = @(
    "-m", "engine.runtime",
    "--config", $Config,
    "--tcp", "$($BindIp):$Port",
    "--health-seconds", "$HealthSeconds"
)
Write-Host "Engine : python $($engineArgs -join ' ')"

$proc = Start-Process -FilePath $python -ArgumentList $engineArgs -NoNewWindow -PassThru
if ($AffinityMask) {
    $proc.ProcessorAffinity = [IntPtr][Convert]::ToInt64($AffinityMask.Replace("0x", ""), 16)
    Write-Host "Afinitas: $($proc.ProcessorAffinity) (pid $($proc.Id))"
}
Wait-Process -Id $proc.Id
```

### `deploy/laptop/firewall.ps1` (BARU)

Firewall Windows: port dibuka hanya untuk IP NetBird server/VPS; `-Remove` untuk membersihkan.

```powershell
<#
.SYNOPSIS
  Aturan firewall Windows laptop untuk demo jarak jauh (docs/DEMO-REMOTE.md).
  Jalankan di PowerShell Admin.

.DESCRIPTION
  Membuka port HANYA untuk IP NetBird server (dan VPS bila WebRTC dipakai):
    8765  engine         <- backend di server
    8888  MediaMTX HLS   <- nginx di server
    8889  MediaMTX WHEP  <- nginx di server
    8189  WebRTC TCP     <- VPS (hanya bila -VpsNetBirdIp diisi)
  RTSP 8554 dan API 9997 sengaja tidak dibuka: hanya dipakai di laptop.

  Catatan: aturan BLOCK per aplikasi (mis. python.exe yang dulu ditolak di
  dialog firewall) mengalahkan aturan ALLOW ini. Cek di "Allowed apps".

.EXAMPLE
  .\deploy\laptop\firewall.ps1 -ServerNetBirdIp 100.64.0.5
.EXAMPLE
  .\deploy\laptop\firewall.ps1 -ServerNetBirdIp 100.64.0.5 -VpsNetBirdIp 100.64.0.9
.EXAMPLE
  .\deploy\laptop\firewall.ps1 -Remove
#>
param(
    [string]$ServerNetBirdIp = "",
    [string]$VpsNetBirdIp = "",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Prefix = "AITT demo remote"

$existing = Get-NetFirewallRule -DisplayName "$Prefix*" -ErrorAction SilentlyContinue
if ($existing) { $existing | Remove-NetFirewallRule }
if ($Remove) {
    Write-Host "Aturan '$Prefix*' dihapus."
    return
}
if (-not $ServerNetBirdIp) { throw "Isi -ServerNetBirdIp (IP NetBird server), atau pakai -Remove." }

New-NetFirewallRule -DisplayName "$Prefix - engine 8765" -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 8765 -RemoteAddress $ServerNetBirdIp -Profile Any | Out-Null
New-NetFirewallRule -DisplayName "$Prefix - mediamtx 8888-8889" -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 8888, 8889 -RemoteAddress $ServerNetBirdIp -Profile Any | Out-Null
if ($VpsNetBirdIp) {
    New-NetFirewallRule -DisplayName "$Prefix - webrtc 8189" -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort 8189 -RemoteAddress $VpsNetBirdIp -Profile Any | Out-Null
}

Get-NetFirewallRule -DisplayName "$Prefix*" | Format-Table DisplayName, Enabled, Action -AutoSize
```

### `deploy/vps/nginx-stream-webrtc.conf` (BARU)

Penerusan TCP 8189 di VPS ke laptop (hanya WebRTC).

```nginx
# =============================================================================
# VPS: teruskan media WebRTC (TCP 8189) ke MediaMTX di laptop lewat NetBird.
# Hanya untuk mode cameras.remote-webrtc.yaml. Mode HLS tidak butuh file ini.
#
# Kenapa proxy, bukan iptables DNAT saja: dengan DNAT, balasan laptop tidak
# kembali lewat VPS (asimetris) dan koneksi putus diam-diam. Proxy stream
# membuka koneksi baru dari VPS, jadi arah balik otomatis benar.
#
# Pasang (Debian/Ubuntu):
#   apt install libnginx-mod-stream
#   Taruh blok `stream { ... }` di bawah ini di /etc/nginx/nginx.conf,
#   di LEVEL ATAS (sejajar dengan `http { }`, bukan di dalamnya).
#   Ganti 100.64.0.12 dengan IP NetBird laptop.
#   nginx -t && systemctl reload nginx
#   Buka TCP 8189 di firewall VPS (ufw allow 8189/tcp) dan di firewall
#   penyedia cloud. Rekaman DNS tidak dibutuhkan: MediaMTX mengiklankan IP.
#
# Alternatif tanpa nginx:
#   socat TCP-LISTEN:8189,fork,reuseaddr TCP:100.64.0.12:8189
# =============================================================================

stream {
    server {
        listen 8189;
        proxy_pass 100.64.0.12:8189;
        proxy_connect_timeout 5s;
        # Sesi WebRTC bisa lama tanpa jeda; jangan diputus seperti HTTP.
        proxy_timeout 2h;
    }
}
```

### `scripts/summarize_gladi.py` (BARU)

Ringkasan dan vonis LULUS/GAGAL dari satu atau beberapa CSV `lag_probe`.

```python
"""Ringkas satu atau beberapa CSV lag_probe jadi satu tabel perbandingan.

Dibuat untuk uji A/B laptop 4060 (docs/DEMO-REMOTE.md, "Uji A/B 4060"), tetapi
berlaku untuk CSV gladi mana pun. Hanya pustaka standar, supaya bisa dijalankan
di laptop mana saja tanpa pandas.

    python scripts/summarize_gladi.py bench-out/ab-R0.csv bench-out/ab-R1.csv
    python scripts/summarize_gladi.py --target-fps 8 bench-out/gladi-1060.csv

Kolom yang dibaca (lag_probe): elapsed_s, source, fps, dropped, frame_age_s.
- fps dan dropped dari baris `health` (dropped = kumulatif frames_dropped_stale).
- umur kotak dari baris `view`.
Satu menit pertama dibuang (warmup dan start probe).

Vonis LULUS bila:
- waktu lambat (fps < 80% target) < 5%;
- umur kotak p99 < 1 dtk;
- tidak ada stall (umur > 2 dtk).
Ambang ini sama dengan yang dipakai saat membaca gladi 8 Okt.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

WARMUP_SECONDS = 60.0
SLOW_FRACTION = 0.8
STALL_AGE_SECONDS = 2.0


@dataclass
class Summary:
    name: str
    minutes: float
    fps_median: Optional[float]
    slow_share: Optional[float]
    phase_switches: int
    drops_per_s: Optional[float]
    age_median: Optional[float]
    age_p95: Optional[float]
    age_p99: Optional[float]
    age_max: Optional[float]
    stalls: int

    @property
    def passed(self) -> bool:
        return (
            self.slow_share is not None and self.slow_share < 0.05
            and self.age_p99 is not None and self.age_p99 < 1.0
            and self.stalls == 0
        )


def _num(value: str) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(math.floor(pos))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def summarize(path: Path, target_fps: float) -> Summary:
    health: List[tuple] = []          # (elapsed, fps, dropped)
    ages: List[tuple] = []            # (elapsed, age)
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            elapsed = _num(row.get("elapsed_s", ""))
            if elapsed is None or elapsed < WARMUP_SECONDS:
                continue
            source = row.get("source", "")
            if source == "health":
                fps = _num(row.get("fps", ""))
                if fps is not None:
                    health.append((elapsed, fps, _num(row.get("dropped", ""))))
            elif source == "view":
                age = _num(row.get("frame_age_s", ""))
                if age is not None:
                    ages.append((elapsed, age))

    fps_values = [fps for _, fps, _ in health]
    slow_limit = SLOW_FRACTION * target_fps
    slow = [fps < slow_limit for fps in fps_values]
    switches = sum(1 for a, b in zip(slow, slow[1:]) if a != b)

    rates = []
    for (t0, _, d0), (t1, _, d1) in zip(health, health[1:]):
        if d0 is not None and d1 is not None and t1 > t0 and d1 >= d0:
            rates.append((d1 - d0) / (t1 - t0))

    age_values = [age for _, age in ages]
    # Stall = umur kotak melewati ambang; hitung kejadian, bukan sampel.
    stalls, inside = 0, False
    for age in age_values:
        if age > STALL_AGE_SECONDS and not inside:
            stalls += 1
        inside = age > STALL_AGE_SECONDS

    times = [t for t, _, _ in health] + [t for t, _ in ages]
    minutes = (max(times) - min(times)) / 60.0 if times else 0.0
    return Summary(
        name=path.name,
        minutes=minutes,
        fps_median=_quantile(fps_values, 0.5),
        slow_share=(sum(slow) / len(slow)) if slow else None,
        phase_switches=switches,
        drops_per_s=_quantile(rates, 0.5),
        age_median=_quantile(age_values, 0.5),
        age_p95=_quantile(age_values, 0.95),
        age_p99=_quantile(age_values, 0.99),
        age_max=max(age_values) if age_values else None,
        stalls=stalls,
    )


def _fmt(value: Optional[float], spec: str) -> str:
    return "-" if value is None else format(value, spec)


def render(summaries: Sequence[Summary], target_fps: float) -> str:
    header = (
        f"{'file':<28} {'menit':>5} {'fps med':>7} {'lambat':>7} {'ganti':>5} "
        f"{'drop/s':>6} {'umur med':>8} {'p95':>5} {'p99':>5} {'maks':>5} {'stall':>5}  vonis"
    )
    lines = [f"target {target_fps:g} fps; lambat = fps < {SLOW_FRACTION * target_fps:g}; "
             f"menit pertama dibuang", header, "-" * len(header)]
    for s in summaries:
        lines.append(
            f"{s.name[:28]:<28} {s.minutes:>5.1f} {_fmt(s.fps_median, '.2f'):>7} "
            f"{_fmt(None if s.slow_share is None else s.slow_share * 100, '.1f') + '%':>7} "
            f"{s.phase_switches:>5} {_fmt(s.drops_per_s, '.1f'):>6} "
            f"{_fmt(s.age_median, '.2f'):>8} {_fmt(s.age_p95, '.2f'):>5} "
            f"{_fmt(s.age_p99, '.2f'):>5} {_fmt(s.age_max, '.2f'):>5} {s.stalls:>5}  "
            f"{'LULUS' if s.passed else 'GAGAL'}"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="+", type=Path, help="CSV hasil scripts/lag_probe.py")
    parser.add_argument("--target-fps", type=float, default=10.0,
                        help="core.target_fps profil yang diuji (4060: 10, 1060: 8)")
    args = parser.parse_args(argv)

    summaries = [summarize(path, args.target_fps) for path in args.csv]
    print(render(summaries, args.target_fps))
    return 0 if all(s.passed for s in summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
```

### `engine/tests/test_view_overlay_states.py` (BARU)

Mengunci perbaikan kotak hantu (3 tes).

```python
"""Overlay hanya menggambar track yang terlihat di frame ini.

Gejala yang dikunci: di dashboard satu orang tampil dengan 2-3 kotak. Penyebab:
ByteTrack memberi ID baru (ID switch), sementara track lama tetap dikembalikan
selama masa tenggang `track_buffer_seconds` dengan state LOST dan kotak terakhir
yang membeku. `_maybe_view` dulu mengirim semuanya ke kanal view.

Yang TIDAK boleh berubah: masa tenggang itu tetap milik presensi. Tes ini hanya
memeriksa kanal view.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any, Dict, List

import numpy as np

from engine.config import load_config
from engine.ports.frame import Frame, FrameMetadata
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import Track, TrackState
from engine.runtime.camera import CameraSpec, CameraSupervisor


def _camera(views: List[Dict[str, Any]]) -> CameraSupervisor:
    config = dataclasses.replace(
        load_config(), source_type="mock", auto_warmup=False, strict_mode=True
    )
    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock"), config=config,
        emit_event=lambda m: m, emit_view=lambda m: views.append(m) or m,
        view_fps=1000.0,
    )
    clock = SimpleNamespace(
        offset=1_791_250_000.0, camera_id="r1", stream_epoch=1,
        at=lambda pts: "2026-10-08T11:00:00Z",
    )
    # Assembler baru dibuat saat stream terbuka; di sini cukup jam-nya saja.
    camera._assembler = SimpleNamespace(clock_for=lambda camera_id: clock)
    return camera


NOW = 1_000.0


def _frame() -> Frame:
    return Frame(
        image=np.zeros((100, 200, 3), dtype=np.uint8),
        metadata=FrameMetadata(
            frame_id=1, source_id="r1", fps=10.0,
            width=200, height=100, pts=5.0, pts_source="container",
            timestamp=NOW,
        ),
    )


def _track(track_id: int, state: TrackState, x: float, last_seen: float = NOW) -> Track:
    track = Track(track_id=track_id, bbox=BoundingBox(x, 10.0, x + 40.0, 90.0), state=state)
    track.last_seen_timestamp = last_seen
    track.attributes["track_uuid"] = f"uuid-{track_id}"
    return track


def test_track_lost_tidak_dikirim_ke_overlay():
    views: List[Dict[str, Any]] = []
    camera = _camera(views)
    tracks = [
        _track(1, TrackState.LOST, 10.0, last_seen=NOW - 0.8),  # kotak hantu
        _track(2, TrackState.TRACKED, 60.0),   # orang yang sama, ID baru
        _track(3, TrackState.NEW, 120.0),
        _track(4, TrackState.REMOVED, 150.0),
    ]
    camera._maybe_view(_frame(), tracks, 5.0)

    assert len(views) == 1
    sent = [box["track_uuid"] for box in views[0]["boxes"]]
    assert sent == ["uuid-2", "uuid-3"]


def test_frame_tanpa_track_aktif_tetap_dikirim_kosong():
    """Frame kosong itu bermakna: tanpanya browser terus menggambar kotak terakhir."""
    views: List[Dict[str, Any]] = []
    camera = _camera(views)
    camera._maybe_view(_frame(), [_track(1, TrackState.LOST, 10.0, last_seen=NOW - 1.0)], 5.0)

    assert len(views) == 1
    assert views[0]["boxes"] == []


def test_lost_sekejap_tetap_digambar_supaya_tidak_berkedip():
    """Satu frame tanpa deteksi (0,1 dtk di 10 fps) tidak boleh menghapus kotak."""
    views: List[Dict[str, Any]] = []
    camera = _camera(views)
    tracks = [
        _track(1, TrackState.LOST, 10.0, last_seen=NOW - 0.1),
        _track(2, TrackState.LOST, 60.0, last_seen=NOW - 0.5),
    ]
    camera._maybe_view(_frame(), tracks, 5.0)

    sent = [box["track_uuid"] for box in views[0]["boxes"]]
    assert sent == ["uuid-1"]
```

### `engine/tests/test_summarize_gladi.py` (BARU)

Tes `summarize_gladi.py` (4 tes).

```python
"""scripts/summarize_gladi.py: vonis A/B 4060 harus sama dengan bacaan manual 8 Okt."""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("summarize_gladi", Path("scripts/summarize_gladi.py"))
sg = importlib.util.module_from_spec(_spec)
sys.modules["summarize_gladi"] = sg
_spec.loader.exec_module(sg)

FIELDS = ["wall_t", "elapsed_s", "camera_id", "source", "frame_age_s", "lag_s",
          "fps", "dropped", "drift_s", "note"]


def _write(path: Path, fps_at, age_at, drop_rate_at, seconds: int = 600) -> Path:
    rows = []
    dropped = 0.0
    for t in range(0, seconds, 2):
        dropped += 2 * drop_rate_at(t)
        rows.append({"elapsed_s": t, "source": "health", "fps": fps_at(t), "dropped": dropped})
        rows.append({"elapsed_s": t + 1, "source": "view", "frame_age_s": age_at(t)})
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_run_bersih_lulus(tmp_path):
    path = _write(tmp_path / "bersih.csv", lambda t: 10.0, lambda t: 0.04, lambda t: 0.0)
    s = sg.summarize(path, target_fps=10.0)
    assert s.passed
    assert s.slow_share == 0.0 and s.phase_switches == 0 and s.stalls == 0
    assert abs(s.drops_per_s) < 1e-9


def test_fase_6_fps_dan_stall_gagal(tmp_path):
    # 10 fps di menit 1-4, lalu 6 fps dengan umur kotak naik sampai 8 dtk.
    slow = lambda t: t >= 240
    path = _write(
        tmp_path / "fase.csv",
        lambda t: 6.0 if slow(t) else 10.0,
        lambda t: min(8.0, 0.5 + (t - 240) * 0.05) if slow(t) else 0.1,
        lambda t: 24.0 if slow(t) else 10.0,
    )
    s = sg.summarize(path, target_fps=10.0)
    assert not s.passed
    assert s.phase_switches == 1
    assert 0.55 < s.slow_share < 0.7
    assert s.stalls == 1
    assert s.age_max == 8.0


def test_menit_pertama_dibuang(tmp_path):
    # Warmup lambat tidak boleh menggagalkan run yang sesudahnya bersih.
    path = _write(tmp_path / "warmup.csv", lambda t: 3.0 if t < 60 else 10.0,
                  lambda t: 5.0 if t < 60 else 0.05, lambda t: 0.0)
    assert sg.summarize(path, target_fps=10.0).passed


def test_main_mengembalikan_1_bila_ada_yang_gagal(tmp_path, capsys):
    ok = _write(tmp_path / "ok.csv", lambda t: 10.0, lambda t: 0.04, lambda t: 0.0)
    bad = _write(tmp_path / "bad.csv", lambda t: 6.0, lambda t: 0.5, lambda t: 24.0)
    assert sg.main([str(ok)]) == 0
    assert sg.main([str(ok), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "LULUS" in out and "GAGAL" in out
```

### `docs/DEMO-REMOTE.md` (BARU)

Runbook demo jarak jauh, termasuk §8 uji A/B 4060.

````markdown
# Demo jarak jauh: engine di laptop, backend + frontend di server

Susunan:

```
LAPTOP (lokasi kamera)                     SERVER (Portainer CE)
ffmpeg -> MediaMTX -> engine               nginx (frontend) + backend
              :8888/:8889   :8765            |                 |
                  ^           ^              |                 |
                  |           +--- NetBird --+-----------------+   backend  -> engine
                  +--------------- NetBird --+                     nginx    -> MediaMTX (HLS/WHEP)

Penonton: browser -> Cloudflare -> VPS -> NetBird -> server:80
```

Kenapa MediaMTX di laptop:

- Engine, MediaMTX, dan ffmpeg tetap lokal, persis seperti gladi 4060 yang lulus
  (10 fps, umur kotak 0,04 dtk). Video ke penonton menyeberang internet sekali saja.
- Jam di HLS (PROGRAM-DATE-TIME) dan waktu kotak dari engine sama-sama dari jam
  laptop, jadi overlay tidak bergantung pada sinkronisasi jam antar mesin.

Yang lewat NetBird hanya dua: backend ke engine (event dan kotak, kecil) dan nginx
server ke MediaMTX laptop (video untuk penonton).

## 0. Prasyarat

- Paket backend r6 sudah terpasang di repo, karena image dibangun dari repo:
  `policy.yaml` tetap berkomentar, dan email memuat tautan dashboard.
- Laptop: env conda engine, model wajah di `engine/models/`, `mediamtx.exe`,
  dan `ffmpeg`.
- NetBird terpasang dan login di **laptop, server, dan VPS**.
- Catat tiga IP NetBird dari `netbird status` di tiap mesin. Contoh di dokumen ini:

  | Mesin | IP NetBird (contoh) |
  |---|---|
  | laptop | `100.64.0.12` |
  | server | `100.64.0.5` |
  | VPS | `100.64.0.9` |

## 1. NetBird

Di dashboard NetBird, buat grup `aitt-laptop`, `aitt-server`, dan `aitt-vps`.
Ganti policy bawaan "All" dengan policy berikut (protokol TCP):

| Dari | Ke | Port |
|---|---|---|
| aitt-server | aitt-laptop | 8765, 8888, 8889 |
| aitt-vps | aitt-laptop | 8189 (hanya untuk mode WebRTC) |
| aitt-vps | aitt-server | 80 (jalur web yang sudah ada) |

Cek jalurnya dari laptop:

```powershell
netbird status -d
```

Peer server harus berstatus **P2P**. Kalau **Relayed**, semua tetap jalan, tapi
video ke penonton lebih tersendat. Coba jaringan lain atau buka UDP keluar.

**Jangan pakai nama `*.netbird.cloud` di env container.** DNS NetBird terpasang di
host, dan container tidak bisa me-resolve-nya. Pakai IP.

## 2. Jam

Overlay mode WebRTC membandingkan jam laptop dengan jam browser penonton. Timer di
dashboard memakai jam server. Sinkronkan ketiganya sebelum demo:

```powershell
w32tm /resync          # laptop dan PC penonton (PowerShell Admin)
```
```bash
timedatectl            # server: "System clock synchronized: yes"
```

## 3. Laptop

Semua perintah dari folder repo.

### 3.1 Firewall (sekali, PowerShell Admin)

```powershell
.\deploy\laptop\firewall.ps1 -ServerNetBirdIp 100.64.0.5
# mode WebRTC: tambahkan -VpsNetBirdIp 100.64.0.9
# hapus setelah demo: .\deploy\laptop\firewall.ps1 -Remove
```

Kalau dulu pernah menekan "Cancel" di dialog firewall untuk `python.exe` atau
`mediamtx.exe`, Windows membuat aturan **Block** yang mengalahkan aturan di atas.
Cek di *Windows Defender Firewall → Allowed apps*.

### 3.2 MediaMTX (terminal 1)

```powershell
.\deploy\laptop\start-mediamtx.ps1 -MediaMtxExe C:\path\ke\mediamtx.exe
# mode WebRTC: tambahkan -VpsPublicIp <IP publik VPS>
```

### 3.3 Video uji (terminal 2)

Paksa 25 fps. Sumber 30 fps adalah penyebab fps 6 di gladi 8 Okt.

```powershell
ffmpeg -re -stream_loop -1 -i ongame.mp4 -an -r 25 -c:v libx264 -preset veryfast `
  -tune zerolatency -pix_fmt yuv420p -bf 0 -g 25 -keyint_min 25 `
  -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam01
```

Atau pakai `.\scripts\publish_test_video.ps1 -Video ongame.mp4 -Fps 25`.

### 3.4 Engine (terminal 3)

```powershell
conda activate vision-engine
.\deploy\laptop\start-engine.ps1 -NetBirdIp 100.64.0.12
# laptop 1060: -Config engine/config/demo-1060.yaml
# kunci ke P-core (laptop Intel hybrid): -AffinityMask 0xFFFF
```

Engine mendengarkan **hanya di IP NetBird**, jadi tidak terbuka di Wi-Fi tempat
laptop berada. Peringatan "TANPA autentikasi handshake" memang akan muncul: backend
belum mendukung `ENGINE_SHARED_KEY`. Pengamannya ACL NetBird dan firewall.

Engine butuh ±1 menit untuk warmup, lalu menunggu `set_cameras` dari backend.

Jangan jalankan `lag_probe` atau engine kedua selama demo. Engine hanya melayani satu
koneksi, dan koneksi terakhir yang menang.

## 4. Server (Portainer CE)

### 4.1 Stack

*Stacks → Add stack → Repository*:

| Isian | Nilai |
|---|---|
| Repository URL / reference | repo dan branch demo (mis. `main-v2`) |
| Compose path | `deploy/docker-compose.portainer.yml` |
| Environment variables | *Advanced mode*, tempel `deploy/portainer.env.example`, lalu isi |
| GitOps updates | **mati** di hari demo |

Wajib diisi:
- `LAPTOP_NETBIRD_IP`
- `INITIAL_ADMIN_PASSWORD` (minimal 8 karakter)
- `DASHBOARD_URL` (domain publik)

Kalau email ikut didemokan, isi juga `SMTP_*` dan ubah `SMTP_ENABLED` jadi `true`.

Build image frontend (npm) memakan beberapa menit. Lakukan jauh sebelum demo, bukan
di pagi harinya.

Kalau deploy gagal dengan pesan `stack.env` tidak ditemukan, berarti versi Portainer
belum membuat file itu untuk stack Git. Isi ulang variabel di UI dan redeploy. Kalau
tetap gagal, hapus baris `env_file` dan pindahkan variabel penting (admin, SMTP,
`DASHBOARD_URL`) ke blok `environment:` backend.

### 4.2 Uji jalur dari server, sebelum membuka browser

```bash
nc -zv 100.64.0.12 8765                                  # engine
curl -s http://100.64.0.12:8888/cam01/index.m3u8 | head   # HLS dari MediaMTX laptop
docker exec ai-time-tracking-frontend-1 wget -qO- http://100.64.0.12:8888/cam01/index.m3u8 | head
curl -s http://127.0.0.1:8000/api/system/status           # "engine": "connected"
curl -s http://127.0.0.1:8000/api/cameras                 # stream_url /hls/cam01/index.m3u8
```

Nama container tergantung Portainer; cek dengan `docker ps`. Kalau uji dari
container gagal tetapi dari host berhasil, cek firewall host server (iptables/ufw)
untuk lalu lintas dari jaringan Docker ke interface NetBird.

## 5. VPS dan Cloudflare

- Reverse proxy domain di VPS mengarah ke `http://100.64.0.5:80`, jalur yang sudah ada.
- **Cloudflare → Caching → Cache Rules:** buat aturan *Bypass cache* untuk path
  `/hls/*`. MediaMTX memakai segmen `.mp4`, dan Cloudflare meng-cache ekstensi itu
  secara default.
- SSE (`/api/detections/stream`, `/api/notifications/stream`) aman. Deteksi
  mengalir terus, notifikasi mengirim `ping` setiap 15 detik, dan nginx kita sudah
  mematikan buffering. Kalau reverse proxy di VPS adalah nginx, matikan juga
  buffering untuk `/api/`:

  ```nginx
  location /api/ {
      proxy_pass http://100.64.0.5:80;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_buffering off;
      proxy_read_timeout 1h;
  }
  ```

## 6. Verifikasi akhir (dari HP atau laptop lain, di luar jaringan)

1. Buka domain → login admin.
2. Dashboard: video jalan. HLS tertinggal beberapa detik dari kejadian, itu normal.
   Kotak muncul di atas orang.
3. Pengaturan: ubah batas ke 2 menit → tersimpan. Perubahan ada di volume `/data`,
   tidak hilang saat redeploy.
4. Enrollment → orang dikenali → pelanggaran → kotak pesan (dan email bila aktif).

## 7. Mode WebRTC (opsional, latensi sub-detik)

Media WebRTC tidak bisa lewat proxy Cloudflare. Jalurnya lewat samping:
browser → **IP publik VPS:8189 (TCP)** → NetBird → laptop:8189.

1. Laptop: `start-mediamtx.ps1 -VpsPublicIp <IP publik VPS>`, lalu
   `firewall.ps1 ... -VpsNetBirdIp 100.64.0.9`.
2. VPS: pasang `deploy/vps/nginx-stream-webrtc.conf` (ganti IP laptop) dan buka TCP
   8189 di firewall VPS dan firewall penyedia cloud.
3. Portainer: `CAMERAS_CONFIG_FILE=cameras.remote-webrtc.yaml`, lalu redeploy (atau
   restart backend).

Jaringan yang hanya membuka port 80/443 (Wi-Fi kantor atau kampus) memblokir 8189,
dan videonya akan hitam. Frontend tidak punya fallback otomatis. Kalau terjadi saat
demo, kembalikan ke `cameras.remote-hls.yaml`.

## 8. Uji A/B 4060: perubahan mana yang krusial

Gladi 8 Okt di laptop 4060:

| Run | Jam | Hasil |
|---|---|---|
| 1 | 10:26 | fps berganti 6 dan 10, stall sampai 9 dtk |
| 2 | 11:53, turbo hidup | lebih buruk |
| 3 | 15:50 | **bersih**: 10,00 fps, 0 drop, umur kotak p99 0,09 dtk |

Di antara run 2 dan run 3 ada tiga perubahan sekaligus, jadi belum jelas mana yang
menyelesaikan masalah. Uji ini memisahkannya, supaya hari demo cukup memastikan
tombol yang memang wajib.

Kerjakan **di laptop saja (gladi A)**, sebelum menyambung ke server. Engine
dijalankan di `127.0.0.1`, sehingga backend di server tidak bisa ikut masuk.
Engine hanya melayani satu koneksi; kalau backend menyambung, ia akan berebut
koneksi dengan `lag_probe`.

Kondisi yang sama untuk semua run:
- turbo sesuai setelan EB (`PERFBOOSTMODE 0`);
- dicolok charger;
- video yang sama;
- profil `demo-4060.yaml`;
- 15 menit per run;
- pola pemakaian laptop sama (misalnya pindah jendela beberapa kali).

| Run | ffmpeg | Afinitas engine | Power throttling ffmpeg + mediamtx | Menguji |
|---|---|---|---|---|
| R0 | `-r 25` | `0xFFFF` | Never On | mengulang run 3; harus LULUS dulu |
| R1 | **tanpa `-r`** (asli 30 fps) | `0xFFFF` | Never On | peran fps sumber |
| R2 | `-r 25` | **tanpa** | Never On | peran afinitas P-core |
| R3 | `-r 25` | `0xFFFF` | **reset** | peran power throttling |

Power throttling engine selalu dimatikan oleh engine itu sendiri, jadi R3 hanya
menguji ffmpeg dan mediamtx. Untuk R3, jalankan di PowerShell Admin lalu
kembalikan sesudahnya:

```powershell
powercfg /powerthrottling reset /path "<path ffmpeg.exe>"
powercfg /powerthrottling reset /path "<path mediamtx.exe>"
# sesudah R3:
powercfg /powerthrottling disable /path "<path ffmpeg.exe>"
powercfg /powerthrottling disable /path "<path mediamtx.exe>"
```

Perintah tiap run:

```powershell
# terminal 1-2: MediaMTX dan ffmpeg seperti §3.2-3.3 (R1: hapus "-r 25")
# terminal 3: engine (R2: hapus -AffinityMask)
.\deploy\laptop\start-engine.ps1 -BindIp 127.0.0.1 -HealthSeconds 2 -AffinityMask 0xFFFF
# terminal 4: tunggu warmup ±1 menit, lalu
python scripts/lag_probe.py --camera cam01=rtsp://127.0.0.1:8554/cam01 --minutes 15 --out bench-out/ab-R0.csv
```

Ringkas semua run sekaligus:

```powershell
python scripts/summarize_gladi.py bench-out/ab-R0.csv bench-out/ab-R1.csv bench-out/ab-R2.csv bench-out/ab-R3.csv
```

Ringkasan menghitung fps median, persentase waktu lambat (fps < 8), jumlah
pergantian fase, drop per detik, umur kotak (median, p95, p99, maks), dan stall
(umur kotak > 2 dtk). Vonis LULUS kalau waktu lambat < 5%, p99 < 1 dtk, dan tidak
ada stall. Untuk tiga gladi 8 Okt, hasilnya GAGAL, GAGAL, LULUS, sama dengan bacaan
manual.

Cara membaca:
- **R0 GAGAL:** run 3 tidak bisa diulang, berarti ada faktor lain. Berhenti di sini
  dan kirim CSV, log GPU, dan log HWiNFO.
- **R1, R2, atau R3 GAGAL:** perubahan yang dibatalkan di run itu krusial, dan
  wajib masuk checklist demo (§9).
- **Semua LULUS:** tidak ada satu perubahan pun yang krusial sendirian. Pertahankan
  ketiganya untuk demo, karena biayanya nol.

## 9. Checklist hari demo

- [ ] GitOps update Portainer **mati**.
- [ ] `netbird status -d` di laptop: server dan VPS tersambung.
- [ ] Jam laptop dan server sinkron.
- [ ] Laptop dicolok charger. Power throttling untuk python, ffmpeg, dan mediamtx
      berstatus "Never On" (`powercfg /powerthrottling list`).
- [ ] MediaMTX, ffmpeg (25 fps), dan engine jalan. Tidak ada `lag_probe`.
- [ ] Laptop 4060: engine dengan `-AffinityMask 0xFFFF`, sampai uji A/B (§8)
      membuktikan tidak perlu.
- [ ] `/api/system/status` → `engine: connected`.
- [ ] Dashboard dibuka dari jaringan luar: video dan kotak muncul.
- [ ] Cadangan: laptop 1060 (`-Config engine/config/demo-1060.yaml`) dan mode HLS.

## 10. Gejala dan penyebab

| Gejala | Penyebab paling mungkin |
|---|---|
| Tidak bisa login, tidak ada error | `INITIAL_ADMIN_PASSWORD` tidak sampai ke backend (env/`stack.env`) |
| `engine: disconnected` | Engine mati, IP NetBird salah, firewall/ACL 8765, atau ada `lag_probe`/engine lain yang memegang koneksi |
| Halaman jalan, video hitam (HLS) | MediaMTX laptop mati, ffmpeg belum publish, firewall/ACL 8888, atau `LAPTOP_NETBIRD_IP` salah |
| Video hitam (WebRTC), HLS jalan | TCP 8189 diblokir di VPS atau di jaringan penonton, atau `-VpsPublicIp` tidak diisi |
| Video jalan, tidak ada kotak | `camera_id` beda, atau engine belum menerima `set_cameras` (lihat `GET /api/cameras`, `is_running`) |
| Kotak tertinggal jauh dari orang | Jam laptop dan PC penonton tidak sinkron (mode WebRTC) |
| Video tersendat-sendat | NetBird relayed; cek `netbird status -d` |
| Satu orang tampil dengan 2-3 kotak | Engine lama: track LOST ikut digambar (sudah diperbaiki di paket ini). Kalau masih muncul: dua kotak sama-sama bergerak = deteksi ganda; kotak berganti-ganti = ID switch tracker |
| Batas waktu tidak tersimpan | Volume `/data` tidak bisa ditulis; cek log backend |
````

### `deploy/.gitignore` (UBAH)

Tambahkan satu baris di akhir file:

```gitignore
stack.env
```
