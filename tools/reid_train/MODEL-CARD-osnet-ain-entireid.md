# Kartu model ReID — OSNet-AIN, RandPerson + fine-tune ENTIRe-ID (kandidat demo)

> Diisi dari CSV Colab yang diunggah user 18 Okt 2026 (`eval.csv`, `eval_1.csv`, `eval_2.csv`,
> `eval_market.csv`, `log.csv`); angka disalin oleh skrip, bukan diketik tangan. Kolom yang tidak
> diketahui ditulis "belum diisi — dari pelatih". Templat: `MODEL-CARD.md`.

## Identitas

| Hal | Isi |
|---|---|
| Berkas | belum diisi — ONNX hasil `export_onnx.py` dari `last.pth` fine-tune ENTIRe-ID |
| SHA-256 ONNX | belum diisi — wajib sebelum dipasang (`reid.model_sha256`) |
| Tanggal latih / ekspor | belum diisi — dari pelatih |
| Commit repo (kit) | tidak berlaku: latih dan eval memakai skrip Colab di luar repo (keputusan user) |
| Status | kandidat demo, **belum disetujui EA** |

## Arsitektur dan inisialisasi

`osnet_ain` (varian pasti belum diisi — dari pelatih), masukan 1x3x256x128, embedding 512-d. Bobot awal
ImageNet (torchreid). ImageNet saja, tanpa latih ReID, di Market-1501: mAP 0,0283, R1 0,0989.

## Data latih

1. RandPerson (sintetis), run Colab `ain_colab`.
2. Fine-tune ENTIRe-ID (gambar nyata), 20 epoch, **split train/test buatan sendiri** (bukan protokol resmi).
   Jumlah ID / gambar / kamera: belum diisi — dari pelatih.
- Tidak ada data klien dipakai melatih: belum dikonfirmasi.
- Lisensi ENTIRe-ID untuk proyek klien: **belum dicek**.

## Hasil

| Model | target (ENTIRe-ID split sendiri) mAP / R1 / R5 / R10 | Market-1501 mAP / R1 / R5 / R10 |
|---|---|---|
| RandPerson `ain_colab` best | — | 0,4251 / 0,6876 / 0,8394 / 0,8839 |
| RandPerson `ain_colab` last (eval ulang 2x: `eval_1`, `eval_2`) | 0,2224–0,2292 / 0,2250–0,2328 / 0,3643–0,3805 / 0,4353–0,4515 | 0,4275–0,4348 / 0,6927–0,6933 / 0,8358–0,8370 / 0,8839–0,8881 |
| **Fine-tune ENTIRe-ID 20 epoch, last (kandidat demo)** | 0,6775 / 0,6814 / 0,8565 / 0,8945 | 0,4004 / 0,6636 / 0,8100 / 0,8578 |
| Crop berlabel kamera lokasi (`eval_reid.py`) | belum ada | |

Log fine-tune, mAP target / Market: ep5 0,5687 / 0,3589 → ep10 0,6392 / 0,3965 → ep15 0,6603 / 0,4010 → ep20 0,6683 / 0,3956. Akurasi train akhir 0,9905, ±20,3 dtk/epoch.

Tafsiran:
- Model yang sama dievaluasi ulang bergeser ±0,007 mAP, jadi selisih < ±0,01 adalah derau. Kenaikan ep15 → ep20
  termasuk derau: latih sudah jenuh, menambah epoch tidak berguna.
- Fine-tune ENTIRe-ID menaikkan target 0,22 → 0,68 dengan harga Market 0,43 → 0,40 (generalisasi turun sedikit).
- Tidak satu pun angka ini memprediksi kinerja di CCTV klien.

## Ambang rekomendasi

Belum ada. `reid.match_threshold` tetap `null` (usulan 0,80 di `engine/identity/reid/merge.py` belum dikalibrasi)
sampai `eval_reid.py` dijalankan pada crop berlabel dari 5 kamera lokasi, dengan salah gabung lintas kamera <= 1%.
Ambang baru berlaku hanya setelah EA menyetujui.

## Batasan yang diketahui

- Split ENTIRe-ID buatan sendiri: angka target hanya sah bila ID **dan** kamera/sesi test tidak muncul di train. Belum diverifikasi.
- Skrip latih/eval di Colab, di luar repo: tidak bisa direproduksi dari repo ini.
- Domain klien (dalam ruangan, cahaya, sudut kamera atas) belum diuji. Bila karyawan berseragam, risiko salah gabung naik tajam; ukur dengan crop lokasi.
- Kecepatan: OSNet di onnxruntime ±9,5 dtk per batch >= 4 (SERAH-TERIMA #1). Ini masalah runtime, bukan bobot.
