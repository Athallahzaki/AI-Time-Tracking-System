# 12 — Kesepakatan Prototype dan Rencana Fase Berikutnya

Versi 1.1 · 9 Oktober 2026 · Internal tim (EA, EB, BE, FE, COM)

Dokumen ini mencatat hasil diskusi 8 Oktober 2026 tentang arah prototype. Isinya
menggantikan bagian dokumen lama yang bertentangan; daftar perbedaannya ada di
dokumen 13 (Daftar Pembaruan). Bila ada keputusan baru, dokumen ini diperbarui,
bukan ditambah dokumen lain.

## 1. Tujuan

Permintaan asli klien: *"pemantauan ruang hiburan agar karyawan tidak lebih dari
30 menit istirahat di luar jam istirahat"*, ditambah *"kalau bisa track pertama
kali masuk"*.

Turunannya untuk sistem: **berapa lama setiap karyawan berada di area rekreasi per
hari, dan siapa yang melewati batas**, dengan bukti yang cukup untuk ditindaklanjuti
HR. Sistem memberi tanda; keputusan sanksi tetap di tangan HR.

Sistem dipahami sebagai satu rantai. Setiap mata rantai punya pemilik (§7):

| # | Mata rantai | Pertanyaan | Komponen |
|---|---|---|---|
| 1 | Deteksi | Ada orang di frame? | D-FINE |
| 2 | Identifikasi | Siapa orang ini? | SCRFD + glintr100 + enrollment |
| 3 | Kontinuitas | Masih orang yang sama saat wajah tidak terlihat? | Tracker + ReID |
| 4 | Lokasi | Dia di area yang memotong jatah? | 5 kamera + kategori lokasi |
| 5 | Penghitungan | Berapa menit hari ini? | Ledger backend |
| 6 | Keputusan | Melewati batas? | Policy + pelanggaran |
| 7 | Tindak lanjut | Siapa diberi tahu, bagaimana diverifikasi? | Kotak pesan, email, report, koreksi HR |

## 2. Definisi prototype selesai

Prototype dinyatakan selesai bila **semua** kriteria berikut lulus dan hasil ujinya
tercatat.

### 2.1 Performa

| Kriteria | Target | Cara uji |
|---|---|---|
| Kamera | 5 kamera serentak | Mesin engine benchmark (§6) |
| Kecepatan analisis | ≥ 6 fps stabil per kamera | `lag_probe` + `summarize_gladi.py`, waktu lambat < 5% |
| Umur kotak | p99 < 1 detik, tanpa stall (> 2 detik) | sama |
| Tampilan kotak | Halus (§3.7) | Pemeriksaan visual dengan kriteria §3.7 |
| Target lanjutan | 10–12 fps per kamera | Hanya bila ruang performa tersisa |

### 2.2 Beban (stress test)

| Kriteria | Target |
|---|---|
| Orang terlihat sekaligus | 100 orang **total di 5 kamera** (±20 per kamera) |
| Karyawan terdaftar | 100 |
| Syarat saat beban penuh | Analisis tetap ≥ 6 fps per kamera; umur kotak < 1 detik; wajah yang terlihat jelas teridentifikasi ≤ 5 detik |

Sumber video uji: dataset kerumunan publik (misalnya MOT20) yang di-publish ke
MediaMTX untuk beban, dan rekaman tim sendiri untuk identifikasi.

### 2.3 Akurasi (usulan, angka ditetapkan tim)

Performa tanpa akurasi tidak cukup: sistem bisa stabil sambil menagih orang yang
salah.

- 0 pelanggaran tertagih ke orang yang salah selama **N** jam uji rekaman.
- Minimal **X%** kunjungan teridentifikasi.
- Threshold rekognisi dikalibrasi dengan wajah karyawan (bukan nilai bawaan ArcFace).

### 2.4 Operasional

- Analisis kamera aktif/nonaktif otomatis sesuai jadwal di pengaturan (§3.3).
- Stabil selama jam operasional, minimal **3 hari berturut-turut**, tanpa intervensi:
  memori tidak terus naik, pulih sendiri saat kamera putus, tidak ada event hilang.

### 2.5 Tingkat status

Kolom status di tabel target memakai tiga tingkat, bukan "tested/cek":

