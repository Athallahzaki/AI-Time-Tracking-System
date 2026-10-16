# 09 — Workplan

Versi 1.2 · diperbarui 9 Oktober 2026 · lihat dokumen 12 (kesepakatan), 13 (daftar pembaruan), dan 14 (timeline)

## 1. Kerangka waktu

| Tahap | Durasi | Isi |
|---|---|---|
| Pengembangan fase 1 | 6 minggu (rentang 1–1,5 bulan) | Minggu 1–6 di bawah, ditambah lingkup prototype per 8 Oktober 2026 (§3, bagian "Tambahan lingkup prototype") |
| Instalasi & enrollment (pra-pilot) | ±3–5 hari kerja | Pemasangan server, konfigurasi kamera/MediaMTX, enrollment karyawan oleh HR |
| Pilot = masa maintenance | 2–3 minggu | Minggu kalibrasi + minggu pengukuran dengan versi dibekukan |

Tim: **Engine A (EA)** kontrak, identitas, ReID (logika, model, worker), dan stabilitas operasional; **Engine B (EB)** deteksi, tracker, struktur engine (penjadwal berdetak, ingest GPU), dan performa 5 kamera; **Backend (BE)**; **Frontend (FE)**; **Communicator (COM)** penghubung ke perusahaan CCTV/klien. Pembagian rinci per mata rantai ada di dokumen 12 §7.

Jadwal 6 minggu untuk empat pengembang **ketat**, dan lingkup prototype bertambah per 8 Oktober 2026 (ReID, data master, report, dua jenis email). Karena itu pekerjaan dibagi menjadi *wajib sebelum pilot* dan *bisa menyusul*; bila waktu kurang, yang dipotong adalah kolom kedua, bukan pengujian. Penempatan pekerjaan ke kalender diusulkan di **dokumen 14** (12 Oktober – pilot 30 November); sampai disepakati, dokumen 14 berstatus usulan.

Pilot baru dimulai setelah **prototype dinyatakan selesai** menurut kriteria terukur dokumen 12 §2 (performa, beban, akurasi, operasional), dengan status fitur memakai tiga tingkat: berfungsi (simulasi) → teruji data nyata → terkalibrasi (dokumen 12 §2.5).

## 2. Wajib sebelum pilot vs bisa menyusul

| Wajib sebelum pilot | Bisa menyusul (masa maintenance atau sesudahnya) |
|---|---|
| Auth + peran (admin = HR, viewer = akun karyawan), TLS, perbaikan P1–P4 | Enrollment dari rekaman CCTV (`enroll_from_track`) |
| Pengerasan akses: semua endpoint data wajib login dan disaring per peran di backend, SSE per pengguna, video live (`/hls/`, `/whep/`) hanya admin lewat `auth_request` nginx (dokumen 12 §3.8) | Restrukturisasi folder backend/frontend penuh |
| Transport engine yang diperkeras (P2, P3, P12) | Refactor `CameraFeedCard`/TypeScript penuh (P26) |
| Ledger kunjungan + kategori lokasi + pengecualian (P5, P21, P13) | Deteksi frame beku & perubahan adegan (E4, E5) |
| Data master karyawan (ID, nama, divisi, email, status aktif) + manajemen pengguna sebagai menu terpisah; enrollment web terpandu dengan combobox pencarian karyawan (P22, dokumen 12 §3.1–3.2) | Jadwal mute berulang, notifikasi browser, saluran tambahan |
| Pengaturan dari web: jam istirahat per hari, jadwal operasional engine, jadwal dan penerima email rekap harian (dokumen 12 §3.3) | Penerima per supervisor (relasi karyawan–atasan), peran HR/supervisor terpisah dari admin, akun SMTP dapat diubah dari web (dokumen 12 §4) |
| Peringatan dua tahap, kotak pesan dashboard per peran, email per pelanggaran (karyawan + CC HR; HR saja bila karyawan tanpa email), email rekap harian terjadwal dengan lampiran `.xlsx` (dokumen 12 §3.4) | Fine-tuning detector |
| Halaman report admin + export `.xlsx` dari satu generator di backend (dokumen 12 §3.5) | PWA / aplikasi mobile |
| Recognizer terpasang, keputusan SCRFD (P20), kalibrasi threshold rekognisi dengan wajah karyawan | Opsi `useAbsoluteTimestamp` MediaMTX |
| ReID harian berjangkar wajah: galeri multi-sudut, identitas tertunda, atribusi mundur, label sumber identitas (dokumen 12 §3.6) | Target analisis 10–12 fps per kamera (dokumen 12 §2.1) |
| Mainstream ke engine (P19), frame terbaru + fps adaptif (P17), rekognisi asinkron (P7), ByteTrack benar (P8), pengurangan ID switch tracker | Identifikasi murni dari bentuk tubuh/gait tanpa wajah (**tidak dijanjikan**, dokumen 12 §3.6) |
| Performa 5 kamera ≥ 6 fps per kamera (penjadwal berdetak + batch D-FINE, NVDEC setelah spike; dokumen 12 §3.9) + interpolasi kotak di frontend | |
| NTP, pengukuran selisih jam (P9), overlay toleransi (P16) | |
| Kebijakan produksi (P6), migrasi berversi, backup | |
| Uji operasional 3 hari berturut-turut tanpa intervensi (dokumen 12 §2.4) | |
| Restrukturisasi root repo: `docs/CHANGELOG.md`, `docs/arsip/`, `.gitattributes`, README berindeks (dokumen 12 §10.3) | |

