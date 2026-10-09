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

### 8.1 Penjadwal berdetak: free vs tick (paket r9)

Paket r9 menambah penjadwal berdetak tahap 1 (dokumen 04 §14, `engine/runtime/tick_scheduler.py`).
Default tetap `free` (perilaku lama); profil uji `engine/config/demo-4060-tick.yaml` menyalakannya
(`core.scheduler: tick`, `core.tick_fps: 6`, `detector.batch_wait_ms: 15`).

Uji ini bagian dari baseline 5 kamera (minggu 1) dan gerbang 23 Oktober. Kondisi sama dengan
§8 (R0), tetapi **5 stream** (`cam01`..`cam05`, video yang sama boleh) dan dua profil:

| Run | Profil | Target untuk ringkasan |
|---|---|---|
| T0 | `demo-4060.yaml` (free, 10 fps) | `--target-fps 10` |
| T0-6 | `demo-4060.yaml` dengan `start-engine.ps1 -TargetFps 6` (free, 6 fps) | `--target-fps 6` |
| T1 | `demo-4060-tick.yaml` (tick, 6 fps) | `--target-fps 6` |

T0-6 perlu supaya perbandingannya adil: tick di 6 fps harus dibandingkan dengan free di 6 fps,
bukan free di 10 fps.

Publish lima stream sekaligus dari satu video (satu proses ffmpeg per path, encode sama dengan
§3.3) di terminal terpisah, dan biarkan jalan selama semua run:

```powershell
.\scripts\publish_test_video.ps1 -Video ongame.mp4 -Fps 25 -Count 5
```

Skrip berhenti sendiri (dan menghentikan semua proses) bila satu stream mati; run yang terjadi
sesudahnya tidak valid. Lalu per run, ganti profil engine dan nama CSV:

```powershell
.\deploy\laptop\start-engine.ps1 -BindIp 127.0.0.1 -HealthSeconds 2 -AffinityMask 0xFFFF -Config engine/config/demo-4060-tick.yaml
python scripts/lag_probe.py --camera cam01=rtsp://127.0.0.1:8554/cam01 --camera cam02=rtsp://127.0.0.1:8554/cam02 `
  --camera cam03=rtsp://127.0.0.1:8554/cam03 --camera cam04=rtsp://127.0.0.1:8554/cam04 `
  --camera cam05=rtsp://127.0.0.1:8554/cam05 --minutes 15 --out bench-out/ab-T1.csv
python scripts/summarize_gladi.py --target-fps 6 bench-out/ab-T0-6.csv bench-out/ab-T1.csv
```

Ringkasan menampilkan satu baris per kamera (cam01..cam05) dan satu baris gabungan per file.
Vonis tetap satu per file: LULUS hanya bila kelima kamera LULUS. Kamera yang gagal terlihat dari
barisnya; bila hanya satu kamera yang menyimpang, itu masalah sumber/decode kamera itu, bukan irama.

Log engine mode tick mencetak ringkasan tiap 60 detik: jumlah detak, detak telat (dan maksimum
keterlambatannya), detak yang dilompati, dan detak terlewat per kamera. Kirim log itu bersama CSV.

Cara membaca:
- **T1 LULUS, T0-6 GAGAL:** penjadwal memperbaiki stabilitas; lanjut ke tahap 2 sesuai dokumen 14.
- **Keduanya LULUS:** 6 fps saja sudah cukup cadangan; tick tetap dipakai karena memberi batch
  serentak dan irama yang bisa diprediksi, tetapi tidak mendesak.
- **Keduanya GAGAL:** masalahnya bukan irama. Lihat detak telat di log: bila banyak, satu langkah
  lebih lama dari periode (GPU/CPU kurang) -- turunkan `tick_fps` atau ukur per tahap dengan py-spy.
- **`missed_ticks` besar hanya di satu kamera:** kamera itu yang lambat (decode, sumber), bukan
  penjadwalnya.

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
