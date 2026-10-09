# 06 — Permasalahan Sistem & Rekomendasi Solusi

Versi 1.2 · diperbarui 9 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Daftar ini menggabungkan audit 23 Sep 2026, analisis 24 Sep 2026, dan diskusi arah produk. Masalah yang sudah diperbaiki di build `2026.09.23-audit-fixes` dicantumkan ringkas di §1; sisanya adalah pekerjaan fase 1. Pembaruan 8 Oktober 2026 menandai status butir yang berubah (**Status 8 Okt**) tanpa menghapus isi lama, dan menambah butir baru dari risiko dokumen 12 §8.

Kolom **Kapan**: **Pra-pilot** = wajib selesai sebelum pilot; **Pilot** = dikerjakan di minggu kalibrasi pilot; **Lanjut** = setelah fase 1; **Prototype** = syarat definisi prototype selesai (dokumen 12 §2).

## 1. Sudah diperbaiki (terverifikasi di kode)

Outbox engine durabel dengan `outbox_id` dan `high_water` (K1); pengiriman event berbasis kursor, deteksi lubang `seq` dan replay (K2); model jatah tunggal "hadir di lokasi" (K3); ledger dari event durabel (K4); query interval per tanggal (T1); interval tumpang-tindih tidak lagi error (T2); `door_region` dikirim (T3); penutupan klien tanpa deadlock (T4); dead-letter (T5); satu kunci tulis di engine (T6); retry kamera (T7); YAML rusak menggagalkan start (T8); override kamera persisten (T9); SQLite WAL + writer terpisah + retensi deteksi (T10); alur enrollment selesai (T11); `track_uuid` tidak didaur ulang (N1); tes backend masuk repo (N2).

Catatan: klaim "384 tes lulus" belum diverifikasi ulang di luar lingkungan build; jalankan `python -m pytest -q` dan `npm run build` di CI.

**Tambahan per 8 Oktober 2026 (paket sampai r7):**

- **Kotak ganda/hantu di overlay** ("2–3 kotak per orang"): track LOST ikut digambar dengan posisi beku sampai 1 detik. Diperbaiki di r7: overlay hanya menggambar track aktif + LOST ≤ 0,3 detik.
- **Fps tidak stabil di laptop 4060** (berganti 10 ↔ 6, stall sampai 9 detik): run bersih 10,00 fps, 0 drop, umur kotak p99 0,09 detik tercapai setelah ffmpeg `-r 25`, afinitas P-core, dan pengecualian power throttling. Dugaan turbo CPU **gugur** (turbo hidup justru lebih buruk). Perubahan mana yang krusial masih dipastikan lewat uji A/B (`docs/DEMO-REMOTE.md` §8); sampai itu selesai ketiganya dipertahankan.
- **Ringkasan gladi otomatis:** `scripts/summarize_gladi.py` menghasilkan tabel dan vonis LULUS/GAGAL dari CSV `lag_probe`.
- **Login pengguna** dengan token sesi dan peran `admin`/`viewer` sudah ada; endpoint pengubah data dijaga `require_admin`. Lihat status P1.
- **Deployment Portainer:** `docker-compose.portainer.yml` (`env_file: stack.env`, `policy.yaml` di volume) sehingga pengaturan tidak hilang saat redeploy.

## 2. Masalah terbuka

