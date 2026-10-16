# 02 — Arsitektur Backend

Versi 1.1 · diperbarui 8 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Backend (FastAPI, Python) adalah tempat **semua kebijakan** tinggal: menerima event dari engine, mengubahnya menjadi kunjungan dan pemakaian jatah, mengirim peringatan, menyimpan koreksi, dan melayani frontend. Backend tidak meng-import apa pun dari `engine/`; satu-satunya yang dibagi adalah `contracts/`.

## 1. Kondisi sekarang (build 2026.09.23, dengan catatan kode per 8 Oktober 2026)

Yang sudah ada dan dipertahankan:

- Klien engine dengan handshake `hello`/`hello_ack`, kursor `seq` per `outbox_id`, deteksi lubang `seq` dan permintaan replay, dead-letter untuk pesan rusak.
- Penyimpanan event dan checkpoint dalam satu transaksi (SQLite WAL), sehingga crash tidak menggandakan atau menghilangkan event.
- Ledger free time dari event durabel (`free_time.py`): gabungan lintas kamera, penggabungan oklusi, pengaman engine diam, dibangun ulang dari database saat start.
- Kebijakan dari `policy.yaml` (zona waktu, jam istirahat resmi dengan menit, toleransi, jatah, peringatan).
- Koreksi append-only yang diterapkan ke hitungan; override kamera persisten; enrollment request/result; SSE untuk overlay; kunci API opsional.
- **Tambahan per 8 Oktober 2026:** login pengguna dengan token sesi (tabel `users`, `auth_sessions`), peran `admin` dan `viewer`, endpoint pengubah data dijaga `require_admin`, dan email pelanggaran lewat SMTP ke daftar global `SMTP_TO`.

Yang harus berubah untuk fase 1 (rinciannya di bagian berikut dan dokumen 06):

- Ledger dihitung ulang dari nol di setiap request, dan `visit_id` tidak stabil (koreksi HR bisa hilang, P5).
- Belum ada kategori lokasi: **semua kamera memotong jatah** (P21).
- Data master karyawan baru berisi ID dan nama (tanpa kunci internal terpisah, divisi, email, status aktif); akun pengguna belum terhubung ke karyawan; belum ada report dan rekap harian. Relasi ke supervisor **ditunda** ke fase berikutnya (dokumen 12 §4).
- Banyak endpoint GET (pelanggaran, notifikasi, statistik, kamera, stream deteksi, status email) masih terbuka tanpa login, dan nginx masih menyuntikkan `X-API-Key` ke request `/api/` (P1, dokumen 12 §3.8).
- Transport ke engine tanpa timeout/keepalive/autentikasi (P2, P3).
- Konfigurasi kamera di dua tempat (`cameras.yaml` dan tabel override); migrasi skema ad-hoc.

## 2. Komponen target

| Komponen | Tanggung jawab |
|---|---|
| `engine_link` | Koneksi ke engine: handshake terautentikasi, keepalive dan read timeout (±90 detik, berbasis `engine.health` tiap 30 detik), ACK bertumpuk, deteksi gap/replay, dead-letter, sinkronisasi deklaratif `set_cameras`/`set_roster`, pengukuran selisih jam engine–backend |
| `ingest` | Validasi pesan terhadap skema, simpan event durabel, teruskan ke ledger |
| `ledger` | Membangun dan memperbarui **kunjungan** secara inkremental dari event; menerapkan kategori lokasi, jam istirahat (per hari), toleransi, pengecualian; menghitung pemakaian harian dan pertama terlihat; **atribusi mundur ReID** saat `identity.resolved` (§10.4) |
| `policy` | Memuat dan memvalidasi kebijakan (jatah, jam istirahat, toleransi, ambang peringatan, kategori default); menolak start di mode produksi bila nilai belum disahkan |
| `settings` | Pengaturan yang diubah admin dari web dan disimpan di database: jam istirahat per hari, jadwal operasional engine, jadwal dan penerima rekap harian (§10.1) |
| `scheduler` | Menjalankan jadwal: mengaktifkan/menonaktifkan analisis kamera lewat `set_cameras`, mengirim rekap harian, mengejar rekap yang terlewat (§10.1, §10.2) |
| `alerts` | Menentukan kapan peringatan dini, pelanggaran, dan orang tak dikenal dipicu; deduplikasi; status mute per kamera |
| `notify` | Antarmuka pengiriman notifikasi dengan dua adapter fase 1: **dashboard** (kotak notifikasi per pengguna + SSE, disaring per peran) dan **email** (SMTP: per pelanggaran dan rekap harian), plus antrian kirim ulang. Adapter lain (WhatsApp, Telegram, push) dapat ditambah kemudian |
| `reports` | Report per karyawan per hari dan rentang tanggal; **satu generator `.xlsx`** untuk lampiran rekap harian dan export halaman report (§10.3) |
| `enrollment` | Data master karyawan, permintaan enrollment ke engine, enrollment dari rekaman CCTV (konfirmasi HR), penonaktifan dan penghapusan data wajah |
| `auth` | Login, sesi/token, peran (`admin`, `viewer`), penyaringan data per peran (viewer hanya data karyawan miliknya), manajemen pengguna |
| `media` | Integrasi MediaMTX: hook autentikasi baca/publish, token playback; endpoint `auth_request` nginx untuk `/hls/` dan `/whep/` (hanya admin) |
| `store` | Repositori per entitas, migrasi berversi, retensi |

