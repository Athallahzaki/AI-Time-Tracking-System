# 01 — Arsitektur Sistem

Versi 1.1 · diperbarui 8 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

## 1. Kebutuhan klien

Permintaan asli klien:

> "Buatkan untuk pemantauan ruang hiburan agar karyawan tidak lebih dari 30 menit istirahat di luar jam istirahat, dan kalau bisa track pertama kali masuk."

Tafsiran yang dipakai tim (**diputuskan**, detail angka berupa **asumsi** di konfigurasi):

- Jatah **30 menit per karyawan per hari**, dihitung dari waktu karyawan **terlihat** di lokasi rekreasi, **di luar jam istirahat resmi**.
- Pelanggar diberi **peringatan**, dan pelanggaran **dilaporkan ke HR** (peran admin) lewat kotak pesan dashboard; email pelanggaran dikirim ke karyawan dengan CC HR, atau ke HR saja bila karyawan tidak punya email (dokumen 12 §3.4). Penerima per supervisor/atasan menjadi kandidat fitur berikutnya (dokumen 12 §4). Konsekuensi keuangan atau sanksi berada di luar aplikasi.
- Karyawan diidentifikasi **dari kamera** (pengenalan wajah), tanpa kartu atau perangkat tambahan. Saat wajah tidak terlihat, kesinambungan dijaga tracker dan **ReID berjangkar wajah** (dokumen 12 §3.6); ReID tidak menetapkan identitas sendiri.
- "Pertama kali masuk" dicatat sebagai **pertama kali terlihat** per hari di kamera pintu masuk/lobby. Ini bukan absensi resmi.
- Posisi tim: mitra pengembang software, di bawah perusahaan CCTV yang menjadi penghubung ke klien. Spesifikasi dan konfigurasi server ditentukan tim.

## 2. Prinsip produk

**Alat bantu supervisor, bukan hakim otomatis.** Sistem mencatat, menghitung, dan memberi tanda. Keputusan akhir atas pelanggaran diambil manusia (HR) yang bisa melihat buktinya. Prinsip ini menentukan tingkat akurasi yang cukup: sistem yang menjatuhkan sanksi otomatis butuh akurasi mendekati sempurna, sedangkan sistem yang memberi tanda plus bukti cukup andal selama ia **tidak pernah salah menagih orang lain**.

**Lebih baik "tidak dikenal" daripada salah orang.** Setiap keraguan identitas diarahkan ke status tidak dikenal dan alur koreksi HR, bukan ke tebakan terbaik. Untuk ReID berlaku hal yang sama: ambang ketat, lebih baik terpecah daripada tertukar, dan ReID tidak boleh membatalkan hasil wajah.

**Hanya waktu yang terlihat yang dihitung.** Waktu berjalan antar-lokasi yang tidak tertangkap kamera tidak ditagih. Ini lebih menguntungkan karyawan dan lebih mudah dibela bila dipersoalkan.

**Engine mengamati, backend memutuskan.** Engine tidak mengetahui angka bisnis apa pun (jatah, jam istirahat, kategori lokasi). Semua kebijakan tinggal di backend sebagai konfigurasi. Jadwal operasional analisis juga diputuskan backend dan diteruskan ke engine lewat `set_cameras`.

## 3. Lokasi dan kategori

Lima kamera di lima lokasi berbeda yang tidak saling tumpang-tindih (topologi terpisah). Setiap kamera diberi **kategori lokasi** yang menentukan perlakuannya:

| Kamera | Lokasi | Kategori (asumsi default) | Memotong jatah | Dipakai untuk |
|---|---|---|---|---|
| CAM-1 | Luar gedung | `pintu_masuk` | Tidak | Pertama terlihat |
| CAM-2 | Lobby | `transit` | Tidak | Pertama terlihat, lintasan |
| CAM-3 | Smoking area | `rekreasi` | Ya | Jatah |
| CAM-4 | Ruang hiburan | `rekreasi` | Ya | Jatah |
| CAM-5 | Ruang billiard | `rekreasi` | Ya | Jatah |

