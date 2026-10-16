# 04 — Arsitektur Engine

Versi 1.2 · diperbarui 9 Oktober 2026 · lihat dokumen 12 (kesepakatan), 13 (daftar pembaruan), dan 14 (timeline)

Engine (Python) mengubah video menjadi **event pengamatan**: siapa terlihat, di kamera mana, dari kapan sampai kapan. Engine tidak mengetahui kebijakan perusahaan apa pun; pemeriksaan `contracts/tools/policy_grep.py` di CI menegakkan batas ini.

## 1. Tiga bidang

| Bidang | Isi | Sifat |
|---|---|---|
| Inference bersama | Model detector, face detector, embedder, GPU | Stateless, dapat di-batch lintas kamera |
| Per kamera | Ingest, decode, timeline PTS, tracker, zona | Terisolasi; satu kamera bermasalah tidak menjatuhkan yang lain |
| Identitas & presence | Referensi wajah, matcher, arbiter, assembler interval, outbox | Dibagi eksplisit lintas kamera |

Ketiga bidang tetap berada di **satu proses**. Sejak 9 Oktober 2026 ritme proses itu dipegang satu penjadwal berdetak tetap, bukan oleh thread tiap kamera (§14).

## 2. Alur per frame

```
RTSP (MediaMTX) → ingest per kamera (PyAV di CPU, atau NVDEC di GPU — §14.5)
   → mailbox: hanya frame terbaru per kamera yang disimpan
   → penjadwal berdetak tetap (mis. tiap 1/6 detik) mengambil frame terbaru semua kamera
   → detector orang (LibreYOLO D-FINE m/s), satu batch untuk semua kamera per detak
   → per kamera: tracker (ByteTrack / IoU)
   → zona (pintu / interior / tepi frame)
   → antrian rekognisi (prioritas track yang lahir di pintu)
        → crop kepala → SCRFD (wajah + 5 landmark) → align → AuraFace (embedding 512-d)
        → matcher matriks + uji margin → arbiter (akumulasi bukti, verifikasi ulang)
   → (rencana) ReID berbasis kejadian: embedding tubuh, galeri harian, identitas tertunda (§11)
   → presence assembler (interval kehadiran, stitching, zona akhir)
   → emit event durabel ke outbox SQLite  +  view.frame best-effort
```

## 3. Komponen

**Ingest (EB).** PyAV dengan PTS asli dari kontainer, `stream_epoch` yang naik setiap reconnect, dan offset jam dinding yang ditetapkan per epoch. RTSP lewat TCP. Reconnect dengan backoff; kamera yang gagal dicoba ulang 5→60 detik selama masih diminta backend.

**Perception (EB).** Detector D-FINE lewat LibreYOLO (MIT), filter kelas orang di model. Tracker: ByteTrack (MIT, di-vendor) atau IoU. Konfigurasi runtime saat ini (`dfine-m.yaml`, `dfine-s.yaml`) masih memakai IoU, dan ByteTrack tidak menerima deteksi berskor rendah karena model dipanggil dengan `conf=0.5` (P8). Mengurangi ID switch tracker adalah prasyarat ReID (§11).

**Identity (EA).** Recognizer ONNX (SCRFD `scrfd_10g_bnkps` + AuraFace `glintr100`) yang dapat dimatikan lewat config dan gagal keras bila dinyalakan tapi model tidak bisa dimuat. Matcher matriks dengan threshold (default 0,37) dan margin (default 0,06), belum dikalibrasi pada data klien. Arbiter memegang identitas selama track hidup, memverifikasi ulang tiap 60 detik, dan melepas identitas setelah beberapa kali tidak sepakat. Enrollment policy menilai kualitas foto dan kemiripan antar-karyawan.

**Presence (EA).** Membentuk `presence.interval` per identitas per kamera, menyambung track yang putus sebentar (stitching) hanya atas bukti perseptual, dan mencatat zona awal/akhir.

**ReID (EA: logika, model, dan worker; rencana).** Lihat §11. Model dan worker pindah dari EB ke EA per 9 Oktober 2026 supaya EB fokus ke restrukturisasi (§14).

**Penjadwal (EB; rencana).** Penjadwal berdetak tetap, mailbox frame terbaru, dan ingest GPU. Lihat §14.