1. **Berfungsi (simulasi)** — jalan dengan video uji atau fake engine.
2. **Teruji data nyata** — jalan dengan CCTV/rekaman lokasi asli.
3. **Terkalibrasi** — ada angka akurasi dan ambang yang ditetapkan dari data klien.

## 3. Fitur dan keputusan

### 3.1 Data master karyawan dan enrollment

- Admin membuat data karyawan dulu: ID karyawan, nama, divisi, email, status aktif.
- Enrollment wajah memilih karyawan lewat **combobox dengan pencarian**, bukan input ID bebas.
- ID karyawan adalah label yang boleh diedit; sistem memakai **kunci internal** yang
  tidak berubah, supaya referensi wajah dan riwayat tidak terputus.
- Karyawan dinonaktifkan → referensi wajahnya dihapus (UU PDP).
- Kolom email dipakai untuk email pelanggaran (§3.4).

### 3.2 Pengguna dan peran

| Peran | Siapa | Akses |
|---|---|---|
| Admin | HR | Semua: monitoring, report, data karyawan, manajemen pengguna, pengaturan |
| Viewer | Karyawan | Hanya notifikasi pelanggaran **miliknya** dan **pemakaian free time miliknya hari ini** |

- Manajemen pengguna (akun login) dan data karyawan adalah **dua menu terpisah**.
- Akun viewer terhubung ke satu karyawan. Dibuat dari halaman data karyawan
  ("Buat akun"): username = ID karyawan, password sementara, wajib diganti saat login pertama.
- Admin terakhir tidak boleh dihapus atau dinonaktifkan.

### 3.3 Pengaturan dari web (admin)

| Pengaturan | Keterangan |
|---|---|
| Batas jatah dan peringatan | Sudah ada |
| Jam istirahat resmi | **Per hari** (Jumat bisa berbeda). Perubahan berlaku **mulai hari berikutnya** dan dicatat |
| Jadwal operasional engine | Jam analisis aktif/nonaktif per hari |
| Jadwal email rekap harian | Jam kirim |
| Penerima rekap harian (HR) | Daftar alamat, maksimal 20; disimpan di database; `SMTP_TO` jadi nilai bawaan |

**Jadwal engine:** yang dimatikan adalah **analisis kamera**, bukan proses engine.
Backend mengirim `set_cameras` dengan `enabled: false` di luar jam operasional. Track
yang masih hidup saat jadwal mati ditutup dengan alasan `schedule_off`, sehingga
tidak dibaca sebagai "semua orang pulang".

### 3.4 Notifikasi dan email

| Jenis | Penerima | Waktu |
|---|---|---|
| Kotak pesan dashboard | Admin: semua; viewer: miliknya | Real-time (SSE) |
| Email per pelanggaran | Karyawan **+ CC HR**; bila karyawan tanpa email → **HR saja** | Saat batas terlewati |
| Email rekap harian | Daftar HR, dengan lampiran `.xlsx` | Sesuai jadwal |

- Email per pelanggaran hanya berisi data karyawan yang bersangkutan.
- Bila dikirim ke HR karena karyawan tanpa email, nama dan ID karyawan ada di subjek.
- Rekap harian sebaiknya dikirim setelah analisis nonaktif (data hari itu lengkap).
- Rekap tahan server mati: tiap hari dicatat terkirim/belum; yang terlewat dikirim
  saat server hidup; tidak pernah ganda.

### 3.5 Report dan Excel

Halaman report (admin), per karyawan per hari:

- total free time terpakai, sisa jatah, jumlah kunjungan;
- rincian per lokasi (ruang hiburan, biliar, smoking area, …);
- status (aman / peringatan / lewat);
- setelah ReID: menit yang sumbernya ReID (bukan wajah);
- filter rentang tanggal.

Dua jenis Excel, **satu pembuat file di backend** (angka dijamin identik):

| Jenis | Isi | Pemicu |
|---|---|---|
| Lampiran email harian | Rekap semua karyawan hari itu | Otomatis |
| Export halaman report | Rentang tanggal dan filter pilihan HR | Tombol "Export Excel" |

Format `.xlsx`, bukan CSV (Excel berlokal Indonesia salah membaca pemisah CSV).