Kategori adalah konfigurasi per kamera. Bila klien memutuskan lobby ikut dihitung, cukup satu perubahan konfigurasi.

**Pengecualian per karyawan.** Karyawan yang lokasi kerjanya memang di area tersebut (resepsionis dan satpam di lobby/luar, OB di ruang hiburan) dikecualikan dari penghitungan di lokasi itu. Pengecualian diatur HR dan tercatat di jejak audit.

## 4. Gambaran komponen

```
  5 kamera CCTV (RTSP, H.264/H.265)
        │
        ▼
  ┌──────────────┐  substream H.264 ──► browser (WebRTC/LL-HLS)
  │   MediaMTX   │
  └──────┬───────┘
         │ RTSP (mainstream untuk analisis)
         ▼
  ┌─────────────────────────── Mesin A (GPU) ───────────────────────────┐
  │ ENGINE: ingest → deteksi orang → tracking → wajah → identitas →     │
  │         ReID berjangkar wajah → presence (interval kehadiran) →     │
  │         outbox durabel                                              │
  └──────────────────────────────┬──────────────────────────────────────┘
                                 │ NDJSON/TCP (kanal events, view, control)
  ┌──────────────────────────────▼──────── Mesin B ──────────────────────┐
  │ BACKEND: ingest event → ledger kunjungan → kebijakan jatah →        │
  │          peringatan & notifikasi → laporan → REST/SSE API           │
  │ FRONTEND (nginx): dashboard, enrollment, koreksi, laporan, admin    │
  └──────────────────────────────┬──────────────────────────────────────┘
                                 ▼
        Admin (HR) / viewer (karyawan) — dashboard sesuai peran + email
```

Topologi dua mesin (**diputuskan** sebagai rancangan acuan): engine di mesin A (dengan GPU), backend, frontend, dan MediaMTX di mesin B. Keduanya Ubuntu/Debian headless. Untuk demo jarak jauh dipakai susunan lain (§4.1); apakah susunan demo itu juga dipakai untuk operasi/produksi **belum diputuskan** (lihat catatan risiko laptop di dokumen 12 §6 dan §8).

**Kecepatan analisis.** Target prototype: **≥ 6 fps stabil per kamera** untuk 5 kamera serentak; frontend **menginterpolasi** posisi kotak antar frame analisis (per `track_uuid`, di mode HLS dan WebRTC). 10–12 fps menjadi target lanjutan bila ruang performa tersisa (dokumen 12 §2.1, §3.7).

### 4.1 Topologi demo jarak jauh

Susunan yang dipakai untuk demo (dokumen 12 §6; runbook `docs/DEMO-REMOTE.md` di repo):

```
LAPTOP (Windows, lokasi kamera)            SERVER (Portainer CE)
ffmpeg → MediaMTX → engine                 frontend (nginx) + backend
            ▲          ▲                        │            │
            │          └──── NetBird (8765) ────┼────────────┘  backend → engine
            └─────── NetBird (HLS 8888/WHEP 8889) ◄┘            nginx → MediaMTX laptop

Penonton: browser → Cloudflare → VPS → NetBird → server:80
```

- **Laptop** (i7-13700HX, RTX 4060 Laptop, 16 GB): engine, MediaMTX, dan ffmpeg. Engine mendengarkan hanya di IP NetBird, dibatasi ACL NetBird dan firewall Windows.
- **Server** (i5-3470, 16 GB; Portainer CE): backend dan frontend, dideploy dengan `deploy/docker-compose.portainer.yml`.
- Laptop dan server berjauhan, tersambung lewat **NetBird**. Yang lewat NetBird hanya event/kotak (backend ↔ engine) dan video (nginx server ↔ MediaMTX laptop).
- Video ke browser **default HLS** (tembus Cloudflare); WebRTC opsional lewat TCP 8189 di IP publik VPS.

## 5. Workflow ujung ke ujung

**Persiapan.**