| ID | Tingkat | Area | Masalah | Rekomendasi | Kapan |
|---|---|---|---|---|---|
| P1 | Kritis | OPS/BE | Nginx menyuntikkan `X-API-Key` ke semua request `/api/` dari browser mana pun; tidak ada autentikasi pengguna | Login + peran; nginx berhenti menyuntik kunci; kunci API hanya antar-layanan. **Status 8 Okt: sebagian.** Login dan peran sudah ada; penyuntikan `X-API-Key` di template nginx masih ada; endpoint GET masih terbuka (lihat P29) | Pra-pilot |
| P2 | Kritis | EA/BE | Tanpa timeout/keepalive: koneksi setengah mati menahan kunci tulis engine sehingga backend baru tidak bisa handshake (terbukti lewat repro); backend tidak mendeteksi engine yang mati tanpa FIN | TCP keepalive dua sisi; timeout kirim di engine; tutup koneksi lama sebelum mengambil kunci di handshake; read timeout backend ±90 detik | Pra-pilot |
| P3 | Tinggi | EA/OPS | Socket engine tanpa autentikasi dan plaintext; host lain di LAN dapat membaca event, mengirim `set_cameras` dengan URI bebas, dan menendang backend (ACK dari klien liar memangkas outbox) | Challenge HMAC di `hello`, jaringan privat/TLS, allow-list URI di engine, bind ke antarmuka spesifik. **Status 8 Okt: mitigasi demo.** Engine bind ke IP NetBird + ACL NetBird + firewall Windows; `ENGINE_SHARED_KEY` belum didukung backend, sehingga handshake masih tanpa autentikasi | Pra-pilot |
| P4 | Tinggi | OPS | MediaMTX tanpa autentikasi: siapa pun dapat membaca stream dan mem-publish video palsu ke path `publisher` | `source: rtsp://` dari kamera, akun baca engine, otorisasi browser lewat backend, CORS dibatasi. **Status 8 Okt: diputuskan** bahwa `/hls/` dan `/whep/` hanya untuk admin lewat `auth_request` nginx (dokumen 12 §3.8); belum diterapkan | Pra-pilot |
| P5 | Tinggi | BE | `visit_id` berubah saat kunjungan tertutup (`visit_tr_…` → `visit_iv_…`); koreksi HR hilang diam-diam (terbukti lewat repro: 0 dtk → 880 dtk) | Ledger kunjungan tersimpan dengan id stabil (dokumen 02 §4) | Pra-pilot |
| P6 | Tinggi | PO/BE | `policy.yaml` berisi nilai development (jatah 2 menit) tanpa pengaman | `policy.dev.yaml` terpisah; backend menolak start produksi dengan nilai yang belum disahkan. **Status 8 Okt:** jam istirahat akan diatur dari web per hari (berlaku mulai hari berikutnya), bukan lagi tetap di `policy.yaml` (dokumen 12 §3.3) | Pra-pilot |
| P7 | Tinggi | EB/EA | Rekognisi sinkron di loop frame dengan kunci global lintas kamera; SCRFD memproses crop kecil di kanvas 640 | Worker asinkron + batching; input SCRFD 160–320 | Pra-pilot |
| P8 | Sedang | EB | Profil runtime memakai tracker IoU; ByteTrack tidak menerima deteksi skor rendah karena model dipanggil `conf=0.5` | Panggil model sekali pada 0,1; filter 0,5 hanya untuk detector; ukur lalu jadikan default. **Status 8 Okt:** pengurangan ID switch tracker menjadi prasyarat ReID (dokumen 12 §3.6) | Pra-pilot |
| P9 | Sedang | BE/EA | Selisih jam mesin A–B memengaruhi kunjungan terbuka (dilewati atau basi) | NTP tunggal; ukur selisih dari `hello_ack`/`engine.health`; alarm > 2 detik | Pra-pilot |
| P10 | Sedang | FE | Overlay WebRTC memakai `Date.now() - 0.8`; `playoutDelayHint` diabaikan Safari/Firefox | Sinkron berbasis frame; LL-HLS + PDT untuk ponsel. **Status 8 Okt:** demo jarak jauh memakai HLS sebagai default; frontend akan menginterpolasi posisi kotak per `track_uuid` di mode HLS dan WebRTC (dokumen 12 §3.7) | Pra-pilot |
| P11 | Sedang | FE/OPS | HTTP/1.1 dan satu SSE per kamera → batas 6 koneksi per origin | TLS + HTTP/2; satu SSE multipleks | Pra-pilot |
| P12 | Sedang | BE/EA | ACK per event (DELETE + commit per event); balasan kontrol ditulis dari thread baca → potensi saling tunggu | ACK bertumpuk (tiap N event/200 ms); balasan kontrol lewat antrian penulis tunggal | Pra-pilot |
| P13 | Sedang | BE | Ledger dihitung ulang per request (2 query per karyawan); `protocol_events` tanpa retensi | `daily_usage` termaterialisasi; retensi event | Pra-pilot |
| P14 | Sedang | EA/PO | Referensi wajah tidak terenkripsi; tidak ada penghapusan saat karyawan keluar | Enkripsi at-rest; penghapusan terpropagasi ke engine. **Status 8 Okt:** diputuskan bahwa penonaktifan karyawan menghapus referensi wajah (UU PDP, dokumen 12 §3.1); cache tubuh ReID dihapus otomatis tiap akhir hari | Pra-pilot |
| P15 | Rendah | FE | STUN Google di-hardcode; tidak ada TURN; tidak ada fallback WHEP → HLS | Konfigurasi ICE dari backend; fallback otomatis. **Status 8 Okt:** demo memakai HLS default; WebRTC opsional lewat TCP 8189 di IP publik VPS sebagai pengganti TURN; fallback otomatis masih belum ada | Pra-pilot |
| P16 | Sedang | FE | Overlay live memilih frame deteksi terdekat tanpa batas toleransi → kotak basi digambar di video baru | Toleransi ±1 detik; penanda "analisis tertinggal" | Pra-pilot |
| P17 | Tinggi | EB | Ingest PyAV sinkron tanpa membuang frame → latensi menumpuk tanpa batas saat engine lambat | Thread pembaca + slot frame terbaru + fps adaptif + metrik lag (dokumen 04 §6) | Pra-pilot |
| P18 | Sedang | EB | Offset jam ditetapkan sekali per epoch → drift osilator kamera dan bias awal tidak pernah dikoreksi | Ukur drift, koreksi perlahan, NTP kamera, timestamp absolut (dokumen 04 §7) | Pra-pilot / Pilot |
| P19 | Tinggi | OPS/EB | Engine membaca substream (resolusi rendah) → wajah terlalu kecil untuk dikenali | Dua path per kamera: mainstream ke engine, substream H.264 ke browser | Pra-pilot |
| P20 | Sedang | EA/PO | Asal bobot SCRFD di repositori AuraFace belum dipastikan (kemungkinan bobot insightface non-komersial) | Cek hash; terima risiko tercatat atau ganti ke YuNet sebelum kalibrasi | Pra-pilot |
| P21 | Kritis | BE | Tidak ada kategori lokasi: semua kamera memotong jatah (lobby dan luar ikut terhitung) | Kategori per kamera + pengecualian per karyawan | Pra-pilot |
| P22 | Tinggi | BE/FE | Tidak ada data master karyawan dan relasi supervisor → laporan ke supervisor tidak punya tujuan | Entitas `employee` dengan `supervisor_id`. **Status 8 Okt: diubah.** Data master berisi kunci internal, ID karyawan (dapat diedit), nama, divisi, email, status aktif; laporan dan email ditujukan ke HR dan karyawan, bukan supervisor. Relasi supervisor menjadi kandidat fase berikutnya (dokumen 12 §3.1, §4) | Pra-pilot |
| P23 | Sedang | BE | Konfigurasi kamera di dua tempat (YAML + tabel override); migrasi skema ad-hoc | Database sebagai sumber kebenaran, YAML sebagai seed; migrasi berversi | Pra-pilot |
| P24 | Rendah | BE/FE | Sisa model "gap = istirahat" di UI, skema, dan nama (`gap_id`, `BreakPolicy`) | Hapus/ganti nama sebelum ada pengguna | Pra-pilot |
| P25 | Rendah | BE/EA | Foto enrollment dikirim base64 di kanal kontrol yang sama dengan event | Cukup untuk fase 1; pindah ke jalur unggah terpisah bila lambat | Lanjut |
| P27 | Sedang | BE/FE/EA | Status koneksi hanya terhubung/tidak; saat engine restart (import, muat model, buka RTSP, warmup detector) dashboard tampak mati padahal sedang pulih | Status bertahap dari backend: `terputus` → `menyambung` → `handshake` → `sinkronisasi` → `pemanasan kamera` → `live`, per kamera; ditampilkan di dashboard | Pra-pilot |
| P28 | Sedang | OPS/EA | Engine yang hang (proses hidup tapi macet) tidak pernah dipulihkan otomatis | systemd `WatchdogSec` / healthcheck kontainer yang me-restart engine bila heartbeat internal atau `engine.health` berhenti. **Status 8 Okt:** stabilitas operasional (service, watchdog, uji 3 hari) dipegang jalur Engine A (dokumen 12 §7); di laptop Windows engine dijalankan sebagai service yang hidup ulang otomatis | Pra-pilot |
| P26 | Rendah | FE | `CameraFeedCard.vue` dan `useDetectionStream.ts` terlalu besar; JS/TS campur | Pecah ke composable, pindah ke TypeScript | Pilot / Lanjut |
| P29 | Kritis | BE/OPS | Banyak endpoint GET terbuka tanpa login (pelanggaran, notifikasi, statistik, kamera, stream deteksi, `GET /api/settings/email` berisi alamat penerima); SSE notifikasi dikirim ke siapa pun; `/hls/` dan `/whep/` terbuka bagi yang tahu URL. Dashboard kini dapat diakses dari internet | Direncanakan (dokumen 12 §3.8): semua endpoint data wajib login; data per orang dan SSE disaring per peran di backend; video live dan stream deteksi hanya admin lewat `auth_request` nginx; report hanya admin | Prototype |
| P30 | Tinggi | EB | 5 kamera serentak belum pernah diuji; arsitektur sekarang satu proses Python untuk semua kamera | Benchmark 5 kamera paling awal. **Status 9 Okt:** tetap satu proses + satu D-FINE; ritme dipegang penjadwal berdetak tetap, pemrosesan sebanyak mungkin di GPU (NVDEC setelah spike); proses per kamera opsi terakhir (dokumen 12 §3.9, dokumen 04 §14). Target ≥ 6 fps per kamera, umur kotak p99 < 1 detik (dokumen 12 §2.1) | Prototype |
| P31 | Tinggi | COM | Belum ada akses CCTV/rekaman lokasi → identifikasi, kontinuitas, lokasi, dan ReID tidak bisa diuji sungguhan | COM meminta rekaman multi-kamera sekarang; tim merekam skenario sendiri | Prototype |
| P32 | Tinggi | EA | Threshold rekognisi belum dikalibrasi (masih nilai bawaan) → risiko salah tagih dengan 100 karyawan | Kalibrasi dengan wajah karyawan sebelum uji akurasi; angka N dan X kriteria akurasi belum diputuskan (dokumen 12 §2.3, §9) | Prototype |
| P33 | Tinggi | OPS/EA | Laptop sebagai mesin operasional: restart Windows Update, sleep, panas | Service otomatis, pengaturan daya, jam aktif Windows Update, pemantauan suhu; RAM 16 GB untuk 5 kamera + ReID perlu diukur | Prototype |
| P34 | Tinggi | COM/PO | Persetujuan biometrik karyawan (termasuk penampilan tubuh untuk ReID) belum ada → risiko hukum (UU 27/2022) | COM membawa ke legal klien; data ReID dihapus harian | Prototype |
| P35 | Sedang | OPS | Server benchmark i5-3470 (gen 3) tidak lagi menerima pembaruan microcode | Cukup untuk demo BE/FE dengan disk SSD; dipertimbangkan ulang untuk produksi | Lanjut |

