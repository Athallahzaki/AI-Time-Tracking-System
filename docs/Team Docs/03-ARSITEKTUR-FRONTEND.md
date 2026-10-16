# 03 — Arsitektur Frontend

Versi 1.1 · diperbarui 8 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Frontend adalah aplikasi web Vue 3 (Vite, Tailwind, komponen reka-ui, hls.js), disajikan oleh nginx di mesin B. Tidak ada aplikasi mobile native di fase 1; dashboard dibuat responsif sehingga dapat dibuka dari ponsel.

## 1. Kondisi sekarang

- Rute yang ada (paket r7): Login, Dashboard (`DashboardView`), Enrollment, dan Pengaturan; Enrollment dan Pengaturan hanya untuk peran `admin`. Komponen dashboard ada di `components/dashboard/`: feed kamera, overlay deteksi, statistik, panel jatah, enrollment, koreksi manual, alert orang tak dikenal. Peran yang dikenal frontend saat ini: `admin` dan `viewer`.
- Enrollment masih memakai ID karyawan yang diketik bebas; belum ada data master karyawan, manajemen pengguna dari menu, halaman report, maupun tampilan khusus viewer (dokumen 13 §2).
- Pemutar video mendukung tiga mode: **WHEP/WebRTC** (latensi rendah), **LL-HLS** (lewat MediaMTX), dan **file MP4 langsung** (untuk demo dan uji rekaman).
- Overlay kotak deteksi berasal dari SSE backend (`/api/detections/stream`), satu koneksi per kamera. Posisi kotak belum diinterpolasi antar frame analisis (lihat §3).
- Masih ada sisa model "gap = istirahat" (`GapClassificationBadge.vue`, istilah gap di form koreksi dan `useEmployeeAllowance.ts`).
- Kode campuran JavaScript dan TypeScript; `CameraFeedCard.vue` (±730 baris) dan `useDetectionStream.ts` (±600 baris) memegang terlalu banyak tanggung jawab.

## 2. Halaman target fase 1

Peran pada prototype mengikuti dokumen 12 §3.2: **admin = HR** (semua akses) dan **viewer = akun karyawan** (hanya data miliknya). Peran HR dan supervisor yang terpisah dari admin adalah kandidat fitur berikutnya (dokumen 12 §4), bukan bagian prototype.

| Halaman | Peran | Isi |
|---|---|---|
| Login | semua | Masuk, ganti password; password sementara wajib diganti saat login pertama |
| Monitoring langsung | admin | Grid 5 kamera, overlay, siapa sedang di lokasi rekreasi, status koneksi engine bertahap dan status per kamera (pemanasan/live/degraded/gagal), zoom digital |
| Jatah hari ini | admin | Daftar karyawan: pemakaian, sisa, status, rincian per lokasi, pertama terlihat |
| Pelanggaran | admin | Daftar pelanggaran dengan snapshot bukti; verifikasi atau tolak; penanda "perlu dicek HR" untuk pelanggaran yang sebagian besar waktunya bersumber dari ReID (rencana, §3) |
| Data karyawan | admin | Data master: ID karyawan, nama, divisi, email, status aktif. ID karyawan adalah label yang boleh diedit; relasi memakai kunci internal dari backend. Tombol **"Buat akun"** membuat akun viewer (username = ID karyawan, password sementara). Penonaktifan menghapus referensi wajah |
| Enrollment | admin | Karyawan dipilih lewat **combobox dengan pencarian** dari data master (bukan input ID bebas); enrollment terpandu, status referensi |
| Manajemen pengguna | admin | Menu terpisah dari data karyawan: daftar akun login, peran, aktif/nonaktif. Admin terakhir tidak dapat dihapus atau dinonaktifkan |
| Orang tak dikenal | admin | Daftar alert, tetapkan ke karyawan (enrollment dari CCTV), mute per kamera dengan durasi |
| Tinjauan ReID | admin | Antrean tinjauan HR untuk pelanggaran/kunjungan bersumber ReID (rencana, bergantung pada ReID dokumen 12 §3.6) |
| Koreksi & audit | admin | Koreksi kunjungan, pengecualian lokasi, jejak audit |
| Laporan | admin | Per karyawan per hari: total free time terpakai, sisa jatah, jumlah kunjungan, rincian per lokasi, status (aman/peringatan/lewat), menit bersumber ReID (setelah ReID tersedia); filter rentang tanggal; tombol **"Export Excel"** (`.xlsx`) |
| Pengaturan | admin | Batas jatah dan peringatan (sudah ada); jam istirahat resmi **per hari** (berlaku mulai hari berikutnya, perubahan dicatat); jadwal operasional analisis engine per hari; jam kirim email rekap harian; daftar penerima rekap (HR, maksimal 20 alamat) |
| Admin sistem | admin | Kamera (kategori, zona pintu, sumber), kebijakan, kesehatan sistem |
| Ringkasan saya | viewer | Hanya notifikasi pelanggaran **miliknya** dan **pemakaian free time miliknya hari ini** |