1. Perusahaan CCTV memasang kamera sesuai kebutuhan teknis (lihat dokumen 10) dan mengarahkan jam kamera ke server NTP lokal.
2. Admin mendaftarkan kamera, kategori lokasi, dan zona pintu di dashboard, serta mengatur jam istirahat resmi per hari dan jadwal operasional analisis (dokumen 12 §3.3).
3. Admin (HR) membuat data master karyawan (ID karyawan, nama, divisi, email, status aktif) dan melakukan enrollment wajah dari web dengan memilih karyawan lewat combobox berpencarian: foto terpandu 3–5 sudut, dinilai kualitasnya oleh engine. Akun viewer untuk karyawan dibuat dari halaman data karyawan (dokumen 12 §3.1–3.2).

**Operasi harian.**

4. MediaMTX menarik stream dari setiap kamera. Engine membaca stream analisis; browser membaca substream. Analisis kamera aktif/nonaktif otomatis sesuai jadwal: di luar jam operasional backend mengirim `set_cameras` dengan `enabled: false` (proses engine tetap hidup), dan track yang masih hidup ditutup dengan alasan `schedule_off`.
5. Engine mendeteksi orang, melacaknya (track), dan mencoba mengenali wajah pada momen yang baik (terutama saat masuk pintu). Identitas dipegang tracker selama orang tetap terlihat. Bila track hilang, **ReID berjangkar wajah** menyambungkannya: cache tubuh harian multi-sudut hanya diisi dari track yang identitasnya dikonfirmasi wajah; tubuh tanpa wajah diberi ID sementara (`ANON-xxxx`) dan diselesaikan ke karyawan saat wajahnya terkonfirmasi (**identitas tertunda**). Cache ReID dihapus otomatis di akhir hari.
6. Engine memancarkan event durabel (`track.*`, `presence.interval`, `camera.*`, `engine.health`) bernomor urut ke backend. Event disimpan di outbox engine sampai backend mengonfirmasi (ACK). Untuk ReID ditambahkan `identity.resolved`, alasan `schedule_off`, dan label `identity_source` (`face | tracking | reid | reid_retro`); kontraknya disepakati jalur EA dan dirinci di dokumen 07.
7. Backend menyimpan event, memperbarui **ledger kunjungan**: siapa, di lokasi mana, dari jam berapa sampai jam berapa, dan berapa detik yang ditagih setelah kategori lokasi, jam istirahat resmi, masa toleransi, dan pengecualian diterapkan. Saat menerima `identity.resolved`, backend memindahkan semua interval kelompok `ANON` ke karyawan tersebut (**atribusi mundur**).
8. Saat pemakaian seorang karyawan mencapai ambang peringatan (asumsi: sisa 5 menit), backend memunculkan **peringatan dini** di dashboard. Saat melewati 30 menit, backend menandai **pelanggaran**, memunculkannya di kotak pesan dashboard (admin melihat semua, viewer hanya miliknya) dan mengirim email ke karyawan + CC HR (HR saja bila karyawan tanpa email); snapshot bukti hanya dapat dilihat di dashboard setelah login.
9. Orang yang tidak dikenali dalam waktu tertentu memicu alert "orang tak dikenal" (dapat dimatikan sementara per kamera oleh admin/HR).

**Verifikasi dan laporan.**

10. HR (admin) memverifikasi pelanggaran lewat bukti; pelanggaran yang sebagian besar waktunya bersumber ReID ditandai "perlu dicek HR". Bila salah, HR melakukan koreksi (kecualikan kunjungan atau sesuaikan menit) yang tercatat di jejak audit.
11. Laporan per karyawan per hari dengan filter rentang tanggal: total pemakaian, sisa jatah, jumlah kunjungan, rincian per lokasi, status (aman/peringatan/lewat), menit bersumber ReID, pelanggaran, dan jam pertama terlihat. Export `.xlsx` dari halaman report, dan email rekap harian ke daftar HR dengan lampiran `.xlsx` sesuai jadwal (dokumen 12 §3.4–3.5).