## 3. Model data inti

| Entitas | Isi pokok | Catatan |
|---|---|---|
| `employee` | **kunci internal** (tidak berubah), ID karyawan (label, boleh diedit), nama, divisi, email, status aktif | Diperluas. Referensi wajah dan riwayat merujuk kunci internal, sehingga ID karyawan dapat diedit tanpa memutus data. Kolom email dipakai untuk email pelanggaran. `supervisor_id` ditunda ke fase berikutnya (dokumen 12 §4) |
| `user` | akun login, peran (`admin` = HR, `viewer` = karyawan), relasi ke satu `employee` (wajib untuk viewer), status aktif, penanda wajib ganti password | Sudah ada (tanpa relasi ke karyawan); diperluas. Peran `hr`/`supervisor` terpisah adalah kandidat fase berikutnya |
| `camera` | id, nama, URI analisis, URL tampilan, **kategori lokasi**, `door_region`, aktif | Menjadi sumber kebenaran; `cameras.yaml` hanya seed awal |
| `location_exemption` | karyawan × kamera/kategori, berlaku dari–sampai, alasan, pembuat | Baru |
| `enrollment` | karyawan, `enrollment_version`, jumlah referensi, sumber (foto/CCTV), status | Referensi wajah sendiri tetap di engine |
| `protocol_event` | `(outbox_id, seq)` unik, tipe, person, kamera, waktu, payload | Sudah ada; diberi retensi |
| `visit` | **id stabil**, karyawan, kamera, kategori, mulai, selesai, terbuka/tertutup, detik terhitung, detik ditagih, daftar segmen sumber, `identity_source` per segmen | Baru; menggantikan kunjungan yang dihitung ulang per request |
| `daily_usage` | karyawan × tanggal: detik ditagih, rincian per lokasi, jumlah kunjungan, pertama terlihat, status (aman/peringatan/pelanggaran), detik bersumber ReID | Baru; dibaca dashboard, report, dan rekap harian |
| `violation` | karyawan, tanggal, waktu tercapai, snapshot bukti, status verifikasi, verifikator, penanda **perlu dicek HR** bila sebagian besar waktunya bersumber ReID | Baru |
| `correction` | koreksi HR append-only terhadap `visit_id` stabil atau rentang waktu | Sudah ada; kunci diganti ke id kunjungan stabil |
| `alert_mute` | kamera, jenis alert, mulai, sampai, pembuat, alasan | Baru |
| `notification` | penerima, saluran, isi, status kirim, percobaan | Baru |
| Pengaturan (§10.1) | jam istirahat per hari dengan tanggal berlaku, jadwal operasional engine per hari, jam kirim rekap, daftar penerima rekap (maks. 20) | Baru; nama tabel belum diputuskan |
| Status rekap harian | tanggal, terkirim/belum, waktu kirim | Baru; menjamin rekap tidak ganda dan yang terlewat dikirim (§10.2) |
| `audit_log` | siapa, kapan, aksi, objek, nilai lama/baru | Baru; mencakup koreksi, pengecualian, mute, perubahan kamera/kebijakan/pengaturan, data karyawan, dan pengguna |

