# Serah Terima

Ditulis ulang di akhir setiap sesi. Terakhir: 16 Oktober 2026 malam, sesi EA + EB (paket ea-r12 + hasil gladi 4060). `SERAH-TERIMA-EA-R3.md` tetap berlaku untuk ReID/`schedule_off`/watchdog. Angka: CHANGELOG ea-r9, ea-r10, ea-r12.

## Lingkup (disepakati 16 Okt)

- **Prototype = demo untuk klien**: cukup gambaran yang jalan dan lancar dilihat. Tidak mengejar angka.
- **M4 (6 Nov) dan M5 (20 Nov) tetap gerbang pra-pilot** sesuai dok. 12 §2 / dok. 14: stress test 100 orang, identifikasi <= 5 dtk, uji operasional 3 hari. Optimasi rekognisi dikerjakan untuk gerbang ini, bukan untuk demo.

## Selesai

- ea-r12 (scheduler rekognisi per kamera + jam bersama): **pytest penuh lulus di laptop**.
- Gladi 4060, 5 kamera, 6 fps, 15 menit, watchdog + `-AffinityMask 0xFFFF`: 6,00 fps, 0 stall, p99 umur kotak 0,24 dtk (cam01/02/04), LULUS. Rekognisi: 47 ms/wajah, 11-17 wajah/dtk, 21-54% permintaan dibuang (jenuh sepanjang run).
- WARNING giliran nyasar: 1-3 per laporan (dulu ~60% giliran). Sisa = bug lain, lihat Temuan #2.
- ea-r13: kit latih ReID, query val kosong pada subset RandPerson asli diperbaiki. ReID untuk demo: latih OSNet (run cepat 5 epoch untuk uji pipa EA-R3 1-6, run penuh 60 epoch untuk demo); BE handler `identity.resolved` + saring ANON wajib sebelum ReID disambung ke backend.

## Temuan gladi (belum dikerjakan)

1. **Video uji tidak bisa mengukur identifikasi**: EMP123 diam sepanjang video -> 5 sampel per run, semuanya saat startup serentak 5 kamera (5,8-10,7 dtk). Semua angka identifikasi lama (termasuk vonis gerbang ea-r10) tidak sebanding.
2. **Giliran frame pertama track baru terbuang**: `ZonePriorityQueue.step` (langkah 3c `pipeline/engine.py`) jalan sebelum binding memberi `track_uuid` (langkah 5), jadi kunci sementara `cam-tN` di-pop lalu dibuang binding. Perbaikan: selama ada consumer, jangan submit track tanpa `track_uuid`.
3. **Track tak dikenal dicoba ulang tanpa batas** (retry 1 dtk, backoff 5 dtk selamanya): worker jenuh oleh orang tak ter-enroll; orang baru antre di prioritas yang sama. Usul: backoff bertingkat + track baru didahulukan (di belakang config).
4. **Korektor offset P18 kebablasan (jalur EB)**: setelah diskontinuitas stream (titik loop video, +-260 dtk) offset digeser 0,2/langkah lalu loncat +0,4; bias positif tidak pernah dikoreksi balik. cam03/cam05: umur kotak -0,35 (mustahil) lalu +0,50 tetap. Analisis tidak terpengaruh; kotak dashboard tergeser +-0,35 dtk sampai reconnect. Konfirmasi: `ffprobe` durasi `uji-siap.mp4`.
5. Log engine ada di `logs\engine\engine-*.err.log` (logging ke stderr), bukan `.out.log`.

## Belum (diurutkan untuk M4)

1. Video uji dengan orang ter-enroll yang masuk-keluar frame (minimal: rekam sendiri dengan HP), atau stream per kamera dengan start bergeser.
2. ea-r14: Temuan #2 + #3 (tidak menghalangi ReID).
3. face_bench terisolasi vs gladi (47 ms = model atau rebutan GPU?), lalu putuskan TensorRT / SCRFD kecil / batching.
4. Stress test bertahap (MOT20) sebelum 6 Nov.
5. BE: endpoint baca tanpa login -> **wajib sebelum demo publik** lewat Cloudflare bila memakai data karyawan asli (UU PDP). ReID dihitung salah diam-diam (EA-R3 #2).
6. EB: Temuan #4.
7. Kecil: MSDA hub-kernels, `swscale_resize`, kolom `drop/s` `summarize_gladi`, README Python 3.13.

## Keputusan yang perlu disetujui

- Gerbang rekognisi tetap mati; dinilai ulang dengan video uji yang benar.
- Patokan perubahan rekognisi: median identifikasi tidak naik (dok. 12 §2.2: <= 5 dtk), diukur dari video dengan orang masuk-keluar.

## Langkah berikutnya

Demo: rapikan tampilan + login BE. Gerbang M4: video uji -> ea-r14 -> face_bench -> stress test.