## 6. Aturan jatah (ringkas)

| Parameter | Nilai | Status |
|---|---|---|
| Jatah harian | 30 menit | Diputuskan (permintaan klien) |
| Jam istirahat resmi | Default 12:00–13:00; diatur admin dari web **per hari** (Jumat bisa berbeda), perubahan berlaku mulai hari berikutnya dan dicatat | Mekanisme diputuskan (dokumen 12 §3.3); nilai per hari = asumsi |
| Masa toleransi per kunjungan (`qualification_seconds`) | 20 detik (kunjungan lebih pendek tidak ditagih; 20 detik pertama gratis) | Asumsi |
| Penggabungan jeda dalam satu lokasi (`visit_merge_gap_seconds`) | 30 detik | Asumsi, dikalibrasi saat pilot |
| Jeda antar-lokasi | Tidak diisi otomatis | Diputuskan |
| Peringatan dini | Sisa 5 menit | Asumsi |
| Batas "track basi" bila engine diam | 90 detik | Diputuskan (teknis) |
| Jadwal operasional analisis | Jam aktif/nonaktif per hari, diatur dari web | Mekanisme diputuskan; jam belum ditetapkan (dokumen 12 §9 no. 2) |
| Zona waktu | Asia/Jakarta | Asumsi |

Nilai di `backend/configs/policy.yaml` kini sudah memakai jatah 30 menit, tetapi file itu masih ditandai sebagai nilai sementara dan **wajib** disahkan HR sebelum pilot (masalah P6). Batas jatah dan peringatan dapat diubah admin dari halaman Pengaturan.

## 7. Batasan masalah fase 1

**Termasuk fase 1:**

- 5 kamera, 5 lokasi, satu site, satu zona waktu.
- Analisis ≥ 6 fps stabil per kamera untuk 5 kamera serentak, dengan interpolasi kotak di frontend; stress test 100 orang total di 5 kamera dan 100 karyawan terdaftar (dokumen 12 §2.1–2.2).
- Identifikasi wajah dengan model AuraFace (embedder, file `glintr100.onnx`) dan detektor wajah SCRFD; data master karyawan dan enrollment dari web.
- **ReID harian berjangkar wajah** sebagai penyambung kontinuitas: galeri tubuh multi-sudut per hari, identitas tertunda, atribusi mundur, label sumber identitas (dokumen 12 §3.6).
- Ledger kunjungan dengan kategori lokasi, jam istirahat resmi per hari, masa toleransi, pengecualian per karyawan.
- Jadwal operasional analisis kamera dari web.
- Pertama terlihat per hari.
- Peringatan dua tahap dan notifikasi lewat **email** (per pelanggaran ke karyawan + CC HR, rekap harian ke HR) dan **kotak pesan dashboard** sesuai peran (lapisan notifikasi berupa adapter, sehingga saluran lain dapat ditambah kemudian).
- Halaman report per karyawan per hari, export `.xlsx`.
- Koreksi manual HR dengan jejak audit; mute alert orang tak dikenal per kamera dengan durasi.
- Login, peran **admin (= HR)** dan **viewer (= karyawan, hanya data miliknya)**, manajemen pengguna; semua endpoint data wajib login dan disaring per peran di backend; TLS.
- Dashboard web responsif (dapat dibuka dari ponsel).
- Pilot 2–3 minggu dalam masa maintenance.

**Tidak termasuk fase 1:**

- Aplikasi mobile native; kontrol PTZ/zoom optik kamera (zoom digital di browser diperbolehkan).
- Integrasi payroll/keuangan, sanksi otomatis.
- Absensi resmi masuk/pulang kantor.
- Multi-site, lebih dari ±10 kamera (arsitektur memungkinkan, belum diuji).
- Pengenalan orang murni dari bentuk tubuh/pakaian/gait tanpa wajah sama sekali sebagai sumber identitas (masalah riset, tidak dijanjikan). ReID berjangkar wajah di atas **termasuk**.
- Peran HR/supervisor terpisah dari admin dan penerima email per supervisor (kandidat fitur berikutnya, dokumen 12 §4).
- Dokumentasi pengguna akhir (dibuat setelah produk jadi).