### 3.6 ReID

**Tujuan:** bila track seseorang hilang (membelakangi kamera, tertutup, pindah
ruangan), orangnya tetap bisa dilacak. ReID adalah **referensi untuk memastikan
orangnya lewat cache tubuh yang diambil dari orang yang sudah dikenali wajahnya**.

**Desain:**

1. **Berjangkar wajah.** Cache tubuh hanya diisi dari track yang identitasnya
   dikonfirmasi lewat wajah. ReID tidak pernah menetapkan identitas sendiri dan
   tidak boleh membatalkan hasil wajah.
2. **Galeri harian multi-sudut.** Per orang disimpan beberapa embedding tubuh
   (depan, belakang, samping) yang dikumpulkan sepanjang hari. Dihapus otomatis di akhir hari.
3. **Identitas tertunda.** Tubuh tanpa wajah diberi ID sementara (`ANON-xxxx`);
   track yang penampilannya cocok digabung. Saat wajahnya terkonfirmasi, seluruh
   kelompok diselesaikan ke karyawan itu (`identity.resolved`), dan backend
   memindahkan semua intervalnya (**atribusi mundur**).
4. **Aturan penggabungan.** Dua track yang hidup bersamaan di tempat berbeda tidak
   boleh digabung; waktu tempuh minimum antar 5 lokasi (luar, lobi, smoking area,
   ruang hiburan, biliar) dipakai untuk menolak sambungan mustahil; ambang ketat
   (lebih baik terpecah daripada tertukar).
5. **Perhitungan berbasis kejadian.** Embedding dihitung saat identitas
   dikonfirmasi, sesekali selama orang terlihat (interval diatur di config,
   default 15 detik, bisa dijauhkan bila berat), dan saat track tanpa identitas
   muncul. Bukan tiap frame.
6. **Label sumber.** `identity_source: face | tracking | reid | reid_retro`.
   Pelanggaran yang sebagian besar waktunya dari ReID ditandai "perlu dicek HR".

**Prasyarat:** kurangi ID switch tracker lebih dulu.

**Ukuran keberhasilan:** persentase sambungan ReID yang benar; persentase menit
pemakaian yang sumbernya ReID.

**Di luar lingkup:** pengenalan orang murni dari bentuk tubuh/gait tanpa wajah sama
sekali (masih masalah riset; tidak dijanjikan). Worst case "wajah tidak pernah
terlihat sepanjang hari" ditangani dengan kamera jangkar dan alur "tidak dikenal" ke HR.

**Estimasi:** ±2 minggu dengan 4 jalur paralel, **bergantung pada rekaman
multi-kamera untuk evaluasi**.

Penempatan di kalender: dokumen 14. Sejak 9 Oktober 2026 model ReID dan
worker-nya dipegang EA (bukan EB), dan ReID menerima crop/embedding hanya lewat
antrean internal engine (§3.9).

| Hari | Kegiatan |
|---|---|
| 1–2 | Kontrak protokol disepakati (EA) |
| 3–8 | EA, EB, BE, FE paralel; BE/FE memakai `fake_engine` |
| 9–10 | Integrasi engine asli |
| 11–12 | Evaluasi dengan rekaman |

### 3.7 Tampilan kotak

- Analisis 6 fps; frontend **menginterpolasi** posisi kotak antar frame analisis
  (per `track_uuid`), di mode HLS dan WebRTC.
- Kriteria halus: kotak digambar ulang tiap frame layar (±60 kali/detik), tidak
  melompat, hilang paling lama 0,3 detik setelah orangnya hilang.
- Orang baru muncul/hilang tidak diinterpolasi (wajar).
- Kotak hantu (track LOST) sudah diperbaiki di paket r7.

### 3.8 Keamanan akses

Dashboard kini dapat diakses dari internet, sehingga:

- Semua endpoint data wajib login; data per orang disaring di backend sesuai peran.
- Notifikasi dan SSE disaring per pengguna di backend (bukan disembunyikan di frontend).
- Video live (`/hls/`, `/whep/`) dan stream deteksi hanya untuk admin, lewat
  `auth_request` nginx ke backend.
- `GET /api/settings/email` wajib login (berisi alamat penerima).
- Report hanya untuk admin.

