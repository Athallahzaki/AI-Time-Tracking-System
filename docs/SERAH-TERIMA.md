# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 9 Oktober 2026, sesi EB (paket eb-r10).

## Selesai

- eb-r10: alat baseline 5 kamera. `publish_test_video.ps1 -Count N` (satu ffmpeg per path cam01..camN),
  `summarize_gladi.py` per kamera + baris gabungan (vonis per file, 1 kamera tidak berubah),
  DEMO-REMOTE §8.1 memakai `-Count 5`. 10 tes `test_summarize_gladi.py` lulus. `engine/runtime/`
  dan profil tidak disentuh.
- Dari sesi EA (tetap berlaku): ea-k1 kontrak identitas, ea-r1 logika ReID, ea-r2 kit latih OSNet
  (`tools/reid_train/`, belum dijalankan dengan data/bobot asli). Rincian di CHANGELOG.

## Belum

1. Baseline 5 kamera nyata (T0, T0-6, T1) belum dijalankan; angka belum ada.
2. `publish_test_video.ps1 -Count` belum pernah dijalankan (cloud tanpa PowerShell). Hanya dibaca ulang.
3. ReID: latihan nyata, worker embedding, perakitan ke presence (EA, lihat CHANGELOG ea-r2).

## Keputusan yang perlu disetujui

- Vonis multi-kamera: LULUS hanya bila SEMUA kamera lulus. Ambang tidak diubah, tetapi sekarang
  satu kamera buruk menggagalkan file; sebelumnya median campuran bisa menutupinya. Setuju?
- Line ending: CLAUDE.md minta CRLF, tetapi seluruh repo (index git) LF dan tidak ada `* text=auto`.
  File paket ini mengikuti LF agar diff tidak membengkak. Putuskan (butir lama "* text=auto").
- Terbuka: timeline dokumen 14, data GPU di `engine/ports/frame.py`, keputusan ReID ea-r2.

## Uji manual di laptop 4060 (PowerShell, dari root repo)

1. Uji publish pendek: `.\scripts\publish_test_video.ps1 -Video ongame.mp4 -Fps 25 -Count 5`
   (MediaMTX sudah jalan). Harap: lima proses `ffmpeg` di Task Manager; `ffplay rtsp://127.0.0.1:8554/cam03`
   menampilkan gambar. Matikan satu proses ffmpeg: skrip harus menyebut `camNN (kode ...)`,
   menghentikan sisanya, dan keluar dengan galat. Ctrl+C: tak ada ffmpeg yatim tersisa.
2. `-Count 1` tanpa `-Count`: perilaku lama (satu stream `cam01`). `-Count 3 -Path x`: ditolak.
3. Catat CPU laptop saat 5 publish tanpa engine (biaya encode 5 x x264 veryfast ikut baseline).
   Bila CPU sudah tinggi, pakai `-Width 1280` dan catat di hasil.
4. Jalankan T0, T0-6, T1 sesuai DEMO-REMOTE §8.1 (15 menit tiap run). Publish tidak boleh
   dimatikan di antara run. Ringkas: `python scripts/summarize_gladi.py --target-fps 6 bench-out/ab-T0-6.csv bench-out/ab-T1.csv`.
5. Periksa: tabel punya baris cam01..cam05 + baris `[5 kam]` per file; kirim CSV dan log engine.

## Langkah berikutnya

Jalankan baseline di laptop dan kirim CSV; hasilnya menentukan gerbang 23 Oktober (dokumen 14).
EA: kontrak antrean EA-EB 13 Okt, worker embedding tubuh.
