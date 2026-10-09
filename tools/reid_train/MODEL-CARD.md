# Kartu model ReID — <nama berkas ONNX>

> Templat. Salin per model, isi semua `<…>`. Hapus baris yang tidak berlaku, jangan dikosongkan diam-diam.

## Identitas

| Hal | Isi |
|---|---|
| Berkas | `<osnet_ain_rp_imagenet.onnx>` |
| SHA-256 ONNX | `<64 heksa dari export_onnx.py>` |
| Tanggal latih / ekspor | `<YYYY-MM-DD>` |
| Commit repo (kit) | `<git rev-parse HEAD>` (tercatat di `runs/<nama>/config.json`) |
| Status | `<kandidat | disetujui EA | pembanding saja>` |

## Arsitektur

`<osnet_ain_x1_0 | osnet_x1_0 | osnet_ain_x0_25>` (torchreid `<versi/commit>`), masukan 1x3x256x128,
keluaran `embedding` 512-d `<mentah | L2 di dalam graf>`, opset 17. Pra-proses: BGR→RGB, resize
256x128, /255, mean `0.485 0.456 0.406`, std `0.229 0.224 0.225`.

## Inisialisasi

- `<imagenet | scratch>`
- Bila imagenet: ID Drive `<…>`, SHA-256 bobot `<dari config.json → bobot_imagenet.sha256>`,
  sumber: torchreid `docs/MODEL_ZOO.md` (ImageNet pretrained models). Lisensi bobot ini:
  `<dicek oleh siapa/kapan; belum diverifikasi oleh kit>`.

## Data latih

- RandPerson, subset 132.145 gambar (sintetis), Apache-2.0.
  Tautan: <https://github.com/VideoObjectSearch/RandPerson>.
  Atribusi: `<kutipan yang diminta pemilik dataset, salin dari repo mereka>`.
- Hasil `prepare_randperson.py`: `<id train / id val / gambar / kamera>` dari `summary.json`; seed `<0>`.
- Tidak ada data klien yang dipakai melatih: `<ya | tidak, jelaskan>`.

## Konfigurasi latih

`<salin dari runs/<nama>/config.json: arch, init, epochs, batch, lr, weight_decay, warmup,
label_smooth, margin, erase_prob, amp, seed, torch, perangkat>`. Augmentasi: flip, random resized
crop (0,85–1), color jitter, gaussian blur p 0,3, random erasing `<p>`.

## Hasil

| Evaluasi | mAP | rank-1 | Catatan |
|---|---|---|---|
| Val RandPerson (sintetis), epoch `<n>` | `<…>` | `<…>` | hanya untuk memilih epoch, **bukan** prediksi kinerja nyata |
| Crop berlabel tim (`eval_reid.py`) | `<…>` | `<…>` | `<n orang, n kamera, n gambar>` |
| Pembanding `PEMBANDING-msmt17.onnx` pada crop yang sama | `<…>` | `<…>` | tidak untuk engine |

## Ambang rekomendasi

Dari `eval_reid.py` pada crop tim, salah gabung ≤ 1% (pasangan beda-orang-beda-kamera):

| Ambang kosinus | Sambungan benar % | Salah gabung % | Salah gabung semua kamera % |
|---|---|---|---|
| `<0,xx>` | `<…>` | `<…>` | `<…>` |

Jumlah pasangan: positif `<…>`, negatif lintas-kamera `<…>`. Keyakinan: `<rendah bila data tim sedikit>`.
Ambang ini mengganti usulan 0,80 di `engine/identity/reid/merge.py` **hanya** setelah EA menyetujui.

## Batasan yang diketahui

- Dilatih pada data sintetis; domain CCTV klien (cahaya, sudut, pakaian) bisa berbeda jauh.
- `<tambahkan temuan dari evaluasi: kamera/orang yang buruk, dsb.>`
