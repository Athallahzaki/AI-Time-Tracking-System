# Perbaikan lag_probe: crash saat engine lambat mulai (3 Okt 2026)

Ekstrak di root proyek di atas paket `engineA-engineB_batas-thread-cpu_nvdec-opsional_rekognisi-async_koreksi-jam`.

## Gejala
`TypeError: unsupported format string passed to NoneType.__format__` di akhir probe 5 menit.

## Penyebab
- Jendela "awal" dihitung dari saat probe dibuka (0–60 dtk). Di GTX 1060, `view.frame` pertama
  baru datang setelah lebih dari 60 dtk (muat D-FINE + warmup CUDA).
- Akibatnya median awal = None dan format `:.2f` crash. CSV tetap tersimpan, karena ditulis sebelum
  ringkasan dibuat.

## Perbaikan (`scripts/lag_probe.py`)
- Jendela awal sekarang dihitung dari `view.frame` pertama.
- Ringkasan mencetak "view.frame pertama pada detik N probe; X sampel".
- Nilai kosong dicetak "-", tidak lagi crash.
- Baru: `--summarize CSV` untuk meringkas ulang hasil lama tanpa mengulang uji.

  ```
  python scripts/lag_probe.py --summarize bench-out/lag-A-latest.csv
  ```

Tes: `engine/tests/test_lag_probe.py` +1 (reproduksi kasus lapangan + ringkas ulang CSV).
