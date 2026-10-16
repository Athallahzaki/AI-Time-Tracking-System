# 07 — Protokol Komunikasi & API

Versi 1.1 · diperbarui 8 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Dua antarmuka: **protokol engine ↔ backend** (NDJSON di atas TCP, kontrak beku di `contracts/schema/engine_protocol.schema.json`) dan **API backend ↔ frontend** (REST + SSE, OpenAPI di `/openapi.json`). Rincian skema per field tetap di `ENGINE_PROTOCOL.md` dan skema JSON; dokumen ini merangkum dan mencatat perubahan fase 1.

## 1. Protokol engine ↔ backend

### 1.1 Aturan dasar

- **Transport:** NDJSON (satu objek JSON per baris). TCP antar-mesin (A ↔ B); Unix socket bila satu mesin.
- **Tiga kanal** dalam satu koneksi, dibedakan field `channel`:

| Kanal | Arah | Jaminan |
|---|---|---|
| `control` | Backend → Engine (dan balasannya) | Request/response, ACK segera saat diterima |
| `events` | Engine → Backend | Andal, berurut (`seq`), dapat diputar ulang dari outbox |
| `view` | Engine → Backend | Best-effort, boleh dibuang |

- **Amplop:** setiap pesan memiliki `type`, `v`, `ts` (RFC3339 UTC). Pesan `events` menambahkan `seq` (bilangan bulat monoton per `outbox_id`).
- **Waktu:** semua `*_pts` dalam detik relatif terhadap awal stream pada `stream_epoch`; semua `*_at` RFC3339 UTC dihitung engine. Backend tidak menghitung durasi dari jamnya sendiri.
- **Engine tidak pernah menunggu backend:** `view` dibuang saat antrian penuh; `events` menunggu di outbox.
- **Evolusi:** field tak dikenal diabaikan; penambahan field tidak menaikkan versi; perubahan yang memutus kompatibilitas menaikkan `protocol_version`.

### 1.2 Katalog pesan

**Kontrol (backend → engine):**

| Pesan | Fungsi |
|---|---|
| `hello` | Pesan pertama; membawa `last_event_seq` untuk replay |
| `set_cameras` | Daftar kamera yang diinginkan (deklaratif): `camera_id`, `uri`, `door_region` opsional, `enabled`. Juga dipakai untuk jadwal analisis: di luar jam operasional backend mengirim `enabled: false` (dokumen 12 §3.3) |
| `set_roster` | Daftar karyawan yang dikenali + `enrollment_version` (deklaratif) |
| `enroll` | Permintaan enrollment: `request_id`, `person_id`, `enrollment_version`, foto (JPEG base64) |
| `ack` | Konfirmasi event sampai `through_seq` (memangkas outbox) |

**Balasan kontrol (engine → backend):** `hello_ack` (versi, model, `oldest_available_seq`, `outbox_id`), `ack` (diterima/ditolak), `enroll_result` (per foto, alasan, `collides_with`), `replay_gap` (rentang event yang tidak lagi tersedia).

**Events (engine → backend):**

| Pesan | Makna |
|---|---|
| `presence.interval` | **Output utama**: satu identitas terlihat di satu kamera dari `start_at` sampai `end_at`, dengan zona awal/akhir dan alasan berakhir |
| `track.started` / `track.ended` | Siklus hidup track. Alasan berakhir yang ada di skema: `left_frame`, `occluded_timeout`, `merged_into_other_track`, `camera_lost`, `engine_shutdown`, `identity_released`; `schedule_off` direncanakan (§1.4) |
| `track.identified` | Track dikenali sebagai karyawan (kemiripan, margin, jumlah bukti); `identity_source` saat ini `face` atau `tracking` |
| `track.heartbeat` | Track masih hidup (tiap 30 detik) |
| `track.resumed` | Track disambung ke track sebelumnya (stitching) |
| `track.identity_changed` | Identitas track dilepas atau berganti |
| `person.unidentified_present` | Orang tak dikenal hadir lebih dari batas waktu |
| `camera.online` / `camera.failed` / `camera.degraded` / `camera.coverage` | Status kamera, offset jam per epoch, alasan degradasi |
| `engine.health` | Kesehatan engine (tiap 30 detik): model dimuat, antrian, laju buang, status kamera |
| `snapshot` | Daftar track yang hidup + offset jam per kamera (rekonsiliasi) |
| `enrollment_needed` | Karyawan di roster yang belum punya referensi |
| `identity.resolved` | **Rencana, belum ada di skema.** Kelompok track beridentitas sementara (`ANON-xxxx`) diselesaikan ke karyawan setelah wajahnya terkonfirmasi (§1.4) |

