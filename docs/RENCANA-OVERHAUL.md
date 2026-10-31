# Rencana Overhaul Engine (bedah, bukan tulis ulang)

Disusun 31 Okt–1 Nov 2026 dari pembacaan kode commit `c990bc4` (yang berjalan di pilot
RTX 5090) dan satu benchmark sintetis. **Belum ada butir yang direproduksi dengan kamera
sungguhan**; setiap butir wajib diukur sebelum dan sesudah di laptop RTX 4060.

Aturan kerja:

- Pilot tetap di `c990bc4`. Semua butir dikerjakan di branch terpisah, diuji di 4060,
  baru dikirim ke pilot. Angka latensi dari 4060 **tidak** dipindah ke 5090 begitu saja.
- Satu butir = satu paket = satu entri CHANGELOG, dengan angka sebelum/sesudah.
- Butir bertanda **[data]** menunggu data lapangan (§3) sebelum dikerjakan.

---

## 1. Ringkasan prioritas

| # | Butir | Jenis | Alasan urutan |
|---|---|---|---|
| P1 | Keamanan login dashboard | backend + config | Dashboard pilot terbuka ke internet; data biometrik di belakangnya |
| P2 | Kegagalan sistem dihitung sebagai kegagalan wajah | kode kecil | Menyebabkan kunjungan singkat **hilang dari laporan** |
| P3 | Tidak ada NMS untuk D-FINE + ambang tracker | kode kecil + config | Kotak ganda → track ganda → ANON ganda |
| P4 | Race di `MatrixMatcher` | kode kecil | Bisa menempelkan nama karyawan yang salah, diam-diam |
| P5 | Kotak tertinggal ±2 dtk di dashboard | frontend + **[data]** | Masalah sinkronisasi, bukan GPU |
| P6 | ReID membuat ANON baru terus | config + kode | Butuh kalibrasi dan tabel waktu tempuh |
| P7 | Outbox menulis sinkron di thread kamera | kode | Naik ke atas **bila disk server HDD** **[data]** |
| P8 | Klaim identitas lintas kamera + makna `identity_confidence` | redesain | Satu-satunya butir struktural |
| P9 | D-FINE ke ONNX | kode + model | Terakhir: mengubah angka latensi semua butir lain |
| P10 | Kebersihan | kecil | Lihat §2.10 |

---

## 2. Rincian butir

### P1. Keamanan login

- **Gejala:** dashboard dipublikasikan lewat Traefik VPS; `/api/auth/login` tanpa rate
  limit; username karyawan = `employee_id` (mudah ditebak); password minimal 8 karakter.
- **Akar:** `backend/routers/auth.py` (login, cookie `secure` dari `AUTH_COOKIE_SECURE`,
  default `false`). Sudah tercatat di SERAH-TERIMA sejak paket sebelumnya, belum dikerjakan.
- **Perbaikan:** (1) `AUTH_COOKIE_SECURE=true` di `deploy/.env` pilot (tanpa ubah kode);
  (2) rate limit per IP + per username di login; (3) sementara keduanya belum ada, batasi
  akses dashboard di Traefik (allowlist IP / autentikasi tambahan).
- **Yang sudah sehat (jangan diulang):** PBKDF2-SHA256 310.000 iterasi, `compare_digest`,
  tanpa password admin default, cookie `httponly` + `samesite=lax`, video lewat
  `auth_request` ke `/api/auth/video-authorize`.
- **Ukur:** 20 login gagal beruntun dari satu IP → ditolak; cookie di browser bertanda Secure.

### P2. Kegagalan sistem dihitung sebagai kegagalan wajah

- **Gejala:** identifikasi >15 dtk, sampai 84 dtk (catatan ea-r15).
- **Akar:** `identity/admission.py` menaikkan `attempts` saat `pop()`, sebelum ada pekerjaan.
  `presence/binding.py` melapor `produced_evidence=False` untuk empat kasus; hanya satu yang
  sungguh kegagalan wajah:
  1. recognizer jalan, wajah tidak ada → **gagal sah**;
  2. antrean worker penuh (`recognitions_rejected`) → bukan salah wajah;
  3. job basi >0,5 dtk dikembalikan `None` oleh `pipeline/recognition_worker.py` → tercatat
     `recognitions_empty`, bukan salah wajah;
  4. track/frame sudah tidak ada saat giliran → bukan salah wajah.
  Lima "gagal" → backoff 5 dtk. Waktu dikenali ≈ saat wajah layak, dibulatkan ke slot 5 dtk
  berikutnya, + ±2 dtk untuk 3 bukti (`identity/evidence.py`).
