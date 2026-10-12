# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 12 Oktober 2026, sesi EB (baseline 5 kamera, DEMO-REMOTE §8.1). Tidak ada kode yang diubah; hasil juga dicatat di `DEMO-REMOTE.md` §8.1 dan CHANGELOG (paket eb-r1).

## Selesai

- Baseline 5 kamera × 1080p25 di 4060, probe 15 menit per run (`lag_probe` + `summarize_gladi`):
  - T0-6 free 6 fps: **LULUS**. fps 6.00, umur kotak med 0.13 / p99 0.28 dtk, tanpa stall.
  - T1 tick 6 fps (tanpa batch): LULUS tipis. fps 5.95, med 0.30 / p99 0.66 dtk.
  - Free dan tick di target 10 (idk3/idk2): keduanya mentok **7.7 fps/kamera (≈38 frame/dtk)**, vonis GAGAL karena target tidak tercapai.
  - T0 free target 10 sebelumnya mentok di 6.26 fps (≈31 frame/dtk). Kondisi laptop berbeda antar sesi, jadi **plafon 31–38 frame/dtk**.
  - Tick + `batch_inference: true` + `cuda_graph: true`: CUDA crash (lihat Belum). Tanpa cuda_graph: 2.5 fps.
- Kesimpulan: **free + 6 fps** jadi baseline (cadangan ±22%). Tick tahap 1 tidak memberi keuntungan terukur. Batch di 4060 gugur.

## Belum (diurutkan)

1. **Empat file paket ea-r3 tidak pernah di-commit**: `engine/identity/reid/{quality,embedder_onnx}.py`, `engine/pipeline/{reid_worker,reid_tap}.py`. Checkout bersih langsung crash di `load_config` (`schema.py:396` mengimpor `quality` tanpa syarat). Ambil dari zip ea-r3 atau laptop; jangan timpa `schema.py`/`service.py`.
2. `deploy/mediamtx/mediamtx.yml` hanya punya `cam01`, sehingga `publish_test_video.ps1 -Count 5` kena 400 Bad Request. Tambah path cam02–cam05 (`source: publisher`).
3. **EB1 belum tuntas**: profil CPU per tahap + `py-spy` (dok. 14) belum ada. Ini input vonis spike NVDEC (EB2).
4. Bug: kombinasi batch + cuda_graph membuat `illegal memory access`. Fallback per gambar di `dfine_detector.py:440` ikut gagal karena konteks CUDA sudah mati. Kamera reconnect di proses yang sama tak pernah pulih. Usulan: tolak kombinasi saat validasi config, atau pad batch ke ukuran tetap; error CUDA fatal = proses keluar supaya watchdog me-restart.
5. Dugaan bug jam (P18): satu kamera per run punya umur kotak konstan +0.4 dtk (cam05 di T1, cam04 di idk3), sebarannya sempit, jadi lebih mirip offset tetap daripada antrean. Cek median `drift_s` per kamera di `bench-out/ab-idk3.csv`. Jalur EA.
6. Log usang `factory.py:242` ("No consumer is attached … does not recognise anything"). Consumer dipasang di `camera.py:415`, jadi teks log ini menyesatkan.
7. Kolom `drop/s` di `summarize_gladi` = `frames_replaced` (slot tertimpa sebelum diambil), bukan frame hilang. Nilainya tidak bisa dibandingkan antar mode; ganti nama atau beri catatan.

## Keputusan yang perlu disetujui

- 5 kamera di 4060: `core.target_fps` profil demo-4060 diturunkan ke 6, atau tetap 10 + `-TargetFps 6`? Mengubah default harus eksplisit.
- **Desain penjadwal tahap 2 (19–23 Okt) bertumpu pada "1 batch D-FINE per detak"**, padahal batch tidak jalan di 4060. Pilih: pad batch tetap, tunggu perbaikan LibreYOLO, atau inferensi berurutan per detak (≈ free). EA–EB sebelum 19 Okt.
- Plafon yang dijanjikan ke klien: pakai batas bawah (31 frame/dtk), sebelum ReID.

## Uji manual di laptop

1. `py-spy record --pid <engine> --duration 300 --rate 50 --subprocesses --format speedscope -o bench-out/profil-T0-6.json` pada kondisi T0-6, plus `nvidia-smi dmon`. Decode ≥30% CPU = EB2 lanjut; jika tidak, tunda.
2. Ulang T0-6 dengan log tersimpan (`python -m engine.runtime ... 2>&1 | Tee-Object bench-out/T0-6-engine.log`). Pastikan `rekognisi: diproses N` naik; jika ~0, video tidak memicu rekognisi dan uji ulang dengan video berwajah jelas. Pantau juga `ditolak-penuh`/`basi`.
3. Catat kondisi tiap run (charger, mode daya, suhu) di nama CSV.

## Langkah berikutnya

Commit file ea-r3 + mediamtx.yml, lalu profil py-spy (vonis EB2), lalu angkat isu batch/penjadwal ke rapat EA–EB.
Terbuka dari sesi EA (ea-r2): latihan ReID nyata, lisensi bobot torchreid, crop berlabel tim (lihat `SERAH-TERIMA-EA-R3.md`).