**View (engine → backend):** `view.frame` berisi kotak ternormalisasi per track, `person_id` bila dikenal, sumber identitas (`identity_source`: saat ini `face` atau `tracking`), dan skor detector; untuk overlay saja. Sejak paket r7, `view.frame` hanya memuat track aktif dan track LOST yang terakhir terlihat ≤ 0,3 detik (dokumen 04 §13).

### 1.3 Siklus koneksi

1. Backend menyambung dan mengirim `hello` dengan `last_event_seq` milik `outbox_id` yang diketahui.
2. Engine membalas `hello_ack` (dan `replay_gap` bila outbox tidak lagi menyimpan rentang yang diminta), memasang koneksi dan kursor secara atomik, lalu memutar ulang event setelah `last_event_seq`.
3. Bila `outbox_id` berbeda dari yang diketahui backend, backend menyambung ulang dengan kursor milik outbox tersebut.
4. Backend mengirim `set_cameras` dan `set_roster`.
5. Backend memproses event berurutan; bila `seq ≠ last + 1` tanpa `replay_gap`, backend memutus dan meminta replay (maksimal 3 kali, lalu lubang dicatat). Pesan yang gagal divalidasi masuk dead-letter dan tetap di-ACK.
6. Backend meng-ACK event; engine memangkas outbox sampai `through_seq`.

### 1.4 Perubahan protokol fase 1

Semua perubahan di bawah bersifat **penambahan** kecuali disebut lain, dan harus disepakati pemilik skema (EA) sebelum diimplementasikan.

| Perubahan | Alasan | Masalah |
|---|---|---|
| Autentikasi handshake: engine mengirim `nonce` di awal koneksi, `hello` membawa HMAC(kunci bersama, nonce); koneksi tanpa bukti ditolak | Mencegah klien liar membaca event atau memangkas outbox | P3, E3 |
| TCP keepalive dua sisi; timeout kirim di engine; koneksi lama diputus sebelum handshake baru mengambil kunci tulis | Koneksi setengah mati tidak lagi mengunci engine | P2 |
| Read timeout backend = 3 × interval `engine.health` | Deteksi engine hilang | P2, E1 |
| ACK bertumpuk (tiap N event atau 200 ms) | Mengurangi tulis outbox dan risiko saling tunggu | P12 |
| `engine.health.cameras` diperluas per kamera: `lag_seconds`, `effective_fps`, `frames_dropped_stale`, `clock_drift_seconds` | Kejujuran data saat overload dan drift | P17, P18 |
| `camera.degraded` dipakai untuk: lag bertahan, frame beku, perubahan adegan; membawa `since_at` | Rentang observasi yang turun kualitasnya terlihat | E4, E5, E15 |
| Pesan kontrol baru `forget_person` (`person_id`) | Penghapusan referensi saat karyawan keluar | P14, E13 |
| Pesan kontrol baru `enroll_from_track` (`request_id`, `person_id`, `track_uuid`), dijawab `enroll_result` | Enrollment dari rekaman CCTV lewat konfirmasi HR; engine menyimpan cache crop wajah terbaik per track untuk jangka pendek | Dokumen 02 §5 |
| Allow-list URI sumber di engine (selain di backend) | Pertahanan berlapis terhadap `set_cameras` liar | P3 |

Status di skema per paket r7: `auth_challenge` dan blok `auth` (HMAC) di `hello`, `forget_person`/`forget_result`, `enroll_from_track`, field per kamera di `engine.health`, serta `since_at` dan `camera.recovered` untuk rentang `camera.degraded` sudah ada di `engine_protocol.schema.json`. Backend belum mendukung kunci bersama handshake (`ENGINE_SHARED_KEY`); pada demo jarak jauh pengamannya ACL NetBird dan firewall (`docs/DEMO-REMOTE.md` §3.4).

**Tambahan per 8 Oktober 2026 (rencana, belum diimplementasikan; dokumen 12 §3.3 dan §3.6).** Kontrak ini disepakati EA pada hari 1–2 rencana ReID sebelum EB, BE, dan FE bekerja paralel; BE/FE memakai `fake_engine` sampai engine asli siap. Nama field di bawah adalah usulan dan baru final setelah masuk skema.

| Perubahan | Isi | Alasan |
|---|---|---|
| Event baru `identity.resolved` | `anon_id`, `person_id`, `track_uuids` (seluruh track dalam kelompok) | Atribusi mundur: backend memindahkan semua interval kelompok `ANON-xxxx` ke karyawan setelah wajahnya terkonfirmasi |
| Identitas sementara `ANON-xxxx` | Dipakai untuk tubuh tanpa wajah yang digabung lewat ReID; bentuk dan letak field (`person_id` atau field terpisah) belum diputuskan | Identitas tertunda ReID |
| Nilai `identity_source` diperluas | `face`, `tracking`, `reid`, `reid_retro` (skema saat ini hanya `face`, `tracking` di `track.identified` dan `view.frame`) | Label sumber di UI dan report; pelanggaran yang sebagian besar dari ReID ditandai "perlu dicek HR" |
| `end_reason` baru `schedule_off` | Track yang masih hidup saat analisis dimatikan oleh jadwal ditutup dengan alasan ini | Tidak dibaca sebagai "semua orang pulang" |
| Jadwal analisis lewat `set_cameras` | Memakai field `enabled` yang sudah ada; tidak perlu pesan baru | Proses engine tetap hidup, hanya analisis kamera yang dimatikan |