**API (EA).** Server NDJSON tiga kanal, outbox SQLite dengan `high_water` dan `outbox_id`, pengiriman event berbasis kursor, satu kunci tulis. Lihat dokumen 07.

**Bench (EB).** Harness pengukuran: latensi per tahap, throughput, false gap, kontinuitas identitas, ID switch. Menjadi alat ukur semua keputusan optimisasi. Untuk uji live, `scripts/lag_probe.py` dan `scripts/summarize_gladi.py` (paket r7) menghasilkan tabel dan vonis LULUS/GAGAL.

## 4. Konfigurasi runtime (fase 1)

| Parameter | Nilai | Catatan |
|---|---|---|
| Detector | D-FINE m (default), s (opsi) | `--model m|s` |
| Input detector | 640 | |
| Target fps analisis | **≥ 6 per kamera, 5 kamera serentak** (kriteria prototype); 10–12 target lanjutan | Profil saat ini: `dfine-*.yaml` 12, `demo-4060.yaml` 10, `demo-1060.yaml` 8. Diturunkan adaptif saat overload (§6) |
| Tracker | ByteTrack setelah dibuktikan di bench | Saat ini IoU di profil runtime |
| Rekognisi | Aktif, `onnx_face` | Model di mesin engine, tidak dibundel |
| `min_face_px` | 40 (runtime), 112 (enrollment) | Gerbang pose/blur runtime ditambahkan (§8) |
| RTSP | TCP, timeout 8 detik | |
| Outbox | `engine/data/outbox.sqlite3`, maks. 200.000 event | |
| Heartbeat track / health | 30 detik / 30 detik | |
| Interval pembaruan galeri ReID | 15 detik (default, dapat diubah di config) | Rencana (§11) |

## 5. Perubahan fase 1

**Pemulihan, startup, dan stabilitas operasional (EA).** Stabilitas operasional dipegang Engine A (dokumen 12 §7). Engine dijalankan di bawah supervisor proses (systemd dengan `Restart=always` dan `WatchdogSec`, atau healthcheck kontainer; di laptop Windows: service yang hidup ulang otomatis). Loop utama mengirim detak ke watchdog; bila loop macet, engine di-restart otomatis (P28). Port engine dibuka sedini mungkin, dan pemuatan model berat dilaporkan lewat `engine.health` (`models_loaded`, `degraded_components`), sehingga backend dapat tersambung dan menampilkan fase "pemanasan" alih-alih ditolak koneksinya (P27). Kriteria lulus: stabil selama jam operasional minimal **3 hari berturut-turut** tanpa intervensi (memori tidak terus naik, pulih sendiri saat kamera putus, tidak ada event hilang; dokumen 12 §2.4).

Catatan laptop Windows (mesin engine demo, dokumen 12 §6 dan `docs/DEMO-REMOTE.md` §8–§9):

- Run bersih 10 fps di laptop RTX 4060 tercapai setelah tiga perubahan sekaligus: sumber ffmpeg dipaksa `-r 25`, engine dikunci ke P-core (`-AffinityMask 0xFFFF`), dan power throttling ffmpeg/MediaMTX dimatikan. Engine sendiri mematikan power throttling prosesnya (`engine/runtime/winpower.py`). Perubahan mana yang krusial masih dipastikan lewat uji A/B; sampai hasilnya ada, ketiganya dipertahankan.
- Turbo CPU bukan penyebab (turbo hidup justru lebih buruk); setelan kembali ke setelan EB.
- Untuk operasi harian: sleep dimatikan, jam aktif Windows Update diatur, laptop dicolok charger, suhu dipantau. Kecukupan RAM 16 GB untuk 5 kamera + ReID belum diukur.

**Rekognisi asinkron (EB/EA).** Rekognisi semula dijalankan sinkron di dalam loop frame setiap kamera, dengan satu kunci global lintas kamera (P7). Dengan lima lokasi terpisah, setiap orang dikenali ulang di setiap ruangan, sehingga beban ini menjatuhkan fps semua kamera. Kondisi r7: sudah ada satu worker rekognisi untuk semua kamera (`engine/pipeline/recognition_worker.py`) dengan antrean terbatas; crop yang lebih tua dari 0,5 detik dibuang. Batching crop lintas kamera di worker ini masih harus dibuktikan di bench.

**Input SCRFD sesuai crop.** SCRFD saat ini memproses crop kepala (±60–150 px) di kanvas 640×640. Gunakan input 160–320 untuk crop kepala.

