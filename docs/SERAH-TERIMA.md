# Serah Terima

Terakhir: 12 November 2026, paket ea-r31 + be-r14 + fe-r9 (template wajah dari CCTV), di atas `2bbe9bd`, tanpa
GPU. Pilot di `2bbe9bd` lewat paket deploy `ai-time-tracking-deploy_2026-11-12b`. **Paket 2–12 Nov belum pernah
diuji di 4060/5090**, dan itu tetap pekerjaan berikutnya.

## Selesai

- ea-r31/be-r14/fe-r9: template wajah dari CCTV, rancangan `docs/RENCANA-TEMPLATE-WAJAH.md`. Engine penuh,
  backend, kontrak, build frontend, `policy_grep` lulus. Tampilan menu belum dilihat di browser.
- ea-r30 (`2bbe9bd`): fallback kotak penuh untuk wajah (tangan terangkat).
- 11 Nov: Paket A–H (panel debug, kondisi gambar, debug Fase 2, watchdog, dll.).

## Saklar (semua default mati = perilaku lama)

| Saklar | Di mana | Menyalakan |
|---|---|---|
| `face_templates.enabled: true` | config engine (restart) | penangkap kandidat + `template.*` |
| `FACE_TEMPLATES_ENABLED=1` | env backend | menu Template Wajah, penarik, jadwal |
| "Aktif" di menu Template Wajah | `app_settings` | penarikan + penerapan terjadwal |
| `recognition.full_box_fallback: true` | config engine (restart) | fallback kotak penuh |
| `DEBUG_PANEL_ENABLED=1` / `debug.enabled` / `image_condition.enabled` | backend / engine | panel debug, crop, kondisi gambar |
| `ENGINE_WATCHDOG=1` | `.env` server 5090 | watchdog engine (sudah ada di image sejak §13 DEPLOY) |

## Keputusan

- **Perlu disetujui EA:** kontrak `template.*` (skema terpisah, tidak durabel). Juga: angka awal penimbang.
- **Perlu kesepakatan klien (tertulis):** tabel kandidat menyimpan crop wajah karyawan dari CCTV; siapa tahu,
  berapa lama, siapa menghapus. Sama untuk crop panel debug (`debug.enabled` menyala di server 5090).
- Disetujui Zena 11 Nov: kontrak debug sementara, kedaluwarsa 28 Feb 2027.
- Masih terbuka: `ENGINE_SHARED_KEY` wajib di non-loopback; auth MediaMTX; tafsir JAT-04; MON-07.
- Override kalibrasi pilot 12 Nov: `reid.reevaluate` menyala sebelum `reid.match_threshold` dikalibrasi;
  `travel_time_seconds` kosong (default 30 dtk menolak gabung perpindahan ruangan yang lebih cepat).

## Belum

- **[UJI DI GPU, PERTAMA]** paket 2–12 Nov di 4060 atas rekaman lokasi, banding `c990bc4`.
- Template wajah di 4060: langkah §10 `RENCANA-TEMPLATE-WAJAH.md`; ukur "identifikasi: ... median" sebelum/sesudah.
- `SERAH-TERIMA` lama menulis watchdog "belum dipasang": ternyata sudah ada di paket deploy 5090 (opt-in).
- Usulan belum dibuat: interval pengaman pendek untuk track belum dikenali saat `analysis_trigger` menyala
  (sekarang 120 dtk); kredit wajah saat ReID memberi label karyawan.
- Kalibrasi `image_condition`, tabel waktu tempuh, `reid.match_threshold`; insiden `cam01b` 404; temuan 3/4/8.

## Uji manual (urut)

1. Template wajah: ketiga saklar menyala, mode `persetujuan`, satu orang ber-enrollment berjalan 10 menit
   dari beberapa sudut → kandidat muncul ≤ 1 menit setelah terkonfirmasi, maks. satu per menit; orang kedua
   berdampingan → kandidat margin tipis masuk "Perlu dilihat"; setujui + "Terapkan sekarang" → Terpasang;
   Cabut → skor kembali. Matikan saklar engine → menu menulis "Engine tidak melayani template".
2. ea-r30: tangan naik lurus 15 dtk, flag mati lalu menyala; log "fallback kotak penuh".
3. Panel debug, kondisi gambar, debug Fase 2: langkah di CHANGELOG paket F/G/H.
4. Redeploy: backend dulu, lalu frontend, lalu engine; tabel backend dan kolom `refs.source` dibuat otomatis.