## 8. Keputusan kunci

| Keputusan | Status |
|---|---|
| Model jatah = waktu terlihat di lokasi rekreasi (bukan model "gap = istirahat") | Diputuskan |
| Kebijakan bisnis hanya di backend, sebagai konfigurasi | Diputuskan |
| Detector orang: LibreYOLO D-FINE m (default) / s | Diputuskan |
| Recognizer wajah: SCRFD + AuraFace via onnxruntime, dapat dimatikan lewat config | Diputuskan |
| ReID harian berjangkar wajah (tidak menetapkan identitas sendiri), identitas tertunda, atribusi mundur | Diputuskan (8 Okt 2026, dokumen 12 §3.6) |
| Analisis ≥ 6 fps per kamera + interpolasi kotak di frontend; 10–12 fps target lanjutan | Diputuskan (8 Okt 2026) |
| Dua mesin, Ubuntu/Debian headless | Diputuskan sebagai rancangan acuan; demo memakai laptop Windows + server Portainer CE (§4.1); susunan produksi akhir belum diputuskan |
| Video ke browser pada demo jarak jauh: HLS default, WebRTC opsional | Diputuskan (demo) |
| Kategori lokasi per kamera + pengecualian per karyawan | Diputuskan (nilai default = asumsi) |
| Peran: admin = HR, viewer = karyawan | Diputuskan untuk prototype; "HR sama dengan admin" tercatat sebagai asumsi (dokumen 12 §5) |
| Jadwal analisis kamera aktif/nonaktif dari web (`set_cameras`, `schedule_off`) | Diputuskan; jam operasional terbuka |
| Saluran notifikasi: email (karyawan + CC HR; rekap harian ke HR) + kotak pesan dashboard sesuai peran | Diputuskan (28 Sep 2026, diperbarui 8 Okt 2026) |
| Retensi data | Terbuka — rekomendasi di dokumen 10, keputusan klien. Cache ReID: satu hari, dihapus otomatis (asumsi, dokumen 12 §5) |

## Riwayat perubahan

- Ditambahkan baris versi 1.1 (8 Oktober 2026) dengan rujukan ke dokumen 12 dan 13.
- §1: pelaporan pelanggaran diubah dari supervisor/atasan ke HR (admin) dengan email karyawan + CC HR; ditambah peran ReID berjangkar wajah.
- §2: prinsip "lebih baik tidak dikenal" diperluas untuk ReID; jadwal analisis disebut sebagai keputusan backend.
- §4: ReID ditambahkan ke alur engine, penerima diubah ke admin (HR)/viewer (karyawan), status topologi dua mesin diperjelas, target ≥ 6 fps + interpolasi kotak ditambahkan.
- §4.1 baru: topologi demo jarak jauh (laptop engine + MediaMTX + ffmpeg, server Portainer CE, NetBird, Cloudflare → VPS, HLS default).
- §5: workflow diperbarui untuk data master karyawan, combobox enrollment, akun viewer, jadwal analisis (`schedule_off`), ReID dan identitas tertunda, `identity.resolved` dan atribusi mundur, penerima notifikasi, report dan rekap harian `.xlsx`.
- §6: jam istirahat menjadi pengaturan web per hari; ditambah baris jadwal operasional analisis; catatan `policy.yaml` disesuaikan dengan isi repo (sudah 30 menit, masih menunggu pengesahan HR).
- §7: ReID berjangkar wajah dipindah ke lingkup fase 1; peran, notifikasi, report, dan target performa diperbarui; pengecualian dipersempit ke identifikasi tubuh tanpa wajah dan peran HR/supervisor terpisah.
- §8: ditambah keputusan ReID, target fps, video demo, peran, dan jadwal analisis; status topologi, saluran notifikasi, dan retensi diperbarui.