**ByteTrack yang benar.** Model dipanggil sekali dengan confidence rendah (0,1). Detector memfilter 0,5 untuk konsumennya sendiri; tracker menerima hasil mentah untuk asosiasi tahap kedua. Karena kalibrasi confidence keluarga DETR berbeda, manfaat tahap kedua diukur di bench sebelum dijadikan default.

**Tracker memakai dt dari PTS.** Buffer track dinyatakan dalam detik dan dihitung dari PTS, bukan jumlah frame, sehingga frame yang dilewati tidak membuat track mati prematur.

**Inferensi yang cukup untuk 5 kamera (EB).** Kriteria prototype: 5 kamera serentak, analisis **≥ 6 fps stabil per kamera** (waktu lambat < 5%), umur kotak p99 < 1 detik tanpa stall > 2 detik, juga saat beban 100 orang total di 5 kamera dan 100 karyawan terdaftar (dokumen 12 §2.1–§2.2). Target 10–12 fps hanya dikejar bila ruang performa tersisa. Kondisi r7: semua kamera berjalan dalam **satu proses Python**, dengan detector D-FINE bersama dan batching opsional antar-kamera. Keputusan 9 Oktober 2026: **tetap satu proses dan satu D-FINE**; yang diubah adalah cara menjadwalkannya (penjadwal berdetak tetap) dan tempat kerjanya (sebanyak mungkin di GPU, termasuk decode NVDEC). Proses per kamera hanya dipertimbangkan bila baseline membuktikan GIL sebagai penghambat setelah penjadwal terpasang. Rinciannya di §14. Ekspor D-FINE ke ONNX/TensorRT FP16 tetap opsi bila inferensi sendiri menjadi penghambat. Estimasi beban: 5 kamera × 6 fps = 30 inferensi per detik (5 × 12 = 60 untuk target lanjutan); PyTorch tanpa batching ±15–25 ms per gambar, TensorRT FP16 ±5–6 ms. Angka ini estimasi dan diverifikasi di bench (dokumen 09). Lima kamera serentak belum pernah diuji (dokumen 12 §8).

## 6. Real-time: frame terbaru dan fps adaptif

Kondisi awal: ingest PyAV membaca frame secara sinkron di thread pemrosesan dan tidak pernah membuang frame. Bila engine lebih lambat dari kamera, keterlambatan terus bertambah (P17). Timestamp event tetap benar karena berbasis PTS; yang terdampak adalah kesegaran dashboard, overlay, dan peringatan.

Desain fase 1 (EB), diwujudkan oleh penjadwal berdetak di §14:

1. **Thread pembaca per kamera** yang selalu menguras socket dan men-decode setiap frame, lalu menyimpan hanya **frame terbaru** (dengan PTS asli) di satu slot. Paket tidak boleh dibiarkan menumpuk: pembaca yang lambat membuat MediaMTX membuang paket, dan frame rusak (smear sampai keyframe berikutnya) merusak embedding tanpa error.
2. **Fps adaptif yang seragam** sebagai mekanisme utama. Di struktur §14, "fps" adalah frekuensi detak penjadwal, sama untuk semua kamera. Kontroler memantau lag (PTS terbaru yang ter-decode dikurangi PTS yang sedang diproses) dan menurunkan target fps bertahap (12 → 8 → 6), lalu menaikkannya kembali dengan histeresis. Jarak antar-frame tetap rata sehingga tracker stabil. Karena 6 fps adalah batas bawah kriteria prototype, kamera yang bertahan di anak tangga terbawah dan tetap tertinggal berarti target §5 tidak tercapai.
3. **Lompat ke frame terbaru** hanya bila lag melewati ambang keras (±1 detik), dengan tracker diberi dt asli dari PTS.
4. **Kejujuran data:** `engine.health` membawa `lag_seconds`, `effective_fps`, dan `frames_dropped_stale` per kamera. Lag yang bertahan di atas ambang memicu `camera.degraded` (sudah ada di skema) dengan alasan dan rentang waktu, sehingga HR dapat melihat kapan kualitas observasi turun.

Mode file (`PlaybackSource`) tidak diubah: tidak membuang frame dan menahan pembacaan agar tidak melampaui waktu putar.