Viewer hanya melihat data miliknya; pembatasan ditegakkan di backend (dokumen 12 §3.8), bukan hanya disembunyikan di UI. Berkas `.xlsx` dibuat oleh backend (satu pembuat file untuk lampiran email dan export report), bukan di browser. Penerima per supervisor dan akun pengirim SMTP yang dapat diubah dari web adalah kandidat berikutnya (dokumen 12 §4).

## 3. Video dan overlay

**Sumber video browser** adalah substream H.264 dari MediaMTX. Browser tidak pernah menyambung langsung ke kamera. H.265 tidak dipakai untuk browser karena dukungannya tidak merata. Video live (`/hls/`, `/whep/`) dan stream deteksi hanya untuk admin; nginx memeriksanya lewat `auth_request` ke backend (dokumen 12 §3.8).

**Pemilihan mode:**

- Desktop di LAN: WebRTC (WHEP) untuk latensi rendah.
- Ponsel atau jaringan yang tidak mendukung WebRTC: LL-HLS. Fallback otomatis dari WHEP ke HLS bila negosiasi gagal (P15); fallback ini **belum ada** di kode saat ini.
- **Demo jarak jauh** (penonton lewat Cloudflare → VPS → NetBird → server): **HLS adalah mode default** karena dapat melewati Cloudflare. WebRTC opsional lewat TCP 8189 di IP publik VPS; jaringan yang hanya membuka port 80/443 akan menampilkan video hitam, dan pemulihannya manual dengan kembali ke konfigurasi HLS (`docs/DEMO-REMOTE.md` §7).
- Konfigurasi ICE (STUN/TURN) diambil dari backend, bukan di-hardcode.

**Sinkronisasi overlay:**

- Mode HLS mencocokkan `at` dari engine dengan `EXT-X-PROGRAM-DATE-TIME`. Ini jalur yang disarankan untuk sinkron rapi.
- Mode WebRTC saat ini memakai `Date.now() - 0.8 dtk` dan `playoutDelayHint`, yang diabaikan Safari/Firefox (P10). Fase 1: sinkron berbasis timestamp frame (`requestVideoFrameCallback`) bila tersedia, dan terima presisi ±200–300 ms sebagai batas wajar.
- **Toleransi wajib** untuk jalur live: bila frame deteksi terdekat berselisih lebih dari ±1 detik dari posisi video, kotak disembunyikan dan ditampilkan penanda "analisis tertinggal" (P16). Tanpa ini, kotak lama digambar di atas video baru.
- Kualitas sinkron bergantung pada NTP di kamera, mesin A, dan mesin B (dokumen 04 §7, dokumen 05). Pada topologi demo jarak jauh, MediaMTX berada di laptop engine sehingga PDT HLS dan `at` sama-sama berasal dari jam laptop; mode WebRTC tetap membandingkan jam laptop dengan jam browser penonton.

**Interpolasi kotak (rencana, dokumen 12 §3.7):**

- Target analisis prototype adalah 6 fps per kamera. Frontend **menginterpolasi** posisi kotak di antara dua frame analisis, per `track_uuid`, di mode HLS maupun WebRTC.
- Kriteria "halus": kotak digambar ulang setiap frame layar (±60 kali per detik), tidak melompat, dan hilang paling lama 0,3 detik setelah orangnya hilang.
- Track yang baru muncul atau baru hilang tidak diinterpolasi (tidak ada pasangan frame untuk diinterpolasi).
- Interpolasi tidak menggantikan toleransi ±1 detik di atas: bila data analisis tertinggal, kotak tetap disembunyikan.
- Kotak hantu (track LOST digambar dengan posisi beku) sudah diperbaiki di sisi engine pada paket r7: `view.frame` hanya memuat track aktif dan track LOST yang hilang ≤ 0,3 detik (dokumen 04 §13). Frontend tidak perlu menyaring ulang.

**Label sumber identitas (rencana):** kotak, rincian kunjungan, dan pelanggaran menampilkan sumber identitas sesuai `identity_source` (`face`, `tracking`, `reid`, `reid_retro`; dokumen 07 §1.4). Nilai `reid` dan `reid_retro` baru ada setelah ReID diimplementasikan. Identitas sementara (`ANON-xxxx`) dapat berubah menjadi nama karyawan setelah backend menerima `identity.resolved` (atribusi mundur).

**Mode file langsung (demo):** video diperlambat mengikuti kecepatan engine (`playbackRate` minimum 0,25×, pause bila tertinggal lebih dari 1 detik). Perilaku ini sengaja, hanya untuk demo/uji rekaman, dan tidak berlaku untuk live.

