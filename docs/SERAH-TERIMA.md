# Serah Terima

Terakhir: 12 November 2026, paket ea-r30 (fallback kotak penuh), di atas `849bd8f`, tanpa GPU. Pilot tetap di
`c990bc4`; **paket 2–12 Nov belum pernah diuji di 4060/5090**, dan itu tetap pekerjaan berikutnya.

## Selesai

- ea-r30: wajah dicari ulang di seluruh kotak bila potongan kepala 45% kosong (kasus tangan terangkat).
  Tes `test_fallback_kotak_penuh.py` + `test_rekognisi_beban.py` lulus; rangkaian engine penuh belum dijalankan.
- 11 Nov: Paket F (panel debug), G (kondisi gambar), H (debug Fase 2), A–E, uji penerimaan JAT.

## Saklar (semua default mati = perilaku lama)

| Saklar | Di mana | Menyalakan |
|---|---|---|
| `recognition.full_box_fallback: true` | config engine (restart) | fallback kotak penuh untuk wajah |
| `DEBUG_PANEL_ENABLED=1` | env backend | menu Debug + rute `/api/debug/*` |
| `debug.enabled: true` | config engine | cache crop + log engine ke panel |
| `image_condition.enabled: true` | config engine | pemantau kondisi gambar |

## Keputusan

- Disetujui Zena 11 Nov: kontrak debug sementara `debug.*`, kedaluwarsa 28 Feb 2027.
- **Perlu disetujui:** izin mode debug + apakah klien tahu fitur crop; `ENGINE_SHARED_KEY` wajib di non-loopback;
  auth MediaMTX; tafsir JAT-04; MON-07 kacamata.
- **Perlu dicek di pilot (override kalibrasi 12 Nov 13:34):** `reid.reevaluate` menyala padahal
  `reid.match_threshold` belum dikalibrasi; `travel_time_seconds` kosong (default 30 dtk menolak gabung untuk
  perpindahan ruangan lebih cepat dari itu); catat nilai override wajah/detektor yang dipasang.

## Belum

- **[UJI DI GPU, PERTAMA]** semua paket 2–12 Nov di 4060 atas rekaman lokasi, banding `c990bc4`.
- **[Paket E, pasang]** watchdog di engine server 5090: menunggu cara engine dijalankan di sana (docker run /
  stack / image). Tidak ada definisi container engine di repo.
- **[usulan, belum dibuat]** interval pengaman lebih pendek untuk track belum dikenali saat `analysis_trigger`
  menyala (sekarang 120 dtk); kredit wajah saat ReID memberi label karyawan.
- Kalibrasi `image_condition`, tabel waktu tempuh, `reid.match_threshold`; insiden `cam01b` 404; temuan 3/4/8.

## Uji manual (urut)

1. ea-r30 di 4060: rekam 15 dtk gerakan tangan naik lurus → turun. Jalankan dua kali, flag mati lalu menyala.
   Dengan flag menyala, nama harus terkonfirmasi saat tangan masih di atas; log "fallback kotak penuh: dicoba
   N, wajah ketemu M" naik; bandingkan "identifikasi: ... median" dan ms worker rekognisi.
2. Panel debug, kondisi gambar, debug Fase 2, versi campuran: langkah di CHANGELOG paket F/G/H.
3. Redeploy: backend dulu, lalu frontend; `ENGINE_SHARED_KEY` kosong sampai engine ikut; GitOps Portainer mati.
