# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 9 Oktober 2026, sesi EA (paket r7–r10).

## Kondisi repo

- r7: overlay hanya track aktif + LOST ≤ 0,3 dtk; deploy Portainer (engine di laptop
  lewat NetBird); `summarize_gladi.py`; protokol uji A/B 4060.
- r8: restrukturisasi repo (`docs/CHANGELOG.md`, `docs/arsip/`, `.gitattributes`
  `*.sh` LF, `.gitignore` model/SQLite). Pastikan skrip `restrukturisasi-r8` sudah
  dijalankan dan di-commit.
- r9: penjadwal berdetak tahap 1 (`core.scheduler: tick`, default `free`), kerangka
  tahap 2, mailbox, stub NVDEC, `scripts/spike_nvdec.py`. 22 tes baru; engine +
  contracts lulus. Tes backend tidak dijalankan di sesi itu (FastAPI tidak terpasang).

## Belum dikerjakan (urut prioritas, lihat dokumen 14)

1. Fitur dokumen 12 §3 untuk BE/FE: data master karyawan, pengguna dan peran, pengaturan
   dari web, email per pelanggaran + rekap harian, `.xlsx`, report, pengetatan akses.
2. ReID (EA): logika di usulan `engine/identity/reid/`, kontrak `identity.resolved`,
   `ANON-xxxx`, `identity_source`, alasan `schedule_off` di skema.
3. Penjadwal tahap 2 (EB): rakit `TickScheduler` ke `service.py`, `camera.py` jadi
   state per kamera.
4. r10: `CLAUDE.md`, `docs/PETA-KODE.md`, `scripts/pack_for_claude.py` baru dibuat; belum
   dipakai di sesi nyata. Koreksi peta bila ada yang meleset.

## Keputusan yang perlu disetujui tim

- Timeline dokumen 14 masih **usulan**.
- Model + worker ReID pindah dari EB ke EA (dokumen 12 §7 v1.1).
- `* text=auto` ditunda (dokumen 12 §10.3).
- Cara frame membawa data GPU di `engine/ports/frame.py`: diputuskan di kontrak 13 Okt.

## Uji manual di laptop (tidak bisa di cloud)

- A/B 4060 R0–R3 (`docs/DEMO-REMOTE.md` §8) dan free vs tick T0-6/T1 5 stream (§8.1).
- Spike NVDEC 15–16 Okt: `python scripts/spike_nvdec.py --url rtsp://127.0.0.1:8554/cam01 --seconds 60`.

## Langkah berikutnya

Sesuai dokumen 14 minggu 1 (mulai 12 Okt): kontrak protokol + antarmuka antrean
internal (13 Okt), baseline 5 kamera + spike (16 Okt), data master BE/FE.