**Zoom digital:** perbesaran di sisi browser (pinch/scroll) dengan overlay ikut ditransformasi dalam container yang sama. Tidak menyentuh kamera atau AI. Zoom optik/PTZ tidak termasuk fase 1.

**Koneksi SSE:** satu stream multipleks untuk semua kamera menggantikan satu `EventSource` per kamera, karena HTTP/1.1 membatasi 6 koneksi per origin (P11). Nginx dikonfigurasi TLS dan HTTP/2. Stream notifikasi disaring per pengguna di backend: admin menerima semua, viewer hanya miliknya (dokumen 12 §3.4, §3.8).

## 4. Enrollment dari web

- Karyawan yang di-enroll dipilih lewat combobox dengan pencarian dari data master; enrollment tidak dapat dibuat untuk ID yang belum terdaftar.
- Mode kamera terpandu (`getUserMedia`, butuh HTTPS): instruksi sudut wajah, umpan balik kualitas sebelum dikirim, 3–5 foto.
- Mode unggah file sebagai alternatif.
- Hasil per foto dari engine ditampilkan dengan alasan penolakan yang dapat dipahami HR ("wajah terlalu kecil", "buram", "terlalu miring", "pencahayaan kurang", "lebih dari satu wajah", "mirip dengan karyawan X").
- Dari halaman orang tak dikenal: tombol "tetapkan ke karyawan" untuk menambah referensi dari CCTV, dengan konfirmasi eksplisit.

## 5. Struktur kode target

Mengikuti `PROJECT STRUCTURE.md` (dokumen 08):

```
frontend/src/
├── views/        # Halaman yang dipetakan ke rute
├── features/     # live-monitoring, allowance, violations, employees, users, unknown, corrections, reports, settings, viewer, admin
├── components/   # UI lintas fitur (ui/, layout/)
├── composables/  # useWhep, useHls, useDirectSync, useOverlaySync, useAuth, …
├── services/     # Klien API, stream SSE multipleks
├── stores/       # Pinia hanya untuk state lintas fitur (pengguna, daftar kamera)
├── router/       # Rute dan penjaga akses per peran
└── assets/
```

Seluruh kode dipindah ke TypeScript. `CameraFeedCard.vue` dipecah menjadi composable per mekanisme; interpolasi kotak ditempatkan di composable sinkron overlay, bukan di komponen. Komponen dan istilah model gap dihapus.

## 6. Build dan penyajian

- `npm run build` menghasilkan aset statis yang disajikan nginx (`deploy/frontend/`).
- Nginx: TLS, HTTP/2, proxy `/api` ke backend, `/whep` dan `/hls` ke MediaMTX (dengan `auth_request` ke backend, hanya admin), header keamanan. Nginx tidak menyuntikkan kunci API.
- Untuk demo jarak jauh, image frontend dibangun lewat stack Portainer (`deploy/docker-compose.portainer.yml`); build npm memakan beberapa menit dan dilakukan jauh sebelum demo (`docs/DEMO-REMOTE.md` §4).
- Build frontend belum diverifikasi di lingkungan penyusunan dokumen; wajib dijalankan di CI.

## Riwayat perubahan

- 8 Oktober 2026 (v1.1): §1 diperbarui sesuai kode r7 (rute Login/Dashboard/Enrollment/Pengaturan, peran admin/viewer, enrollment masih ID bebas, belum ada interpolasi).
- §2: peran disederhanakan menjadi admin (= HR) dan viewer (= karyawan); peran hr/supervisor terpisah dipindah ke kandidat berikutnya.
- §2: halaman baru Data karyawan (dengan "Buat akun"), Manajemen pengguna, Pengaturan (jam istirahat per hari, jadwal engine, jam rekap, penerima HR), Tinjauan ReID, dan Ringkasan saya untuk viewer.
- §2: halaman Laporan diganti isinya sesuai dokumen 12 §3.5, export menjadi `.xlsx` dari backend.
- §3: video live dan stream deteksi hanya untuk admin lewat `auth_request`; HLS sebagai default untuk demo jarak jauh, WebRTC opsional; dicatat bahwa fallback WHEP→HLS belum ada.
- §3: ditambah interpolasi kotak per `track_uuid` (HLS dan WebRTC) dengan kriteria halus dokumen 12 §3.7, catatan perbaikan kotak hantu r7, dan label sumber identitas `face/tracking/reid/reid_retro`.
- §3: SSE notifikasi disaring per pengguna di backend; catatan jam pada topologi demo jarak jauh.
- §4: enrollment memilih karyawan lewat combobox dengan pencarian.
- §5–§6: daftar fitur target ditambah `users`, `settings`, `viewer`; catatan build image lewat Portainer.