## 4. Alur penghitungan jatah

1. Event durabel masuk (`track.started`, `track.identified`, `track.heartbeat`, `track.identity_changed`, `track.ended`, `presence.interval`, `camera.failed`, `snapshot`, serta event baru `identity.resolved`; rincian kontrak di dokumen 07 yang diperbarui jalur Engine A). `track.ended` dengan alasan `schedule_off` berarti analisis dimatikan oleh jadwal, bukan orangnya pergi.
2. `ledger` memperbarui **segmen terbuka** per track teridentifikasi, dan saat `presence.interval` tiba, menutup segmen dengan batas waktu dari engine. Setiap segmen membawa `identity_source` (`face`, `tracking`, `reid`, `reid_retro`).
3. Segmen dipetakan ke `visit` **di lokasi yang sama** bila jaraknya ≤ `visit_merge_gap_seconds`. Perpindahan ke lokasi lain selalu membuat kunjungan baru. ID kunjungan dibuat sekali saat kunjungan lahir dan tidak berubah ketika segmen ditambahkan atau ditutup.
4. Untuk setiap kunjungan dihitung: detik di luar jam istirahat resmi **hari itu** (jam istirahat diatur per hari dari web; perubahan berlaku mulai hari berikutnya), dikurangi toleransi; nol bila kategori lokasi bukan `rekreasi` atau karyawan dikecualikan di lokasi itu.
5. `daily_usage` diperbarui. Karena kamera terpisah tidak tumpang-tindih, waktu di dua lokasi sekaligus berarti salah satu identifikasi keliru: kunjungan yang bertabrakan ditandai **impossible travel** untuk diperiksa HR dan tidak ditagih dua kali.
6. `alerts` mengevaluasi ambang dan memicu peringatan atau pelanggaran; `notify` mengirim sesuai §6 (kotak pesan dashboard; email ke karyawan + CC HR).
7. Saat `identity.resolved` tiba, interval milik ID sementara `ANON-xxxx` dipindahkan ke karyawan yang terkonfirmasi (atribusi mundur, §10.4), lalu langkah 4–6 dievaluasi ulang untuk karyawan tersebut.
8. Pembangunan ulang penuh dari `protocol_event` tetap tersedia sebagai jalur pemulihan (misalnya setelah perubahan kebijakan atau kategori berlaku surut), bukan jalur normal.

Waktu yang dipakai adalah waktu event dari engine (`*_at`, berbasis PTS). Untuk kunjungan yang masih terbuka, "sekarang" diambil dari jam backend yang sudah dikoreksi dengan selisih jam engine yang terukur (lihat P9 dan dokumen 04 §7).

## 5. Enrollment dari web

- HR membuat data karyawan (ID karyawan, nama, divisi, email, status aktif), lalu memilih karyawan lewat **combobox dengan pencarian** (bukan input ID bebas) dan mengambil 3–5 foto lewat kamera browser (mode terpandu dengan umpan balik kualitas) atau unggah file. Akses kamera browser mensyaratkan HTTPS.
- Backend meneruskan permintaan `enroll` ke engine dengan **kunci internal** karyawan; engine menilai kualitas (ukuran wajah ≥112 px, pose frontal, ketajaman, pencahayaan), mendeteksi kemiripan dengan karyawan lain, dan menyimpan referensi. Hasil (`enroll_result`) ditampilkan per foto.
- **Enrollment dari rekaman CCTV:** dari alert orang tak dikenal atau dari daftar kunjungan, HR memilih potongan dan menetapkan "ini karyawan X". Wajah terbaik dari track itu ditambahkan sebagai referensi tambahan bersumber CCTV. Hanya lewat konfirmasi manusia; tidak pernah otomatis.
- Penonaktifan karyawan memicu penghapusan referensi wajah di engine (UU PDP) dan pencatatan di jejak audit.
- Foto asli enrollment: **asumsi** disimpan terenkripsi di mesin engine agar migrasi model tidak memerlukan enrollment ulang, dan dihapus saat karyawan dinonaktifkan.
- Catatan transport: foto dikirim sebagai base64 di kanal kontrol. Cukup untuk fase 1; dipindah ke jalur unggah terpisah bila enrollment massal terasa lambat.

