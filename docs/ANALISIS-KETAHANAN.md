# Analisis Ketahanan dan Rencana Lanjutan

Hasil diskusi dan pengujian 10–11 November 2026 (Zena + Claude), atas commit `6751ae2`
(`Claude-Branch`). Pilot masih berjalan di `c990bc4`. Permintaan klien: **robustness**. Target
tim: prototype dengan backend dan engine ±80% jadi, belum siap produksi.

Status kerja harian tetap di `docs/SERAH-TERIMA.md`; dokumen ini menyimpan temuan, angka, dan
alasan di balik urutan kerja supaya tidak perlu diturunkan ulang.

Tanda: **[terukur]** = diuji di lingkungan cloud (CPU, tanpa GPU/kamera); **[kode]** = dari
membaca kode; **[penalaran]** = belum diukur.

## 0. Batas yang ditetapkan Zena

- Traefik, Cloudflare, dan ACL NetBird **tidak diubah**. Yang boleh diubah: cara pesan dan video
  dikirim (engine, backend, frontend, MediaMTX).
- Dashboard debug masuk ke frontend admin yang sudah ada (satu frontend), bukan sistem terpisah.
- Fitur debug harus bisa dinyalakan dan dimatikan.

## 1. Insiden 11 Nov ±04:00 — `cam01b` 404

**Gejala.** Engine: `HTTPNotFoundError ... rtsp://netbird-client:8554/cam01b`, dicoba ulang tiap
60 dtk; penghitung engine membeku (71.606 gambar, 3.247 rekognisi). Dashboard:
`WHEP signaling failed: HTTP 404` dari `stream.zenahost.my.id/cam01b/whep`.

**Diagnosis.** Dua rute berbeda (RTSP engine, WHEP browser) mendapat jawaban yang sama: 404.
Itu bukan jaringan putus (yang akan berupa timeout, *connection refused*, atau 502), melainkan
MediaMTX yang menjawab "path ada, stream tidak siap". Rantainya:

```
kamera Dahua 192.168.1.108 ──LAN──> MediaMTX laptop ──NetBird──> MediaMTX server ──> engine
                                                                               └──> browser
```

Relay berantai meneruskan kegagalan: bila laptop kehilangan `cam01b`, server ikut 404. Log
MediaMTX yang dikirim (kemungkinan laptop, dari nama muxer) sunyi untuk `cam01b` sejak
04:00:15, jadi dugaan terkuat adalah hop kamera → laptop. **Belum dikonfirmasi.**

**Langkah diagnosis (dari hulu):**

1. Laptop: `curl -s http://localhost:9997/v3/paths/get/cam01b` → `"ready"`?
2. Laptop: bandingkan dengan `cam01a` (stream utama, kamera yang sama). `cam01a` siap tetapi
   `cam01b` tidak = hanya sesi substream yang mati; keduanya tidak siap = kamera/LAN.
3. Server: path yang sama + log `[path cam01b] [RTSP source]`. `bad status code: 404` = laptop
   tidak punya stream; timeout = hop NetBird.
4. Kandidat penyebab: *Auto Maintain* Dahua (reboot terjadwal), sleep/maintenance Windows di
   laptop, batas koneksi RTSP Dahua, IP DHCP berubah.

Pulih sendiri bila sumber kembali (MediaMTX menyambung ulang, engine mencoba tiap 60 dtk).
Paket 10–11 Nov **tidak** berkaitan: tidak menyentuh `deploy/`, masuk ke GitHub 06:58, dan pilot
belum di-redeploy.

**Peringatan "part duration changed"** di log MediaMTX: terpisah dari 404. Timestamp frame dari
kamera tidak rata (kemungkinan *smart codec*/frame rate variabel); hanya berdampak ke klien HLS
iOS. Dashboard memakai WebRTC.

## 2. Keamanan

### 2.1 Di luar kode (paling mendesak)

