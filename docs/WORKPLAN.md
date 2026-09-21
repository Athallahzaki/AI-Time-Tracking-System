# Rencana Kerja Paralel

**AI Time Tracking System** · v1 · 19 September 2026

Pembagian tugas untuk empat orang bekerja paralel di tiga jalur. Acuan teknisnya
`ARCHITECTURE.md`; kontrak antar-jalurnya `ENGINE_PROTOCOL.md`.

---

## 1. Komposisi dan arah bantuan

| Jalur | Orang | Bobot pekerjaan | Beban per orang |
| --- | --- | --- | --- |
| Engine | 2 | ~50% | ~25 |
| Backend | 1 | ~30% | **~30** |
| Frontend | 1 | ~20% | ~20 |

Arah bantuan yang disepakati: **frontend → backend → engine.** Dua orang engine tetap
di engine dan tidak ditarik ke mana pun.

### Satu koreksi terhadap asumsi awal

Bottleneck-nya **bukan engine, tapi backend.** Engine memang bagian terbesar, tapi ia
dikerjakan dua orang; backend dikerjakan satu orang dengan beban per-orang tertinggi —
dan di atas itu, backend adalah **satu-satunya yang memblokir dua jalur lain**.
Frontend tidak bisa bergerak tanpa kontrak API-nya, dan integrasi tidak bisa diuji
tanpa klien protokolnya.

Konsekuensinya:

1. **Frontend membantu backend lebih awal**, bukan setelah frontend selesai. Bantuan
   yang datang di akhir tidak menolong jalur kritis.
2. **Backend menerbitkan OpenAPI di hari-hari pertama**, sebelum menulis logika apa
   pun. Itu deliverable pertamanya, bukan hasil sampingan nanti.
3. **Backend punya bus factor 1.** Minimal satu orang lain harus bisa membaca kodenya.
   Cara termurah: frontend mengerjakan bagian backend yang menghadap API, jadi ada dua
   orang yang paham bentuk datanya.

Bantuan backend ke engine kemungkinan besar **tidak akan pernah terjadi**, dan itu
tidak apa-apa. Jangan merencanakan jadwal yang bergantung padanya.

---

## 2. Fase 0 — Membuka blokir

Tidak ada yang boleh mulai membangun sebelum empat hal ini ada. Semuanya kecil;
targetnya hitungan hari, bukan minggu.

| # | Deliverable | Pemilik | Kenapa lebih dulu |
| --- | --- | --- | --- |
| 0.1 | Skema pesan + validator | **Engine A** | Engine yang tahu apa yang realistis dipancarkan |
| 0.2 | `fake_engine` + 14 skenario | **Engine A** | Membuka blokir backend & frontend seketika |
| 0.3 | OpenAPI backend↔frontend | **Backend** | Membuka blokir frontend |
| 0.4 | Spesifikasi kebijakan istirahat | **Backend + HRD** | Tanpa ini backend tidak punya yang dikerjakan |
| 0.5 | `bench.py` + rekaman ponsel | **Engine B** | Bisa membatalkan asumsi arsitektur |
| 0.6 | Uji akurasi `PROGRAM-DATE-TIME` MediaMTX | **Frontend** | Bisa membatalkan pilihan transport video |

**Kenapa `fake_engine` ditulis orang engine, bukan backend.** Kalau backend yang
menulis, ia mengkodekan apa yang *ia harap* engine pancarkan. Kalau engine yang
menulis, ia mengkodekan apa yang *benar-benar akan* dipancarkan. Yang kedua jauh lebih
berguna, dan selisihnya baru ketahuan di integrasi kalau salah pilih.

**0.4 bukan pekerjaan engineer.** Pertanyaannya: kapan istirahat mulai dihitung — saat
keluar pintu atau saat tidak terlihat? Pindah ruangan untuk kerja itu istirahat atau
bukan? Jatah 30 menit per hari atau per sesi? Keluar 5 menit lalu masuk lagi, satu
istirahat atau dua? Bagaimana shift yang melewati tengah malam? Itu dijawab HRD, dan
tim engine bisa jalan tanpa jawabannya — **backend tidak bisa.**

