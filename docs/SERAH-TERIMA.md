# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 15 Oktober 2026, sesi EA + EB (paket ea-r9). `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk ReID/`schedule_off`/watchdog. Angka uji minggu ini: CHANGELOG ea-r9.

## Selesai

- Vonis uji 4060: 6 fps × 5 kamera **LULUS** (p99 0,22 dtk); crash GPU → kode 3 → watchdog hidup ulang **lulus**; batch D-FINE **gugur**; P18 **bukan bug jam** (antrean pembaca saat jenuh); NVDEC **tunda** (decode ±10% CPU); hambatan berikutnya **rekognisi wajah** (jenuh ±18 wajah/dtk, 35% dibuang).
- ea-r9: gerbang kualitas sebelum embedding (`recognition.embed_*`, default mati); `backoff_interval_seconds`/`attempts_before_backoff` dari config; WARNING worker rekognisi jenuh; start ditolak untuk input SCRFD yang tidak cocok dengan model; kode keluar 2 untuk config salah dan watchdog menunggu config diubah; `batch_check` membandingkan dengan ukuran 1 dan keluarannya ASCII.
- Tes cloud: engine 680 lulus / 9 dilewati; kontrak 151; `policy_grep` bersih.

## Belum (diurutkan)

1. **Kalibrasi gerbang rekognisi** (uji manual #1). Tanpa itu stress test 100 orang (dok. 12 §2.2) kemungkinan gagal.
2. Batch embedding glintr100 / SCRFD beberapa crop sekaligus; glintr100 lewat onnxruntime TensorRT EP FP16 (calon TensorRT yang lebih berguna daripada D-FINE).
3. SCRFD berdimensi dinamis (ekspor ulang) bila ingin input < 640; ukur ulang ms/wajah dan recall.
4. MSDA: peringatan "No accelerated MSDA provider" muncul di runtime. Coba `libreyolo[hub-kernels]` di env kloningan; prioritas rendah (detector 50% sibuk).
5. `swscale_resize: true` setelah `scaling_check` (±70% waktu thread kamera = konversi warna).
6. Traceback asli uji crash ea-r8 belum dicatat (dari `logs\engine\engine-20261015-212945.err.log`).
7. Kolom `drop/s` `summarize_gladi` = `frames_replaced`; ganti nama/beri catatan.
8. Backend: ReID dihitung salah diam-diam (SERAH-TERIMA-EA-R3 #2); endpoint baca + video belum butuh login.

## Keputusan yang perlu disetujui

- Penjadwal tahap 2: batch gugur → tetap `free` (atau tick tanpa batch). Rapat EA–EB.
- Nilai gerbang rekognisi untuk profil demo/pilot, dari uji manual #1.
- Start ditolak untuk `face_detector_input_size` yang tidak cocok dengan model berbentuk tetap (tidak ada tombol mati).

## Uji manual di laptop

1. **Gerbang rekognisi.** Salin `demo-4060.yaml` ke profil lokal, buka komentar blok ea-r9 (embed_* + backoff), gladi 6 fps 15 menit seperti 15 Okt (watchdog `-HealthSeconds 2 -TargetFps 6`, `ENGINE_OUTBOX_PATH` uji, `lag_probe` 5 kamera). Bandingkan dengan run 640 tanpa gerbang (16 wajah/dtk, 54 ms, 35% dibuang): `rekognisi: diproses/ditolak-penuh/basi/rata2`, `gerbang embedding: ...`, `detector bersama ... ms/gambar`, dan apakah `EMP123` tetap dikenali di kelima kamera (event `track.identified` di CSV/log). Gerbang yang membuat orang terdaftar tak dikenali = terlalu ketat.
2. **Kode keluar 2.** Profil lokal dengan kunci salah (mis. `core: {kunci_tidak_ada: 1}`) lewat watchdog: log `config engine salah ... (kode 2)`, tidak ada hidup ulang; perbaiki berkasnya → `berubah; mencoba lagi`.
3. **Input SCRFD.** Profil lokal `face_detector_input_size: 480`: engine menolak start dengan pesan "model ini berbentuk tetap", kode keluar 2, watchdog menunggu config diubah. Kembalikan 640.

## Langkah berikutnya

Uji manual #1 → pilih nilai gerbang → stress test bertahap (video berorang banyak, mis. MOT20) sebelum M4 (6 Nov). Rapat EA–EB: penjadwal tetap `free`, prioritas EB pindah ke rekognisi.