- **MediaMTX tanpa autentikasi** [kode]. `deploy/mediamtx/mediamtx.yml` tidak punya blok auth;
  port 8554/8888/8889 terbuka di semua antarmuka. Rute `/whep/` dan `/hls/` di nginx sudah
  dijaga `auth_request`, tetapi `stream.zenahost.my.id` tidak melewati nginx itu. Uji dari luar
  tanpa login:
  `curl -i -X POST https://stream.zenahost.my.id/cam01a/whep -H "Content-Type: application/sdp" -d "x"`
  → 401/403 aman; 400/404/201 dari MediaMTX = CCTV bisa ditonton tanpa akun. `cam02`–`cam05`
  (`source: publisher`) juga bisa diisi video palsu oleh siapa pun yang menjangkau 8554.
  Karena Traefik tidak boleh diubah, pengamanannya di MediaMTX sendiri (auth bawaan).
- **Kredensial kamera** `admin:admin123` + IP kamera ada di repo publik (`mediamtx.yml`). Ganti
  password kamera (riwayat git tetap menyimpan yang lama), pindahkan URL sumber ke env
  (`MTX_PATHS_<PATH>_SOURCE`).
- **IP klien di belakang Cloudflare** (dari 10 Nov): batas login per IP kemungkinan berlaku per
  edge Cloudflare. Cek dengan uji manual SERAH-TERIMA.

### 2.2 Temuan di kode

| # | Temuan | Dampak | Tingkat |
|---|---|---|---|
| 1 | `must_change_password` hanya ditegakkan frontend | Akun berpassword sementara memakai seluruh API [terukur: viewer pw-sementara GET data = 200] | Tinggi |
| 2 | Ganti/reset password tidak mencabut sesi lama | Token curian tetap hidup [terukur: token lama = 200 setelah ganti] | Tinggi |
| 3 | Token di `localStorage` (cookie httpOnly sudah ada); tanpa CSP | Satu XSS = sesi dicuri | Sedang |
| 4 | Kanal engine tanpa kunci bila `ENGINE_SHARED_KEY` kosong (default) | Host di NetBird bisa menyamar sebagai backend (`enroll`, `forget_person`) | Sedang |
| 5 | Viewer membaca `GET /api/cameras` (`source_uri`) dan `GET /api/settings/email` | Bocor alamat internal / kredensial RTSP / penerima HR | Sedang |
| 6 | `/docs`, `/redoc`, `/openapi.json` publik lewat nginx | Peta API terbuka | Rendah |
| 7 | `require_api_key` tidak dipakai rute mana pun, tetapi nginx menyuntikkan `X-API-Key` | Kontrol palsu | Rendah |
| 8 | Login melewati PBKDF2 bila username tidak ada | Enumerasi username lewat waktu | Rendah |

### 2.3 Yang sudah benar (jangan diulang)

SQL berparameter; nama kolom dinamis dari daftar tetap. Ekspor `.xlsx` di-escape sebagai teks.
Penggantian sumber kamera lewat allowlist. Scoping viewer konsisten (absensi, pelanggaran,
notifikasi, laporan, stream). PBKDF2 310.000 iterasi; token sesi disimpan sebagai hash.
Container backend non-root, port hanya localhost. Tanpa `v-html`.

## 3. Uji ketahanan [terukur]

Skrip uji ada di luar repo; akan menjadi tes permanen di Paket C.

**Kanal engine** (engine mock, 127.0.0.1):

| Uji | Hasil |
|---|---|
| 10 jenis pesan cacat (bukan JSON, tipe salah, `set_cameras`/`set_tuning`/`enroll`/`ack`/`forget_person` rusak, byte acak, JSON bersarang 5.000 tingkat) | Engine tetap hidup |
| JSON bukan objek, `type` berupa objek, UTF-8 tidak sah | Hidup, tetapi 4 traceback tak tertangani: thread pembaca mati, koneksi putus |
| Satu baris 300 MB tanpa newline | RSS 37 → 341 MB; **tidak ada batas baris setelah handshake** |
| 200 koneksi diam tanpa `hello` | Klien sah tetap dilayani seketika |

Backend membaca dari engine dengan `readline()` tanpa batas juga [kode, belum diuji].

