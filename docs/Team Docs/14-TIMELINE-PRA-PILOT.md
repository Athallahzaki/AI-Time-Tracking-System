# 14 — Timeline Pra-Pilot (Usulan)

Versi 1.1 · 9 Oktober 2026 · Internal tim · **Usulan, belum disepakati**

Timeline ini menempatkan pekerjaan dokumen 12 (kesepakatan), 09 (workplan), dan 04 §14
(restrukturisasi engine) ke kalender, dari mulai kerja sampai pilot dimulai. Statusnya **usulan**: tanggal
berubah bila tim atau klien memutuskan lain. Bila disepakati, tanggal di sini
menggantikan catatan "penempatan di kalender belum diputuskan" di dokumen 09.

## 1. Asumsi

| Asumsi | Nilai |
|---|---|
| Mulai kerja | Senin, 12 Oktober 2026 |
| Hari kerja | Senin–Jumat |
| Tim | EA, EB, BE, FE, COM (pemilik per dokumen 12 §7) |
| Libur | Belum memperhitungkan libur nasional/cuti bersama; periksa kalender resmi |
| Panjang pengembangan | 6 minggu (12 Oktober – 20 November), lalu 1 minggu instalasi |
| Pilot | Mulai Senin, 30 November 2026 (2–3 minggu, dokumen 09 §5) |
| Video uji sebelum CCTV tersedia | Rekaman di-publish ke MediaMTX (5 stream) |

Catatan jujur: dokumen 12 memperkirakan ReID ±2 minggu **bila empat jalur
dikhususkan untuknya**. Di timeline ini BE dan FE juga mengerjakan data master,
pengaturan, email, dan report, sehingga ReID dibentangkan sekitar 3–4 minggu
(kode 2 minggu, evaluasi menyusul saat rekaman ada).

Versi 1.1 menambahkan restrukturisasi engine (dokumen 12 §3.9, dokumen 04 §14): penjadwal berdetak tetap
dibangun dulu di jalur CPU (minggu 2), ingest GPU/NVDEC menyusul (minggu 3) bila
spike 15–16 Oktober lulus. Supaya EB fokus ke struktur dan performa, **model ReID
pindah dari EB ke EA**.

## 2. Ringkasan per minggu

| Minggu | Tanggal | Fokus | Gerbang di akhir minggu |
|---|---|---|---|
| 0 | 8–9 Okt | Kesepakatan (dok. 12–13), paket r7, uji 4060 | — selesai |
| 1 | 12–16 Okt | Fondasi: restrukturisasi repo, kontrak protokol + antarmuka internal engine, baseline 5 kamera, spike NVDEC, data master | Kontrak disepakati (13 Okt); baseline + vonis NVDEC (16 Okt) |
| 2 | 19–23 Okt | Penjadwal berdetak, keamanan akses, pengaturan, ReID logika + model | Penjadwal stabil + akses aman + ReID terintegrasi (23 Okt) |
| 3 | 26–30 Okt | Ingest GPU / optimasi, email + rekap + report, atribusi mundur | **Fitur lengkap** (30 Okt); batas waktu rekaman CCTV |
| 4 | 2–6 Nov | Lima stream + stress test, kalibrasi, evaluasi ReID | **M4** lima stream (6 Nov) |
| 5 | 9–13 Nov | Uji operasional 3 hari, uji akurasi, perbaikan | Uji operasional + akurasi lulus (13 Nov) |
| 6 | 16–20 Nov | Pembekuan, gerbang siap pilot, persiapan instalasi | **M5** siap pilot (20 Nov) |
| 7 | 23–27 Nov | Instalasi di lokasi + enrollment karyawan | Instalasi + enrollment selesai (27 Nov) |
| — | 30 Nov | **Pilot dimulai** (minggu kalibrasi) | — |

## 3. Rincian per jalur

### Engine A

| Tanggal | Pekerjaan | Rujukan |
|---|---|---|
| 12–13 Okt | Kontrak protokol: `identity.resolved`, ID `ANON-xxxx`, `identity_source` (face/tracking/reid/reid_retro), alasan `schedule_off`; skenario `fake_engine` untuk BE/FE. **Antarmuka antrean internal** per-kamera → inti identitas, disepakati dengan EB | Dok. 12 §3.6; dok. 04 §14.4 |
| 14–19 Okt | Logika ReID: galeri harian multi-sudut, aturan penggabungan (tidak di dua tempat sekaligus, waktu tempuh 5 lokasi), identitas tertunda, hapus cache harian; hanya lewat antrean | ReID hari 3–7 |
| 20–22 Okt | Model ReID ke ONNX, quality gate crop tubuh, worker rekognisi/ReID yang memakai sisa waktu tiap detak (pindah dari EB) | Dok. 12 §3.6; dok. 04 §14.3 |
| 23 Okt | Integrasi ReID dengan penjadwal berdetak (bersama EB, BE) | ReID hari 10 |
| 26–30 Okt | Penutupan track `schedule_off` di struktur baru; engine sebagai service + watchdog + auto-start di Windows | Dok. 12 §3.3, §7; dok. 04 §14.6 |
| 2–6 Nov | Kalibrasi threshold rekognisi dengan wajah karyawan/rekaman; evaluasi ReID | Dok. 12 §2.3; ReID hari 11–12 |
| 9–13 Nov | Pemilik uji operasional 3 hari; perbaikan stabilitas | Dok. 12 §2.4 |