Di sisi tampilan, frontend menginterpolasi posisi kotak antar frame analisis per `track_uuid` (dokumen 03 §3), sehingga 6 fps analisis tetap tampil halus.

## 7. Waktu dan drift

Jam event dihitung `at = offset + pts`, dengan `offset` ditetapkan sekali per epoch saat frame pertama tiba. Ini benar untuk durasi (selisih PTS), tetapi jam absolutnya bisa bergeser:

- **Drift osilator kamera:** kamera murah dapat meleset puluhan ppm (±1–9 detik per hari). Koneksi RTSP yang bertahan berhari-hari mengakumulasi selisih ini, berbeda per kamera.
- **Bias awal:** offset diambil dari waktu tiba frame pertama, yang sudah termasuk latensi dan burst GOP dari MediaMTX (1–4 detik).
- **Jam berbeda antar-mesin:** `at` berasal dari mesin A, PDT HLS dari mesin B, "sekarang" di backend dari mesin B, dan WebRTC dari jam browser.

Dampak ke hitungan jatah kecil (detik), tetapi terlihat pada overlay, "pertama terlihat", dan gabungan lintas kamera. Solusi fase 1:

1. **NTP tunggal:** mesin B menjadi server NTP lokal (chrony); mesin A dan kelima kamera disinkronkan ke sana (kamera: tanggung jawab perusahaan CCTV).
2. **Ukur drift di engine:** selisih waktu tiba terhadap `offset + pts` per frame, nilai minimum dalam jendela beberapa detik, dilaporkan di `engine.health`; offset dikoreksi perlahan (slew) bila melewati 0,5 detik, tidak melompat.
3. **Timestamp absolut dari kamera** (opsi MediaMTX `useAbsoluteTimestamp`) bila kamera sudah ber-NTP dan mengirim RTCP yang benar. Diuji dengan model kamera nyata.
4. Backend mengukur selisih jam engine–backend dari `ts` di `hello_ack`/`engine.health` dan memberi alarm bila lebih dari 2 detik.

## 8. Akurasi identitas

- **Dataset evaluasi** dari rekaman lokasi klien (pilot minggu 1), memakai metrik yang relevan untuk produk: detik salah tagih per orang per hari, false accept (orang A ditagih ke B), tingkat identifikasi, false gap.
- **Kalibrasi threshold dan margin** AuraFace pada data klien (wajah karyawan, bukan nilai bawaan), dengan titik operasi yang memprioritaskan false accept sangat rendah. Kriteria prototype: 0 pelanggaran tertagih ke orang yang salah selama N jam uji rekaman dan minimal X% kunjungan teridentifikasi; nilai N dan X belum ditetapkan (dokumen 12 §2.3, §9). Uji beban memakai 100 karyawan terdaftar; kalibrasi diulang bila jumlah karyawan berubah jauh.
- **Gerbang kualitas runtime:** yaw/pitch dari 5 landmark, blur pada wajah yang sudah di-align, ukuran wajah minimum ±48–56 px; bobot bukti di arbiter mengikuti kualitas.
- **Embedding agregat per track**, tertimbang kualitas, sebagai pelengkap keputusan per frame.
- **Referensi domain CCTV** lewat konfirmasi HR (dokumen 02 §5), dengan batas jumlah, uji keragaman, dan larangan menambah dari match bermargin tipis.
- **Fine-tuning detector** pada footage klien bila bench menunjukkan deteksi (bukan identitas) sebagai sumber kesalahan utama.
- **ReID tubuh** kini masuk prototype dengan desain berjangkar wajah (§11): ReID hanya meneruskan identitas yang sudah dikonfirmasi lewat wajah dan tidak pernah menjadi sumber identitas sendiri.

## 9. Karakter lokasi

| Lokasi | Tantangan utama | Strategi |
|---|---|---|
| Ruang hiburan | Relatif ideal bila kamera menghadap tempat duduk | Identifikasi di pintu dan saat menghadap TV |
| Billiard | Wajah menunduk ke meja, cahaya kontras | Identifikasi di pintu; tracker memegang identitas |
| Smoking area | Cahaya berubah, wajah tertutup tangan/rokok, menunduk ke ponsel | Ekspektasi "tidak dikenal" tertinggi; alur konfirmasi HR |
| Lobby | Tamu dan kurir, lalu-lalang | Kategori transit; alert tak dikenal dapat dimatikan |
| Luar | Backlight, jarak jauh, helm/masker, publik | Kategori pintu masuk; hanya "pertama terlihat" |