**Backend** (78 rute, DB sementara): tanpa login semua ditolak kecuali `login`,
`/api/settings/display`, `/` (disengaja); viewer tidak bisa mengubah apa pun; body/parameter
cacat dan percobaan injeksi SQL → **nol** respons 5xx.

> Koreksi (Paket C): sapuan skrip untuk klaim "nol 5xx" sebagian hampa karena sesi admin tercabut di
> tengah jalan. Tes permanen menemukan satu kasus (tanggal cacat di `/api/reports/daily/send` → 502), sudah diperbaiki.

## 4. Availability dan optimisasi engine

**Sudah kuat** [kode]: supervisor per kamera dengan backoff; worker rekognisi/ReID menelan galat
per pekerjaan dan dilaporkan di `engine.health` bila mati; galat GPU fatal → keluar kode 3; outbox
durabel dengan replay. Insiden 11 Nov membuktikan engine bertahan tanpa sumber >30 menit.

**Celah:**

- Engine **macet** (bukan keluar) tidak dinyalakan ulang di server: berkas detak hanya diawasi
  `engine-watchdog.ps1` (Windows); di repo tidak ada definisi container engine maupun
  healthcheck-nya. Cara engine dijalankan di server 5090 belum dikonfirmasi.
- Satu proses untuk semua kamera: galat GPU fatal menjatuhkan kelimanya sekaligus.
- P7 (outbox `commit` sinkron di thread kamera) masih terbuka; relevan bila disk server HDD.

**Biaya ReID tumbuh sepanjang hari** [terukur, data sintetis 60 orang, 5 kamera]:

| Track tersimpan hari itu | Satu pengamatan berwajah |
|---|---|
| 200 | 10 ms |
| 800 | 38 ms |
| 3.200 | 101 ms (puncak 151 ms) |

Pengamatan tanpa wajah tetap < 0,2 ms. Berjalan di bawah kunci koordinator yang juga dipakai
thread kamera (`reid_tap.py`).

> Koreksi (Paket D, 11 Nov): dugaan awal "memindai semua track untuk setiap kelompok" keliru.
> Profil menunjukkan penyebabnya `_sweep_groups` menilai SETIAP kelompok ANON terhadap SETIAP
> orang di galeri tiap wajah terlihat, dan ±80% waktunya habis di `np.stack` dalam
> `PrototypeSet.matrix()`. Perbaikan: matriks disimpan, dan kelompok di bawah ambang terhadap
> orang itu dilewati. Sesudah perbaikan [terukur, simulasi yang sama]: 3.200 track → 1,0 ms;
> 6.000 track → 2,2 ms. Keputusan identik dengan sebelumnya (sidik jari 3.600 pengamatan sama,
> dengan dan tanpa `reevaluate`). Usul "hitung rentang sekali di luar loop" DITOLAK: ternyata
> mengubah keputusan (kelompok yang selesai di sapuan yang sama harus ikut diperiksa).

**P9 (D-FINE ke ONNX) ditunda.** Log pilot: detector 10 ms/gambar, sibuk 0% (1 kamera, 5090).
Kerangka pipeline 0,1 ms/frame [terukur, mock]. Putuskan P9/NVDEC/TensorRT dari angka `sibuk %`
dengan lima kamera menyala.

## 5. Akurasi identitas

Identitas hanya berasal dari wajah; ReID menyebarkannya. Akurasi = seberapa sering wajah layak
didapat × seberapa bersih crop badan.

**Prasyarat semua butir: set crop berlabel dari kelima kamera lokasi** (`eval_reid.py`). Ukur
dua kesalahan terpisah: *salah gabung* (waktu A dibebankan ke B, lebih mahal) dan *terpecah*
(satu orang jadi beberapa ANON). Model card ReID sendiri menulis angka lokasi "belum ada".

### 5.1 Murah, tanpa model baru