- **Dampak data:** `presence/assembler.py` tidak memancarkan interval untuk track yang tak
  pernah dikenali (hanya `unidentified_closed`). Kunjungan yang lebih pendek dari waktu
  identifikasi **tidak ada di laporan**.
- **Perbaikan:** kasus 2–4 melepas giliran tanpa menaikkan `attempts` (pembeda di
  `_complete`, mis. `produced_evidence=None` = "tidak dicoba"). Lalu untuk profil 5090
  longgarkan `admission.backoff_interval_seconds` / `attempts_before_backoff` lewat config.
  Syarat konfirmasi (3 bukti, sebaran 0,5 dtk) **tidak** diubah.
- **Ukur:** median dan p95 `identify_delays` + `unidentified_closed` per jam, sebelum/sesudah,
  di rekaman yang sama.

### P3. Kotak ganda pada satu orang

- **Akar 1:** `detector.iou_threshold` dikirim ke LibreYOLO tetapi paket LibreYOLO 1.6.0
  (`site-packages/libreyolo/postprocess/dfine.py`) tidak menjalankan NMS sama sekali (sigmoid → top-K → potong conf). Konfigurasi mati.
- **Akar 2:** ByteTrack memakan hasil mentah (conf ±0,1) dan membuka track baru di atas
  `tracker.track_threshold` 0,45, **di bawah** `detector.confidence_threshold` 0,50.
- **Efek berantai:** duplikat hidup bersamaan → cannot-link ReID → ANON kedua → kehadiran ganda.
- **Perbaikan:** NMS (`torchvision.ops.batched_nms`) pada hasil mentah sebelum dibagi ke
  detektor dan ByteTrack, ambang ±0,7. Bila duplikat berupa kotak setengah badan di dalam kotak
  penuh **[data]**, tambah cek containment (irisan / luas kotak kecil). Putuskan dengan sadar
  apakah `track_threshold` < `confidence_threshold`.
- **Ukur:** jumlah track per orang di rekaman berlabel; jumlah ANON per jam.

### P4. Race di `MatrixMatcher`

- **Akar:** satu matcher dibagi semua kamera; `match()` (thread kamera, tanpa kunci) membaca
  `_matrix`, `_owner_index`, `_people`; `rebuild()` menggantinya satu per satu. `_emit_lock`
  yang dipegang saat rebuild tidak melindungi pembaca mana pun.
- **Risiko:** baca matriks baru + indeks lama. Paling ringan exception; paling buruk (panjang
  kebetulan sama) **nama karyawan tertukar dengan skor tinggi**.
- **Perbaikan:** rebuild ke variabel lokal, ganti sekaligus sebagai satu tuple; `match()` dan
  `_best_other` (enrollment) membaca tuple itu sekali. ±6 baris di `identity/matcher.py`.
- **Tes:** `match()` konsisten selama `rebuild()` dipanggil berulang dari thread lain.

### P5. Kotak tertinggal ±2 dtk (video tepat waktu)

- **Akar (dugaan kuat):** HLS `lowLatencyMode` menampilkan frame lebih segar daripada kotak yang
  sudah tiba. `resolveDetectionsAt` (`frontend/src/composables/useDetectionStream.ts`) lalu jatuh
  ke `camera.detections` (deteksi terakhir, **tanpa batas umur**). Jalur WebRTC justru benar:
  `WEBRTC_PLAYOUT_DELAY = 5.0` sengaja menahan video agar kotak sempat tiba.
- **Tersangka lain [data]:** (a) selisih jam mesin MediaMTX vs server pilot (cap PDT HLS vs cap
  engine); (b) korektor offset P18 "kebablasan" (catatan ea-r15, `runtime/clock.py`).
- **Perbaikan:** `liveSyncDuration` di `new Hls(...)` sedikit di atas latensi engine; batasi umur
  fallback deteksi terakhir. Diuji di 4060, angkanya disetel dari log pilot.
- **Ukur:** selisih posisi kotak vs orang di rekaman layar; `lag_seconds` dan
  `clock_drift_seconds` dari health engine.