## 6. Peringatan dan notifikasi

- **Peringatan dini** (asumsi: sisa 5 menit) dan **pelanggaran** (melewati 30 menit), masing-masing satu kali per karyawan per hari, dengan deduplikasi.
- Selama pilot, sistem berjalan dalam **mode bayangan**: semua dicatat, notifikasi (dashboard dan email) hanya ke kontak pilot di pihak klien.
- Alert orang tak dikenal per kamera; dapat di-**mute** oleh admin (HR) dengan durasi wajib (maksimum 4–8 jam), aktif kembali otomatis, terlihat di dashboard, dan tercatat di audit. Mute hanya menahan notifikasi; deteksi dan pencatatan tetap berjalan.
- **Saluran (diputuskan): email + notifikasi dashboard sesuai peran.** Siapa menerima apa (diperbarui 8 Oktober 2026, dokumen 12 §3.4):

| Kejadian | Dashboard | Email |
|---|---|---|
| Peringatan dini (sisa 5 menit) | Admin (HR); viewer: hanya miliknya | — (hindari banjir email) |
| Pelanggaran (> 30 menit) | Admin (HR); viewer: hanya miliknya | Karyawan **+ CC HR** (segera); bila karyawan tanpa email → **HR saja**, dengan nama dan ID karyawan di subjek |
| Orang tak dikenal | Admin (HR) | — |
| Status sistem (engine hilang, kamera mati/degraded, jam tidak sinkron) | Admin | Admin |
| Rekap harian | Admin (halaman report) | Daftar penerima HR, terjadwal, lampiran `.xlsx` (§10.2) |

- **Isi email minimal:** nama karyawan, tanggal, total pemakaian, dan tautan ke dashboard. Email per pelanggaran hanya berisi data karyawan yang bersangkutan. Snapshot wajah **tidak** dilampirkan di email; bukti hanya dapat dilihat setelah login. Email bisa diteruskan ke siapa saja, dashboard tidak.
- **Notifikasi dashboard:** kotak notifikasi per pengguna (belum dibaca/sudah dibaca), dikirim real-time lewat SSE yang **disaring per pengguna di backend** (viewer hanya menerima miliknya), dan tetap tersimpan sehingga notifikasi yang muncul saat pengguna tidak membuka dashboard tetap terlihat saat login berikutnya. Opsional: notifikasi browser (Web Notifications API) bila pengguna mengizinkan, yang membutuhkan HTTPS.
- **Batas email:** satu email per pelanggaran per karyawan per hari; satu rekap per hari; alert operasional diringkas (misalnya maksimal satu email per jenis per 15 menit) agar tidak banjir.
- **Konsekuensi:** email lambat dibaca, jadi pelanggaran real-time hanya terlihat cepat bila HR membuka dashboard. Ini dapat diterima karena pelanggaran diverifikasi manusia, bukan ditindak seketika.
- `notify` tetap berupa antarmuka dengan adapter; saluran lain (dokumen 05 §4) dapat ditambah tanpa mengubah logika peringatan.

## 7. Autentikasi dan otorisasi

- Login pengguna dengan sesi/token; password di-hash; opsi SSO bila klien punya. (Sudah ada di kode per 8 Oktober 2026.)
- Peran (diperbarui 8 Oktober 2026, dokumen 12 §3.2):
  - **admin** = HR: akses penuh (monitoring, report, data karyawan, manajemen pengguna, pengaturan, enrollment, koreksi, pengecualian, mute).
  - **viewer** = akun karyawan, terhubung ke satu karyawan: hanya notifikasi pelanggaran **miliknya** dan **pemakaian free time miliknya hari ini**.
  - Peran HR/supervisor terpisah dari admin adalah kandidat fase berikutnya (dokumen 12 §4).