## 3. Rencana per minggu

### Minggu 1 — Fondasi & keputusan

| Jalur | Pekerjaan |
|---|---|
| EA | Cek hash SCRFD dan putuskan (P20); rancang perubahan protokol fase 1 (autentikasi handshake, `forget_person`, `enroll_from_track`, field health baru) dan bekukan di skema |
| EB | Benchmark 5 stream sintetis: MediaMTX + ffmpeg loop ke 5 path, di laptop RTX 4060 (mesin benchmark dokumen 12 §6); ukur decode, detector (PyTorch vs ONNX/TensorRT), rekognisi. Angka ini dasar keputusan hardware |
| BE | Model data baru (employee, user, camera, visit, daily_usage, violation, exemption, alert_mute, audit), migrasi berversi, kebijakan produksi terpisah (P6) |
| FE | Kerangka router + halaman login, layout peran, pemindahan awal ke `features/` |
| COM | Kirim ke perusahaan CCTV: kebutuhan penempatan/resolusi/NTP/dua stream (dokumen 10); tanyakan ke klien: jumlah karyawan, jam istirahat, akun SMTP pengirim email, ketersediaan email karyawan untuk data master, kontak pilot |

### Minggu 2 — Keamanan & koneksi

| Jalur | Pekerjaan |
|---|---|
| EA | Handshake terautentikasi, timeout kirim, pemutusan koneksi lama sebelum kunci, ACK bertumpuk di sisi engine (P2, P3, P12) |
| EB | Pembaca PyAV per kamera + slot frame terbaru; metrik lag; mainstream path (P17, P19) |
| BE | Auth + peran, penghapusan injeksi kunci di nginx (P1), klien engine dengan keepalive/read timeout/ACK bertumpuk, watchdog |
| FE | Halaman karyawan & enrollment terpandu (kamera browser di HTTPS; karyawan dipilih lewat combobox pencarian) |
| OPS | TLS + HTTP/2 di nginx; MediaMTX dengan auth dan dua path per kamera (P4, P11) |

### Minggu 3 — Inti produk

| Jalur | Pekerjaan |
|---|---|
| EA | Recognizer dengan model nyata di pipeline; `forget_person`; enkripsi referensi (P14) |
| EB | Worker rekognisi asinkron + batching; input SCRFD 160–320 (P7) |
| BE | Ledger kunjungan inkremental dengan id stabil, kategori lokasi, pengecualian, impossible travel, `daily_usage`, pertama terlihat (P5, P13, P21) |
| FE | Halaman jatah hari ini + rincian per lokasi; halaman pengecualian |

