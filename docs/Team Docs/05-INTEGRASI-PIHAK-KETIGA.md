# 05 — Integrasi Pihak Ketiga

Versi 1.2 · diperbarui 9 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Dokumen ini mencakup semua komponen di luar kode tim: server media, kamera, sinkronisasi waktu, notifikasi, model AI, dan platform GPU.

## 1. MediaMTX (server media)

**Peran.** MediaMTX (`bluenviron/mediamtx`, versi di compose: 1.21.1) menjadi satu-satunya titik yang menarik stream dari kamera. Engine dan browser membaca dari MediaMTX, bukan dari kamera, sehingga kamera tidak menerima banyak koneksi dan kredensial kamera tidak pernah sampai ke browser. MediaMTX hanya melakukan relay/remux dan tidak men-transcode.

**Path per kamera (fase 1).** Setiap kamera punya dua path:

| Path | Sumber | Pembaca | Codec |
|---|---|---|---|
| `camNN_main` | Mainstream kamera | Engine (RTSP/TCP) | H.264 atau H.265 |
| `camNN_sub` | Substream kamera | Browser (WHEP, LL-HLS) | H.264 |

Saat ini hanya ada `cam01` dengan `source: publisher` yang membaca substream, dan engine ikut membacanya (P19).

**Port.**

| Port | Fungsi | Paparan |
|---|---|---|
| 8554/tcp | RTSP | Hanya ke mesin A (engine) |
| 8888/tcp | HLS | Lewat nginx (`/hls/`) |
| 8889/tcp | WebRTC/WHEP | Lewat nginx (`/whep/`) |
| 8189/udp | Media WebRTC | LAN |
| 8189/tcp | Media WebRTC (demo jarak jauh, opsional) | Lewat IP publik VPS → NetBird → laptop (§7.1) |
| 9997/tcp | API kontrol | Hanya localhost |

**Keamanan (wajib fase 1, P4).** Konfigurasi saat ini tidak mendefinisikan `authInternalUsers`, sehingga siapa pun di jaringan dapat membaca semua stream dan **mem-publish** ke path berjenis `publisher`, yang berarti dapat menyuntikkan video palsu ke analisis. Fase 1:

- Path kamera memakai `source: rtsp://…` (MediaMTX menarik dari kamera), bukan `publisher`.
- Akun baca khusus untuk engine; pembacaan browser diotorisasi lewat backend. Diputuskan 8 Oktober 2026: video live (`/hls/`, `/whep/`) **hanya untuk admin**, diperiksa lewat `auth_request` nginx ke backend (dokumen 12 §3.8). Hook `authMethod: http` atau JWT di MediaMTX tetap opsi lapisan tambahan.
- `hlsAllowOrigins`/`webrtcAllowOrigins` dibatasi ke origin dashboard; API MediaMTX hanya localhost.

**Waktu.** Uji opsi `useAbsoluteTimestamp` agar PDT HLS dan jam event engine berasal dari jam kamera (dokumen 04 §7).

**Kinerja.** Relay 5 kamera ringan untuk CPU. Pembaca yang lambat menyebabkan MediaMTX membuang paket ("reader is too slow"); karena itu engine wajib menguras stream dengan thread pembaca terpisah.

**Demo jarak jauh (8 Oktober 2026).** Pada demo, MediaMTX berjalan di laptop engine bersama ffmpeg dan engine, bukan di server backend; nginx server membaca HLS/WHEP dari laptop lewat NetBird (§7.1, `docs/DEMO-REMOTE.md`). Sumber video uji dipublikasikan ke MediaMTX dengan ffmpeg `-r 25`, tanpa audio, `yuv420p`, tanpa B-frame; sumber 30 fps terbukti menjadi salah satu penyebab fps turun ke 6 di gladi 8 Oktober.

## 2. Kamera dan NVR

- Protokol: RTSP, dengan dua profil stream (mainstream dan substream) aktif.
- Codec: mainstream H.264 atau H.265; **substream wajib H.264** untuk browser.
- Jam kamera: NTP ke server lokal (mesin B). Ini prasyarat kualitas timestamp dan overlay.
- ONVIF/PTZ: tidak dipakai di fase 1.
- Kredensial kamera hanya disimpan di konfigurasi MediaMTX (`.env.mediamtx`, tidak di-commit).
- Kebutuhan penempatan dan resolusi untuk perusahaan CCTV ada di dokumen 10.
- **Rekaman lokasi (8 Oktober 2026):** evaluasi identifikasi dan ReID membutuhkan akses CCTV atau rekaman **multi-kamera** dari lokasi klien (lima lokasi: luar, lobi, smoking area, ruang hiburan, biliar). Permintaan ini dipegang COM; sementara itu tim merekam skenario sendiri (dokumen 12 §8).

