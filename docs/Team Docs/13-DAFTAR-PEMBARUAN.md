# 13 — Daftar Pembaruan per 8–9 Oktober 2026

Versi 1.1 · 9 Oktober 2026 · Internal tim

Daftar ini membandingkan keadaan **sebelumnya** (dokumen 09a, 10, ARCHITECTURE.md,
tabel target prototype, kode sampai paket r6) dengan **keputusan dan perubahan per
8 Oktober 2026** (dokumen 12 dan paket r7). Dipakai supaya anggota tim yang membaca
dokumen lama tahu bagian mana yang sudah tidak berlaku.

## 1. Lingkup dan target

| Topik | Sebelumnya | Sekarang | Rujukan |
|---|---|---|---|
| ReID | Dikecualikan dari fase 1 (dok. 10 §1); "jangan bangun ReID dulu" (ARCHITECTURE §5.4) | **Masuk prototype**: ReID harian berjangkar wajah, identitas tertunda, atribusi mundur | Dok. 12 §3.6 |
| "Posture recognition" | Permintaan klien: mengenali orang dari bentuk tubuh bila wajah tidak pernah terlihat | Tidak dijanjikan (masalah riset). Diganti ReID berjangkar wajah + kamera jangkar + alur "tidak dikenal" ke HR | Dok. 12 §3.6 |
| Kecepatan analisis | 12 fps per kamera (estimasi dok. 10 §2) | **≥ 6 fps per kamera + interpolasi kotak** di frontend; 10–12 fps jadi target lanjutan | Dok. 12 §2.1, §3.7 |
| Beban uji | Asumsi 50–200 karyawan (dok. 10 §1) | Stress test **100 orang total di 5 kamera** + **100 karyawan terdaftar** | Dok. 12 §2.2 |
| Definisi selesai | Tabel fitur dengan status "tested/cek" | Kriteria terukur: performa, beban, akurasi, operasional; tiga tingkat status | Dok. 12 §2 |
| "Engine 24/7" | Belum didefinisikan | Proses engine tetap hidup; **analisis kamera** aktif/nonaktif sesuai jadwal; uji 3 hari | Dok. 12 §2.4, §3.3 |

## 2. Fitur aplikasi

| Topik | Sebelumnya | Sekarang | Rujukan |
|---|---|---|---|
| Data karyawan | Enrollment memakai ID ketikan bebas | **Data master karyawan** (ID, nama, divisi, email, status) + enrollment lewat **combobox** | Dok. 12 §3.1 |
| Peran | `admin` dan `viewer` (viewer = staf yang melihat dashboard) | **Admin = HR** (semua akses); **viewer = akun karyawan**, hanya notifikasi dan pemakaian miliknya | Dok. 12 §3.2 |
| Manajemen pengguna | Admin awal dari env saja | Menu manajemen pengguna untuk admin; akun karyawan dibuat dari data master | Dok. 12 §3.2 |
| Jam istirahat | 12:00–13:00 tetap di `policy.yaml` (dok. 10 §5) | **Diatur dari web, per hari**; berlaku mulai hari berikutnya | Dok. 12 §3.3 |
| Jadwal engine | Engine dinyalakan manual | **Jadwal operasional dari web** (`set_cameras` enabled/disabled, track ditutup `schedule_off`) | Dok. 12 §3.3 |
| Email pelanggaran | Ke daftar penerima global `SMTP_TO` dari env (09a D6) | **Ke karyawan + CC HR**; bila karyawan tanpa email → HR saja | Dok. 12 §3.4 |
| Email rekap | Tidak ada | **Rekap harian ke HR**, jadwal diatur di web, lampiran `.xlsx` | Dok. 12 §3.4 |
| Penerima email | Hanya dari env, tampil read-only di pengaturan | **Daftar HR diatur dari web** (database); env jadi bawaan | Dok. 12 §3.3 |
| Report | Hanya daftar pelanggaran | **Halaman report**: total free time per karyawan per hari, rincian lokasi, status; export `.xlsx` | Dok. 12 §3.5 |
| Tampilan viewer | — | Notifikasi milik sendiri + pemakaian free time hari ini | Dok. 12 §3.2 |

## 3. Keamanan akses

| Topik | Sebelumnya | Sekarang | Rujukan |
|---|---|---|---|
| Endpoint GET | Banyak terbuka tanpa login (pelanggaran, notifikasi, statistik, kamera, stream deteksi, status email) | **Semua wajib login**, disaring per peran di backend | Dok. 12 §3.8 |
| Notifikasi SSE | Semua notifikasi ke siapa pun | Disaring per pengguna | Dok. 12 §3.8 |
| Video live | `/hls/`, `/whep/` terbuka bagi yang tahu URL | Hanya admin, lewat `auth_request` nginx | Dok. 12 §3.8 |

## 4. Engine dan performa