### Minggu 4 — Peringatan, laporan, performa

| Jalur | Pekerjaan |
|---|---|
| EA | Gerbang kualitas runtime (pose/blur/ukuran); persiapan skrip kalibrasi threshold |
| EB | ONNX/TensorRT FP16 + batching lintas kamera; NVDEC; fps adaptif; ByteTrack dengan deteksi skor rendah + ukur (P8) |
| BE | Alerts (peringatan dini, pelanggaran, tak dikenal, mute), `notify` + adapter dashboard (kotak notifikasi + SSE) dan email (SMTP): email per pelanggaran dan rekap harian terjadwal dengan lampiran `.xlsx`; report API + export `.xlsx`; snapshot bukti |
| FE | Halaman pelanggaran (verifikasi), orang tak dikenal + mute, halaman report + tombol "Export Excel" |

### Minggu 5 — Integrasi & ketahanan

| Jalur | Pekerjaan |
|---|---|
| EA/EB | Koreksi drift jam + field health; `camera.degraded` untuk lag; supervisor proses + watchdog engine (P28); uji soak 5 stream 24 jam termasuk kill/hang engine |
| BE | Pengukuran selisih jam (P9); status koneksi bertahap (P27); retensi; backup & uji pemulihan; kesehatan sistem |
| FE | SSE multipleks, toleransi overlay (P16), sinkron WebRTC berbasis frame + fallback HLS (P10, P15), zoom digital, admin kamera/kebijakan |
| Semua | Skenario fixture baru (multi-lokasi, transit, pengecualian, impossible travel, lag); uji restart/putus jaringan (E1, E2, E3, E11, E12) |

### Minggu 6 — Pembekuan & persiapan instalasi

| Jalur | Pekerjaan |
|---|---|
| Semua | Perbaikan bug, pembekuan fitur, rilis kandidat dengan hash model tercatat |
| OPS | Image kontainer engine (nvidia/cuda Ubuntu) dan compose mesin B; verifikasi di distro target; chrony; VPN maintenance |
| BE/FE | Mode bayangan untuk pilot; akun kontak pilot |
| COM | Jadwal instalasi, jadwal enrollment HR, penunjukan pemeriksa sampel di pihak klien |

### Tambahan lingkup prototype (kesepakatan 8 Oktober 2026)

Pekerjaan berikut berasal dari dokumen 12 dan belum tercantum di rencana minggu 1–6. Pemilik mengikuti dokumen 12 §7. Penempatannya di kalender diusulkan di dokumen 14.

