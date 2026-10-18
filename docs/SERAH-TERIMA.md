# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 18 Oktober 2026, sesi EB (paket eb-r12, ReID bucket). Status be-r1/eb-r11/ea-r14 dipertahankan. `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk langkah uji ReID.

## Lingkup

- Prototype = demo klien. **ReID wajib tampil di demo.** M4 (6 Nov) / M5 (20 Nov) tetap gerbang pra-pilot (dok. 12 §2, dok. 14).

## Selesai

- **eb-r12:** `ReidBucketRunner` (satu session ORT per `reid.batch_buckets` [1,2,4,8], warmup per shape sendiri, padding nol, HEURISTIC) menggantikan session tunggal; API embedder tetap. Log start: provider per bucket, torch di `sys.modules`, NVRTC (Windows). fd 2 -> `logs/engine/engine-c-stderr.log` bila ReID+CUDA (`--no-stderr-redirect`). Config -> `osnet_ain_reid.onnx`. Engine+kontrak 901 -> 925 lulus (CPU). Menutup "Belum" #1 lama (stall ganti shape), menunggu ukur di laptop.
- be-r1 (ANON tidak dihitung, `identity.resolved` -> `reid_retro`), eb-r11 (`core.idle_fps`, profil hemat BELUM diukur), ea-r12..r14. Rincian di CHANGELOG.

## Belum (urut untuk demo ReID)

1. **torch ada di proses engine** (audit eb-r12): detector D-FINE = LibreYOLO (PyTorch), `engine/perception/dfine_detector.py:195` (`from libreyolo import LibreYOLO`) + `import torch` baris 179/227/247/336/349/610, satu proses dengan worker ReID. Bucket menghindari ganti shape per session, jadi stall NVRTC mestinya ikut hilang, tetapi harus diukur. Opsi bila tetap stall (perlu keputusan EA/EB): (a) worker ReID di subprocess tanpa torch; (b) D-FINE ke ONNX/TensorRT (engine bebas torch); (c) urutan muat DLL: cuDNN pip (`preload_dlls`) sebelum torch, torch\lib tidak di jalur DLL ORT.
2. Model ReID: salin ONNX fine-tune ENTIRe-ID ke `engine/models/reid/osnet_ain_reid.onnx`, isi `reid.model_sha256` (semua profil masih null); verifikasi split + lisensi ENTIRe-ID; `eval_reid.py` di crop 5 kamera -> `match_threshold` (salah gabung <= 1%), lengkapi kartu model.
3. Uji ulang validator setelah ea-r14 (matikan/nyalakan publish satu stream; `stream_epoch` naik, 0 GAGAL).
4. Rekaman skenario demo ReID (wajah kamera A -> membelakangi kamera B) + `eval_reid.py`.
5. Uji ujung ke ujung engine ReID -> backend nyata (`identity.resolved` mengubah pemakaian di dashboard).
6. Ukur eb-r11 di laptop; bila SCRFD 320 kurang: batch embedding glintr100 (B2).
7. ea-r15: frame pertama track baru terbuang; backoff track tak dikenal. EB: korektor offset P18 kebablasan.

## Di luar lingkup, ditemukan di jalan (belum dikerjakan)

- `/api/auth/login` tanpa rate limit dan `AUTH_COOKIE_SECURE` default `false` (sebelum demo publik).
- `schemas/enrollment.py` / `set_roster` belum menolak `ANON-`; `report_service` memuat baris ANON (kosmetik).
- `onnx` tidak ada di `requirements-dev.txt` (hanya `tools/reid_train/requirements-train.txt`); tes ONNX sintetis engine dilewati tanpanya.
- Pesan galat `_session` ("lihat pesan [E:onnxruntime] di atas") kini harus dicari di `engine-c-stderr.log` saat ReID+CUDA.

## Keputusan yang perlu disetujui

- eb-r12 mengubah default `reid.model_path` ke `osnet_ain_reid.onnx` dan mengalihkan fd 2 otomatis saat ReID+CUDA (atas permintaan tugas). Kontrak tidak berubah.
- Sebelumnya: be-r1 dari `claude/funny-thompson-nt4y1d`; eb-r11 ditumpuk di atas be-r1; `idle_fps` perlu persetujuan EA sebelum pilot; ea-r14 menolak start bila CUDA diminta tetapi ORT CPU.

## Uji manual di laptop (eb-r12, env engine TANPA torch untuk langkah 1)

1. `python tools/reid_train/diag_reid_bucket.py engine\models\reid\osnet_ain_reid.onnx` -> bucket median ±28 ms, 0 frame >100 ms, selisih <= 1e-4.
2. `python -m pytest engine/tests/test_reid_bucket.py -q` (uji GPU model asli harus jalan, bukan dilewati).
3. Start engine profil demo dengan `reid.enabled: true`: log harus menunjukkan `bucket 1/2/4/8: provider aktif ['CUDAExecutionProvider', ...]`, `torch tidak ada` (ATAU WARNING torch ADA, lihat Belum #1), `NVRTC tidak termuat`; spam nvrtc hanya di `logs/engine/engine-c-stderr.log`, traceback tetap di konsol/err.log.
4. Gladi 5 kamera dengan ReID: latensi worker ReID per batch (tidak ada lonjakan detik-an), VRAM 4 session x `onnx_gpu_mem_limit_mb`.

Lainnya tetap: eb-r11 (scrfd_dynamic, face_bench, gladi hemat), `docs/UJI-REID-1060.md`, `python scripts/check_gpu_env.py`.

## Langkah berikutnya

Ukur eb-r12 di laptop -> putuskan Belum #1 bila masih stall -> pasang model ReID final + SHA -> uji pipa ReID + validator + backend nyata -> rekam skenario + kalibrasi -> demo.