## 10. Stream yang dianalisis

Konfigurasi MediaMTX saat ini menarik **substream** H.264 kamera dan engine membacanya. Resolusi substream (umumnya 640×360 sampai 704×576) terlalu kecil untuk wajah di jarak ruangan (P19). Fase 1: engine membaca **mainstream** (1080p ke atas, H.264 atau H.265, keduanya dapat di-decode PyAV/NVDEC), browser membaca substream H.264. MediaMTX menyediakan dua path per kamera.

## 11. ReID berjangkar wajah (rencana, dokumen 12 §3.6)

Status: **belum diimplementasikan**. Kontrak protokolnya (`identity.resolved`, ID sementara `ANON-xxxx`, nilai `identity_source` baru) disepakati EA lebih dulu (dokumen 07 §1.4). Pembagian: EA memegang logika (galeri, aturan penggabungan, identitas tertunda), model ReID, dan worker-nya (sejak 9 Oktober 2026; sebelumnya model dan worker di EB). ReID menerima crop dan embedding hanya lewat antrean internal (§14.4), sehingga tidak bergantung pada jalur frame CPU atau GPU.

**Tujuan.** Bila track seseorang hilang (membelakangi kamera, tertutup, pindah ruangan), orangnya tetap dapat dilacak lewat cache tubuh yang diambil dari orang yang sudah dikenali wajahnya.

**Desain:**

1. **Berjangkar wajah.** Cache tubuh hanya diisi dari track yang identitasnya dikonfirmasi lewat wajah. ReID tidak pernah menetapkan identitas sendiri dan tidak boleh membatalkan hasil wajah.
2. **Galeri harian multi-sudut.** Per orang disimpan beberapa embedding tubuh (depan, belakang, samping) yang dikumpulkan sepanjang hari, dan **dihapus otomatis di akhir hari** (UU PDP; dokumen 12 §8).
3. **Identitas tertunda.** Tubuh tanpa wajah diberi ID sementara `ANON-xxxx`; track yang penampilannya cocok digabung ke kelompok yang sama. Saat wajah salah satu track terkonfirmasi, engine mengirim `identity.resolved` untuk seluruh kelompok, dan backend memindahkan semua intervalnya ke karyawan itu (atribusi mundur).
4. **Aturan penggabungan.** Dua track yang hidup bersamaan di tempat berbeda tidak boleh digabung (cannot-link). Waktu tempuh minimum antar 5 lokasi (luar, lobi, smoking area, ruang hiburan, biliar) dipakai untuk menolak sambungan yang mustahil; nilai waktu tempuhnya belum ditetapkan. Ambang dibuat ketat: lebih baik terpecah daripada tertukar.
5. **Perhitungan berbasis kejadian, bukan tiap frame.** Embedding tubuh dihitung saat identitas dikonfirmasi, sesekali selama orang terlihat (interval di config, default 15 detik, dapat dijauhkan bila berat), dan saat track tanpa identitas muncul.
6. **Label sumber.** `identity_source` diperluas menjadi `face | tracking | reid | reid_retro`. Pelanggaran yang sebagian besar waktunya bersumber dari ReID ditandai "perlu dicek HR" oleh backend.

**Prasyarat:** ID switch tracker dikurangi lebih dulu (EB).

**Ukuran keberhasilan:** persentase sambungan ReID yang benar dan persentase menit pemakaian yang sumbernya ReID.

**Di luar lingkup:** pengenalan orang murni dari bentuk tubuh/gait tanpa wajah sama sekali (masih masalah riset, tidak dijanjikan). Kasus "wajah tidak pernah terlihat sepanjang hari" ditangani dengan kamera jangkar dan alur "tidak dikenal" ke HR.

**Ketergantungan:** evaluasi membutuhkan rekaman multi-kamera; persetujuan biometrik (termasuk penampilan tubuh) diurus COM. Estimasi ±2 minggu dengan 4 jalur paralel (dokumen 12 §3.6).

## 12. Jadwal analisis kamera (rencana, dokumen 12 §3.3)