## 3. Edge case kegagalan

| # | Skenario | Apa yang terjadi tanpa perbaikan | Solusi |
|---|---|---|---|
| E1 | Mesin engine mati listrik (tanpa FIN) | Backend menunggu selamanya; dashboard tampak terhubung; tidak ada alarm | Read timeout + watchdog `engine.health`; alert operasional; UPS |
| E2 | Kabel jaringan A–B dicabut lalu dipasang lagi | Event aman di outbox, tetapi backend baru bisa terkunci sampai timeout TCP | Perbaikan P2 |
| E3 | Laptop pengembang menyambung ke engine produksi | Backend produksi ditendang; ACK dari laptop memangkas outbox; event hilang dari produksi | Autentikasi handshake (P3). Catatan 8 Okt: engine hanya melayani satu koneksi; `lag_probe` atau engine kedua selama demo akan merebut koneksi backend |
| E4 | Kamera/NVR mengirim gambar beku (stream hidup) | Orang di gambar beku terus "hadir" dan jatahnya terpotong | Deteksi frame beku (beda/hash frame selama N detik) → `camera.degraded`, penagihan dihentikan |
| E5 | Kamera digeser atau diputar | `door_region` salah; kunjungan terpecah | Deteksi perubahan adegan terhadap frame referensi → alert + tahan penagihan |
| E6 | Mode malam IR (grayscale) | Lebih banyak tidak dikenal atau salah kenal | Threshold per mode; referensi IR; pencahayaan cukup |
| E7 | Masker, topi, helm, membelakangi kamera | Tidak teridentifikasi → tidak ditagih | Identifikasi prioritas di pintu; alert tak dikenal; penetapan manual HR. Catatan 8 Okt: ReID berjangkar wajah (identitas tertunda `ANON-xxxx` + atribusi mundur) masuk prototype; pengenalan murni dari tubuh tanpa wajah sama sekali tidak dijanjikan (dokumen 12 §3.6) |
| E8 | Dua karyawan mirip (kembar, saudara) | Gagal uji margin → tidak dikenal; bila threshold dilonggarkan → salah tagih | Jangan longgarkan margin; tandai pasangan mirip saat enrollment; referensi tambahan |
| E9 | Jam mesin A dan B berbeda | Kunjungan terbuka tidak dihitung atau basi terlalu cepat | NTP + pengukuran selisih + alarm (P9) |
| E10 | Disk mesin engine penuh | Outbox gagal menulis; event hilang atau kamera berhenti | Pemantauan disk, alarm, mode degradasi yang dilaporkan di `engine.health` |
| E11 | Backend mati berhari-hari, outbox melewati 200.000 event | Event tertua dipangkas → `replay_gap` → data hilang | Pantau `outbox_depth`; alert sebelum mendekati batas |
| E12 | Engine restart di tengah kunjungan | Track lama tertutup lewat `snapshot`/basi 90 detik; status "sedang hadir" bisa keliru sesaat | Engine mengirim `snapshot` segera setelah start; backend menutup track run sebelumnya |
| E13 | Karyawan keluar, data wajah tetap tersimpan | Pelanggaran prinsip retensi data pribadi | Penonaktifan memicu penghapusan referensi di engine |
| E14 | Ponsel supervisor di jaringan seluler (CGNAT) | WebRTC gagal tanpa TURN | Fallback LL-HLS lewat VPN, atau TURN. Catatan 8 Okt: demo memakai HLS default lewat Cloudflare; WebRTC lewat TCP 8189 VPS diblokir jaringan yang hanya membuka 80/443 |
| E15 | Engine lebih lambat dari real-time | Latensi menumpuk; peringatan terlambat | Frame terbaru + fps adaptif + `camera.degraded` (P17) |
| E16 | Ruangan penuh, oklusi berat | ID switch, identitas terlepas, kunjungan terpecah | ByteTrack yang benar, kalibrasi `visit_merge_gap_seconds`, uji skenario di bench. Catatan 8 Okt: stress test 100 orang total di 5 kamera (dokumen 12 §2.2) |
| E17 | Karyawan yang bekerja di lokasi itu (resepsionis, satpam, OB) | Jatah habis di pagi hari | Pengecualian per karyawan × lokasi |
| E18 | Orang yang sama "terlihat" di dua lokasi pada waktu yang sama | Ditagih dua kali atau salah orang | Tandai *impossible travel*, jangan tagih ganda, arahkan ke verifikasi HR |
| E19 | Tamu atau vendor rutin memakai billiard/smoking area | Banjir alert orang tak dikenal | Mute alert per kamera dengan durasi (deteksi tetap berjalan) |
| E20 | Kamera tidak bersinkron NTP | Overlay meleset, "pertama terlihat" bergeser, drift bertambah per hari | NTP kamera oleh perusahaan CCTV; koreksi drift di engine (P18) |
| E21 | Stream kamera H.265 dikirim ke browser | Video tidak tampil di sebagian browser | Substream H.264 untuk browser (dokumen 05) |
| E23 | Engine hang (proses hidup, tidak mengirim apa pun) | Socket tetap terbuka; backend menunggu selamanya; tidak ada reconnect | Read timeout backend (P2) + restart otomatis engine oleh supervisor proses (P28) |
| E24 | Engine restart normal | Backend menyambung ulang tiap 2 detik, tetapi engine baru membuka port setelah muat model dan kamera baru hidup setelah warmup; dashboard tampak mati belasan–puluhan detik | Status koneksi bertahap (P27); buka port engine sebelum memuat model berat bila memungkinkan |
| E22 | Perubahan kebijakan (jam istirahat, kategori) di tengah bulan | Laporan lama dan baru tidak konsisten | Kebijakan berversi dengan tanggal berlaku; pembangunan ulang ledger hanya bila diminta, tercatat di audit. Catatan 8 Okt: perubahan jam istirahat dari web berlaku mulai hari berikutnya dan dicatat |
| E25 | Analisis dimatikan jadwal saat masih ada orang di ruangan | Track yang tertutup bisa terbaca sebagai "semua orang pulang" | Track ditutup dengan alasan `schedule_off` dan diperlakukan berbeda dari kepergian (dokumen 12 §3.3) |
| E26 | ReID menggabungkan dua orang berbeda | Menit orang lain ditagihkan ke karyawan yang salah | Ambang ketat (lebih baik terpecah daripada tertukar); tolak sambungan mustahil (track hidup bersamaan di tempat berbeda, waktu tempuh minimum antar lokasi); pelanggaran yang sebagian besar bersumber ReID ditandai "perlu dicek HR" (dokumen 12 §3.6) |
| E27 | Server mati saat jadwal rekap harian | Rekap hari itu tidak terkirim, atau terkirim ganda setelah server hidup | Status rekap per tanggal; yang terlewat dikirim saat server hidup; tidak pernah ganda (dokumen 12 §3.4) |
| E28 | Video uji atau sumber kamera 30 fps di laptop 4060 | Fps analisis berganti 10 ↔ 6, stall beberapa detik | ffmpeg `-r 25`; afinitas P-core; power throttling dimatikan; uji A/B menentukan yang wajib (`docs/DEMO-REMOTE.md` §8) |

