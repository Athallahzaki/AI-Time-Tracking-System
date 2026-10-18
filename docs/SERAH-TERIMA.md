# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 18 Oktober 2026, sesi BE + EB (paket be-r1, eb-r11). Status EA/EB dari ea-r14 dipertahankan di bawah. `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk langkah uji ReID.

## Lingkup

- Prototype = demo klien. **ReID wajib tampil di demo.** M4 (6 Nov) / M5 (20 Nov) tetap gerbang pra-pilot (dok. 12 §2, dok. 14).
- RTX 4060 tidak bisa dipakai sampai Senin 19 Okt; akhir pekan pakai laptop 1060 hanya untuk uji fungsi/diagnosis.

## Selesai

- **be-r1:** ANON-xxxx tidak dihitung/dinotifikasi/dinilai pelanggarannya; handler `identity.resolved` memindahkan `moved_intervals` ke karyawan (`reid_retro`, lintas kamera dan tengah malam, idempoten, `missing_employee` -> HR review); `employee_id` `ANON-` ditolak 422. Uji: 252 -> 268 lulus, 0 gagal. Rincian di CHANGELOG. Ini menutup "Belum" #4 sisi BE.
- **eb-r11:** `core.idle_fps` (detector dihemat di kamera kosong, default mati) + profil `demo-1060-hemat.yaml` / `demo-4060-hemat.yaml` (BELUM diukur). Engine + kontrak 878 -> 894 lulus.
- ea-r12 s.d. ea-r14 (lihat CHANGELOG). Pipa ReID hidup di 4060 (diuji dengan `X:\data\runs\ain_cepat`, 5 epoch RandPerson saja).
- ReID kandidat demo: OSNet-AIN, ImageNet -> RandPerson -> fine-tune ENTIRe-ID 20 epoch (Colab, di luar repo). ENTIRe-ID split sendiri mAP 0,68 / R1 0,68; Market-1501 mAP 0,40 / R1 0,66 (RandPerson saja: 0,22 / 0,43). Jenuh sejak ep15. Rinci: `tools/reid_train/MODEL-CARD-osnet-ain-entireid.md`.

## Belum (urut untuk demo ReID)

1. **OSNet lambat di onnxruntime** (±9,5 dtk batch >= 4 vs PyTorch ±32 ms). Jalankan `tools/reid_train/diag_reid_profile.py`; bila InstanceNormalization: `ganti_instancenorm.py`, ukur ulang `diag_reid_ort.py`; bila bukan: backend embedder TorchScript (paket baru, di belakang flag).
2. Uji ulang validator setelah ea-r14 (matikan/nyalakan publish satu stream; `stream_epoch` naik, 0 GAGAL).
3. Model ReID (tanpa latih ulang): ekspor ONNX fine-tune ENTIRe-ID + isi `reid.model_sha256`; verifikasi split ENTIRe-ID (ID dan kamera/sesi test tidak ada di train); cek lisensi ENTIRe-ID; `eval_reid.py` di crop berlabel 5 kamera lokasi -> kalibrasi `match_threshold` (masih null) dengan salah gabung <= 1%, lalu lengkapi kartu model.
4. Rekaman skenario demo ReID (wajah di kamera A -> membelakangi di kamera B) + `eval_reid.py`.
5. Uji manual ujung ke ujung engine ReID -> backend nyata (be-r1 hanya teruji dengan fixture): pastikan `identity.resolved` dari engine mengubah pemakaian karyawan di dashboard.
6. Ukur eb-r11 di laptop (lihat Uji manual). Bila SCRFD 320 belum cukup menurunkan ms/wajah: paket batch embedding glintr100 (rencana B2). ReID: embedder TorchScript hanya bila profil OSNet bukan InstanceNorm (B1).
7. ea-r15: giliran frame pertama track baru terbuang; backoff track tak dikenal. Curiga SCRFD/glintr100 juga lambat (profil setelah #1). EB: korektor offset P18 kebablasan setelah diskontinuitas stream.

## Di luar lingkup, ditemukan di jalan (belum dikerjakan)

- `/api/auth/login` tanpa rate limit dan `AUTH_COOKIE_SECURE` default `false`: perlu ditangani sebelum demo publik via Cloudflare.
- `schemas/enrollment.py` / `set_roster`: kontrak juga melarang `ANON-` sebagai person_id enroll; be-r1 hanya menutup employee CRUD.
- `report_service` masih memuat baris ANON (`employee_name` "Unknown", pemakaian 0) di `free_time`/`attendance`; `/api/attendance/sessions` menampilkan sesi atas ID ANON. Tidak memicu pelanggaran, hanya kosmetik.

## Keputusan yang perlu disetujui

- be-r1 dibuat dari HEAD `claude/funny-thompson-nt4y1d`, bukan `Claude-Branch` (tertinggal 8 commit, tanpa mekanisme atribusi). Nomor `be-r1` perlu dikonfirmasi tim BE (CHANGELOG belum punya `be-r*`).
- eb-r11 ditumpuk di atas branch be-r1 (merge eb = ikut membawa be-r1). Bila `idle_fps` dinyalakan, `at` track.started di ruangan kosong bisa telat <= 1/idle_fps dtk: EA perlu setuju sebelum dipakai di pilot.
- ea-r14 mengubah `factory.build_engine/build_source` dan `PyAVSource` (jalur EB); engine menolak start bila CUDA diminta tetapi onnxruntime CPU.

## Uji manual di laptop

eb-r11: (1) `python -m engine.tools.scrfd_dynamic --input engine/models/recognition/scrfd_10g_bnkps.onnx --output engine/models/recognition/scrfd_10g_bnkps_dinamis.onnx`; (2) `engine/tools/face_bench.py` 640 tetap vs 320 dinamis (ms/wajah, kosinus); (3) gladi 5 kamera 15 menit dengan profil hemat: log "kamera kosong/aktif lagi", "worker rekognisi membuang N%", `nvidia-smi dmon`, validator 0 GAGAL; (4) cek recall detector 512 di 1060 dan waktu sampai track.started saat orang masuk ruangan kosong (harus <= 1/idle_fps + konfirmasi tracker).

`python -m pytest backend/tests contracts/tests -q` (harus 268 lulus). Engine/ReID: `docs/UJI-REID-1060.md` (1060) atau, di 4060, `python -m pytest engine/tests contracts/tests -q`, `python scripts/check_gpu_env.py`, diagnosis OSNet, uji pipa ReID 5 menit + validator.

## Langkah berikutnya

Profil OSNet -> perbaiki jalur embedding -> uji pipa ReID + validator + backend nyata -> pasang model ReID final + MODEL-CARD -> rekam skenario + eval/kalibrasi di kamera lokasi -> demo.
