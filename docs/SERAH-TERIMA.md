# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 16 Oktober 2026, sesi EA + EB (paket ea-r12). `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk ReID/`schedule_off`/watchdog. Angka uji: CHANGELOG ea-r9, ea-r10, ea-r12.

## Selesai

- ea-r12: bug scheduler rekognisi lintas kamera diperbaiki (kamera mengambil giliran track kamera lain lalu membuangnya + umur dari PTS antarkamera). Simulasi: 74 -> 200 percobaan nyata per 30 dtk (5 kamera x 4 track), 0 giliran nyasar. Log WARNING baru bila giliran nyasar muncul lagi.
- Angka "waktu sampai dikenali" ea-r9/ea-r10 dan vonis gerbang ea-r10 TERCEMAR bug ini; biaya 54 ms/wajah dan "ditolak-penuh" worker tetap berlaku.
- ea-r11 (TensorRT EP, `face_bench`, `scrfd_dynamic`, `setup-env-trt.ps1`) masih BELUM diukur.
- Lisensi bobot AuraFace (SCRFD + glintr100): diverifikasi pengguna Apache-2.0.

## Belum (diurutkan)

1. **pytest penuh di laptop** untuk ea-r12 (cloud sesi ini tanpa PyPI; tes dijalankan lewat runner pengganti).
2. Gladi baseline ULANG dengan ea-r12 sebelum menyentuh TensorRT (uji manual #1).
3. Ukur ea-r11 di 4060 (uji manual #2-#4), lalu bandingkan dengan baseline baru.
4. Bukti dari sesi lain (belum diperiksa di repo): input SCRFD AuraFace ternyata dinamis, hanya deklarasi keluaran terkunci 640 -> `_check_static_size` mungkin terlalu ketat; repo tidak memakai `SessionOptions` (log ORT `VerifyOutputSizes` bisa membanjiri konsol). Wajah terbesar di potongan kepala dipilih (risiko wajah orang lain di ruang ramai).
5. Batching glintr100 dari antrean worker (keluaran dideklarasikan [1,512] tapi batch jalan di CPU).
6. Stress test bertahap (mis. MOT20) sebelum M4 (6 Nov).
7. Backend: ReID dihitung salah diam-diam (EA-R3 #2); endpoint baca + video belum butuh login (semua 200 tanpa token).
8. Kecil: MSDA hub-kernels, `swscale_resize`, traceback crash ea-r8, kolom `drop/s` `summarize_gladi`, README menyebut Python 3.11/3.12 (3.13 lulus).

## Keputusan yang perlu disetujui

- ea-r12 tanpa flag (memperbaiki bug, perilaku lama tidak berguna). Setuju EA-EB.
- Interval retry/backoff/reverify tetap PTS per track; hanya umur/urutan antrean yang pindah ke jam bersama.
- Gerbang rekognisi tidak dipakai di profil; dinilai ulang setelah gladi ea-r12 karena vonisnya tercemar.
- Patokan setiap perubahan rekognisi: median waktu sampai dikenali tidak naik (dok. 12 §2.2: <= 5 dtk).

## Uji manual di laptop

1. Baseline ea-r12: gladi 5 menit `demo-4060.yaml` di env `vision-engine` (watchdog `-HealthSeconds 2 -TargetFps 6`, `lag_probe` ke CSV baru). Catat `rata2 ms`, porsi buang, `identifikasi: ... median`, dan pastikan TIDAK ada WARNING "giliran untuk track yang tidak dikenal". "ditolak-penuh" boleh naik (lebih banyak percobaan nyata).
2. Env TRT: `powershell -ExecutionPolicy Bypass -File scripts\setup-env-trt.ps1` (harap `tensorrt` dan `tensorrt-sesi` OK).
3. `python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --source <video> --varian cuda,trt16 --simpan-potongan bench-out\potongan --json bench-out\face-bench-trt.json`. Bandingkan ms `cuda` (berdiri sendiri) dengan `rata2 ms` gladi: selisih besar = kontensi GPU, bukan biaya model.
4. `scrfd_dynamic` lalu face_bench `--ukuran 640,320,160 --potongan bench-out\potongan --model-detektor <dinamis>`.
5. Bila #3 bagus: config dengan `onnx_tensorrt: true`, gladi seperti #1 di env TRT, bandingkan.

## Langkah berikutnya

pytest di laptop -> gladi baseline ea-r12 -> face_bench (isolasi vs gladi) -> putuskan TensorRT/ukuran SCRFD -> stress test.
