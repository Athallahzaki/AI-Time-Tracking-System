# Dokumentasi Sistem — AI Time Tracking (CCTV)

Versi 2.2 · diperbarui 9 Oktober 2026 · lihat dokumen 12 (kesepakatan), 13 (daftar pembaruan), dan 14 (timeline) · **Internal tim pengembang** (disalurkan ke pihak luar lewat communicator tim)

Set dokumen ini menggantikan acuan lama (`ARCHITECTURE.md` v1, `ENGINE_PROTOCOL.md`, `PROJECT STRUCTURE.md` v1.2, `WORKPLAN.md`) sebagai arah pengembangan **fase 1**. Dokumen lama tetap berlaku untuk detail teknis yang tidak diubah di sini (misalnya rincian skema pesan dan skenario fake engine); bila bertentangan, dokumen ini yang berlaku. Dokumentasi penggunaan (manual HR/supervisor) dibuat setelah produk jadi dan bukan bagian dari set ini.

**Urutan berlaku sejak 8 Oktober 2026.** Dokumen 12 (Kesepakatan Prototype) adalah acuan terbaru. Bila dokumen 01–11 atau dokumen lama bertentangan dengan dokumen 12, **dokumen 12 yang berlaku**. Dokumen 13 mendaftar bagian mana yang sudah tidak berlaku (sebelumnya → sekarang). Keputusan baru dicatat dengan memperbarui dokumen 12, bukan dengan menambah dokumen lain.

## Isi

| No | Dokumen | Isi pokok |
|---|---|---|
| 01 | [Arsitektur Sistem](01-ARSITEKTUR-SISTEM.md) | Kebutuhan klien, prinsip produk, workflow ujung ke ujung, lokasi & kategori, batasan fase 1 |
| 02 | [Arsitektur Backend](02-ARSITEKTUR-BACKEND.md) | Ledger kunjungan, kebijakan, peringatan, laporan, enrollment, auth, penyimpanan |
| 03 | [Arsitektur Frontend](03-ARSITEKTUR-FRONTEND.md) | Halaman, peran, streaming video & overlay, enrollment dari web |
| 04 | [Arsitektur Engine](04-ARSITEKTUR-ENGINE.md) | Ingest, deteksi, tracking, identitas, presence, real-time & drift; §14 restrukturisasi engine (penjadwal berdetak, pemrosesan di GPU) |
| 05 | [Integrasi Pihak Ketiga](05-INTEGRASI-PIHAK-KETIGA.md) | MediaMTX, kamera/NVR, NTP, notifikasi, model, NVIDIA/Docker |
| 06 | [Permasalahan & Rekomendasi](06-MASALAH-DAN-REKOMENDASI.md) | Daftar bug, edge case kegagalan, dan solusinya |
| 07 | [Protokol Komunikasi & API](07-PROTOKOL-DAN-API.md) | Protokol engine ↔ backend, REST/SSE backend ↔ frontend, perubahan fase 1 |
| 08 | [Struktur Proyek](08-STRUKTUR-PROYEK.md) | Folder, kepemilikan, peta restrukturisasi, konfigurasi & data |
| 09 | [Workplan](09-WORKPLAN.md) | 6 minggu pengembangan, pilot 2–3 minggu, per jalur |
| 09a | [Workplan Demo](09a-WORKPLAN-DEMO.md) | Jalur cepat demo klien (±10 hari kerja): MediaMTX, deteksi lewat batas, pesan dashboard + email, login minimal. D6 (penerima global) dan D7 (arti peran viewer) diganti dokumen 12 §3.4 dan §3.2 |
| 10 | [Keterbatasan, Spesifikasi & Hal Terkait Klien](10-KETERBATASAN-SPEK-KLIEN.md) | Batas kemampuan sistem, spek server, kebutuhan ke perusahaan CCTV, asumsi & pertanyaan terbuka. §1 (ReID dikecualikan), §2 (asumsi 12 fps), §5 (jam istirahat tetap) diganti dokumen 12 |
| 11 | [FAQ](11-FAQ.md) | Pertanyaan yang sering muncul, teknis dan non-teknis |
| 12 | [Kesepakatan Prototype](12-KESEPAKATAN-PROTOTYPE.md) | **Acuan terbaru (8 Okt 2026).** Definisi prototype selesai (performa, beban, akurasi, operasional), fitur dan keputusan (data master, peran, pengaturan, email, report, ReID, interpolasi kotak, keamanan akses), lingkungan uji dan deployment, pemilik per jalur, risiko, pertanyaan terbuka, konvensi tim |
| 13 | [Daftar Pembaruan](13-DAFTAR-PEMBARUAN.md) | Perbandingan sebelumnya → sekarang per 8–9 Okt 2026, dan daftar dokumen lama yang terdampak |
| 14 | [Timeline Pra-Pilot](14-TIMELINE-PRA-PILOT.md) | **Usulan.** Kalender 12 Okt – pilot 30 Nov: rincian per jalur, gerbang bertanggal, ketergantungan, jalur kritis. Versi interaktif: `14-TIMELINE-PRA-PILOT.html` |
| — | `docs/CHANGELOG.md` (di repo kode) | Catatan perubahan kode per paket, entri terbaru di atas: tanggal dan nama paket, apa yang berubah, alasan, file yang tersentuh, cara uji. Menggantikan file `PERUBAHAN-*.md` per paket di root; file lama dipindah ke `docs/arsip/` (dokumen 12 §10.2–10.3) |