### Engine B

| Tanggal | Pekerjaan | Rujukan |
|---|---|---|
| 12–14 Okt | Uji A/B 4060 (sisa); **baseline 5 kamera** di struktur lama, dengan profil CPU per tahap (decode, konversi, inferensi, tracking) dan `py-spy` | DEMO-REMOTE §8; dok. 12 §2.1 |
| 15–16 Okt | **Spike NVDEC**: satu stream RTSP → NVDEC → tensor GPU di Windows; ukur CPU%, latensi, VRAM; vonis lanjut/tunda | Dok. 04 §14.5 |
| 19–23 Okt | **Penjadwal berdetak**: mailbox frame terbaru, penjadwal detak tetap, 1 batch D-FINE per detak, `camera.py` jadi state per kamera; jalur CPU dulu; gladi 15 menit 5 kamera | Dok. 04 §14.3–14.4 |
| 26–30 Okt | Bila spike lulus: `nvdec_source`, pra-proses dari tensor GPU, crop di GPU. Bila tidak: optimasi jalur CPU. Penyetelan tracker (kurangi ID switch) | Dok. 04 §14.5 |
| 2–6 Nov | **M4**: lima stream serentak + stress test 100 orang (dataset kerumunan) | Dok. 12 §2.2 |
| 9–13 Nov | Optimasi sisa temuan; dukung uji operasional | — |

### Backend

| Tanggal | Pekerjaan | Rujukan |
|---|---|---|
| 12–16 Okt | Data master karyawan (kunci internal, ID dapat diedit, email, status); manajemen pengguna; akun viewer terhubung karyawan; admin terakhir dilindungi | Dok. 12 §3.1–3.2 |
| 19–23 Okt | Pengetatan akses: semua endpoint wajib login, penyaringan per peran (termasuk SSE), video lewat `auth_request` nginx | Dok. 12 §3.8 |
| 19–23 Okt | Pengaturan: jam istirahat per hari, jadwal engine (`set_cameras`), penerima rekap HR, jadwal rekap | Dok. 12 §3.3 |
| 26–30 Okt | Email per pelanggaran (+CC HR, fallback HR); rekap harian terjadwal (tanpa ganda, kirim susulan); generator `.xlsx`; API report | Dok. 12 §3.4–3.5 |
| 26–30 Okt | Atribusi mundur ReID (interval `ANON`) dan tanda "perlu dicek HR" | Dok. 12 §3.6 |
| 2–6 Nov | Uji SMTP asli (akun klien), perbaikan | — |

### Frontend

| Tanggal | Pekerjaan | Rujukan |
|---|---|---|
| 12–16 Okt | Halaman data karyawan + "Buat akun"; manajemen pengguna; combobox enrollment | Dok. 12 §3.1–3.2 |
| 19–23 Okt | Halaman pengaturan baru; tampilan viewer (notifikasi + pemakaian hari ini); **interpolasi kotak** | Dok. 12 §3.2–3.3, §3.7 |
| 26–30 Okt | Halaman report + export Excel; label sumber identitas; antrean tinjauan HR | Dok. 12 §3.5–3.6 |
| 2–6 Nov | Uji kehalusan overlay pada 5 kamera; build Docker frontend terverifikasi | Dok. 12 §3.7 |

### Communicator

| Tanggal | Pekerjaan |
|---|---|
| 12–16 Okt | Minta akses/rekaman CCTV 5 lokasi; akun SMTP klien; daftar email karyawan; jam operasional engine dan jam rekap; persetujuan biometrik (termasuk data penampilan tubuh untuk ReID); usulan angka N/X akurasi |
| 19–30 Okt | Tindak lanjut jawaban klien; jadwal instalasi dan enrollment |
| 16–20 Nov | Konfirmasi jadwal instalasi, kontak pilot, pemeriksa sampel |

### Bersama

| Tanggal | Pekerjaan |
|---|---|
| 12 Okt | Restrukturisasi repo (paket r8): `.gitattributes`, `docs/CHANGELOG.md`, `docs/arsip/`, README berindeks. Kerangka penjadwal (paket r9, default mati) ikut dipasang |
| 9–13 Nov | Uji akurasi (N jam rekaman); **uji operasional 3 hari** (10–12 Nov, jadwal aktif/nonaktif sungguhan) |
| 16–20 Nov | Pembekuan versi; gerbang **M5**; dokumen pengguna; persiapan instalasi |
| 23–27 Nov | Instalasi di lokasi; enrollment karyawan; uji kirim email di jaringan klien |