### 3.9 Struktur engine (keputusan 9 Oktober 2026)

Masalah utama engine adalah **kestabilan**, bukan rata-rata fps. Keputusan:

- **Satu proses, satu D-FINE** untuk 5 kamera, dengan satu batch per detak. Batch
  sungguhan belum terbukti mempercepat di 4060; yang diandalkan adalah irama detak.
- **Penjadwal berdetak tetap** memegang ritme (mis. tiap 1/6 detik), menggantikan
  thread per kamera yang berjalan secepat mungkin. Tiap kamera hanya men-decode dan
  menyimpan frame terbaru. Frekuensi detak dipilih di bawah kapasitas terukur supaya
  ada cadangan.
- **Pemrosesan sebanyak mungkin di GPU**: decode (NVDEC), resize, inferensi, crop
  wajah/badan. CPU hanya mengatur lalu lintas, menjalankan tracker, dan logika
  identitas/presence.
- **Urutan:** penjadwal dulu di jalur CPU (stabilitas), NVDEC kemudian (efisiensi)
  setelah spike 15–16 Oktober. Jalur CPU tetap ada sebagai fallback.
- **Antarmuka antrean internal** per-kamera → inti identitas disepakati EA–EB di
  kontrak 13 Oktober, supaya ReID tidak bergantung pada jalur frame.
- Proses per kamera hanya dipertimbangkan bila baseline membuktikan GIL sebagai
  penghambat setelah penjadwal terpasang.

Yang tidak berubah: `identity/`, `presence/`, `api/`, kontrak NDJSON, backend,
frontend. Rincian desain, struktur file, dan risiko: dokumen 04 §14. Kerangka kode:
paket r9 (default mati).

## 4. Kandidat fitur berikutnya

- Penerima per supervisor (butuh relasi karyawan–atasan di data master).
- Peran HR/supervisor terpisah dari admin.
- Akun pengirim SMTP dapat diubah dari web (password terenkripsi).
- Target analisis 10–12 fps.

## 5. Asumsi tercatat

Berlaku sampai klien menetapkan lain; dapat diubah tanpa membongkar desain.

| Topik | Asumsi |
|---|---|
| Email pelanggaran | CC ke HR (transparan bagi karyawan) |
| Karyawan tanpa email | Email pelanggaran ke HR saja |
| Perubahan jam istirahat | Berlaku mulai hari berikutnya |
| Penerima rekap | Satu daftar HR, maksimal 20 alamat |
| HR | Sama dengan admin |
| Akses report | Admin saja |
| Interval ReID | Berbasis kejadian; pembaruan galeri default 15 detik |
| Retensi cache ReID | Satu hari, dihapus otomatis |
| Asumsi dokumen 10 §5 lainnya | Tetap berlaku bila tidak disebut di sini |

## 6. Lingkungan uji dan deployment

| Mesin | Spesifikasi | Peran |
|---|---|---|
| Server benchmark | Intel i5-3470 (gen 3), iGPU, 16 GB DDR3 | Backend + frontend (Portainer CE) |
| Laptop engine | Intel i7-13700HX (8P+8E), RTX 4060 Laptop, 16 GB DDR5 | Engine + MediaMTX + ffmpeg |

Topologi demo jarak jauh (lihat `docs/DEMO-REMOTE.md`):

- Laptop dan server berjauhan, tersambung lewat NetBird.
- Penonton: Cloudflare → VPS → NetBird → server.
- Video default HLS; WebRTC opsional lewat TCP 8189 di IP publik VPS.

Catatan:

- Server cukup untuk BE/FE; pastikan disk SSD. CPU gen 3 tidak lagi menerima
  pembaruan microcode; perlu dipertimbangkan untuk produksi.
- Laptop untuk operasi harian berjam-jam: engine dijalankan sebagai service yang
  hidup ulang otomatis, sleep dimatikan, jam aktif Windows Update diatur, dicolok
  charger. RAM 16 GB untuk 5 kamera + ReID harus diukur.
- Temuan 8 Oktober (4060): run bersih 10 fps tercapai setelah ffmpeg `-r 25`,
  afinitas P-core, dan pengecualian power throttling; perubahan yang krusial
  dipastikan lewat uji A/B (`docs/DEMO-REMOTE.md` §8).

