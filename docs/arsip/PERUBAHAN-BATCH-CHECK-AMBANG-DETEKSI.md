# Perubahan: batch_check membandingkan pada ambang deteksi

Dasar: 4060 20:24.
- FP32 + cuda_graph + fast_preprocess: 24,8 ms, IoU 1,000, Δskor 0 -> pra-proses GPU
  terbukti bit-identik. (Pembanding eager 180,5 ms: laptop sedang panas lagi;
  dingin = 17,6 ms.)
- FP16 + graph + fast vs pembanding FP32: 2 dari 60 gambar "salah", IoU min 0,000,
  Δskor 1,000 = jumlah kotak berbeda, vonis "BATCH MENGUBAH HASIL".

Dua masalah di alatnya:
1. Vonis menyebut "BATCH" padahal ukuran 1; yang berubah adalah FP16.
2. Kotak yang dibandingkan adalah SEMUA kotak, termasuk skor rendah (± raw_confidence
   0,1) yang hanya dipakai ByteTrack tahap kedua. Satu kotak 0,11 vs 0,09 sudah
   membuat gambar "salah" dengan IoU 0 dan Δskor 1, tanpa menyebut skornya.

## Perubahan (`engine/tools/batch_check.py`)

- `compare_detail(ref, cand, min_conf)`: kotak >= ambang deteksi (`detector._conf`,
  0,50 di config) WAJIB punya pasangan; pasangannya boleh sedikit di bawah ambang
  (toleransi 0,02) supaya 0,505 vs 0,495 tidak dihitung hilang. Pencocokan dua arah.
- Kolom baru: `beda-semua` (termasuk kotak skor rendah, informasi) dan `skor-maks`
  (skor tertinggi kotak tanpa pasangan) -> langsung terlihat apakah yang berbeda
  kotak penting atau kandidat ByteTrack.
- Vonis "HASIL BERUBAH pada ambang deteksi X (N gambar)" untuk batch / half /
  cuda_graph / fast_preprocess.
- docs/UJI-LAG.md diperbarui.

Tes: test_batch_check.py +3. Suite: 560 passed, 7 skipped.