- Yang dijadwalkan adalah **analisis kamera**, bukan proses engine: proses engine tetap hidup, model tetap termuat.
- Di luar jam operasional, backend mengirim `set_cameras` dengan `enabled: false` untuk kamera yang bersangkutan (field `enabled` sudah ada di skema). Jadwalnya diatur admin dari web dan disimpan di backend; engine tidak mengetahui jadwal.
- Track yang masih hidup saat analisis dimatikan ditutup dengan alasan **`schedule_off`**, sehingga tidak dibaca sebagai "semua orang pulang". Nilai `schedule_off` **belum ada** di enum `end_reason` skema saat ini dan harus ditambahkan EA (dokumen 07 §1.4).

## 13. Overlay `view.frame`

Perbaikan paket r7 (`engine/runtime/camera.py`): `view.frame` hanya memuat track aktif dan track berstatus LOST yang terakhir terlihat **≤ 0,3 detik** lalu (`VIEW_LOST_GRACE_SECONDS = 0.3`). Sebelumnya track LOST ikut digambar dengan posisi beku sampai ±1 detik, sehingga satu orang tampil dengan 2–3 kotak. Bila kotak ganda masih muncul: dua kotak yang sama-sama bergerak menandakan deteksi ganda; kotak yang berganti-ganti menandakan ID switch tracker. Penghalusan gerak kotak dilakukan di frontend (interpolasi, dokumen 03 §3), bukan dengan menaikkan fps analisis.

## 14. Restrukturisasi engine: penjadwal berdetak dan pemrosesan di GPU (rencana, dokumen 12 §3.9)

Status: **diputuskan 9 Oktober 2026, belum diimplementasikan**. Kerangka kodenya dikirim di paket r9 dengan default **mati** (perilaku lama tetap jalan).

### 14.1 Masalah

Laptop RTX 4060 tidak stabil: fps berayun 10 ↔ 6 dan ada stall sampai 9 detik. Yang membuatnya gagal bukan GPU penuh, melainkan bagian CPU yang tersendat. Penyebabnya dua:

1. **Banyak kerja di CPU per frame.** Decode H.264 harus memproses semua frame (25 fps × 5 kamera) walaupun yang dianalisis hanya 6 fps, karena frame non-keyframe tidak bisa dilewati. Ditambah swscale dan salinan numpy. Semuanya berebut CPU dan GIL.
2. **Loop berjalan "secepat mungkin".** Kondisi r7: tiap kamera punya thread sendiri (`CameraSupervisor`) yang membaca frame, mengirim ke `SharedDetector`, lalu menunggu. Batching terjadi *kebetulan*: dispatcher menunggu `batch_wait_ms` (4 ms) berharap kamera lain datang. Ritme tiap kamera ditentukan penjadwalan thread Windows, sehingga setiap gangguan kecil langsung terlihat sebagai fps turun.

Memindahkan kerja ke GPU menyelesaikan masalah 1. Masalah 2 hanya selesai dengan cara menjadwalkan.

### 14.2 Keputusan

| Pertanyaan | Keputusan | Alasan |
|---|---|---|
| Berapa D-FINE | **Satu**, untuk semua kamera | Bobot sekali di VRAM; satu antrean GPU yang teratur. Catatan: batch sungguhan belum terbukti mempercepat di 4060 (uji 3 Okt, `batch_inference: false`), jadi yang diandalkan adalah iramanya, bukan batch-nya |
| Berapa proses | **Satu** | Satu tempat yang menjadwalkan GPU; IPC dan salinan model per proses tidak sepadan selama penghambatnya bukan GIL |
| Siapa memegang ritme | **Penjadwal berdetak tetap** | Detak tetap dengan cadangan kapasitas menyerap gangguan; fps tidak berayun |
| Di mana pemrosesan | **Sebanyak mungkin di GPU**: decode (NVDEC), resize, normalisasi, inferensi, crop wajah/badan | CPU hanya mengatur lalu lintas; tidak sensitif terhadap throttling Windows |
| Yang tetap di CPU | Demux RTSP, ByteTrack, logika identitas/presence, outbox | Murah; memindahkannya ke GPU tidak ada manfaat |
| Urutan | **Penjadwal dulu (jalur CPU), NVDEC kemudian** | Penjadwal = stabilitas; NVDEC = efisiensi. Stabilitas tidak boleh menunggu spike NVDEC |
| Fallback | Jalur CPU (PyAV + numpy) tetap ada di bawah penjadwal yang sama | GTX 1060, CI, mock, `fake_engine` tidak bercabang |