| Pekerjaan | Pemilik | Rujukan |
|---|---|---|
| Data master karyawan (ID sebagai label yang boleh diedit, kunci internal tetap; nonaktif → referensi wajah dihapus) | BE (data, API), FE (halaman data karyawan, combobox enrollment) | Dok. 12 §3.1 |
| Manajemen pengguna: akun viewer dibuat dari data karyawan ("Buat akun", username = ID karyawan, password sementara wajib diganti); admin terakhir tidak boleh dihapus/dinonaktifkan | BE, FE | Dok. 12 §3.2 |
| Tampilan viewer: hanya notifikasi miliknya dan pemakaian free time miliknya hari ini | FE (tampilan), BE (penyaringan) | Dok. 12 §3.2 |
| Pengaturan dari web: batas jatah, jam istirahat per hari (berlaku mulai hari berikutnya, dicatat), jadwal operasional engine, jam kirim rekap, penerima rekap HR (maks. 20, `SMTP_TO` jadi bawaan) | BE, FE | Dok. 12 §3.3 |
| Jadwal engine: backend mengirim `set_cameras` `enabled: false` di luar jam operasional; track ditutup dengan alasan `schedule_off` | BE (penjadwal), EA (kontrak protokol) | Dok. 12 §3.3 |
| Email per pelanggaran (karyawan + CC HR; HR saja bila tanpa email, nama dan ID di subjek) dan rekap harian (lampiran `.xlsx`, tahan server mati, tidak pernah ganda) | BE | Dok. 12 §3.4 |
| Report per karyawan per hari + export `.xlsx`; satu generator untuk lampiran email dan export | BE (report API, generator), FE (halaman report + export) | Dok. 12 §3.5 |
| Pengerasan akses (endpoint, SSE, video live, `GET /api/settings/email`, report admin saja) | BE; nginx `auth_request` | Dok. 12 §3.8 |
| Interpolasi posisi kotak per `track_uuid` di mode HLS dan WebRTC, sesuai kriteria halus | FE | Dok. 12 §3.7 |
| Performa 5 kamera ≥ 6 fps stabil per kamera (penjadwal berdetak, batch D-FINE, NVDEC setelah spike; dokumen 04 §14); stress test 100 orang total di 5 kamera dan 100 karyawan terdaftar | EB; stress test bersama | Dok. 12 §2.1–2.2 |
| Kalibrasi threshold rekognisi dengan wajah karyawan | EA | Dok. 12 §2.3, §7 |
| Stabilitas operasional (service, watchdog) dan uji operasional 3 hari berturut-turut | EA; uji bersama | Dok. 12 §2.4, §7 |
| Restrukturisasi repo dan satu `docs/CHANGELOG.md` (lewat skrip `git mv`/`git rm`) | Belum ditetapkan di dokumen 12 | Dok. 12 §10.2–10.3 |
| Persetujuan biometrik (termasuk penampilan tubuh untuk ReID), akses CCTV/rekaman, pertanyaan klien tersisa | COM | Dok. 12 §7, §9 |

**ReID (±2 minggu, 4 jalur paralel).** Estimasi ini **bergantung pada tersedianya rekaman multi-kamera** untuk evaluasi; tanpa rekaman, hari 11–12 tidak bisa diselesaikan. Prasyarat: ID switch tracker dikurangi lebih dulu (EB).

| Hari | Kegiatan | Pemilik |
|---|---|---|
| 1–2 | Kontrak protokol disepakati (`identity.resolved`, `schedule_off`, `identity_source`) | EA |
| 3–8 | Paralel: EA logika ReID (galeri, aturan penggabungan, identitas tertunda), model ReID dan worker-nya; EB penjadwal berdetak; BE atribusi mundur; FE label sumber identitas dan antrean tinjauan HR. BE/FE memakai `fake_engine` | EA, EB, BE, FE |
| 9–10 | Integrasi engine asli | Bersama |
| 11–12 | Evaluasi dengan rekaman (persentase sambungan ReID benar, persentase menit bersumber ReID) | Bersama |

## 4. Instalasi & enrollment (pra-pilot)

1. Pasang mesin A dan B (UPS, jaringan gigabit, NTP), deploy kontainer, konfigurasi MediaMTX dengan kamera nyata. Catatan: demo saat ini memakai topologi jarak jauh (engine di laptop, backend + frontend di server Portainer CE, lewat NetBird; lihat `docs/DEMO-REMOTE.md`); topologi produksi akhir **belum diputuskan**.
2. Verifikasi setiap kamera: sudut, resolusi wajah di pintu, jam NTP, dua stream.
3. Atur kategori lokasi, zona pintu, pengecualian awal, jam istirahat per hari, dan jadwal operasional engine.
4. HR membuat data karyawan (termasuk email bila tersedia) dan akun viewer bila dipakai, lalu melakukan enrollment seluruh karyawan **sebelum** pilot dimulai.
5. Smoke test ujung ke ujung: satu orang uji berjalan melewati lima lokasi; periksa kunjungan, pemakaian, overlay, email pelanggaran, dan rekap harian.

## 5. Pilot (2–3 minggu, dalam masa maintenance)