## 3. Sinkronisasi waktu (NTP)

- Mesin B menjalankan chrony sebagai server NTP lokal (upstream: pool NTP publik atau NTP kantor).
- Mesin A dan kelima kamera disinkronkan ke mesin B.
- Backend memantau selisih jam engine–backend; alarm bila lebih dari 2 detik.
- Demo jarak jauh: jam laptop, server, dan PC penonton disinkronkan sebelum demo (`w32tm /resync` di Windows, `timedatectl` di server), karena overlay mode WebRTC membandingkan jam laptop dengan jam browser penonton (`docs/DEMO-REMOTE.md` §2).

## 4. Notifikasi

**Diputuskan (28 Sep 2026): email + notifikasi di dashboard sesuai peran.** Rincian siapa menerima apa ada di dokumen 02 §6. Backend tetap menyediakan antarmuka `notify` dengan adapter, sehingga saluran lain dapat ditambah kemudian tanpa mengubah logika peringatan.

**Diperbarui (8 Okt 2026, dokumen 12 §3.3–§3.4): dua jenis email.**

| Jenis | Penerima | Waktu |
|---|---|---|
| Email per pelanggaran | Karyawan (alamat dari data master) **+ CC HR**; bila karyawan tanpa email → **HR saja** | Saat batas terlewati |
| Email rekap harian | Daftar penerima HR, lampiran `.xlsx` | Sesuai jadwal yang diatur di web |

- Daftar penerima HR **diatur dari web** oleh admin, disimpan di database, maksimal 20 alamat. `SMTP_TO` dari env tidak lagi menjadi satu-satunya daftar penerima; nilainya dipakai sebagai bawaan.
- Rekap harian dicatat terkirim/belum per tanggal: yang terlewat saat server mati dikirim saat server hidup kembali, dan tidak pernah ganda.
- Akun pengirim SMTP tetap dari env; pengubahan dari web (dengan password terenkripsi) adalah kandidat fase berikutnya (dokumen 12 §4).

**Kebutuhan email (SMTP):**

- Akun pengirim dari server email klien (Microsoft 365, Google Workspace, atau mail server kantor) lewat SMTP dengan TLS, bukan server email buatan sendiri; email dari domain tanpa SPF/DKIM/DMARC akan masuk spam.
- Mesin B membutuhkan akses keluar ke server SMTP tersebut (port 587).
- Kredensial SMTP disimpan di `.env` mesin B, tidak di repo. Pada deployment Portainer, variabel `SMTP_*` diisi di environment stack dan `SMTP_ENABLED` diubah menjadi `true`.
- Data master karyawan perlu memuat email karyawan; ketersediaannya dari pihak klien **belum dipastikan** (dokumen 12 §9).
- Uji pengiriman ke alamat karyawan dan HR nyata saat instalasi, termasuk pengecekan folder spam.

Tabel di bawah adalah perbandingan yang menjadi dasar keputusan, disimpan sebagai acuan bila saluran lain diminta di masa depan.

| Saluran | Kelebihan | Kekurangan | Cocok untuk |
|---|---|---|---|
| **Aplikasi mobile khusus (ringan)** | Push dan tampilan bukti dengan tombol verifikasi di satu tempat; tidak bergantung platform chat | Biaya pengembangan terbesar di jadwal 6 minggu; distribusi lewat store atau instal manual; perawatan tiap update OS; push tetap butuh FCM/APNs (server perlu akses internet keluar) | Fase berikutnya |
| **PWA (web yang di-install)** | Memakai kode dashboard yang sama; Web Push tanpa store | Push di iOS hanya bila di-install ke home screen (iOS 16.4+); butuh HTTPS | Jalan tengah bila klien menginginkan "aplikasi" |
| **WhatsApp Business API (resmi)** | Paling pasti dibaca; tanpa instalasi | Verifikasi bisnis oleh Meta, biaya per percakapan, template pesan harus disetujui; data pelanggaran melewati server Meta | Peringatan real-time bila klien siap biaya & proses |
| **WhatsApp tidak resmi (library web)** | Murah dan cepat | Melanggar ketentuan WhatsApp, nomor dapat diblokir kapan saja | **Tidak direkomendasikan** |
| **Telegram bot** | Gratis, API resmi, tombol aksi | Tidak semua karyawan memakai Telegram | Peringatan real-time berbiaya rendah |
| **Email (SMTP)** | Gratis, formal, arsip | Lambat dibaca | Laporan harian/mingguan |

