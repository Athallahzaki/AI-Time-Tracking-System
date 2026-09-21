# Status Kesesuaian Workplan

Review 21 September 2026: implementasi sesuai arah arsitektur, tetapi belum M5
(siap uji lapangan). Posisi realistis berada di M1 menuju M2.

| Bagian | Status | Catatan |
| --- | --- | --- |
| 0.1 schema/validator | Selesai | JSON Schema dan validator tersedia |
| 0.2 fake engine + 14 skenario | Selesai | fixture dan fake engine tersedia |
| 0.3 OpenAPI | Selesai runtime | `/openapi.json` dan `/docs` |
| 0.4 kebijakan HRD | Siap dikonfigurasi | YAML tervalidasi; keputusan resmi HRD masih diperlukan |
| 0.5 benchmark/rekaman | Sebagian | harness ada; baseline lapangan belum ada |
| 0.6 PROGRAM-DATE-TIME | Belum | MediaMTX belum tersedia |
| A2–A7 engine | Mayoritas selesai | identity, presence, outbox, runtime diuji |
| A8 enrollment | Sebagian besar | admission ada; model nyata belum terpasang |
| B2–B6 pipeline | Sebagian besar | PTS, zone, queue, matcher ada |
| B7–B9 model/NVDEC | Sebagian | D-FINE Nano terpasang; benchmark lapangan dan NVDEC belum |
| C1–C4 API/protokol/storage | Selesai minimum | replay dan event mentah tersedia |
| C5 session derivation | Selesai minimum | endpoint `/api/attendance/derived` |
| C6 break quota/alert | Selesai minimum | kuota, warning, timezone, dan endpoint tersedia |
| C7 camera/roster reconcile | Selesai minimum | otomatis saat startup dan reconnect |
| C8 MediaMTX/auth | Belum | konfigurasi deploy belum ada |
| C9 koreksi append-only | Selesai minimum | double-write diperbaiki |
| C10 enrollment API | Selesai minimum | request/result tersedia |
| D1–D7 frontend | Sebagian | dashboard ada; HLS playback/auth belum lengkap |

Perubahan review: memperbaiki runtime engine yang gagal karena mismatch signature,
mengaktifkan router backend, membuat kontrol kamera lintas proses, menambahkan
konfigurasi koneksi engine, endpoint derivasi attendance, tes backend, dependency
terkunci rentang versi, CORS yang valid, README, dan panduan testing. Audit terakhir
menghapus worker lama yang mengimpor engine ke backend, memasukkan tes backend ke
konfigurasi pytest, dan menambah tes regresi batas proses.

Sebelum dipakai HRD: sepakati kebijakan, ambil rekaman representatif dan luluskan
benchmark, pasang model legal, implementasikan roster/MediaMTX/auth, lakukan soak
test kamera serta restart/replay, dan gunakan migrasi database production.