- Manajemen pengguna (akun login) dan data karyawan adalah dua menu terpisah. Akun viewer dibuat dari halaman data karyawan ("Buat akun"): username = ID karyawan, password sementara, wajib diganti saat login pertama.
- **Admin terakhir** tidak boleh dihapus atau dinonaktifkan.
- **Semua endpoint data wajib login**, termasuk GET dan SSE; data per orang disaring di backend sesuai peran (bukan disembunyikan di frontend). `GET /api/settings/email` wajib login karena berisi alamat penerima. Report hanya untuk admin.
- Video live (`/hls/`, `/whep/`) dan stream deteksi hanya untuk admin, diperiksa lewat `auth_request` nginx ke backend.
- Kunci API hanya untuk komunikasi antar-layanan. Nginx **tidak lagi** menyuntikkan kunci ke request browser (P1). Per 8 Oktober 2026 penyuntikan ini masih ada di template nginx dan perlu dihapus.
- Semua aksi yang mengubah data tercatat di `audit_log` dengan identitas pengguna yang login; `corrected_by` tidak lagi diisi bebas oleh klien.

## 8. Penyimpanan

- SQLite (WAL) tetap dipakai untuk fase 1: satu site, 5 kamera, satu proses backend. Evaluasi PostgreSQL bila multi-site atau lebih dari satu instance backend.
- **Migrasi berversi** (Alembic atau skrip bernomor) wajib sebelum instalasi pertama di klien.
- Retensi dijalankan oleh job terjadwal sesuai kebijakan klien (rekomendasi di dokumen 10).
- Persistensi kanal `view` (tabel `detection_frames`, `track_observations`, `track_sessions`) ditinjau: bila riwayat kotak per frame tidak dibutuhkan klien, dihapus untuk mengurangi beban tulis dan data pribadi.
- Backup harian database backend dan referensi wajah di engine; prosedur pemulihan diuji sekali sebelum pilot.
- Pada deployment Portainer (`docker-compose.portainer.yml`), database dan `policy.yaml` berada di volume `/data`, sehingga pengaturan tidak hilang saat redeploy.

## 9. Operasional

- Singleton yang dibuat saat import dipindah ke `lifespan` FastAPI dan disuntikkan sebagai dependency.
- Endpoint kesehatan menyajikan: status koneksi engine, umur pesan terakhir dari engine, selisih jam engine–backend, lag per kamera, kedalaman outbox engine, dead-letter, status notifikasi.
- Watchdog: bila tidak ada pesan dari engine selama read timeout, status engine = hilang, koneksi diputus dan disambung ulang, alert operasional dikirim. Di luar jam operasional (analisis dimatikan jadwal), ketiadaan event kamera bukan alarm, karena proses engine tetap hidup dan hanya analisis kamera yang nonaktif.
- **Status koneksi bertahap (P27):** `engine_link` menyajikan fase `terputus`, `menyambung`, `handshake`, `sinkronisasi`, lalu per kamera `pemanasan` dan `live` (dari `camera.online` dan frame pertama), beserta waktu sejak fase terakhir berubah. Frontend menampilkannya sehingga engine yang sedang pulih tidak terlihat sebagai error.

## 10. Pengaturan, rekap harian, report, dan ReID (kesepakatan 8 Oktober 2026)

Bagian ini merangkum tanggung jawab backend dari dokumen 12 §3. Pemilik jalur: BE (dokumen 12 §7).

### 10.1 Pengaturan dari web (admin)

| Pengaturan | Aturan |
|---|---|
| Batas jatah dan peringatan | Sudah ada |
| Jam istirahat resmi | Per hari (Jumat bisa berbeda). Perubahan berlaku **mulai hari berikutnya** dan dicatat di audit |
| Jadwal operasional engine | Jam analisis aktif/nonaktif per hari. Yang dimatikan adalah **analisis kamera**, bukan proses engine: di luar jam operasional backend mengirim `set_cameras` dengan `enabled: false`; track yang masih hidup ditutup engine dengan alasan `schedule_off` |
| Jadwal email rekap harian | Jam kirim |
| Penerima rekap harian (HR) | Daftar alamat, **maksimal 20**, disimpan di database; `SMTP_TO` dari env menjadi nilai bawaan |

