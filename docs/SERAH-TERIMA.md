# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 17 Oktober 2026, sesi EA + EB (paket ea-r14). `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk langkah uji ReID. Angka: CHANGELOG ea-r9 s.d. ea-r14.

## Lingkup

- Prototype = demo klien (gambaran yang jalan). **ReID wajib tampil di demo.** M4 (6 Nov) / M5 (20 Nov) tetap gerbang pra-pilot (dok. 12 §2, dok. 14).
- RTX 4060 tidak bisa dipakai sampai Senin 19 Okt; akhir pekan pakai laptop 1060 hanya untuk uji fungsi/diagnosis, bukan angka performa 5 kamera.

## Selesai

- ea-r12 (scheduler per kamera) lulus pytest di laptop. ea-r13: query val kit latih diperbaiki. ea-r14: lihat CHANGELOG.
- Model ReID: `X:\data\runs\ain_cepat` (5 epoch, val mAP 0,98 sintetis; ±1.000 dtk/epoch). Run 25 epoch BELUM dijalankan.
- Uji pipa ReID (EA-R3 1–6) di 4060: pipa hidup, cannot-link 0 pelanggaran; dua masalah di bawah.

## Belum (urut untuk demo ReID)

1. **OSNet lambat di onnxruntime** (±9,5 dtk batch >= 4, PyTorch ±32 ms). Jalankan `tools/reid_train/diag_reid_profile.py` (1060 akhir pekan bila ONNX bisa disalin, atau 4060 Senin). Bila InstanceNormalization: `ganti_instancenorm.py` di reid-env, lalu ukur ulang `diag_reid_ort.py`. Bila bukan: backend embedder TorchScript (paket baru, di belakang flag).
2. Uji ulang validator setelah ea-r14: matikan/nyalakan publish satu stream di tengah run; `stream_epoch` harus naik, 0 GAGAL.
3. Latih 25 epoch (`--epochs 25 --workers 8`, ±7 jam) di 4060; cek `nvidia-smi` utilisasi GPU.
4. BE: handler `identity.resolved` + ANON tidak dihitung/memicu pelanggaran sebelum resolved (EA-K1 §2) — wajib sebelum ReID disambung ke backend. Login endpoint baca sebelum demo publik.
5. Rekaman skenario demo ReID (wajah di kamera A -> membelakangi di kamera B, jeda > 30 dtk atau turunkan `default_travel_time_seconds`); sekalian bahan `eval_reid.py` + ambang sementara.
6. ea-r15 (tidak menghalangi ReID): giliran frame pertama track baru terbuang; backoff bertingkat track tak dikenal.
7. Curiga: SCRFD/glintr100 (47–54 ms/wajah) mungkin juga lambat karena onnxruntime; profil dengan `diag_reid_profile.py <onnx wajah>` setelah #1.
8. EB: korektor offset P18 kebablasan setelah diskontinuitas stream.

## Keputusan yang perlu disetujui

- ea-r14 mengubah `factory.build_engine/build_source` dan `PyAVSource` (jalur EB): argumen opsional `stream_epoch_base`, default 0.
- Engine menolak start bila CUDA diminta tetapi onnxruntime CPU (sebelumnya diam-diam CPU).

## Uji manual di laptop

Akhir pekan (1060): ikuti `docs/UJI-REID-1060.md` dari awal (termasuk bila ONNX tidak bisa disalin). Senin (4060):

1. `python -m pytest engine/tests contracts/tests -q`; di reid-env: `python -m pytest tools/reid_train/tests -q`.
2. `python scripts/check_gpu_env.py`: baris `nvrtc` OK (tambahkan folder CUDA v12.6\bin ke PATH bila PERINGATAN).
3. Diagnosis OSNet (#1), lalu uji pipa ReID 5 menit + validator (#2). Engine selalu dari jendela `vision-engine`, latihan dari jendela `reid-env`.

## Langkah berikutnya

Profil OSNet -> perbaiki jalur embedding -> uji pipa ReID + validator -> latih 25 epoch -> rekam skenario -> BE handler -> demo.