## 7. Pemilik per jalur

| Jalur | Mata rantai | Pekerjaan |
|---|---|---|
| **Engine A** | 2, 3 | Kontrak protokol (`identity.resolved`, `schedule_off`, `identity_source`) dan antarmuka antrean internal engine, kalibrasi threshold rekognisi, ReID (logika, model, worker), presence, **stabilitas operasional** (service, watchdog, uji 3 hari) |
| **Engine B** | 1, 3, 4 | Deteksi, tracker (ID switch), **struktur engine dan performa 5 kamera ≥ 6 fps**: penjadwal berdetak, mailbox frame terbaru, ingest NVDEC, batching (§3.9) |
| **BE** | 5, 6, 7 | Data master karyawan, pengguna dan peran, penyaringan per peran, pengaturan (jam istirahat, jadwal engine, jadwal dan penerima email), email per pelanggaran dan rekap, generator `.xlsx`, report API, atribusi mundur ReID |
| **FE** | 7 | Halaman data karyawan, manajemen pengguna, combobox enrollment, pengaturan, report + export, tampilan viewer, interpolasi kotak, label sumber identitas, antrean tinjauan HR |
| **COM** | — | Akses CCTV/rekaman, persetujuan biometrik karyawan (termasuk penampilan tubuh untuk ReID), pertanyaan klien yang tersisa (§9) |
| **Bersama** | — | Integrasi, stress test, uji operasional 3 hari |

Catatan beban: jalur Engine B paling berat (struktur engine + performa 5 kamera).
Stabilitas operasional dan model ReID sengaja dipindah ke Engine A.

## 8. Risiko dan ketergantungan

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Belum ada akses CCTV/rekaman lokasi | Mata rantai 2–4 dan ReID tidak bisa diuji sungguhan | COM meminta rekaman sekarang; tim merekam skenario sendiri |
| 5 kamera belum pernah diuji | Target §2.1 bisa tidak tercapai | Benchmark 5 kamera paling awal; penjadwal berdetak dan batching (§3.9) |
| NVDEC di Windows belum terbukti | Efisiensi GPU tidak tercapai | Spike 15–16 Okt; stabilitas tidak bergantung pada NVDEC (jalur CPU di bawah penjadwal) |
| Satu proses = satu titik mati | Crash mematikan 5 kamera | Watchdog + service auto-restart; decoder terisolasi per kamera |
| Laptop sebagai mesin operasional | Restart Windows Update, sleep, panas | Service otomatis, pengaturan daya, pemantauan suhu |
| Beban Engine B | Performa atau struktur dikorbankan diam-diam | Model ReID dipindah ke EA; tinjau beban mingguan |
| Persetujuan biometrik | Risiko hukum (UU 27/2022) | COM membawa ke legal klien; data ReID dihapus harian |
| Threshold belum dikalibrasi | Salah tagih dengan 100 karyawan | Kalibrasi sebelum uji akurasi §2.3 |

## 9. Pertanyaan yang masih terbuka

1. Nilai N dan X untuk kriteria akurasi (§2.3).
2. Jam operasional engine per hari dan jam kirim rekap harian.
3. Ketersediaan email karyawan untuk data master.
4. Persetujuan biometrik karyawan dari pihak klien.
5. Pertanyaan dokumen 10 §6 yang belum terjawab (kategori lokasi, karyawan yang
   bekerja di area rekreasi, retensi, kontak pilot, denah).

## 10. Konvensi tim

### 10.1 Pengiriman perubahan

- Kode dikirim sebagai **zip kumulatif** berisi file dengan struktur repo; `.md`
  dipakai untuk diskusi.
- Line ending CRLF, kecuali `.sh` (LF).

### 10.2 Changelog

Semua catatan perubahan masuk **satu file `docs/CHANGELOG.md`**, entri terbaru di
atas. Satu bagian per paket: tanggal dan nama paket, apa yang berubah, alasan, file
yang tersentuh, cara uji. Tidak ada lagi file `PERUBAHAN-*.md` baru di root.

### 10.3 Restrukturisasi repo