**0.5 bisa membatalkan rencana.** Kalau rekaman menunjukkan umur track rata-rata dua
menit sebelum putus padahal orangnya masih di ruangan, monitoring istirahat tidak
layak dibangun apa pun logika backend-nya (§4.7 `ARCHITECTURE.md`). Lebih baik tahu di
hari ketiga daripada bulan ketiga.

**0.6 murah tapi menentukan.** MediaMTX menyajikan file video sebagai RTSP, jadi uji ini
tidak butuh kamera: putar file, tonton lewat HLS, bandingkan
`EXT-X-PROGRAM-DATE-TIME` dengan waktu sebenarnya. Kalau melesetnya besar, itu
satu-satunya hal yang bisa memaksa kembali ke relay buatan sendiri — dan lebih baik
ketahuan sekarang, saat C8 masih satu hari kerja, bukan setelah frontend membangun
overlay di atasnya.

---

## 3. Jalur Engine — 2 orang

Dua orang, dua sub-jalur yang hampir tidak bertabrakan. **Engine A** memegang kontrak
dan lapisan identitas; **Engine B** memegang pipeline dan performa.

### Engine A — kontrak & identitas

| Urutan | Tugas | Selesai kalau |
| --- | --- | --- |
| A1 | Skema + `fake_engine` + skenario (0.1, 0.2) | Backend bisa jalan tanpa engine asli |
| A2 | Bug kebenaran §9 butir 1–5 | Satu match tunggal tidak lagi membuka sesi |
| A3 | Evidence accumulator + fusi embedding | Konfirmasi dari bukti tersebar, bukan frame berkorelasi |
| A4 | Margin test + dedup identitas antar track | Dua orang mirip tidak saling klaim |
| A5 | State `HELD` + penyambungan `track.resumed` | Identitas bertahan saat orang membelakangi kamera |
| A6 | Emisi `presence.interval` sesuai kontrak | 14 skenario cocok dengan perilaku engine asli |
| A7 | Outbox + sequence + replay | Backend restart tidak kehilangan event |
| A8 | Enrollment diperketat (§10) | Duplikat & tabrakan ditolak dengan alasan spesifik |

### Engine B — pipeline & performa

| Urutan | Tugas | Selesai kalau |
| --- | --- | --- |
| B1 | `bench.py` + rekaman representatif (0.5) | Empat metrik dasar terukur |
| B2 | Bug §9 butir 7, 9, 10 | Deteksi basi, gagal diam-diam, dan `crop()` view beres |
| B3 | Parameter temporal jadi detik + turun ke 10 fps | FPS naik ~3× tanpa ID switch memburuk |
| B4 | Ingest PyAV + PTS + offset wallclock (§5.5) | PTS tersedia; offset ditetapkan ulang tiap reconnect |
| B5 | `door_region` + prioritas antrian | Track baru di pintu didahulukan |
| B6 | Matcher matriks + head-crop + quality gate | Latency p95 turun, akurasi tidak |
| B7 | Ganti tracker ke ByteTrack MIT | Ultralytics lepas dari tracker; umur track tidak memburuk |
| B8 | Ganti detector ke LibreYOLO + retune | Ultralytics lepas sepenuhnya |
| B9 | NVDEC — hanya kalau profil menuntut | Decode tidak lagi jadi hambatan |

**Titik temu A dan B:** A5 dan A6 butuh `door_region` dari B5, dan keduanya butuh PTS
dari B4. Urutkan B4 dan B5 lebih awal daripada yang terlihat perlu, supaya A tidak
menunggu.

**Jangan pernah mengerjakan B7 dan B8 bersamaan.** Mengganti tracker dan detector
sekaligus membuat penurunan kualitas mustahil diatribusikan.

---

## 4. Jalur Backend — 1 orang

Bekerja melawan `fake_engine` sejak hari pertama. **Tidak pernah butuh kamera**
kecuali untuk relay video (C7).

