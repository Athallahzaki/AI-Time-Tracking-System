# Perubahan: pra-proses GPU bit-identik + batch_check --reference-fp32

Dasar: batch_check 4060 20:13 dan 20:17 (cuda_graph + fast_preprocess):

| | ms/gambar | IoU min | Δskor |
|---|---|---|---|
| FP32 | 17,6 (dari 28,5) | 0,989 | 0,006 |
| FP16 | 14,4 | 1,000* | 0,000* |

*pembanding juga FP16, jadi FP16 vs FP32 belum terukur.

## 1. Selisih 1 ulp di GPU

Tes CPU membuktikan tensor identik, tetapi di GPU `div_(255.0)` dikerjakan
PyTorch sebagai kali kebalikan dan meleset 1 ulp untuk sebagian nilai -> IoU
0,989 di FP32. Sekarang normalisasi memakai tabel 256 nilai `float32(i)/255`
yang dihitung numpy (`_normalise_lut`), diindeks di GPU: identik dengan
pra-proses LibreYOLO, tetap tanpa salinan float di CPU.

Tes yang ditambahkan di berkas tes (test_tensor_di_gpu_juga_sama_persis,
test_lut_sama_dengan_pembagian_numpy) dipertahankan dan kini lulus; tes duplikat
dariku dibuang.

## 2. batch_check --reference-fp32

Pembanding dijalankan FP32 walau kandidat `--half`, sehingga "salah"/IoU/Δskor
mengukur selisih FP16 terhadap FP32. Status half dipulihkan sesudahnya.

Tes: 557 passed, 7 skipped di sini (tes ber-torch/CUDA jalan di laptop uji).