| Periode | Aturan | Kegiatan |
|---|---|---|
| Minggu pilot 1: kalibrasi | Boleh mengubah apa saja | Kumpulkan dataset evaluasi, kalibrasi threshold/margin, sesuaikan zona dan `visit_merge_gap_seconds`, perbaiki bug, tambah referensi yang kurang |
| Minggu pilot 2–3: pengukuran | Versi software, model, dan konfigurasi **dibekukan** (kecuali bug kritis, dicatat tanggalnya) | Ukur akurasi; laporan harian dalam mode bayangan |

**Mode bayangan:** semua dicatat dan laporan dibuat; peringatan hanya dikirim ke kontak pilot di pihak klien.

**Pembanding (ground truth):** sistem menyimpan snapshot per kunjungan; pemeriksa dari pihak klien menilai sampel acak (asumsi: 50 kunjungan per minggu) sebagai benar/salah orang dan benar/salah durasi.

**Kriteria lulus pilot (usulan, disepakati dengan klien lewat COM):**

| Metrik | Target |
|---|---|
| Salah tagih ke orang lain (false accept) pada sampel | 0 kasus, atau ≤ 1% dengan semua kasus terkoreksi lewat verifikasi |
| Kunjungan rekreasi yang teridentifikasi | ≥ 85% (sisanya "tidak dikenal", bukan salah orang) |
| Selisih durasi terhadap pembanding | ≤ 1 menit per karyawan per hari |
| Ketersediaan sistem selama pengukuran | ≥ 99% (di luar gangguan listrik/jaringan klien) |
| Lag analisis p95 | ≤ 2 detik per kamera |

Catatan: kriteria prototype di dokumen 12 §2 lebih ketat untuk kotak (umur kotak p99 < 1 detik, tanpa stall > 2 detik) dan harus lulus sebelum pilot. Angka akurasi prototype (**N** jam uji, **X%** kunjungan teridentifikasi) **belum diputuskan** (dokumen 12 §9). Untuk pelanggaran yang sebagian besar waktunya bersumber ReID, sampel pemeriksa sebaiknya mencakup kasus bertanda "perlu dicek HR".

**Setelah pilot:** keputusan go-live bersama klien; email pelanggaran diaktifkan ke karyawan + CC HR (HR saja bila karyawan tanpa email) dan rekap harian ke daftar HR (dokumen 12 §3.4); penerima per supervisor masih kandidat fitur (dokumen 12 §4). Tanggung jawab dukungan setelah masa maintenance mengikuti kesepakatan kontrak (perlu dituliskan, lihat dokumen 10).

## 6. Milestone

| M | Nama | Lulus kalau |
|---|---|---|
| M1 | Rangkaian palsu (sudah) | Fake engine → backend → frontend jalan |
| M2 | Kebijakan benar (diperbarui) | Skenario multi-lokasi, transit, pengecualian hijau |
| M3 | Engine asli masuk | Skenario yang sama hijau dengan engine asli + recognizer |
| M4 | Lima stream hidup | 5 kamera serentak ≥ 6 fps stabil per kamera (waktu lambat < 5%), umur kotak p99 < 1 detik tanpa stall > 2 detik, overlay halus dengan interpolasi (dokumen 12 §2.1) |
| M5 | Siap pilot | Prototype selesai menurut dokumen 12 §2 (performa, beban, akurasi, uji operasional 3 hari) dan hasil ujinya tercatat; auth + peran, pengerasan akses, notifikasi (kotak pesan, email per pelanggaran, rekap harian), report + `.xlsx`, data master + enrollment web, ReID, instalasi terverifikasi di distro target |
| M6 | Lulus pilot | Kriteria §5 terpenuhi |

