# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 16 Oktober 2026, sesi EA + EB (paket ea-r10). `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk ReID/`schedule_off`/watchdog. Angka uji: CHANGELOG ea-r9 (vonis 14–15 Okt) dan ea-r10 (gerbang).

## Selesai

- Vonis uji 4060: 6 fps × 5 kamera **LULUS**; crash GPU → kode 3 → watchdog hidup ulang **lulus**; batch D-FINE **gugur**; P18 **bukan bug jam**; NVDEC **tunda**; hambatan berikutnya **rekognisi wajah** (54 ms/wajah = SCRFD ±21 + glintr100 ±33; jenuh ±18 wajah/dtk).
- Uji gerbang rekognisi (ea-r9) **gagal sebagai solusi beban**: ukuran 56 = nol orang dikenali; skor 0,6 + samping 0,5 = beban turun (29 ms) tetapi dikenali ±56 dtk (vs 4–6). Gerbang tetap di kode, mati di profil.
- ea-r10: metrik "waktu sampai dikenali" di log engine dan `lag_probe` (kolom `identify_s`, kamera untuk `track.identified`); usulan gerbang lama dihapus dari `demo-4060.yaml`.
- Kode keluar 2 untuk config salah dan input SCRFD yang tidak cocok: diuji di laptop (uji manual ea-r9 #2–#3).
- Tes cloud: engine 686 lulus / 9 dilewati; kontrak 151; `policy_grep` bersih.

## Belum (diurutkan)

1. **Biaya per wajah**: glintr100 lewat onnxruntime TensorRT EP FP16 (33 ms), lalu SCRFD berdimensi dinamis di 320 (21 ms). Ukur dengan `rata2 ms`, porsi buang, DAN baris `identifikasi: ... median`.
2. Stress test bertahap dengan video berorang banyak (mis. MOT20) sebelum M4 (6 Nov).
3. MSDA: "No accelerated MSDA provider" di runtime; coba `libreyolo[hub-kernels]` di env kloningan (prioritas rendah).
4. `swscale_resize: true` setelah `scaling_check`.
5. Traceback asli uji crash ea-r8 belum dicatat.
6. Kolom `drop/s` `summarize_gladi` = `frames_replaced`; ganti nama/beri catatan.
7. Backend: ReID dihitung salah diam-diam (SERAH-TERIMA-EA-R3 #2); endpoint baca + video belum butuh login.
8. Opsional: kalibrasi `embed_max_yaw` saja (0,7, tanpa skor/mundur); cek dulu apakah `yaw_ratio` wajar untuk kamera dari atas (41% wajah dinilai > 0,5).

## Keputusan yang perlu disetujui

- Penjadwal tahap 2: batch gugur → tetap `free`. Rapat EA–EB.
- Gerbang rekognisi tidak dipakai di profil demo/pilot; beban dikejar lewat percepatan model.
- Patokan baru setiap perubahan rekognisi: median waktu sampai dikenali tidak naik (dok. 12 §2.2: ≤ 5 dtk).

## Uji manual di laptop

1. Gladi 5 menit dengan `demo-4060.yaml` asli (watchdog `-HealthSeconds 2 -TargetFps 6`, `ENGINE_OUTBOX_PATH` uji, `lag_probe` 5 kamera ke CSV baru). Harap: ringkasan probe menampilkan `track.identified` dan "waktu sampai dikenali" per kamera; log engine `identifikasi: ... median` ±4–6 dtk. Ini baseline untuk butir Belum #1.

## Langkah berikutnya

Baseline uji manual #1 → spike glintr100 TensorRT EP FP16 (env kloningan; bandingkan embedding vs CUDA EP, ms/wajah, waktu sampai dikenali) → SCRFD dinamis → stress test.
