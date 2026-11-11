# Serah Terima

Terakhir: 11 November 2026, Paket F + G + H, di atas `da5b134`, tanpa GPU. Urutan A–H di
`docs/ANALISIS-KETAHANAN.md` §7 selesai dibangun. Pilot tetap di `c990bc4`; **paket 2–11 Nov belum pernah diuji
di 4060/5090**, dan itu sekarang pekerjaan berikutnya, bukan kode baru.

## Selesai (engine 869 dgn 8 dilewati, backend 172, kontrak 166, build frontend lulus)

- Paket F: panel debug Fase 1 (menu Debug: kesehatan sebagai laju, log backend + browser, rekaman CSV).
- Paket G: pemantau kondisi gambar (IR/gelap menahan ReID; buram/beku dilaporkan).
- Paket H: debug Fase 2 (kontrak `debug.*` terpisah, log engine, crop tubuh dengan sesi debug + audit).
- Sebelumnya hari ini: A–E (`da5b134`), uji penerimaan JAT (`d8d796c`).

## Saklar baru (semua default mati = perilaku lama)

| Saklar | Di mana | Menyalakan |
|---|---|---|
| `DEBUG_PANEL_ENABLED=1` | env backend | menu Debug + rute `/api/debug/*` |
| `debug.enabled: true` | config engine | cache crop di memori + log engine ke panel |
| `image_condition.enabled: true` | config engine | pemantau kondisi gambar |
| izin "mode debug" per akun admin | Manajemen Pengguna | boleh membuka crop |

## Keputusan

- **Disetujui Zena 11 Nov:** kontrak debug sementara `debug.*` (Paket H). **Kedaluwarsa 28 Feb 2027**: tes kontrak
  akan gagal sesudahnya; hapus atau angkat jadi kontrak resmi.
- **Perlu disetujui:** siapa yang diberi izin mode debug dan apakah klien tahu fitur crop ada; engine menolak start
  tanpa `ENGINE_SHARED_KEY` di alamat non-loopback; autentikasi MediaMTX; tafsir JAT-04; ekspektasi MON-07 kacamata.
- Dari 3–10 Nov: kontrak `set_tuning`; ea-r17/ea-r21; kuota login per (username, IP).
- Batas dari Zena: Traefik, Cloudflare, ACL NetBird tidak diubah.

## Belum

- **[UJI DI GPU, PERTAMA]** semua paket 2–11 Nov di 4060 atas rekaman lokasi, banding `c990bc4`, baru ke pilot.
- **[kalibrasi]** ambang `image_condition` dari rekaman siang/redup/IR (baca angkanya di menu Debug); tabel waktu
  tempuh; `reid.match_threshold`.
- **[pasang]** watchdog Docker (Paket E) di compose engine server 5090.
- **[insiden]** `cam01b` 404 sejak 11 Nov ±04:00: hop yang putus belum dikonfirmasi (ANALISIS §1).
- Temuan 3, 4, 8 (ANALISIS §2.2); MediaMTX tanpa auth; `pip-audit`/`npm audit`; uji penerimaan non-kode (§7a).

## Uji manual (urut)

1. Panel: `DEBUG_PANEL_ENABLED=1`, restart backend → menu Debug tampil; matikan satu kamera → status dan alasan
   muncul dalam ±30 dtk; tombol Rekam → CSV terbaca `scripts/summarize_gladi.py`.
2. Kondisi gambar: nyalakan di config engine, tutup lensa / matikan lampu / paksa IR → kolom "Gambar" berubah
   setelah ±3 dtk; saat IR, `gate_kondisi_gambar` naik dan ANON baru tidak bertambah karena embedding IR.
3. Debug Fase 2: `debug.enabled: true` di engine + beri izin mode debug ke satu admin → buka mode dengan password,
   isi alasan, lihat crop ANON; cek `settings_audit` (Pengaturan → riwayat) mencatatnya; setelah 30 menit tertutup.
4. Versi campuran: backend baru + engine pilot lama → panel menulis "Engine tidak melayani debug: tidak dikenal".
5. Dari paket sebelumnya: ReID di GPU (Paket D), watchdog (E), nginx + sesi (B), uji penerimaan JAT, insiden.
6. Redeploy: backend dulu, lalu frontend; `ENGINE_SHARED_KEY` kosong sampai engine ikut; GitOps Portainer mati.
