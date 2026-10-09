# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 9 Oktober 2026, sesi EA (paket ea-r2).

## Selesai

- ea-k1: kontrak `identity.resolved`, `ANON-xxxx`, `schedule_off` (`docs/SERAH-TERIMA-EA-K1.md`).
- ea-r1: logika ReID `engine/identity/reid/` (39 tes), belum dirakit ke runtime, tanpa model.
- ea-r2: kit latih OSNet `tools/reid_train/` (prepare RandPerson → latih → ONNX → eval crop tim);
  7 tes CPU lulus di venv bersih (ujung-ke-ujung 40 gambar palsu). `engine/` tidak disentuh.
  Belum pernah jalan dengan data/bobot asli atau GPU (sesi ini dilarang mengunduhnya).

## Belum

1. Latihan nyata di laptop; angka mAP dan ambang asli belum ada.
2. Worker embedding tubuh di engine (memuat ONNX kit, interval 15 dtk), perakitan ReID ke
   `runtime/camera.py`/presence (EB tahap 2), blok `reid:` di `config/schema.py`.
3. Fitur dokumen 12 §3 untuk BE/FE.

## Keputusan yang perlu disetujui

- Angka default ReID (0,80 / margin 0,05 / 30 dtk) tetap usulan; ambang dari `eval_reid.py` pada
  crop tim menggantikannya hanya setelah EA setuju. Cannot-link juga di kamera sama; koreksi
  interval ANON yang sudah terpancar belum ada di kontrak (EA–BE).
- **Lisensi bobot ImageNet torchreid dan bobot MSMT17 pembanding belum diverifikasi**; varian
  `scratch` ada untuk jalur bersih. Putuskan varian mana yang boleh ke produksi.
- **mAP val RandPerson (sintetis) tidak memprediksi kinerja di CCTV klien.** Keputusan model hanya
  dari `eval_reid.py` pada crop berlabel tim; siapa yang melabel, berapa orang/kamera?
- Random erasing p 0,5 sesuai permintaan, tetapi torchreid memperingatkan itu bisa merugikan
  generalisasi; bandingkan `--erase-prob 0`. torchreid dipin ke f8cd150; Python 3.13 tidak didukung.
- Terbuka dari sesi lalu: timeline dokumen 14, `* text=auto`, data GPU di `engine/ports/frame.py`.

## Uji manual di laptop (urutan; rincian + PowerShell di `tools/reid_train/README.md`)

1. venv Python 3.11, torch CUDA (`torch.cuda.is_available()` harus `True`).
2. `pip install -r requirements-train-deps.txt`, lalu `pip install --no-build-isolation -r requirements-train.txt`
   (Cython gagal → fallback README §3). `python -m pytest tests -q` di `tools\reid_train` harus lulus.
3. Unduh subset RandPerson manual → `prepare_randperson.py` → cek tabel id/gambar/kamera.
4. Bobot ImageNet manual bila `gdown` gagal (`osnet_ain_x1_0_imagenet.pth`, README §6).
5. Latih `--init imagenet` dan `--init scratch` (`--amp`); catat lama epoch dan VRAM (OOM → `--batch 48`).
6. `export_onnx.py` kedua varian (selisih < 1e-3), catat SHA-256.
7. Crop berlabel tim + MSMT17 dari huggingface.co/kaiyangzhou/osnet sebagai `PEMBANDING-msmt17.onnx`;
   `eval_reid.py` ketiganya; isi `MODEL-CARD.md`.
8. Belum diuji di Windows: perintah PowerShell README, DataLoader `spawn` (Linux sudah), kecukupan
   8 GB VRAM pada batch 64.

## Langkah berikutnya

Kontrak antrean EA–EB 13 Okt (`messages.py`), lalu worker embedding tubuh dengan `reid_common.py`
sebagai definisi pra-proses, lalu perakitan ke presence. Hasil uji laptop menentukan model dan ambang.