| Topik | Sebelumnya | Sekarang | Rujukan |
|---|---|---|---|
| Kotak ganda di overlay | Track LOST ikut digambar dengan posisi beku sampai 1 detik ("2–3 kotak per orang") | **Diperbaiki (r7)**: overlay hanya track aktif + LOST ≤ 0,3 detik | CHANGELOG r7 |
| Laptop 4060 | Fps berganti 10 ↔ 6, stall sampai 9 detik | Run bersih 10,00 fps, 0 drop, umur kotak p99 0,09 dtk; penyebab dipastikan lewat uji A/B | DEMO-REMOTE §8 |
| Sumber video uji | Script ffmpeg tanpa `-r` (sumber 30 fps) | `-r 25`, tanpa audio, `yuv420p`, tanpa B-frame | DEMO-REMOTE §3.3 |
| Turbo CPU | Diduga penyebab (P-core terkunci 2 GHz) | **Gugur**: turbo hidup justru lebih buruk; kembali ke setelan EB | Hasil uji 4060 8 Okt |
| Ringkasan gladi | Dianalisis manual | `scripts/summarize_gladi.py`: tabel + vonis LULUS/GAGAL | CHANGELOG r7 |
| Arsitektur performa | Satu proses Python; thread per kamera berjalan secepat mungkin; batching kebetulan (tunggu 4 ms). Rencana 8 Okt: proses per kamera | **9 Okt: tetap satu proses + satu D-FINE**, ritme dipegang **penjadwal berdetak tetap**, pemrosesan sebanyak mungkin di GPU (NVDEC menyusul spike). Proses per kamera jadi opsi terakhir | Dok. 12 §3.9; dok. 04 §14 |
| Pemilik model ReID | EB (model + worker) | **EA** (logika, model, worker); EB fokus ke struktur engine | Dok. 12 §7 |
| Antarmuka ReID ↔ engine | Belum ditentukan | Antrean internal per-kamera → inti identitas, disepakati di kontrak 13 Okt | Dok. 04 §14.4 |
| Kerangka penjadwal | — | Paket r9: `mailbox`, `tick_scheduler`, `nvdec_source` (stub), default mati | CHANGELOG r9 |

## 5. Deployment dan infrastruktur

| Topik | Sebelumnya | Sekarang | Rujukan |
|---|---|---|---|
| Topologi | Mesin A (engine) + mesin B (BE, FE, MediaMTX) di satu LAN, Ubuntu headless (dok. 10 §2) | Demo: **engine + MediaMTX + ffmpeg di laptop (Windows)**, **BE + FE di server Portainer CE**, berjauhan lewat **NetBird**; penonton lewat **Cloudflare → VPS** | DEMO-REMOTE |
| Compose | `docker-compose.yml`: tanpa `env_file`, config `:ro`, bind mount relatif | Tambahan **`docker-compose.portainer.yml`**: `env_file: stack.env`, `policy.yaml` di volume, tanpa bind mount relatif | CHANGELOG r7 |
| Video ke browser | WebRTC/HLS dari MediaMTX lokal | **HLS default** (tembus Cloudflare); WebRTC opsional lewat TCP 8189 di IP publik VPS | DEMO-REMOTE §2, §7 |
| Engine di jaringan | Bind 127.0.0.1 | Bind **IP NetBird**; dibatasi ACL NetBird + firewall Windows | DEMO-REMOTE §1, §3 |
| Mesin benchmark | Spesifikasi rekomendasi (dok. 10 §2) | Server i5-3470/16 GB; laptop i7-13700HX + RTX 4060 Laptop/16 GB | Dok. 12 §6 |

## 6. Konvensi tim

| Topik | Sebelumnya | Sekarang | Rujukan |
|---|---|---|---|
| Catatan perubahan | Satu file `PERUBAHAN-*.md` per paket di root (28 file) | **Satu `docs/CHANGELOG.md`**, terbaru di atas; file lama ke `docs/arsip/` | Dok. 12 §10.2 |
| Pengiriman kode | Zip, lalu sempat `.md` berisi kode | **Zip kumulatif**; `.md` hanya untuk diskusi | Dok. 12 §10.1 |
| Line ending | CRLF kecuali `.sh`, tapi `.sh` berubah jadi CRLF di repo | `.gitattributes` (`*.sh text eol=lf`) + renormalisasi; **`* text=auto` ditunda** (paket r8) | Dok. 12 §10.3 |
| Struktur repo | Root penuh catatan, dokumen status basi | **Selesai paket r8**: `docs/CHANGELOG.md`, `docs/arsip/` (31 file), README berindeks, `.gitignore` untuk bobot model dan SQLite | Dok. 12 §10.3 |
| Timeline | Dok. 09: minggu 1–6 tanpa tanggal | **Dok. 14**: 12 Okt – pilot 30 Nov, gerbang bertanggal (usulan) | Dok. 14 |
| Status fitur | "tested / cek" | Berfungsi (simulasi) → teruji data nyata → terkalibrasi | Dok. 12 §2.5 |

## 7. Dokumen lama yang terdampak

| Dokumen | Bagian yang tidak berlaku lagi | Pengganti |
|---|---|---|
| 10-KETERBATASAN-SPEK-KLIEN | §1 ReID dikecualikan; §2 asumsi 12 fps; §5 jam istirahat tetap 12–13 | Dok. 12 §3.6, §2.1, §3.3 |
| 09a-WORKPLAN-DEMO | D6 penerima global; D7 arti peran viewer | Dok. 12 §3.4, §3.2 |
| ARCHITECTURE.md | §5.4 "Jangan bangun ReID dulu" | Dok. 12 §3.6 |
| WORKPLAN_STATUS.md, PACKAGE_VERSION.txt | Seluruhnya (status 23 September) | Dok. 12 + tabel target |
| Tabel target prototype | Kolom status; estimasi ReID tanpa syarat | Dok. 12 §2.5, §3.6 |
| 04-ARSITEKTUR-ENGINE v1.1 | §5 "proses per kamera dan/atau batching"; §11 "EB memegang model ReID" | Dok. 04 v1.2 §14; dok. 12 §3.9, §7 |

## Riwayat perubahan

- 9 Oktober 2026 (v1.1): baris arsitektur performa diganti keputusan struktur
  engine; ditambah pemilik model ReID, antarmuka antrean, kerangka penjadwal r9,
  status restrukturisasi repo r8, timeline dokumen 14, dan dokumen 04 v1.1 sebagai
  dokumen terdampak.
- 8 Oktober 2026 (v1.0): versi pertama.