1. Isi tabel waktu tempuh (lihat SERAH-TERIMA), lalu kalibrasi ambang pada skor himpunan.
2. Piksel wajah: engine memakai substream `cam01b`; gerbang `min_face_px: 40`. Periksa
   resolusinya; bila kecil, pakai stream utama (GPU menganggur). Matikan *smart codec* di kamera.
3. Enrollment dari CCTV lewat `enroll_from_track`, bukan foto ponsel.
4. Gerbang crop badan: tolak kotak yang bertumpuk dengan kotak lain (`identity/reid/quality.py`
   hanya memeriksa tinggi, rasio, tepi). Embedding rata-rata dengan cerminan horizontal;
   putuskan dari beberapa crop terbaik per track.
5. `tracker.track_buffer_seconds: 1.0` → uji 2–3 dtk (lebih sedikit track pecah, risiko tertukar
   saat ramai).

### 5.2 Perubahan pipeline (jalur EA, struktural)

1. Putuskan per tracklet dan tunda keputusan; interval sudah mulai sejak track lahir dan
   `identity.resolved` sudah ada.
2. **Penyelesaian ulang akhir hari** (sebelum purge): kelompokkan ulang semua tracklet ANON
   sekaligus dengan cannot-link, waktu tempuh, jangkar wajah. Pilihan utama bila hanya satu.
3. Poligon abaikan per kamera (cermin, TV, poster) + saring track yang tidak pernah bergerak.
4. Naikkan laju analisis sesaat saat orang masuk zona pintu (kebalikan `idle_fps`).
5. Dua stream per kamera (deteksi di substream, crop wajah dari stream utama), hanya bila stream
   utama terbukti terlalu berat.
6. Topologi sebagai skor (fusi wajah + tubuh + ruang-waktu), terakhir.
7. Keputusan HR di antrean review sebagai label kalibrasi dan daftar pasangan "berbeda".

### 5.3 Model pembantu

- **Pose** (mis. RTMPose, ONNX, lisensi permisif): gerbang oklusi, arah tubuh untuk prototipe
  sebanding, posisi kepala, deteksi dua orang dalam satu kotak.
- **Penilai kualitas wajah**: menyaring wajah buram/gelap yang lolos gerbang geometris.
- **Tracker berbasis penampilan** (keluarga BoT-SORT/Deep OC-SORT) memakai embedding OSNet yang
  sudah dihitung; wilayah bersama EA–EB.
- **Tidak disarankan:** super-resolusi wajah (mengarang detail), gait, model atribut,
  segmentasi orang.

### 5.4 Lapangan

Sudut kamera, cahaya/WDR, kecepatan rana (wajah buram), bitrate tetap, lensa bersih. NTP di
semua kamera dan mesin (cannot-link dan waktu tempuh bergantung pada jam). Ambang per kamera.
Ambang wajah harus menolak non-karyawan (tamu, kurir), bukan memaksakan kecocokan terdekat.
Cek apakah karyawan klien berseragam (embedding tubuh lemah → bobot ke wajah dan topologi).
Rekaman emas berlabel (di luar repo) diputar ulang lewat `runtime_uji.py` setiap ambang,
model, atau tracker berubah.

### 5.5 Inframerah dan kondisi gambar

Mode IR: deteksi/tracking hampir tidak terpengaruh; **ReID tubuh rusak** (warna hilang, kain
gelap bisa tampak terang, galeri siang tidak sebanding); wajah menurun. Engine saat ini tidak
mengenali frame IR [kode]. Curigai kamera luar menjelang malam dan ruangan redup yang
bolak-balik mode di jam kerja.

Urutan: (1) periksa rekaman jam kerja; (2) kunci mode warna / naikkan ambang perpindahan /
*smart IR* di kamera; (3) bila tidak terhindarkan, engine diberi tahu.

**Pemantau kondisi gambar** (usulan, tanpa AI, ±1×/dtk pada frame diperkecil, saklar default
mati, ambang dikalibrasi dari rekaman dan bisa diubah dari tab Kalibrasi):