### P6. ReID: keluar frame → ANON baru

- **Akar:** (1) `travel_time_seconds: {}` → semua pasangan kamera berbeda memakai default 30 dtk;
  muncul di kamera lain <30 dtk = "mustahil" (`identity/reid/merge.py`). (2) `match_threshold: null`
  = usulan 0,80, belum dikalibrasi; orang sama lintas sudut 0,7–0,9. (3) Keputusan gabung hanya
  sekali, di embedding pertama (paling jelek); tidak ada penilaian ulang, tidak ada gabung ANON↔ANON
  (`identity/reid/pending.py`).
- **Perbaikan berurutan:** tabel waktu tempuh dari denah → kalibrasi `tools/reid_train/eval_reid.py` (salah gabung
  ≤1%) → log alasan penolakan (`travel_time`/`cannot_link`/ambang/margin) di
  `_assign_without_face` → penilaian ulang + gabung ANON↔ANON.
- **Prinsip yang dipertahankan:** "lebih baik terpecah daripada tertukar".

### P7. Outbox sinkron di thread kamera

- **Akar:** `emit_event` (`runtime/service.py`, `api/server.py`) mengambil `_emit_lock` lalu
  `SqliteOutbox.append` commit + fsync sinkron (`synchronous` default FULL). Setelah 200.000 entri,
  `_enforce_cap` menghapus 1 baris + commit kedua **setiap** append.
- **Dampak:** NVMe tidak terasa. HDD ±8–20 ms/fsync dari anggaran 100 ms/frame; saat ganti shift
  bisa memicu lingkaran: kamera macet → frame terlompat → track putus → event bertambah.
- **Perbaikan:** (1) pemangkasan per gugus (mis. per 1.000 baris); (2) group commit: thread kamera
  hanya enqueue, satu thread penulis memberi seq + satu transaksi + satu fsync per gugus, pengirim
  tetap membaca dari outbox yang sudah tersimpan (aturan "simpan dulu, kirim kemudian" utuh).
  Antrean dibatasi dan **memblok** bila penuh (tidak membuang event durabel); dikuras saat shutdown.
  Batas atas gugus ±500. (3) Opsional `synchronous=NORMAL` **hanya bersama** lompatan seq saat start.
- **Ditolak:** outbox di RAM saja; buffer RAM yang dikirim sebelum tersimpan (seq dipakai ulang
  setelah crash → event baru dibuang backend); chunking ukuran tetap + timer (latensi saat sepi);
  log segmen buatan sendiri; ML untuk keputusan tulis.
- **Tes:** seq monoton dengan banyak thread; crash di tengah gugus tidak memakai ulang seq;
  antrean penuh memblok; `since()` tidak melihat transaksi setengah jadi.
- **Pertanyaan terbuka:** apakah heartbeat per track (30 dtk) perlu durabel atau cukup di `view`.

### P8. Identitas lintas kamera dan makna keyakinan

- **Akar:** arbiter per kamera (`identity/arbiter.py`); dedup klaim hanya dalam satu kamera.
  `identity/reid/pending.py` menyerahkan tabrakan dua klaim wajah ke arbiter, arbiter tidak melihat kamera lain.
  `_confidence_from` = `0,7·(cos+1)/2 + 0,3·min(margin/0,3,1)`, tidak dikalibrasi (cos 0 tetap 0,35).
- **Perbaikan berurutan:** (1) tolak klaim wajah bersamaan di dua kamera, kecuali pasangan kamera
  yang bidang pandangnya tumpang-tindih (dideklarasikan di config); (2) kalibrasi skor wajah dengan
  regresi logistik pada pasangan berlabel (data yang sama dengan P6); (3) `identity_confidence` =
  probabilitas hasil kalibrasi. Fusi probabilistik multi-track baru dipertimbangkan setelah ini.
- **Cek dulu:** apakah backend memakai `identity_confidence` untuk keputusan, bukan hanya tampilan.

### P9. D-FINE ke ONNX

- **Jalan:** LibreYOLO 1.6 bisa ekspor D-FINE (`dynamic=True`, wajib untuk detektor bersama) dan
  memuat `.onnx` lewat `OnnxBackend`; `model_path` cukup diganti.
