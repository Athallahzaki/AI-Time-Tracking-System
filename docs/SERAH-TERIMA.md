# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 9 Oktober 2026, sesi EA (paket ea-r1).

## Selesai

- ea-k1 (sesi sebelumnya): kontrak `identity.resolved`, `ANON-xxxx`, `identity_source`,
  `schedule_off`; rincian untuk BE/EB di `docs/SERAH-TERIMA-EA-K1.md`.
- ea-r1: logika ReID di `engine/identity/reid/` (messages, gallery, merge, pending) +
  39 tes `test_reid_*.py`. Seluruh `engine/tests` lulus, `policy_grep` bersih. Belum
  dirakit ke runtime; tanpa model (embedding = vektor numpy).

## Belum

1. Rakit ReID ke `runtime/camera.py`/penjadwal (EB tahap 2) dan ke presence: perakit event
   mengisi `moved_intervals` dari `Resolution.track_uuids`, lalu memancarkan
   `identity.resolved`. Pengirim pesan wajib mengisi `face_person_id` hanya dari wajah.
2. Model + worker embedding tubuh (EA), interval embedding 15 dtk dari config (§3.6 butir 5).
3. Blok `reid:` di `config/schema.py` (sekarang `ReidConfig.from_mapping` sudah siap, belum
   dibaca loader; default tetap mati karena belum dirakit).
4. Fitur dokumen 12 §3 untuk BE/FE; penjadwal tahap 2 (EB).

## Keputusan yang perlu disetujui

- **Angka default** (usulan, perlu rekaman multi-kamera): ambang 0,80, margin 0,05, waktu
  tempuh pasangan tak tercantum 30 dtk, toleransi tumpang-tindih 0. Waktu tempuh nyata
  antar 5 lokasi diukur di lokasi klien.
- **Cannot-link berlaku juga di kamera yang sama** (dua track hidup bersamaan = dua orang).
- **Klaim yang dicabut belakangan** (rentang hidup memanjang lalu bertabrakan): track
  dikeluarkan dari kelompok/orang dan dinilai ulang. Interval yang sudah terpancar dengan
  ANON lama belum punya mekanisme koreksi di kontrak; perlu dibahas EA–BE.
- **Resolusi seluruh kelompok** tidak memeriksa ulang tabrakan dengan track wajah orang
  tujuan (sesuai §3.6 butir 3); tabrakan sesudahnya ditangani lewat pencabutan.
- Masih terbuka dari sesi lalu: timeline dokumen 14, `* text=auto`, data GPU di
  `engine/ports/frame.py` (13 Okt).

## Uji manual di laptop

- Belum ada untuk ea-r1 (logika murni). Sesudah dirakit: evaluasi dengan rekaman
  multi-kamera (persentase sambungan benar, menit bersumber ReID).
- Dari sesi lalu: A/B 4060 dan free vs tick (`docs/DEMO-REMOTE.md` §8, §8.1); spike NVDEC
  15–16 Okt.

## Langkah berikutnya

Kontrak antrean internal EA–EB 13 Okt: `messages.py` diusulkan sebagai bentuk pesan
per-kamera → inti identitas. Lalu worker embedding tubuh dan perakitan ke presence.