Yang **tidak** diubah: `identity/`, `presence/`, `api/`, `store/`, kontrak NDJSON, backend, frontend.

### 14.3 Penjadwal berdetak

```text
[decoder cam01] ─┐
[decoder cam02] ─┤   mailbox per kamera: hanya frame terbaru (yang lama dibuang)
      ...        ├──────────────────────────────────────────────┐
[decoder cam05] ─┘                                              ▼
                                   penjadwal: bangun tiap 1/fps detik
                                   1. ambil frame terbaru semua kamera aktif
                                   2. 1 batch D-FINE untuk semua frame
                                   3. per kamera: tracker → zona → binding → presence → event/view
                                   4. sisa waktu sampai detak berikut: rekognisi wajah / ReID
```

Aturan:

1. **Kamera tanpa frame baru dilewati** pada detak itu (decoder putus atau telat). Batch jalan dengan kamera yang ada frame-nya; satu kamera bermasalah tidak menahan empat lainnya.
2. **Detak yang molor tidak dikejar.** Bila satu detak melewati jadwal, detak berikutnya langsung jalan tanpa mengulang detak yang terlewat. Kejadian ini dihitung (`ticks_late`); bila beruntun, fps adaptif (§6) menurunkan frekuensi detak.
3. **Rekognisi dan ReID memakai sisa waktu.** Pekerjaan identitas tidak boleh menunda detak berikutnya; yang tidak sempat diproses tetap antre dan crop yang terlalu tua dibuang (aturan 0,5 detik yang sudah ada).
4. **Cadangan kapasitas.** Frekuensi detak dipilih di bawah kapasitas terukur (mis. kapasitas 10–12 fps, dijalankan 6 fps). Cadangan inilah yang membuat sistem stabil.
5. **Ukuran keberhasilan** adalah stabilitas, bukan rata-rata fps: p99 umur kotak, jumlah stall, persen waktu lambat (`summarize_gladi.py`).

### 14.4 Struktur kode dan antarmuka internal

Nama file masih usulan:

```text
engine/
├── ingest/
│   ├── pyav_source.py        # tetap: jalur CPU (1060, CI, file)
│   ├── nvdec_source.py       # BARU: RTSP → NVDEC → tensor GPU (setelah spike, §14.5)
│   └── mailbox.py            # BARU: frame terbaru per kamera
├── ports/
│   └── frame.py              # DIUBAH: Frame dapat membawa data di GPU
├── perception/
│   ├── shared_detector.py    # DIUBAH: pemanggil batch sinkron; tunggu-4-ms dibuang
│   └── dfine_detector.py     # DIUBAH sedikit: terima tensor GPU langsung
├── runtime/
│   ├── tick_scheduler.py     # BARU: detak tetap → batch → bagi hasil per kamera
│   ├── camera.py             # DIROMBAK: tinggal state per kamera, tanpa thread loop sendiri
│   └── service.py            # DIUBAH: merakit penjadwal
└── pipeline/
    └── recognition_worker.py # DIUBAH: anggaran waktu per detak; crop dari GPU
```

Logika per kamera di `runtime/camera.py` (tracker, zona, binding, presence, heartbeat, overlay) **dipakai ulang**, hanya pemanggilnya yang berpindah dari "thread sendiri" ke "dipanggil penjadwal tiap detak".

**Antarmuka internal per-kamera → inti identitas** (disepakati EA–EB di kontrak 13 Oktober): pesan berisi `camera_id`, `track_id`, PTS/waktu, crop (wajah dan/atau badan, di CPU atau GPU), dan konteks zona, dikirim lewat antrean. Selama satu proses, antrean itu `queue.Queue`; ReID dan rekognisi tidak memegang referensi objek milik thread kamera. Dengan begitu logika ReID tidak perlu diubah bila jalur frame berganti dari CPU ke GPU, atau bila suatu saat proses dipecah.

### 14.5 Ingest GPU (NVDEC) dan spike

Jalur sasaran: demux RTSP (CPU) → NVDEC → frame tetap di memori GPU → resize/normalisasi (`fast_preprocess` yang sudah ada) → D-FINE → hanya kotak yang kembali ke CPU → crop wajah/badan diambil dari frame resolusi penuh di GPU → embedding kembali ke CPU.