| Urutan | Tugas | Selesai kalau |
| --- | --- | --- |
| C1 | OpenAPI backend↔frontend (0.3) | Frontend bisa mulai dengan mock |
| C2 | Spesifikasi kebijakan bersama HRD (0.4) | Semua pertanyaan di §2 terjawab tertulis |
| C3 | Klien protokol: NDJSON, reconnect, `hello`, seq | Skenario 6 & 7 hijau |
| C4 | Skema penyimpanan + simpan interval mentah | Restart tidak kehilangan apa pun; bisa dihitung ulang |
| C5 | Penurunan sesi dari interval + aturan celah | Skenario 1–4 hijau — ini inti produknya |
| C6 | Logika jatah istirahat + peringatan | Skenario 2 & 3 membedakan celah palsu dari asli |
| C7 | Rekonsiliasi `set_cameras` / `set_roster` | Skenario 11 hijau |
| C8 | MediaMTX: konfigurasi path + hook auth eksternal | Browser menonton lewat HLS; izin tetap diputuskan backend |
| C9 | Koreksi manual sebagai event append-only | Riwayat koreksi bisa diaudit, tidak ada timpa |
| C10 | API enrollment (teruskan ke engine, simpan audit) | Penolakan sampai ke UI dengan alasannya |

**C5 adalah inti produk, bukan plumbing.** Di situlah "celah ini istirahat atau
kegagalan tracking" diputuskan. Beri waktu paling banyak di sana dan jangan buru-buru
melewatinya untuk mengejar fitur lain.

**C8 menyusut drastis** setelah keputusan memakai MediaMTX (§6.7.1 `ARCHITECTURE.md`).
Backend tidak lagi menulis klien RTSP, muxer fMP4, WebSocket, atau integrasi MSE — yang
tersisa cuma file konfigurasi dan satu endpoint yang menjawab "user ini boleh melihat
`r1`?". Satu sampai dua minggu berubah jadi satu hari, dan itu dipotong tepat dari jalur
kritis.

MediaMTX juga menyajikan file video sebagai server RTSP, jadi jalur ini bisa dibangun
dan diuji penuh tanpa kamera asli sama sekali.

---

## 5. Jalur Frontend — 1 orang

Bekerja melawan OpenAPI dan fixture. Mulai dengan mock, pindah ke backend asli begitu
C3 hidup.

| Urutan | Tugas | Selesai kalau |
| --- | --- | --- |
| D1 | Kerangka dashboard + mock dari OpenAPI | Halaman jalan tanpa backend hidup |
| D2 | Tampilan ruangan: siapa hadir, sejak kapan | Data dari snapshot backend |
| D3 | Player HLS + overlay canvas selaras `at` | Kotak duduk di tempat yang benar, di resolusi apa pun |
| D4 | Panel jatah istirahat per orang | Sisa jatah, riwayat celah, penanda celah meragukan |
| D5 | Alert orang tak dikenal | Muncul sebagai sesuatu yang bisa ditindaklanjuti |
| D6 | UI enrollment + tampilan penolakan | Alasan per gambar terbaca jelas oleh non-teknis |
| D7 | UI koreksi manual + tampilan audit | Siapa mengoreksi apa, kapan, kenapa |
| D8 | **Pindah membantu backend** | Lihat §1 |

**D3 adalah bagian tersulit di jalur ini.** Penyelarasannya lewat field `at` (jam
dinding) yang dicocokkan ke `EXT-X-PROGRAM-DATE-TIME` di manifest HLS — bukan lewat
`pts`, yang dipakai untuk menyambung ke event engine. Bisa dibangun sepenuhnya dengan
fixture: satu file video disajikan MediaMTX + satu file NDJSON `view.frame` yang
direkam, tanpa backend dan tanpa kamera.

Dan ingat presisinya tidak wajib: kotak telat 150 ms cuma terlihat sedikit meleset,
dan tidak ada perhitungan absensi yang terpengaruh. Jangan habiskan seminggu mengejar
kesempurnaan di lapisan kosmetik.

