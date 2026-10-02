# Uji Delay Engine vs Dashboard (MediaMTX)

Tujuan: memastikan dari mana delay kotak deteksi berasal, dengan angka, bukan perasaan.

| Pola | Artinya | Pemilik |
|---|---|---|
| Delay **bertambah** terus seiring waktu | Engine lebih lambat dari kamera (P17) | Engine B (ingest), Engine A bila rekognisi menyala (P7) |
| Delay **tetap**, engine segar di probe, dashboard telat | Jalur backend → frontend / sinkronisasi video (P10, P16) | Frontend |
| Delay **tetap tapi besar** di probe | Bias offset frame pertama (P18) atau jam beda mesin | Engine B |

Alat:

- `scripts/publish_test_video.ps1` / `.sh`: publish video uji ke MediaMTX sebagai `cam01`, tanpa B-frame, keyframe tiap 1 detik.
- `scripts/lag_probe.py`: menyambung ke engine sebagai pengganti backend, mencatat umur kotak dan lag per kamera, lalu memberi kesimpulan.
- Engine sekarang melapor sendiri: `engine.health.camera_metrics` (`lag_seconds`, `effective_fps`, `frames_dropped_stale`) dan event `camera.degraded`/`camera.recovered` dengan `kind: "lag"` bila tertinggal lebih dari 1 detik selama 5 detik.

## Persiapan (sekali)

1. MediaMTX jalan: `.\deploy\mediamtx\start-mediamtx.ps1`. Path `cam01` harus `source: publisher` (konfigurasi saat ini).
2. ffmpeg terpasang: `winget install Gyan.FFmpeg`.
3. Video uji 1080p berisi orang yang bergerak, minimal 2–3 menit, awal dan akhir sebaiknya kosong (supaya titik loop tidak mengacaukan track).
4. Semua langkah di **mesin engine** (mesin dengan GPU), supaya jam probe dan engine sama.

## Langkah 1: publish video

```powershell
.\scripts\publish_test_video.ps1 -Video C:\video\uji.mp4 -Fps 25
```

Biarkan jendela ini berjalan. Cek di browser `http://localhost:8889/cam01` bahwa video tampil.

## Langkah 2: engine dengan perbaikan (live_buffer: latest)

Terminal baru:

```powershell
python -m engine.runtime --config engine/config/dfine-m.yaml --tcp 127.0.0.1:8765 `
    --health-seconds 2 --outbox engine/data/outbox-uji.sqlite3
```

Outbox uji dipakai supaya outbox asli tidak tercampur. **Jangan jalankan backend** selama probe: engine hanya melayani satu backend.

## Langkah 3: probe 5 menit

Terminal ketiga:

```powershell
python scripts/lag_probe.py --camera cam01=rtsp://127.0.0.1:8554/cam01 --minutes 5 --out bench-out/lag-A-latest.csv
```

Catat kesimpulannya. Perhatikan juga log engine: seharusnya **tidak ada** `reader is too slow` di MediaMTX, dan `PTS went backwards` mendekati 0.

## Langkah 4: pembanding tanpa thread pembaca

Salin config dan matikan buffer:

```powershell
Copy-Item engine/config/dfine-m.yaml bench-out/dfine-m-tanpa-buffer.yaml
# edit bench-out/dfine-m-tanpa-buffer.yaml: live_buffer: "none"
```

Ulangi langkah 2 dengan `--config bench-out/dfine-m-tanpa-buffer.yaml`, lalu langkah 3 dengan `--out bench-out/lag-B-none.csv`.

Yang diharapkan bila teori benar dan GPU tidak mampu real-time: **B bertambah, A stabil**. Bila A dan B sama-sama stabil, GPU-nya cukup cepat untuk satu kamera dan delay yang dulu terlihat berasal dari tempat lain (langkah 5).

## Langkah 5: jalur lengkap dengan dashboard

Hentikan probe. Jalankan backend dan frontend seperti biasa (engine tetap dengan `dfine-m.yaml`). Di dashboard, amati satu orang yang bergerak:

- menit ke-1: perkiraan selisih kotak terhadap orangnya (detik);
- menit ke-5: perkiraan yang sama;
- mode pemutar yang dipakai (WebRTC / HLS).

Bandingkan dengan hasil probe langkah 3. Bila probe bilang engine segar (umur kotak ≤ 1,5 dtk) tetapi dashboard telat beberapa detik, penyebabnya di frontend: tebakan `Date.now() − 0,8` di mode WebRTC (P10) dan kotak basi tanpa batas toleransi (P16). Coba mode HLS sebagai pembanding, karena HLS mencocokkan waktu lewat `EXT-X-PROGRAM-DATE-TIME`.

## Langkah 6 (opsional): pengaruh rekognisi wajah

Bila recognizer sudah terpasang, ulangi langkah 2–3 dengan `recognizer: onnx_face`. Bila fps analisis turun drastis atau lag mulai bertambah, itu P7 (rekognisi sinkron di loop frame) dan perlu worker asinkron (Engine A + B).

## Yang dikirim balik ke tim

| Uji | Config | Kesimpulan probe | Umur kotak awal → akhir | Lag median | fps | Dashboard menit 1 / 5 |
|---|---|---|---|---|---|---|
| A | dfine-m (latest) | | | | | — |
| B | tanpa buffer | | | | | — |
| C | jalur lengkap | — | — | — | — | |

Lampirkan juga berkas CSV dari `bench-out/`.

## Keterbatasan probe

- Umur kotak memakai `at` dari engine, yang menyimpan bias offset frame pertama (P18). Karena itu yang dibaca adalah **pola**, bukan angka mutlaknya.
- Umur negatif berarti `at` berada di masa depan: sumber diputar lebih cepat dari real-time atau jam berbeda. Probe menyatakan data **tidak valid** dalam kasus itu, bukan "segar".
- `lag_seconds` hanya terlapor dengan `live_buffer: latest`. Tanpa thread pembaca, lag bersembunyi di buffer socket dan hanya terlihat dari umur kotak yang bertambah.