## 4. Urutan pengerjaan

1. **Keamanan dan keandalan koneksi:** P1, P29, P3, P4, P2, P12.
2. **Kebenaran angka yang dilihat HR:** P21, P22, P5, P13, P6, P9, P23, P24, P32.
3. **Engine untuk 5 kamera nyata:** P30, P19, P17, P7, P8, P18, P20, inferensi TensorRT/batching.
4. **Frontend:** P16, P11, P10, P15.
5. **Operasional:** E1, E4, E5, E10, E11, P27, P28, P33 (watchdog, status koneksi bertahap, restart otomatis engine, frame beku, perubahan adegan, disk, outbox, laptop sebagai mesin operasional).
6. **Prasyarat di luar kode (COM):** P31, P34.

Rincian per minggu ada di dokumen 09. Pembagian per jalur (Engine A, Engine B, BE, FE, COM) dan definisi prototype selesai ada di dokumen 12 §2 dan §7.

## Riwayat perubahan

- Versi 1.2 (9 Oktober 2026): P30 diperbarui sesuai keputusan struktur engine (penjadwal berdetak, GPU, dokumen 12 §3.9).
- Versi 1.1 (8 Oktober 2026): baris versi ditambahkan; pengantar menjelaskan penanda **Status 8 Okt** dan nilai baru kolom Kapan (**Prototype**).
- §1: ditambah butir yang selesai sampai r7 (kotak hantu, fps 4060 dengan uji A/B tertunda, `summarize_gladi.py`, login + peran, compose Portainer).
- §2: status ditandai pada P1 (sebagian), P3 (mitigasi NetBird), P4 (diputuskan), P6, P8, P10, P14, P15, P22 (diubah: tanpa supervisor), P28.
- §2: ditambah P29 (endpoint GET/SSE/video terbuka) dan P30–P35 dari risiko dokumen 12 §8 dan §6.
- §3: catatan 8 Okt pada E3, E7, E14, E16, E22; ditambah E25–E28 (`schedule_off`, salah gabung ReID, rekap saat server mati, sumber 30 fps).
- §4: urutan pengerjaan memasukkan butir baru dan langkah 6 untuk prasyarat COM.
