# Status Kesesuaian Workplan

Review 20 September 2026: implementasi sesuai arah arsitektur, tetapi belum M5
(siap uji lapangan). Posisi realistis berada di M1 menuju M2.

| Bagian | Status | Catatan |
| --- | --- | --- |
| 0.1 schema/validator | Selesai | JSON Schema dan validator tersedia |
| 0.2 fake engine + 14 skenario | Selesai | fixture dan fake engine tersedia |
| 0.3 OpenAPI | Selesai runtime | `/openapi.json` dan `/docs` |
| 0.4 kebijakan HRD | Belum | default ada; keputusan resmi belum tertulis |
| 0.5 benchmark/rekaman | Sebagian | harness ada; baseline lapangan belum ada |
| 0.6 PROGRAM-DATE-TIME | Belum | MediaMTX belum tersedia |
| A2–A7 engine | Mayoritas selesai | identity, presence, outbox, runtime diuji |
| A8 enrollment | Sebagian besar | admission ada; model nyata belum terpasang |
| B2–B6 pipeline | Sebagian besar | PTS, zone, queue, matcher ada |
| B7–B9 model/NVDEC | Belum/opsional | harus berbasis benchmark |
| C1–C4 API/protokol/storage | Selesai minimum | replay dan event mentah tersedia |
| C5 session derivation | Selesai minimum | endpoint `/api/attendance/derived` |
| C6 break quota/alert | Sebagian | klasifikasi ada; kuota final belum lengkap |
| C7 camera/roster reconcile | Sebagian | kamera tersambung; roster startup belum |
| C8 MediaMTX/auth | Belum | konfigurasi deploy belum ada |
| C9 koreksi append-only | Selesai minimum | double-write diperbaiki |
| C10 enrollment API | Selesai minimum | request/result tersedia |
| D1–D7 frontend | Sebagian | dashboard ada; HLS playback/auth belum lengkap |

Perubahan review: memperbaiki runtime engine yang gagal karena mismatch signature,
mengaktifkan router backend, membuat kontrol kamera lintas proses, menambahkan
konfigurasi koneksi engine, endpoint derivasi attendance, tes backend, dependency
terkunci rentang versi, CORS yang valid, README, dan panduan testing.

Sebelum dipakai HRD: sepakati kebijakan, ambil rekaman representatif dan luluskan
benchmark, pasang model legal, implementasikan roster/MediaMTX/auth, lakukan soak
test kamera serta restart/replay, dan gunakan migrasi database production.