## 4. Gerbang (milestone)

| Tanggal | Gerbang | Lulus kalau |
|---|---|---|
| 13 Okt | Kontrak protokol | Skema event baru disepakati EA–EB–BE–FE; `fake_engine` punya skenarionya; antarmuka antrean internal engine disepakati EA–EB |
| 16 Okt | Baseline + spike NVDEC | Angka fps/umur kotak 5 kamera dan porsi CPU per tahap tercatat; vonis spike NVDEC tertulis |
| 23 Okt | Penjadwal + akses aman + ReID | Penjadwal berdetak: gladi 15 menit 5 kamera di 4060 tanpa ayunan fps (`summarize_gladi.py` LULUS); tidak ada endpoint data terbuka tanpa login; ReID jalan end-to-end |
| 30 Okt | **Fitur lengkap** | Semua fitur dok. 12 §3 berfungsi (tingkat "berfungsi (simulasi)") |
| 6 Nov | **M4** lima stream | ≥ 6 fps per kamera, p99 < 1 detik, stress test 100 orang lulus |
| 13 Nov | Operasional + akurasi | Uji 3 hari tanpa intervensi; kriteria akurasi N/X terpenuhi |
| 20 Nov | **M5** siap pilot | Semua kriteria dok. 12 §2 lulus; versi dibekukan |
| 27 Nov | Instalasi selesai | Sistem jalan di lokasi; karyawan ter-enroll; email terkirim dari jaringan klien |
| 30 Nov | **Pilot dimulai** | — |

## 5. Ketergantungan dan batas waktu

| Butuh | Paling lambat | Dari | Bila terlambat |
|---|---|---|---|
| Rekaman multi-kamera (atau akses CCTV) | 30 Okt | Klien/perusahaan CCTV via COM | Evaluasi ReID dan kalibrasi mundur; M4/M5 mundur |
| Akun SMTP klien + daftar email karyawan | 23 Okt | Klien via COM | Uji email memakai akun tim; email pelanggaran ke HR |
| Jam operasional engine, jam rekap, angka N/X | 23 Okt | Klien/tim | Pakai asumsi dok. 12 §5 |
| Persetujuan biometrik karyawan | Sebelum 23 Nov (enrollment) | Legal klien | Enrollment tidak boleh dimulai |
| Pustaka NVDEC Python yang jalan di Windows + driver | 16 Okt | Tim (EB) | Ingest GPU ditunda; tetap jalur CPU di bawah penjadwal |
| Mesin engine untuk uji 3 hari | 9 Nov | Tim (laptop 4060) | Uji operasional mundur |

## 6. Jalur kritis dan risiko jadwal

- **Jalur kritis:** baseline + spike (16 Okt) → penjadwal berdetak (23 Okt) →
  ingest GPU / optimasi (30 Okt) → M4 (6 Nov) → uji operasional (13 Nov) → M5
  (20 Nov). Bila baseline menunjukkan celah sangat besar, gerbang M4 bergeser lebih
  dulu dari yang lain.
- **Penjadwal = stabilitas, NVDEC = efisiensi.** Bila spike NVDEC gagal, M4 tetap
  dikejar dengan jalur CPU di bawah penjadwal; yang hilang hanya cadangan kapasitas.
- **Bentrok file.** `runtime/camera.py` disentuh EA (ReID, `schedule_off`) dan EB
  (penjadwal) di minggu 2–3. Perubahan struktur EB masuk dulu (23 Okt), EA
  menyesuaikan sesudahnya; logika ReID di antaranya hanya bicara lewat antrean.
- **Rekaman CCTV** menentukan evaluasi ReID dan kalibrasi akurasi; tanpa itu
  minggu 4 hanya bisa memakai rekaman tim sendiri.
- **Beban EB** (penjadwal + ingest GPU) tetap paling padat di minggu 2–3, walau
  model ReID sudah dipindah ke EA.
- **Cadangan waktu** praktis hanya di minggu 6. Bila satu gerbang mundur lebih dari
  3 hari kerja, pilot ikut mundur; yang dipotong adalah kolom "bisa menyusul"
  dokumen 09 §2, bukan pengujian.

## Riwayat perubahan

- 9 Okt 2026 (1.1): restrukturisasi engine dari dokumen 12 §3.9 dan 04 §14 masuk timeline (spike
  NVDEC, penjadwal berdetak, ingest GPU); model ReID pindah dari EB ke EA; gerbang
  16 dan 23 Okt diperluas.
- 8 Okt 2026: versi pertama (usulan), disusun dari dokumen 09 dan 12.