Kondisi 8 Oktober: isi kode rapi dan sesuai paket r7, tetapi root berisi 30 file
`.md` (28 catatan perubahan), dokumen status basi, dan dua `.sh` berubah jadi CRLF.

Struktur sasaran:

```text
/
├── README.md                 # pintu masuk + indeks dokumen
├── .gitattributes            # * text=auto ; *.sh text eol=lf
├── .gitignore  .env.example  pytest.ini  requirements-dev.txt
├── backend/  engine/  frontend/  contracts/  bench/  deploy/  scripts/
└── docs/
    ├── CHANGELOG.md          # gabungan semua catatan perubahan, terbaru di atas
    ├── ARCHITECTURE.md  ENGINE_PROTOCOL.md  PROJECT_STRUCTURE.md  WORKPLAN.md
    ├── DEMO-1060.md  DEMO-REMOTE.md  SETUP-GPU.md  UJI-LAG.md
    └── arsip/                # catatan lama yang masih perlu disimpan apa adanya
```

Langkah:

1. Tambahkan `.gitattributes`, lalu `git add --renormalize .` (memperbaiki `.sh` jadi LF).
2. Gabungkan 28 catatan `PERUBAHAN-*`, `PERBAIKAN-*`, `CHANGES*.md` ke
   `docs/CHANGELOG.md` (urut tanggal). File asli dipindah ke `docs/arsip/`
   dengan `git mv`, supaya riwayatnya tetap tersambung.
3. Hapus atau perbarui dokumen basi: `PACKAGE_VERSION.txt` (build 23 September),
   `WORKPLAN_STATUS.md` (status 23 September). Status terkini ada di dokumen ini dan tabel target.
4. Satukan dua versi catatan timer backend (`CHANGES_TIMER_BACKEND.md` di root dan
   `docs/CHANGES_TIMER_BACKEND_2026-09-22.md`, isinya berbeda).
5. README root: tambah indeks dokumen.

Pemindahan dan penghapusan dilakukan lewat skrip `git mv`/`git rm`, karena zip tidak
bisa memindahkan atau menghapus file.

Status 9 Oktober: dikerjakan di **paket r8** (skrip sekali jalan
`restrukturisasi-r8.ps1`/`.sh`). Satu penyimpangan: `.gitattributes` hanya memasang
`*.sh text eol=lf` dan penanda biner, **tanpa `* text=auto`**, karena renormalisasi
semua file teks bisa menghasilkan diff raksasa bila repo menyimpan CRLF. `* text=auto`
menyusul sebagai commit tersendiri bila tim setuju.

### 10.4 Dokumen yang perlu diperbarui menyusul

| Dokumen | Bagian | Alasan |
|---|---|---|
| 10-KETERBATASAN-SPEK-KLIEN | §1 (ReID dikecualikan), §2 (12 fps), §5 (jam istirahat tetap) | Bertentangan dengan dokumen ini |
| 09a-WORKPLAN-DEMO | D6 (penerima global) | Diganti §3.4 |
| 07-PROTOKOL-DAN-API | Event baru | `identity.resolved`, `schedule_off`, `identity_source` baru |
| 02-ARSITEKTUR-BACKEND | Data master, peran, penjadwal, report | Fitur baru §3 |
| 03-ARSITEKTUR-FRONTEND | Halaman baru, interpolasi | Fitur baru §3 |
| ARCHITECTURE.md §5.4 | "Jangan bangun ReID dulu" | ReID kini masuk prototype |
| Tabel target prototype | Kolom status | Tingkat status §2.5 |
| 04-ARSITEKTUR-ENGINE | §5 "proses per kamera" | Diganti §3.9 (sudah diperbarui, dokumen 04 v1.2 §14) |

## Riwayat perubahan

- 9 Oktober 2026 (v1.1): §3.9 baru (struktur engine: satu proses, satu D-FINE,
  penjadwal berdetak, pemrosesan di GPU, antarmuka antrean internal). §3.6 dan §7:
  model ReID dan worker pindah dari EB ke EA. §8: risiko NVDEC dan satu proses.
  §10.3: status paket r8 dan penyimpangan `* text=auto`. §10.4: dokumen 04.
- 8 Oktober 2026 (v1.0): versi pertama.