Nilai jam operasional engine dan jam kirim rekap untuk klien **belum diputuskan** (dokumen 12 §9). Akun pengirim SMTP tetap dari env; pengubahan dari web adalah kandidat fase berikutnya.

### 10.2 Email

- **Email per pelanggaran:** ke email karyawan dengan CC daftar HR; bila karyawan tanpa email, ke HR saja dengan nama dan ID karyawan di subjek. Isi hanya data karyawan tersebut.
- **Rekap harian:** ke daftar penerima HR sesuai jadwal, dengan lampiran `.xlsx` rekap semua karyawan hari itu. Sebaiknya dikirim setelah analisis nonaktif agar data hari itu lengkap.
- **Tahan server mati (idempoten + catch-up):** status rekap per tanggal dicatat terkirim/belum; rekap yang terlewat dikirim saat server hidup kembali; rekap untuk tanggal yang sama tidak pernah dikirim ganda.

### 10.3 Report API dan `.xlsx`

- Report hanya untuk admin, per karyawan per hari dengan filter rentang tanggal: total free time terpakai, sisa jatah, jumlah kunjungan, rincian per lokasi, status (aman/peringatan/lewat), dan menit bersumber ReID.
- **Satu pembuat file `.xlsx` di backend** dipakai untuk lampiran rekap harian dan tombol "Export Excel" di halaman report, sehingga angkanya identik. Format `.xlsx`, bukan CSV (Excel berlokal Indonesia salah membaca pemisah CSV). Ekspor PDF tidak disebut dalam kesepakatan prototype (belum diputuskan).

### 10.4 Atribusi mundur ReID

- ReID berjangkar wajah: engine tidak pernah menetapkan identitas dari tubuh saja. Tubuh tanpa wajah diberi ID sementara `ANON-xxxx`; saat wajahnya terkonfirmasi, engine mengirim `identity.resolved`.
- Backend memindahkan **semua interval** milik `ANON-xxxx` ke karyawan tersebut (`identity_source: reid_retro`), menghitung ulang `daily_usage`, dan mengevaluasi ulang peringatan/pelanggaran.
- Pelanggaran yang sebagian besar waktunya bersumber ReID ditandai **"perlu dicek HR"** dan masuk antrean tinjauan HR.
- Bentuk pesan dan aturan penggabungan ditetapkan jalur Engine A di dokumen 07; detail di dokumen 12 §3.6.

## Riwayat perubahan

- Versi 1.1 (8 Oktober 2026): baris versi ditambahkan di bawah judul.
- §1: dicatat bahwa login, peran admin/viewer, dan email SMTP sudah ada di kode; masalah endpoint GET terbuka dan penyuntikan `X-API-Key` oleh nginx dicatat; relasi supervisor ditunda.
- §2: ditambah komponen `settings` dan `scheduler`; `ledger`, `notify`, `reports`, `auth`, `media` disesuaikan (atribusi mundur, dua jenis email, satu generator `.xlsx`, penyaringan per peran, `auth_request` video).
- §3: `employee` memakai kunci internal + ID karyawan yang dapat diedit, divisi, email, status; `supervisor_id` ditunda; `user` hanya admin/viewer dan terhubung ke karyawan; ditambah `identity_source`, penanda "perlu dicek HR", entitas pengaturan dan status rekap harian.
- §4: ditambah event `identity.resolved`, alasan `schedule_off`, jam istirahat per hari, dan langkah atribusi mundur; penerima notifikasi tidak lagi supervisor.
- §5: enrollment memakai combobox dan kunci internal; penonaktifan menghapus referensi wajah (UU PDP).
- §6: tabel penerima notifikasi diganti (email pelanggaran ke karyawan + CC HR, HR saja bila tanpa email; rekap harian ke HR dengan `.xlsx`); supervisor diganti admin (HR); SSE disaring per pengguna.
- §7: peran diganti admin = HR dan viewer = karyawan; aturan pembuatan akun, perlindungan admin terakhir, kewajiban login untuk semua endpoint, video via `auth_request`.
- §8–§9: catatan volume `/data` Portainer dan perilaku watchdog di luar jam operasional.
- §10 baru: pengaturan dari web, aturan email dan rekap idempoten, report API dan `.xlsx`, atribusi mundur ReID.