**Dipilih:** email (pelanggaran per karyawan dan rekap harian ke HR) + notifikasi dashboard (real-time bagi yang sedang membuka dashboard). Kanal cepat tambahan (WhatsApp resmi/Telegram) atau aplikasi mobile menjadi opsi fase berikutnya.

## 5. Model AI dan lisensi

| Komponen | Sumber | Lisensi | Catatan |
|---|---|---|---|
| Detector orang D-FINE (n/s/m) | LibreYOLO (`LibreDFINEm.pt`, `LibreDFINEs.pt`) | MIT (library), bobot mengikuti rilis D-FINE | Pengganti Ultralytics (AGPL) |
| Tracker ByteTrack | FoundationVision ByteTrack, di-vendor | MIT | Header lisensi dipertahankan |
| Embedder wajah AuraFace-v1 (`glintr100.onnx`) | Hugging Face `fal/AuraFace-v1` | Apache-2.0 | Eksplisit untuk penggunaan komersial |
| Detektor wajah SCRFD (`scrfd_10g_bnkps.onnx`) | Repositori yang sama (`fal/AuraFace-v1`) | Repositori berlabel Apache-2.0 | **Asal bobot perlu dipastikan** (lihat di bawah) |
| Model ReID (tubuh) | Belum dipilih (jalur Engine B, dokumen 12 §7) | Belum diketahui | Baru 8 Oktober 2026; lisensi bobot wajib dicek sebelum dipakai, seperti SCRFD |
| Runtime | onnxruntime(-gpu), PyAV, OpenCV, NumPy | MIT/BSD/Apache | |

**Catatan SCRFD (terbuka, pemilik: EA).** Repositori `fal/AuraFace-v1` berisi `glintr100.onnx` (AuraFace) serta `scrfd_10g_bnkps.onnx`, `1k3d68.onnx`, `2d106det.onnx`, dan `genderage.onnx`, dengan lisensi Apache-2.0 di level repositori. Model card hanya membahas AuraFace. Keempat file lain bernama dan berukuran sama dengan paket model insightface, yang bobotnya berlisensi non-komersial. Label lisensi repositori tidak otomatis melisensikan ulang bobot pihak lain. Langkah: bandingkan SHA256 `scrfd_10g_bnkps.onnx` dari fal dengan file bernama sama di paket insightface. Bila identik, putuskan antara (a) menerima risiko secara tercatat, atau (b) mengganti detektor wajah dengan YuNet (OpenCV, lisensi permisif, keluaran 5 landmark yang sama) atau bobot yang dilatih sendiri. Penggantian hanya menyentuh `ScrfdDetector` di `face_onnx.py` dan sebaiknya diputuskan **sebelum** kalibrasi threshold di pilot.

Semua file model disimpan di mesin engine (`models/`), tidak dibundel di repo, dan dicatat hash-nya di dokumen rilis.

## 6. Platform GPU dan kontainer

- Driver NVIDIA di host; engine berjalan di kontainer berbasis `nvidia/cuda` Ubuntu dengan NVIDIA Container Toolkit, sehingga lingkungan identik di mesin pengembang Linux, mesin uji, dan server klien.
- Versi CUDA, cuDNN, TensorRT, dan `onnxruntime-gpu` dikunci sebagai satu kombinasi yang teruji.
- Engine sudah divalidasi berjalan di Linux (Arch). Verifikasi akhir dilakukan di distro dan versi yang sama dengan server target sebelum instalasi.
- NVDEC dipakai untuk decode lima stream. PyAV dengan FFmpeg berdukungan CUDA men-decode di GPU tetapi mengunduh frame ke CPU; wheel PyAV bawaan tidak membawa CUDA. Untuk frame yang tetap di GPU (dokumen 04 §14.5) dibutuhkan pustaka NVIDIA tersendiri (mis. PyNvVideoCodec). Dukungan Windows, kecocokan versi CUDA/driver, dan lisensinya diverifikasi di spike 15–16 Oktober sebelum dipakai.
- **Lingkungan benchmark dan demo (8 Oktober 2026, dokumen 12 §6):** engine, MediaMTX, dan ffmpeg berjalan langsung di laptop Windows (i7-13700HX, RTX 4060 Laptop, 16 GB) dalam env conda, bukan kontainer. Backend dan frontend berjalan di server i5-3470/16 GB lewat Portainer CE. Untuk laptop Intel hybrid, engine dikunci ke P-core (`-AffinityMask 0xFFFF`) dan power throttling ffmpeg/MediaMTX dimatikan sampai uji A/B (`docs/DEMO-REMOTE.md` §8) membuktikan mana yang krusial. Apakah laptop dipakai sebagai mesin operasional di lokasi klien belum diputuskan; bila ya, engine dijalankan sebagai service yang hidup ulang otomatis, sleep dimatikan, dan jam aktif Windows Update diatur.

