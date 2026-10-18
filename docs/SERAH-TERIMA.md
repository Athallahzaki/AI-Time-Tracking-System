# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 18 Oktober 2026, sesi EB (paket eb-r12 + eb-r12b, ReID bucket, diuji di 1060). Status be-r1/eb-r11/ea-r14 dipertahankan. `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk langkah uji ReID.

## Lingkup

- Prototype = demo klien. **ReID wajib tampil di demo.** M4 (6 Nov) / M5 (20 Nov) tetap gerbang pra-pilot (dok. 12 §2, dok. 14).

## Selesai

- **eb-r12 (terbukti di 1060):** `ReidBucketRunner` (satu session ORT per `reid.batch_buckets` [1,2,4,8]) + fd 2 -> `logs/engine/engine-c-stderr.log` + config `osnet_ain_reid.onnx`. Uji `demo-1060`, video sama, 5 menit: ReID nyala vs mati fps 7,6 vs 6,7, dikenali 17 vs 17; ReID 18 ms/batch (176 batch, 0 basi/ditolak), 4 bucket CUDA, NVRTC tidak termuat, log C 19 KB; 4 `identity.resolved`, dua memindahkan interval (be-r1 `reid_retro` pertama kali dengan engine nyata); validator 0 pelanggaran. `diag_reid_bucket.py`: 358 -> 29 ms median.
- **Audit torch selesai:** D-FINE (LibreYOLO, `dfine_detector.py:195`) membawa torch ke proses SESUDAH session ReID dibuat; urutan ini terukur aman, opsi subprocess/ONNX-detector tidak diperlukan.
- **eb-r12b:** status torch/NVRTC dicek ulang setelah detector dimuat (baris start lama menyesatkan); `check_gpu_env.py` nvrtc dibalik (di PATH = PERINGATAN); `SETUP-GPU.md`, `UJI-REID-1060.md`: NVRTC JANGAN di PATH. Engine+kontrak 929 lulus.
- be-r1, eb-r11, ea-r12..r14: lihat CHANGELOG.

## Belum (urut untuk demo ReID)

1. **Kalibrasi `match_threshold`** (masih null = usulan 0,80): di uji 1060 cocok galeri 88, dicabut 18 (±20%). `eval_reid.py` di crop berlabel 5 kamera lokasi -> ambang dengan salah gabung <= 1%; isi `reid.model_sha256` (hash 4dc0271f98d1... di laptop) di profil; verifikasi split + lisensi ENTIRe-ID; lengkapi kartu model.
2. **Profil hemat 1060 belum layak demo:** fps 4 + SCRFD 320 -> 1 dari 28 track dikenali (waktu 24,6 dtk). Ukur `face_bench.py` 640 vs 320 dinamis; bila 320 melewatkan wajah, profil hemat butuh SCRFD 640 atau batch embedding glintr100 (B2).
3. Rekaman skenario demo ReID (wajah kamera A -> membelakangi kamera B) + `eval_reid.py`.
4. Uji ujung ke ujung engine ReID -> backend nyata (`identity.resolved` mengubah pemakaian di dashboard).
5. ea-r15: waktu dikenali maks 84 dtk (frame pertama track baru terbuang; backoff track tak dikenal; WARNING "giliran untuk track yang tidak dikenal binding"). EB: korektor offset P18 kebablasan.
6. Uji ulang validator setelah ea-r14 (matikan/nyalakan publish satu stream; `stream_epoch` naik, 0 GAGAL).
7. Gladi 5 kamera dengan ReID: VRAM 4 session x `onnx_gpu_mem_limit_mb`, latensi ReID tetap puluhan ms.

## Di luar lingkup, ditemukan di jalan (belum dikerjakan)

- `/api/auth/login` tanpa rate limit dan `AUTH_COOKIE_SECURE` default `false` (sebelum demo publik).
- `schemas/enrollment.py` / `set_roster` belum menolak `ANON-`; `report_service` memuat baris ANON (kosmetik).
- `onnx` tidak ada di `requirements-dev.txt`; tes ONNX sintetis engine dilewati tanpanya.
- Pesan galat `_session` ("lihat pesan [E:onnxruntime] di atas") kini ada di `engine-c-stderr.log` saat ReID+CUDA.
- `engine-c-stderr.log` satu berkas append tanpa tanggal (tidak ikut dibersihkan `KeepDays` watchdog); ±2-3 MB/hari, prioritas rendah.

## Keputusan yang perlu disetujui

- eb-r12: default `reid.model_path` -> `osnet_ain_reid.onnx`; fd 2 dialihkan otomatis saat ReID+CUDA. eb-r12b: semantik `check_gpu_env.py` nvrtc dibalik. Kontrak tidak berubah.
- Sebelumnya: be-r1 dari `claude/funny-thompson-nt4y1d`; eb-r11 ditumpuk di atas be-r1; `idle_fps` perlu persetujuan EA sebelum pilot.

## Uji manual di laptop (eb-r12b)

1. Jendela tanpa `CUDA\vXX\bin` di PATH: `python scripts/check_gpu_env.py` -> baris `nvrtc` OK.
2. `docs/UJI-REID-1060.md` §4 dengan `demo-1060` + ReID: log memuat `ReID [embedder dimuat]: torch tidak ada` lalu, setelah kamera pertama, `ReID [setelah detector dimuat]: torch ada ... terukur aman`; NVRTC tidak termuat di keduanya.

## Langkah berikutnya

Kalibrasi ambang ReID + SHA di profil -> rekam skenario demo -> uji backend nyata -> putuskan profil 1060 (hemat vs biasa) -> gladi 5 kamera -> demo.