Catatan: PyAV dengan hwaccel memang men-decode di GPU, tetapi frame-nya diunduh ke CPU (bukan nol-salin). Decode yang frame-nya tetap di GPU membutuhkan pustaka NVIDIA tersendiri (mis. PyNvVideoCodec). Dukungan Windows dan kecocokannya dengan versi CUDA/driver tim **belum diverifikasi**.

**Spike 15–16 Oktober (EB):** satu stream RTSP → NVDEC → tensor torch di laptop Windows. Diukur: CPU% dibanding PyAV, latensi decode, VRAM per stream, kestabilan 15 menit. Vonis tertulis: **lanjut** (ingest GPU dikerjakan 26–30 Oktober) atau **tunda** (jalur CPU di bawah penjadwal dioptimasi, NVDEC pasca-pilot).

### 14.6 Risiko

| Risiko | Dampak | Penanganan |
|---|---|---|
| Satu proses = satu titik mati | Crash satu bagian mematikan 5 kamera | Watchdog + service auto-restart (§5) wajib; decoder terisolasi per kamera (putus → kamera offline + reconnect, penjadwal jalan terus) |
| VRAM 8 GB dibagi D-FINE, SCRFD, embedder, model ReID, decoder, buffer frame penuh | Kehabisan memori GPU saat ReID dipasang | Ukur VRAM sebelum ReID diintegrasikan (23 Okt), bukan sesudahnya |
| NVDEC tidak jalan di Windows | Efisiensi tidak tercapai | Jalur CPU tetap di bawah penjadwal; stabilitas tidak bergantung pada NVDEC |
| `runtime/camera.py` disentuh EA (ReID, `schedule_off`) dan EB (penjadwal) bersamaan | Bentrok merge | Perubahan struktur EB masuk dulu (23 Okt); EA menyesuaikan sesudahnya; logika ReID hanya lewat antrean |
| GIL tetap jadi penghambat setelah penjadwal | Fps tidak tercapai | Baru saat itu proses dipecah (inferensi bersama + proses per kamera via shared memory); antarmuka §14.4 membuat ReID tidak ikut berubah |

## Riwayat perubahan

- 9 Oktober 2026 (v1.2): §14 baru, restrukturisasi engine (satu proses, satu D-FINE, penjadwal berdetak tetap, pemrosesan di GPU, spike NVDEC, antarmuka antrean ke inti identitas, risiko). §1, §2, §3, §5, §6, §11 disesuaikan; model dan worker ReID pindah dari EB ke EA; "proses per kamera" turun menjadi opsi terakhir.

- 8 Oktober 2026 (v1.1): §4 dan §5 target analisis diubah dari 12 fps menjadi ≥ 6 fps per kamera di 5 kamera serentak, 10–12 fps sebagai target lanjutan; profil config saat ini dicatat.
- §5: kebutuhan proses per kamera dan/atau batching untuk 5 kamera ditegaskan, beserta kondisi r7 (satu proses, detector bersama, batching opsional) dan kriteria beban dokumen 12 §2.2.
- §5: stabilitas operasional (service, watchdog, uji 3 hari) ditetapkan sebagai tanggung jawab Engine A; ditambah catatan laptop Windows (ffmpeg `-r 25`, afinitas P-core, power throttling, turbo, Windows Update/sleep).
- §5: status rekognisi asinkron diperbarui sesuai kode r7 (worker rekognisi sudah ada).
- §6: catatan bahwa 6 fps adalah batas bawah kriteria prototype dan rujukan ke interpolasi kotak di frontend.
- §8: kalimat "Re-ID tubuh bukan fase 1" diganti; kriteria akurasi N/X (belum ditetapkan) dan 100 karyawan uji ditambahkan.
- §11 baru: desain ReID berjangkar wajah (galeri harian multi-sudut, `ANON-xxxx`, `identity.resolved`, cannot-link, waktu tempuh antar 5 lokasi, interval 15 detik, `identity_source`, purge harian, prasyarat ID switch, di luar lingkup).
- §12 baru: jadwal analisis lewat `set_cameras` `enabled: false` dan alasan akhir track `schedule_off` (belum ada di skema).
- §13 baru: perbaikan overlay r7 (hanya track aktif + LOST ≤ 0,3 detik).
- §2–§3: alur per frame dan daftar komponen ditambah ReID (rencana), prasyarat ID switch, dan alat `summarize_gladi.py`.