## 7. Jaringan dan akses jarak jauh

- Nginx di mesin B: TLS (sertifikat internal atau dari CA kantor), HTTP/2, proxy ke backend dan MediaMTX.
- Koneksi engine ↔ backend lewat jaringan privat (VLAN atau WireGuard) dengan handshake terautentikasi (P3).
- TURN server (misalnya coturn) hanya bila dashboard harus diakses WebRTC dari luar LAN; bila tidak, cukup LL-HLS lewat VPN.
- Akses maintenance tim: VPN (WireGuard/Tailscale) ke kedua mesin, disiapkan saat instalasi dengan persetujuan IT klien.
- Dashboard kini dapat diakses dari internet; karena itu semua endpoint data wajib login dan video live hanya untuk admin (dokumen 12 §3.8, dokumen 02 §7).

### 7.1 Topologi demo jarak jauh (8 Oktober 2026)

Rincian langkah ada di `docs/DEMO-REMOTE.md`.

| Komponen | Pilihan | Catatan |
|---|---|---|
| Jaringan privat laptop–server–VPS | **NetBird** | ACL: server → laptop TCP 8765, 8888, 8889; VPS → laptop TCP 8189 (hanya mode WebRTC); VPS → server TCP 80. Env container memakai IP NetBird, bukan nama `*.netbird.cloud` |
| Backend + frontend | **Portainer CE** di server, `deploy/docker-compose.portainer.yml` | `env_file: stack.env`, `policy.yaml` dan database di volume `/data`; GitOps update dimatikan pada hari demo |
| Akses penonton | **Cloudflare → VPS → NetBird → server:80** | Cache Rule *Bypass* untuk `/hls/*` (segmen `.mp4` di-cache Cloudflare secara bawaan); bila VPS memakai nginx, buffering `/api/` dimatikan untuk SSE |
| Video ke browser | **HLS default** | Tembus Cloudflare; tertinggal beberapa detik, normal |
| WebRTC | **Opsional**, lewat TCP 8189 di IP publik VPS → NetBird → laptop | Tidak bisa lewat proxy Cloudflare; jaringan yang hanya membuka 80/443 memblokirnya, dan frontend belum punya fallback otomatis ke HLS |
| Engine | Bind ke IP NetBird laptop | Dibatasi ACL NetBird + firewall Windows; handshake terautentikasi (`ENGINE_SHARED_KEY`) belum didukung backend (P3 tetap terbuka) |

Topologi ini untuk demo dan benchmark; topologi instalasi di lokasi klien (dokumen 10 §2) belum diputuskan ulang.

## Riwayat perubahan

- 9 Oktober 2026 (v1.2): §6 catatan NVDEC diperjelas (PyAV hwaccel bukan nol-salin; pustaka NVIDIA untuk frame di GPU diverifikasi di spike).
- Versi 1.1 (8 Oktober 2026): baris versi ditambahkan di bawah judul.
- §1: ditambah port 8189/tcp untuk WebRTC demo via VPS; otorisasi video browser diputuskan lewat `auth_request` nginx (hanya admin); catatan MediaMTX di laptop pada demo dan sumber uji ffmpeg `-r 25`.
- §2: ditambah kebutuhan rekaman multi-kamera lokasi klien untuk evaluasi ReID.
- §3: ditambah sinkronisasi jam laptop, server, dan PC penonton untuk demo jarak jauh.
- §4: ditambah dua jenis email (per pelanggaran ke karyawan + CC HR; rekap harian ke HR dengan `.xlsx`), penerima HR diatur dari web (maks. 20, `SMTP_TO` sebagai bawaan), rekap idempoten; uji kirim ke karyawan dan HR menggantikan supervisor.
- §5: ditambah baris model ReID (belum dipilih, lisensi perlu dicek).
- §6: ditambah lingkungan benchmark/demo (laptop Windows 4060 tanpa kontainer, server Portainer CE, afinitas P-core, power throttling).
- §7: ditambah catatan akses internet dan subbagian 7.1 topologi demo (NetBird, Portainer CE, Cloudflare/VPS, HLS default, WebRTC opsional via TCP 8189).