## 7. Risiko jadwal

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Benchmark 5 stream menunjukkan RTX 4060 tidak cukup | Keputusan hardware mundur | Benchmark 5 kamera paling awal; target minimum sudah diturunkan ke ≥ 6 fps + interpolasi kotak; penjadwal berdetak + batching, NVDEC; opsi D-FINE s |
| Kamera dipasang sebelum kebutuhan teknis disampaikan | Akurasi rendah, sulit diperbaiki | COM mengirim kebutuhan di minggu 1 |
| Akun SMTP klien terlambat tersedia atau email masuk spam | Email pelanggaran/rekap tidak sampai | Minta akun SMTP di minggu 1; uji kirim saat instalasi; dashboard tetap berfungsi tanpa email; rekap yang terlewat dikirim saat server hidup |
| Email karyawan tidak tersedia di data master | Email pelanggaran hanya ke HR | Fallback HR saja sudah ditetapkan (dokumen 12 §3.4); COM menanyakan ketersediaan email |
| Enrollment HR belum selesai saat pilot | Minggu kalibrasi habis untuk enrollment | Jadwal enrollment di tahap pra-pilot |
| Keputusan SCRFD berubah setelah kalibrasi | Kalibrasi ulang | Putuskan di minggu 1 |
| Belum ada akses CCTV/rekaman multi-kamera | ReID tidak bisa dievaluasi; estimasi ±2 minggu mundur | COM meminta rekaman sekarang; tim merekam skenario sendiri (dokumen 12 §8) |
| Beban jalur Engine B (performa 5 kamera + inference ReID) | ReID dikorbankan diam-diam | Pembagian dokumen 12 §7; tinjau beban mingguan |
| Laptop dipakai sebagai mesin operasional | Restart Windows Update, sleep, panas menggagalkan uji 3 hari | Engine sebagai service yang hidup ulang otomatis, sleep mati, jam aktif Windows Update diatur, dicolok charger (dokumen 12 §6) |
| Masalah khusus distro target | Instalasi mundur | Kontainer + verifikasi di minggu 6 |

## Riwayat perubahan

- 9 Oktober 2026 (v1.2): pembagian EA/EB diperbarui (model ReID ke EA; struktur engine ke EB); performa 5 kamera merujuk penjadwal berdetak (dokumen 12 §3.9) alih-alih proses per kamera; penempatan kalender merujuk dokumen 14.
- Menambahkan baris versi 1.1 (8 Oktober 2026) dengan rujukan ke dokumen 12 dan 13.
- §1: memperbarui pembagian peran EA/EB sesuai dokumen 12 §7, menambahkan syarat "prototype selesai" (dokumen 12 §2) sebelum pilot, dan mencatat bahwa penempatan pekerjaan tambahan di kalender belum diputuskan.
- §2: memindahkan ReID berjangkar wajah ke "wajib sebelum pilot"; menambah pengerasan akses, pengaturan dari web, dua jenis email, report + `.xlsx`, performa ≥ 6 fps + interpolasi, uji operasional 3 hari, dan restrukturisasi repo; relasi supervisor dipindah ke kandidat fitur.
- §3: menyesuaikan butir minggu 1, 2, dan 4 (pertanyaan COM soal email karyawan, combobox enrollment, email per pelanggaran + rekap, report + export).
- §3, bagian baru "Tambahan lingkup prototype": daftar pekerjaan tambahan per pemilik dan rencana ReID 12 hari beserta ketergantungannya pada rekaman multi-kamera.
- §4: menambahkan catatan topologi demo jarak jauh, pengaturan jam istirahat/jadwal engine, data karyawan + akun viewer, dan pemeriksaan email di smoke test.
- §5: menambahkan catatan kriteria prototype dan N/X yang belum diputuskan; penerima email setelah pilot diganti dari "semua supervisor" menjadi karyawan + CC HR dan rekap HR.
- §6: memperbarui syarat M4 (≥ 6 fps, umur kotak p99 < 1 detik) dan M5 (kriteria dokumen 12 §2 serta fitur baru).
- §7: memperbarui mitigasi fps; menambahkan risiko email karyawan, rekaman multi-kamera untuk ReID, beban Engine B, dan laptop operasional.