| Kondisi | Ukuran | Tindakan |
|---|---|---|
| Mode IR | selisih antar kanal ≈ 0, dengan histeresis | embedding tubuh tidak dibandingkan lintas mode |
| Terlalu gelap | rata-rata kecerahan rendah | crop tidak di-embed |
| Buram / lensa tertutup | ketajaman tepi sangat rendah | dilaporkan; rekognisi ditahan |
| Gambar beku | frame berturut-turut identik | dilaporkan |

Dilaporkan lewat `camera.degraded` (sudah ada, alasan teks bebas, tanpa perubahan kontrak).
Pemisahan galeri ReID per mode adalah perubahan logika jalur EA. **Auto adjust** kecerahan untuk
embedding: tidak (menambah derau, menggeser distribusi, merusak ambang); penyesuaian dilakukan di
kamera. Penyesuaian kontras ringan hanya untuk detektor: mungkin, setelah dibuktikan pada
rekaman gelap, di belakang saklar.

## 6. Dashboard debug admin

**Masalah sebenarnya:** log engine mencetak total kumulatif berulang; engine beku dan engine
sepi menghasilkan baris identik. Data diagnosis sudah ada tetapi tidak dibaca: `engine.health`
(status per kamera, `effective_fps`, `lag_seconds`, `frames_dropped_stale`, antrean, outbox,
disk, `reid_tolak_*`) dan `camera.failed` (dengan `reason`) tersimpan di `protocol_events`,
tanpa endpoint maupun tampilan.

### Fase 1 — tanpa perubahan kontrak (BE + FE)

- Endpoint admin `GET /api/system/health` dari `protocol_events` (`get_protocol_events`).
- Tab Kesehatan: status per kamera, umur frame terakhir, alasan gagal terakhir, fps/lag sebagai
  grafik kecil, penghitung sebagai **laju per menit**, bukan total.
- Log backend (ring buffer) + galat frontend (`window.onerror`, kegagalan WHEP/fetch) dalam satu
  tampilan.
- Tombol Mulai/Hentikan rekaman sesi atas data yang sudah diterima backend; ekspor CSV berformat
  `summarize_gladi.py`.
- Opsional: backend menanyakan `/v3/paths/list` kedua MediaMTX.
- Penjagaan: admin + env `DEBUG_PANEL_ENABLED` (default mati; mati = rute tidak terdaftar).

Tetap skrip (tidak dari dashboard): `lag_probe.py` dan `runtime_uji.py` (menggantikan backend /
menyalakan engine sendiri), `face_bench.py` dan `detector_profile.py` (merebut GPU produksi).

### Fase 2 — kontrak debug (perubahan kontrak, perlu persetujuan)

Isi: log WARNING engine diteruskan; penampil crop ANON (fondasi: cache crop `enroll_from_track`).

Bentuk kontrak debug yang diusulkan:

1. Pesan berawalan `debug.*` di kanal `debug`: tidak durabel, tidak masuk outbox, tanpa ACK/replay.
2. Skema terpisah `contracts/schema/debug.schema.json`; tes menjaga `debug.*` tidak pernah ada di
   kanal `events` maupun fixture.
3. Kemampuan dinegosiasikan saat `hello` (versi campuran engine/backend tetap aman).
4. Default mati di kedua sisi (config engine + env backend).
5. Tes "tanggal kedaluwarsa" yang gagal setelah akhir pilot: hapus atau angkat jadi kontrak resmi.

Penjagaan crop (data biometrik): env plafon + izin per orang `can_debug` + konfirmasi ulang
dengan password sendiri → sesi debug 30 menit yang mati sendiri + alasan wajib + audit per crop
di `settings_audit`. Crop diminta sesuai permintaan, tidak ditulis ke disk backend. **Bukan**
kode debug bersama (tidak bisa diatribusikan, tidak bisa dicabut per orang).

## 7. Urutan kerja yang diusulkan

