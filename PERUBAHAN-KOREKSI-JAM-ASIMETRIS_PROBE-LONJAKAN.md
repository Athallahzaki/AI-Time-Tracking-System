# Perubahan: koreksi jam P18 asimetris + probe tidak tertipu median

Dasar: uji RTX 4060 (lag-A-latest-half.csv, lag-B-none-half.csv), direkam SEBELUM
paket kumulatif 3 Okt. Paket ini ditumpuk DI ATAS paket kumulatif
`engineA-engineB_kumulatif-3okt_detector-bersama-batching_optimasi-4060.zip`.

## 1. engine/runtime/clock.py — bias positif tidak lagi "dikoreksi" cepat

Temuan di run A (latest): saat fps jatuh ke 2,9, sisa bias naik ke +0,51 dtk
(semua frame tiba terlambat = thread pembaca tertinggal). Korektor menyapunya
dalam ±5 dtk (0,51 -> 0,04). Saat antrean terkuras, bias aslinya muncul lagi
sebagai -0,41/-0,47 dan harus dikoreksi balik. Dua kali salah; selama itu `at`
event ±0,5 dtk terlalu awal dan umur frame di probe terlihat lebih segar dari
kenyataan.

Offset diambil dari waktu tiba frame pertama, jadi kesalahan offset hanya bisa
membuat `at` MENDAHULUI kenyataan (bias negatif). Bias positif = delay
sungguhan. Sekarang:

- bias negatif: tetap 0,1 dtk/dtk (seperti sebelumnya),
- bias positif: maksimal `max_rate_late` = 0,002 dtk/dtk (2000 ppm). Cukup untuk
  mengejar drift kristal kamera (puluhan ppm), terlalu lambat untuk menyapu
  antrean beberapa detik.

Rollback: `OffsetCorrector(max_rate_late=0.1)` di camera.py = perilaku lama.

## 2. scripts/lag_probe.py — ringkasan tidak lagi bilang "SEGAR" saat ada lonjakan

Run A diringkas "engine SEGAR dan stabil" padahal umur sempat 6,16 dtk dan fps
jatuh ke 2,3. Sekarang ringkasan menambah p95/maks umur, min/maks fps, dan
PERINGATAN untuk: umur > 2 dtk, fps < 60% median, sisa bias positif > 0,3 dtk.
Bila median segar tetapi ada peringatan: "median SEGAR tetapi TIDAK STABIL".

Ringkas ulang CSV lama: `python scripts/lag_probe.py --summarize lag-A-latest-half.csv`

## Tes

- test_offset_correction.py: +3 tes (bias positif hampir tidak digeser, drift
  kristal 100 ppm tetap terkejar selama 3 jam, bias negatif tetap cepat) +2
  parameter ditolak.
- test_lag_probe.py: +1 tes (median segar + lonjakan -> TIDAK STABIL).
- Seluruh suite: 517 passed, 3 skipped.