- **Yang hilang:** `cuda_graph`, `fast_preprocess` (hook torch), FP16 autocast. ORT CUDA EP FP32
  hampir pasti lebih lambat dari 14,4 ms di 4060. Kecepatan sungguhan baru lewat TensorRT EP
  (proyek tersendiri: cache per GPU/driver).
- **Verifikasi dulu:** tipe kembalian `OnnxBackend` = `Results` yang dibutuhkan ByteTrack
  (`last_result`), bila tidak dan `strict_mode` mati → **diam-diam** jatuh ke IoUTracker;
  apakah NMS numpy-nya aktif untuk D-FINE; ekspor `LibreDFINEm.pt` tanpa masalah opset.
- **Putuskan alasannya:** penyederhanaan deploy (CUDA EP cukup) vs kecepatan (TensorRT) vs edge.

### P10. Kebersihan

- `iou_threshold` di 12 profil: hapus atau sambungkan ke NMS P3.
- 12 profil YAML tanpa pewarisan; bereskan sebelum P9 menambah profil.
- `_emit_lock` dipakai juga untuk enrollment: **bukan bug** (lihat §4), pisahkan bila sempat.
- `set_roster`/skema enrollment belum menolak `ANON-`; laporan memuat baris ANON.
- `onnx` tidak ada di `requirements-dev.txt` → tes ONNX engine diam-diam dilewati (relevan P9).
- Autentikasi handshake engine di `contracts/` belum diimplementasikan backend; naik prioritas bila
  engine dan backend dipisah mesin.

---

## 3. Data lapangan yang dibutuhkan (semuanya baca-saja di pilot)

| Data | Cara | Untuk |
|---|---|---|
| Bentuk kotak duplikat | tangkapan layar: menumpuk vs kotak di dalam kotak | P3 |
| Jenis disk volume data | `lsblk -d -o NAME,ROTA,MODEL`; `docker volume inspect ai-time-tracking-engine-data` | P7 |
| Cookie secure | cek `AUTH_COOKIE_SECURE` di `deploy/.env` | P1 |
| Port MediaMTX terbuka langsung? | konfigurasi Traefik VPS (bila ya, `auth_request` terlewati) | P1 |
| Lag dan koreksi jam | `docker compose logs engine \| grep -E "tertinggal\|meleset"` | P5 |
| Selisih jam | `w32tm /query /status` (DESKTOP-GF5PSD3), `timedatectl` (server) | P5 |
| Metrik rekognisi | `recognitions_rejected`, `recognitions_empty`, `dropped_stale`, `identify_delays` | P2 |
| Pemakaian heartbeat & `identity_confidence` di backend | baca kode backend | P7, P8 |

Catatan: ambang peringatan lag di `runtime/camera.py` belum dicek; bila di atas 2 dtk, log kosong
**tidak** membuktikan engine tidak tertinggal.

## 4. Sudah diperiksa dan sehat (jangan diulang)

- **Assembler presence:** interval mulai dari kelahiran track; `camera_lost` tidak mencatat pulang;
  penyambungan hanya kamera + epoch sama, jendela 5 dtk. Catatan: track dengan label ReID tidak
  pernah disambung (`reid_assigned` mengosongkan `prev_interval_id`).
- **Outbox:** seq bertahan lintas restart, `outbox_id` dilacak backend, dead-letter, volume
  `engine-data` terpisah + cadangan harian di DEPLOY.md.
- **Hashing password dan sesi:** lihat P1.
- **Pembersihan state track di `runtime/camera.py`:** sudah terpusat (butir audit lama, selesai).

## 5. Koreksi (klaim yang pernah salah, jangan diwariskan)

- "`_emit_lock` menahan emisi saat enrollment = penyebab kotak telat": **salah.** Benchmark sintetis
  (store SQLite sungguhan, 5 ref/orang, gambar 30 KB): 100 orang ±9 ms, 500 orang ±35 ms terburuk.
  Kotak lewat `emit_view` yang tidak memakai kunci.
- "`WEBRTC_PLAYOUT_DELAY = 5.0` adalah jebakan": **salah.** Itu mekanisme sinkronisasi yang benar;
  yang tidak punya penahan adalah jalur HLS.
- Dugaan deadlock watchdog (`_state_lock` saat `stop()` beberapa kamera): **belum terbukti**, jangan
  dicatat sebagai bug sebelum ada reproduksi.