| # | Paket | Isi | Kontrak |
|---|---|---|---|
| 0 | (tanpa kode) | Konfirmasi hop insiden 1; `curl` MediaMTX §2.1; ukur 5 kamera (`sibuk %`, lag) + isi tabel waktu tempuh | — |
| A | EA | **Selesai 11 Nov** (ea-r26 + be-r9): batas baris kedua sisi; pesan bukan objek → ack ditolak. Belum: (keputusan) engine menolak start tanpa kunci di alamat non-loopback | tidak |
| B | BE | **Selesai 11 Nov** (be-r10): temuan 1, 2, 5, 6, 7 | tidak |
| C | QA | **Selesai 11 Nov** (be-r11): matriks akses semua rute + fuzz kanal sebagai tes CI permanen | tidak |
| D | EA | **Selesai 11 Nov** (ea-r27): biaya `_sweep_groups` + tes biaya tidak tumbuh | tidak |
| E | EA/deploy | **Skrip selesai 11 Nov** (`deploy/engine/run-with-watchdog.sh`); BELUM dipasang: compose engine server 5090 tidak ada di repo | tidak |
| F | BE+FE | Fase 1 dashboard debug | tidak |
| G | EA | Pemantau kondisi gambar | tidak |
| H | EA+BE+FE | Fase 2 dashboard debug | **ya** |

Akurasi berjalan paralel dan dibuka oleh satu langkah: **set crop berlabel**. Ditunda: P9,
NVDEC, TensorRT, P7 (tunggu jenis disk), enkripsi referensi wajah, token keluar dari
`localStorage`, CSP.

## 7a. Uji penerimaan klien (ditambahkan 11 Nov, dikerjakan sebelum paket A)

Test case klien (MON-01..10, JAT-01..15) dicocokkan dengan kode [kode]. Paket be-r8 + fe-r5 menutup yang gagal
karena fitur belum ada: JAT-02, JAT-05, JAT-07, JAT-12, JAT-14 (CHANGELOG 11 Nov).

Yang tersisa, bukan kode:

- **MON-04:** `boxes.maxAgeMs` default `null`; isi lewat tab Kalibrasi sebelum uji. Simulasi tertinggal:
  `docker pause` engine.
- **MON-07 kacamata:** pantulan yang menutup kedua mata adalah batas pengenalan wajah. Usul ekspektasi baru:
  "tidak salah mengenali dan berstatus tidak dikenal". Kurangi kasusnya dengan enrollment berkacamata.
- **MON-07 IR:** enrollment referensi mode malam (`enroll_from_track` saat IR aktif); lihat §5.5.
- **MON-02/03/09 berpapasan:** batas tracker geometris (§5.3).
- **MON-01, MON-10:** bergantung infrastruktur (insiden §1; lima kamera belum pernah dijalankan bersama).
- **JAT-04:** 20 detik pertama tiap kunjungan selalu gratis, jadi kunjungan 25 dtk ditagih 5 dtk. Sepakati tafsirnya.
- **JAT-10** [penalaran]: `visit_id` = segmen pertama; atribusi mundur yang menambah segmen lebih awal mengubah
  ID kunjungan, dan koreksi pengecualian bisa terlepas. Belum diuji.
- **Konsekuensi produk:** waktu ANON tidak pernah ditagih, jadi karyawan yang wajahnya tidak dikenali (kacamata,
  menunduk) tidak pernah memakai jatah. Klien perlu tahu.

## 8. Keputusan terbuka (Zena)

- Engine menolak start tanpa `ENGINE_SHARED_KEY` di alamat non-loopback (mengubah default).
- Autentikasi MediaMTX (dua mesin + URL engine), setelah hasil `curl` §2.1.
- Persetujuan kontrak debug §6 Fase 2 dan siapa yang boleh `can_debug`.
- Engine di stream utama vs substream, setelah resolusi `cam01b` diketahui.

## 9. Data lapangan yang dibutuhkan

Resolusi dan pengaturan codec `cam01a`/`cam01b`; frame IR pada jam kerja per kamera; waktu
tempuh antar lokasi; `sibuk %`/lag dengan lima kamera; jenis disk server; selisih jam kamera dan
mesin; apakah karyawan berseragam; cara engine dijalankan di server 5090.