**Nilai sebenarnya ada di mode playback, bukan live.** "Tunjukkan apa yang kamera lihat
jam 10:15 saat sistem bilang dia pergi" adalah fitur yang menyelesaikan sanggahan —
prioritaskan seek-ke-timestamp di atas kelancaran tampilan langsung.

**D4 menentukan apakah sistem ini adil.** Celah yang berasal dari `end_zone: interior`
harus **terlihat berbeda** dari celah yang berasal dari `end_zone: door`. Kalau UI
menampilkan keduanya sebagai angka menit yang sama, seluruh kehati-hatian di §4
`ARCHITECTURE.md` hilang di lapisan terakhir.

---

## 6. Milestone integrasi

Integrasi **dari hari pertama**, bukan di akhir. Semua bug yang menarik di sistem ini
ada di sambungan — penyelarasan PTS, reconnect dan replay, penafsiran celah. Tiga
jalur yang masing-masing menguji bagiannya sendiri akan sama-sama lulus, lalu gagal
saat disatukan.

| M | Nama | Isi | Lulus kalau |
| --- | --- | --- | --- |
| M0 | Kontrak beku | 0.1–0.5 selesai | Tiga jalur bisa mulai tanpa saling tanya |
| M1 | Rangkaian palsu | `fake_engine` → backend → frontend | Orang muncul di dashboard, semuanya palsu |
| M2 | Kebijakan benar | C5, C6 + skenario 1–4 | Celah palsu tidak dihitung sebagai istirahat |
| M3 | Engine asli masuk | A6 menggantikan `fake_engine` | Skenario yang sama tetap hijau |
| M4 | Video hidup | C8 + D3 | Kotak selaras dengan video dari kamera asli |
| M5 | Siap uji lapangan | Semua jalur + koreksi manual | Bisa dipakai HRD tanpa pendampingan |

**Jalankan ketiganya bersama setiap hari sejak M1**, meski isinya masih kosong.
Integrasi yang dijalankan harian tidak pernah jadi krisis; integrasi yang ditunda
selalu jadi krisis.

---

## 7. Risiko

**Backend adalah jalur kritis dan bus factor 1.** Mitigasi: frontend masuk lebih awal,
OpenAPI diterbitkan duluan, dan review kode backend wajib dibaca minimal satu orang
lain.

**Spesifikasi kebijakan (0.4) macet di HRD.** Ini risiko jadwal terbesar yang paling
sering diremehkan, karena ia bukan pekerjaan teknis dan tidak ada di backlog siapa pun.
Mitigasi: kejar di hari pertama, dan kalau belum ada jawaban, backend membangun C3–C5
dengan aturan yang dibuat sementara **tapi dipisahkan ke satu modul konfigurasi** supaya
menggantinya nanti tidak menyentuh logika.

**Rekaman ponsel (0.5) membatalkan asumsi.** Bukan risiko jadwal, tapi risiko produk —
dan justru itu alasannya dikerjakan di awal.

**Skema melar ke dua arah.** Terjadi kalau tidak ada pemilik tunggal. Sudah ditangani
di `ENGINE_PROTOCOL.md`, tapi hanya kalau penunjukannya benar-benar dilakukan.

**Dua orang engine saling menunggu.** Titik temunya di B4 dan B5; kalau B mengerjakan
optimisasi dulu, A menganggur. Urutkan B4–B5 lebih awal.

---

## 8. Aturan kerja

**Kontrak dibekukan sebelum kode.** Perubahan skema setelah M1 lewat pemilik skema dan
diumumkan ke tiga jalur.

**Fixture di-commit, bukan dihasilkan ulang.** Tes yang membandingkan dengan output
yang dihasilkan saat itu juga tidak menguji apa-apa.

**Satu variabel per langkah** di jalur engine. Tidak pernah mengganti dua komponen
sekaligus.

**`grep` konstanta kebijakan di `engine/`** sebagai bagian dari CI. Kalau ada angka 30,
kata "istirahat", jam 12–13, atau "penalty" — build merah.

**Kebenaran sebelum kecepatan.** Sistem lambat itu kelihatan; sistem yang salah
mencatat kehadiran dengan percaya diri itu tidak.