Kategori lokasi, jam istirahat, jadwal operasional, pengecualian, dan jatah **tidak** masuk protokol: engine tidak perlu mengetahuinya. Jadwal operasional hanya terlihat oleh engine sebagai `set_cameras` dengan `enabled: false`.

## 2. API backend ↔ frontend

### 2.1 Konvensi

- REST JSON dengan prefiks versi **`/api/v1`** (fase 1). Endpoint lama tanpa versi dipertahankan selama transisi, lalu dihapus.
- Autentikasi dengan sesi/token setelah login. **Semua endpoint data wajib login, termasuk GET** (dokumen 12 §3.8); setiap endpoint diberi peran minimum.
- Peran prototype: **admin** (= HR, semua akses) dan **viewer** (= akun karyawan). Data per orang disaring di backend sesuai peran: viewer hanya menerima notifikasi pelanggaran dan pemakaian free time **miliknya hari ini**. Penyaringan dilakukan di server, bukan disembunyikan di frontend. Peran HR/supervisor terpisah adalah kandidat berikutnya (dokumen 12 §4).
- Pagination (`limit`, `cursor`) untuk daftar; filter tanggal dilakukan di SQL.
- Waktu dalam RFC3339; tanggal laporan dalam zona waktu kebijakan (Asia/Jakarta).
- Streaming: satu SSE multipleks untuk overlay semua kamera dan satu SSE untuk notifikasi dashboard (peringatan, alert, status). SSE notifikasi disaring per pengguna; SSE deteksi/overlay hanya untuk admin.
- Video live (`/hls/`, `/whep/`) hanya untuk admin, diperiksa nginx lewat `auth_request` ke backend.

### 2.2 Endpoint yang sudah ada

Per paket r7. Sebagian besar GET di bawah masih dapat diakses tanpa login (dokumen 13 §3); semuanya akan diwajibkan login sesuai §2.1.

| Metode & path | Fungsi |
|---|---|
| `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` | Autentikasi |
| `GET /api/auth/users`, `POST /api/auth/users` | Daftar dan pembuatan pengguna (admin) |
| `GET /api/system/`, `/api/system/status`, `/api/system/dead-letters` | Status sistem, dead-letter |
| `GET /api/stats` | Statistik dashboard |
| `GET /api/cameras`, `GET /api/cameras/{id}` | Daftar dan detail kamera |
| `POST /api/cameras/{id}/start`, `/stop`, `/source` | Kontrol kamera (sumber hanya dari `allowed_sources`) |
| `GET /api/attendance/active`, `/derived`, `/break-usage`, `/breaks`, `/events`, `/summary` | Pemakaian jatah dan event |
| `POST /api/attendance/corrections`, `GET /api/attendance/corrections` | Koreksi HR |
| `GET /api/enrollments`, `POST /api/enrollments`, `GET /api/enrollments/requests/{id}` | Enrollment |
| `GET /api/violations` | Daftar pelanggaran |
| `GET /api/notifications`, `GET /api/notifications/stream` (SSE), `PATCH /api/notifications/{id}/read` | Kotak pesan dashboard |
| `GET /api/settings/policy`, `PUT /api/settings/policy` | Batas jatah dan peringatan |
| `GET /api/settings/email`, `POST /api/settings/email/test` | Status email (penerima dari env `SMTP_TO`), uji kirim |
| `GET /api/detections/stream` (SSE per kamera), `GET /api/detections/history` | Overlay dan riwayat deteksi |

### 2.3 Endpoint target fase 1

Endpoint bertanda **rencana** adalah tambahan per 8 Oktober 2026 dan belum diimplementasikan. Path untuk kelompok baru masih usulan; path final ditetapkan BE.