Runbook operasional demo jarak jauh (laptop engine + server Portainer CE, NetBird, Cloudflare → VPS) ada di repo: `docs/DEMO-REMOTE.md`.

## Status keputusan

Dokumen ini membedakan tiga hal dan menandainya secara eksplisit:

- **Diputuskan** — disepakati tim, dikerjakan di fase 1.
- **Asumsi** — dipakai sebagai default selama pengembangan karena jawaban klien belum ada; berupa konfigurasi sehingga bisa diubah tanpa mengubah kode.
- **Terbuka** — belum diputuskan; pemilik keputusan disebut.

Untuk status **fitur** (bukan keputusan), sejak 8 Oktober 2026 dipakai tiga tingkat dari dokumen 12 §2.5: berfungsi (simulasi) → teruji data nyata → terkalibrasi.

## Kode area

**EA** = Engine A (kontrak & identitas) · **EB** = Engine B (pipeline & performa) · **BE** = Backend · **FE** = Frontend · **OPS** = deploy/infra · **PO** = keputusan produk/klien · **COM** = communicator tim.

## Sumber

Dokumen ini disusun dari: analisis kode build `2026.09.23-audit-fixes`, audit 23 Sep 2026, analisis pengembangan 24 Sep 2026, keputusan arsitektur engine 18 Sep 2026, dan diskusi arah produk 24 Sep 2026. Pembaruan 8 Okt 2026 bersumber dari diskusi arah prototype 8 Okt 2026 (dokumen 12), daftar pembaruan (dokumen 13), dan paket kode r7. Uji otomatis (pytest, build frontend) belum diverifikasi ulang di lingkungan penyusunan; klaim "tes lulus" di dokumen status repo perlu dijalankan ulang di mesin tim.

## Riwayat perubahan

- 9 Oktober 2026 (v2.2): ditambah dokumen 14 (timeline); entri 04 menyebut §14 restrukturisasi engine; entri 13 mencakup pembaruan 9 Oktober.

- Baris versi diperbarui ke 2.1 (8 Oktober 2026) dengan rujukan ke dokumen 12 dan 13; info audiens dipertahankan.
- Ditambahkan paragraf urutan berlaku: dokumen 12 mengalahkan dokumen 01–11 dan dokumen lama bila bertentangan.
- Ditambahkan entri tabel untuk dokumen 12 (Kesepakatan Prototype), dokumen 13 (Daftar Pembaruan), dan `docs/CHANGELOG.md` sebagai pengganti file `PERUBAHAN-*.md`.
- Entri 09a dan 10 diberi catatan bagian yang sudah diganti dokumen 12.
- Ditambahkan rujukan ke runbook `docs/DEMO-REMOTE.md` di repo.
- Bagian status keputusan ditambah catatan tiga tingkat status fitur (dokumen 12 §2.5).
- Bagian sumber ditambah sumber pembaruan 8 Oktober 2026.
