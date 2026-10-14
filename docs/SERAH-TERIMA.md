# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 14 Oktober 2026, sesi EA + EB (paket ea-r8). `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk ReID/`schedule_off`/watchdog.

## Selesai

- Error GPU fatal (`illegal memory access` dsb.) → kamera `camera.failed reason=gpu_fatal`, model tidak dipanggil lagi, engine berhenti rapi, kode keluar **3** → watchdog menyalakan ulang. Default `core.gpu_fatal_action: "exit"` (lama: `"retry"`).
- Start ditolak untuk `batch_inference` + `cuda_graph` (crash eb-r1); `ENGINE_ALLOW_BATCH_CUDA_GRAPH=1` untuk eksperimen. `batch_check --cuda-graph` tidak terpengaruh.
- Kebocoran 24/7: `attempts_by_uuid`, `_resumed_from`/kandidat sambungan. `retry_in_seconds` = jeda sebenarnya. Log `factory.py` usang diganti.
- Log health "detector bersama ... sibuk N%" + WARNING ≥ 80%.
- `mediamtx.yml` cam02–cam05; peringatan afinitas di `install-engine-task.ps1`; `.sh` LF.
- Afinitas P-core terkonfirmasi sebagai penyebab ayunan/stall 8 Okt (sudah di `start-engine.ps1`).
- Tes cloud: engine 658 lulus / 9 dilewati (sebelumnya 633/9); kontrak 151; `policy_grep` bersih.

## Belum (diurutkan)

1. **Pola error fatal belum dicocokkan dengan traceback asli** 4060. Ambil teks/tipe exception dari log crash tick + batch + `cuda_graph` (12 Okt) atau ulangi 1 menit; bila tidak cocok, tambah pola di `perception/gpu_fatal.py`.
2. Batch berukuran tetap (pad ke jumlah kamera) bila uji manual #2 menunjukkan crash hanya saat ukuran batch berubah. Lalu hapus penjaga `_refuse_known_crash`.
3. EB1: profil `py-spy` + `nvidia-smi dmon` (vonis NVDEC/EB2). `swscale_resize: true` setelah `scaling_check` lulus.
4. P18: cek `drift_s` per kamera (uji manual #3). Positif ±0,4 = backlog decode (EB), bukan jam.
5. Kolom `drop/s` di `summarize_gladi` = `frames_replaced`; ganti nama/beri catatan.
6. Backend: ReID TIDAK gagal validasi, tetapi ANON dihitung sebagai karyawan (koreksi di SERAH-TERIMA-EA-R3 #2). Endpoint baca + video belum butuh login (jalur BE, 19–23 Okt).

## Keputusan yang perlu disetujui

- Default `gpu_fatal_action: "exit"` (perilaku lama = bug). Kode keluar 3 khusus GPU fatal.
- Penjadwal tahap 2 hanya bila batch tetap jalan; bila tidak, tetap `free`. Margin 6 fps × 5 kamera terhadap plafon bawah (31 frame/dtk) hanya ±3%.

## Uji manual di laptop

1. Crash terkendali: `$env:ENGINE_ALLOW_BATCH_CUDA_GRAPH=1`, profil lokal dengan `batch_inference: true` + `cuda_graph: true`, 5 kamera, lewat `engine-watchdog.ps1`. Harap log `error GPU fatal ... kode keluar 3`, watchdog `engine keluar dengan kode 3`, hidup ulang. Kirim traceback-nya (Belum #1). Hapus env sesudahnya.
2. Dua proses terpisah: `python -m engine.tools.batch_check --config engine/config/demo-4060.yaml --source <video> --batch-sizes 5 --cuda-graph`, lalu `--batch-sizes 1,2,5 --cuda-graph`. Pertama lulus + kedua crash = ukuran berubah penyebabnya.
3. `drift_s` per kamera dari `bench-out/ab-idk3.csv` dan `ab-T1.csv` (median per `camera_id`).
4. Gladi T0-6 15 menit: catat baris `detector bersama ... sibuk N%`. `ms/gambar × total frame/dtk ≈ 1000` = dispatcher jenuh.
5. Pasang tugas dengan `-AffinityMask 0xFFFF`; pastikan tidak ada peringatan afinitas.

## Langkah berikutnya

Uji manual 1–2 sebelum rapat EA–EB (penjadwal tahap 2, sebelum 19 Okt), lalu batch tetap atau tetap `free`; py-spy (EB1); BE: auth endpoint baca + penolakan `ANON-` di ledger.
