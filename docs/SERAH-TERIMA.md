# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 2 November 2026, sesi EA (paket ea-r16, overhaul P4).
Rencana kerja sekarang: **`docs/RENCANA-OVERHAUL.md`** (P1–P10). Pilot tetap di `c990bc4`.
Status demo ReID lama (eb-r12/eb-r12b, kalibrasi `match_threshold`, profil hemat 1060): lihat CHANGELOG 18 Okt;
kalibrasi itu kini bagian dari P6.

## Selesai

- **ea-r16 (P4):** roster `MatrixMatcher` diganti atomik (satu tuple `_snapshot`); `enrollment._best_other`
  membaca `snapshot()`. Tes race baru gagal di kode lama (nama `P2`/`Q1` tertukar), lulus di kode baru.

## Belum (urut rencana overhaul)

1. **P1 keamanan login.** Tanpa kode, bisa hari ini di pilot: `AUTH_COOKIE_SECURE=true` di `deploy/.env`;
   batasi dashboard di Traefik VPS. Kode: rate limit login (jalur BE).
2. **P2 koreksi rencana:** job basi dan exception recognizer dikirim worker sebagai `None`, sama dengan
   "wajah tidak ada". Pembeda di `binding._complete` saja tidak cukup; hasil worker butuh sentinel
   (basi/galat). Exception = kasus ke-5 yang belum ada di daftar P2.
3. P3, P5–P10 sesuai rencana; §3 data lapangan pilot belum dikumpulkan.

## Di luar lingkup, ditemukan di jalan

- 6 tes engine sudah gagal sebelum ea-r16 (profil YAML berubah, tes belum): `test_demo_1060_config` (2),
  `test_demo_4060_config`, `test_preflight_demo`, `test_reid_bucket`, `test_reid_embedder`
  (mis. harap `LibreDFINEs.pt`, profil `LibreDFINEm.pt`). Putuskan: profil atau tes yang benar.
- Butir lama tetap: `set_roster` belum menolak `ANON-`; `onnx` tidak di `requirements-dev.txt`;
  `engine-c-stderr.log` tanpa rotasi.

## Keputusan yang perlu disetujui

- ea-r16: `MatrixMatcher.snapshot()` publik baru (dipakai enrollment). Kontrak tidak berubah.

## Uji manual di laptop (ea-r16)

1. `python -m pytest engine/tests/test_matcher_race.py -q` di Windows (penjadwal thread berbeda).
2. Engine biasa dengan wajah terdaftar, lalu enroll/hapus karyawan saat kamera jalan: tidak ada exception
   dari `match()` di log, nama yang dikenali tetap benar.

## Langkah berikutnya

P1 bagian config (pilot) → P2 (dengan koreksi di atas) → P3.