| Kelompok | Endpoint (ringkas) | Peran minimum |
|---|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password` (wajib dipakai saat login pertama dengan password sementara) | semua |
| Pengguna (rencana) | `GET/POST/PATCH /users`: akun login, peran, aktif/nonaktif. Admin terakhir tidak dapat dihapus atau dinonaktifkan. Terpisah dari data karyawan | admin |
| Kamera | `GET /cameras`, `PATCH /cameras/{id}` (nama, kategori, zona pintu, aktif, sumber dari allow-list) | admin |
| Kebijakan | `GET /policy`, `PUT /policy` (berversi, tanggal berlaku) | admin |
| Karyawan / data master (rencana) | `GET/POST/PATCH /employees` (ID karyawan sebagai label yang dapat diedit, nama, divisi, email, status aktif; relasi memakai kunci internal tetap), `POST /employees/{id}/deactivate` (menghapus referensi wajah), aksi "buat akun" yang membuat akun viewer (username = ID karyawan, password sementara), pencarian untuk combobox enrollment | admin |
| Enrollment | `POST /employees/{id}/enrollments` (foto), `POST /employees/{id}/enrollments/from-track`, `GET /enrollments/requests/{id}` | admin |
| Pengaturan (rencana) | Jam istirahat resmi per hari (berlaku mulai hari berikutnya, perubahan dicatat); jadwal operasional analisis engine per hari; jam kirim email rekap harian; daftar penerima rekap HR (maksimal 20, disimpan di database, `SMTP_TO` sebagai bawaan). `GET /api/settings/email` wajib login | admin |
| Pengecualian | `GET/POST/DELETE /exemptions` | admin |
| Jatah | `GET /usage?date=` (daftar), `GET /usage/{employee_id}?date=` (rincian kunjungan per lokasi, pertama terlihat) | admin; viewer hanya miliknya hari ini |
| Pelanggaran | `GET /violations`, `POST /violations/{id}/verify`, `POST /violations/{id}/reject`; membawa penanda "perlu dicek HR" bila sebagian besar waktunya bersumber ReID (rencana) | admin; viewer hanya miliknya (baca) |
| Koreksi | `POST /corrections` (terhadap `visit_id` stabil), `GET /corrections` | admin |
| Tak dikenal | `GET /unknowns`, `POST /unknowns/{id}/assign`, `POST /cameras/{id}/alert-mute` (durasi wajib), `DELETE /cameras/{id}/alert-mute` | admin |
| Laporan (rencana) | Report per karyawan per hari (total free time, sisa jatah, jumlah kunjungan, rincian per lokasi, status, menit bersumber ReID) dengan filter rentang tanggal; export **`.xlsx`** (bukan CSV) dari generator yang sama dengan lampiran email rekap harian. Format PDF belum diputuskan untuk prototype | admin |
| Notifikasi | `GET/PUT /notification-settings` | admin |
| Audit | `GET /audit` | admin |
| Sistem | `GET /system/health` (engine, jam, lag, outbox, disk, notifikasi), `GET /system/dead-letters` | admin |
| Stream | `GET /stream/overlay` (SSE multipleks), `GET /stream/notifications` (SSE, disaring per pengguna) | overlay: admin; notifikasi: semua (disaring) |
| Media | Hook otorisasi MediaMTX dan penerbitan token playback; `/hls/` dan `/whep/` lewat `auth_request` nginx | internal (admin) |

Endpoint yang berbasis model gap (`/breaks`, klasifikasi gap) dihapus setelah frontend pindah.

## Riwayat perubahan

- 8 Oktober 2026 (v1.1): §1.2 katalog diberi catatan pemakaian `set_cameras` `enabled: false` untuk jadwal analisis, daftar `end_reason` yang ada di skema, dan `identity.resolved` sebagai rencana.
- §1.2: `view.frame` dicatat hanya memuat track aktif + LOST ≤ 0,3 detik sejak r7; nilai `identity_source` saat ini (`face`, `tracking`) disebut eksplisit.
- §1.4: ditambah catatan status skema r7 (handshake HMAC, `forget_person`, `enroll_from_track`, field health per kamera, `since_at`/`camera.recovered` sudah ada; backend belum mendukung kunci bersama).
- §1.4: ditambah tabel rencana (belum diimplementasikan): `identity.resolved` (`anon_id`, `person_id`, `track_uuids`), ID sementara `ANON-xxxx`, `identity_source` `face|tracking|reid|reid_retro`, `end_reason` `schedule_off`.
- §2.1: semua endpoint data termasuk GET wajib login; peran admin (= HR) dan viewer (= karyawan) dengan penyaringan per peran di backend, termasuk SSE notifikasi; video live dan stream deteksi hanya admin.
- §2.2: tabel endpoint yang ada disesuaikan dengan kode r7 (auth, pengguna, pelanggaran, notifikasi, pengaturan) dan catatan GET yang masih terbuka.
- §2.3: peran hr/supervisor diganti admin/viewer; ditambah rencana endpoint data master karyawan (termasuk "buat akun"), manajemen pengguna, pengaturan (jam istirahat, jadwal engine, jadwal dan penerima rekap), dan report dengan export `.xlsx`.
