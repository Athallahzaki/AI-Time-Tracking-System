# Uji Delay Engine vs Dashboard (MediaMTX)

Tujuan: memastikan dari mana delay kotak deteksi berasal, dengan angka, bukan perasaan.

| Pola | Artinya | Pemilik |
|---|---|---|
| Delay **bertambah** terus seiring waktu | Engine lebih lambat dari kamera (P17) | Engine B (ingest), Engine A bila rekognisi menyala (P7) |
| Delay **tetap**, engine segar di probe, dashboard telat | Jalur backend → frontend / sinkronisasi video (P10, P16) | Frontend |
| Delay **tetap tapi besar** di probe | Bias offset saat stream dibuka (P18, sekarang dikoreksi bila `live_buffer: latest`) atau jam beda mesin | Engine B |

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

## Uji lanjutan (paket rekognisi-async + koreksi jam)

Hasil 2 Okt: mode `latest` mentok 3,97 fps di FP32 maupun FP16, mode `none` 6,5–8 fps. FP16 tidak mengubah apa pun, jadi pembatasnya CPU/Python, bukan GPU. Urutan di bawah sengaja: plafon ingest dulu (tanpa GPU), baru engine penuh, baru rekognisi. Jangan lompat ke langkah C sebelum A selesai, karena angka C tidak bisa dibaca kalau plafon 4 fps masih ada.

### Persiapan di mesin tanpa Docker / video pendek (mis. GTX 1060)

- MediaMTX tanpa Docker: unduh `mediamtx_v…_windows_amd64.zip` dari github.com/bluenviron/mediamtx/releases, ekstrak, jalankan `.\mediamtx.exe` (config bawaannya menerima publish di path apa pun, termasuk `cam01`).
- Video 1 menit cukup: publisher memutar ulang tanpa henti. Setiap 60 dtk orang "melompat" ke posisi awal, jadi track berakhir lalu mulai lagi; itu wajar.
- **Jangan meng-encode live di mesin yang sedang diukur.** Plafon kita adalah CPU, dan libx264 1080p ikut berebut CPU. Encode sekali, lalu publish tanpa encode ulang:

```powershell
ffmpeg -i C:\video\uji.mp4 -an -vf fps=25 -c:v libx264 -preset veryfast -profile:v high `
  -bf 0 -g 25 -keyint_min 25 -sc_threshold 0 -pix_fmt yuv420p C:\video\uji-siap.mp4
ffmpeg -re -stream_loop -1 -i C:\video\uji-siap.mp4 -c copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam01
```

  Bila engine mencatat `PTS went backwards` setiap 60 dtk, kembali ke `publish_test_video.ps1` (bisa diganti `-c:v h264_nvenc` supaya encode di chip NVENC, bukan CPU) dan catat itu di hasil.
- GTX 1060 (Pascal): `detector.half: false` wajib. Cek `python -c "import torch; print(torch.cuda.get_arch_list(), torch.cuda.is_available())"` memuat `sm_61`; build PyTorch CUDA terbaru bisa sudah membuang Pascal. Angka absolut fps 1060 tidak dibandingkan dengan 4060; yang dibaca polanya.

### A. Cari penyebab plafon 4 fps (tanpa detector, ±10 menit)

Video uji tetap dipublish. Engine **tidak** perlu jalan. `--work-ms 110` meniru durasi detector per frame dari bench 4060; biarkan 110 supaya sebanding dengan data 2 Okt.

```powershell
# 1. Dasar: menunggu GPU (tanpa rebutan CPU)
python -m engine.tools.ingest_ceiling --work-ms 110 --work sleep --json bench-out/ceiling-sleep.json
# 2. Beban CPU sungguhan: resize OpenCV + matmul torch (pool thread seperti detector)
python -m engine.tools.ingest_ceiling --work-ms 110 --work torch --json bench-out/ceiling-torch.json
# 3. Sama, dengan batas thread
python -m engine.tools.ingest_ceiling --work-ms 110 --work torch --cpu-threads 2 --json bench-out/ceiling-torch-t2.json
# 4. Decode di GPU (NVDEC)
python -m engine.tools.ingest_ceiling --work-ms 110 --work torch --variants latest-auto,latest-cuvid --json bench-out/ceiling-cuvid.json
```

(`--uri` default `rtsp://127.0.0.1:8554/cam01`.) Bacaan:

| Hasil | Artinya | Tindakan |
|---|---|---|
| `sleep` OK, `torch` jatuh di varian `latest-*`, `--cpu-threads 2` memulihkan | **Rebutan thread** decoder vs torch/OpenCV (dugaan utama) | `core.cpu_threads: 2` (coba juga 3–4), lalu B |
| `latest-slice` / `latest-frame2` jauh di atas `latest-auto` | Frame threading decoder | `decoder_thread_type` / `decoder_threads` varian pemenang |
| `latest-cuvid` paling tinggi | Decode CPU itu sendiri mahal | `ingest.hwaccel: "cuda"` |
| `latest-cuvid` GAGAL | PyAV ini tidak bisa HWAccel (perlu PyAV ≥ 14 ber-CUDA) | Catat pesan galatnya; lewati |
| Semua varian dekat harapan | Plafon ada di detector/pipeline, bukan ingest | Langsung B; kirim log ke Engine B |

### B. Engine penuh dengan setelan pemenang

Ulangi langkah 2–3 (mode `latest`) **dua kali**: sekali dengan config apa adanya, sekali dengan setelan pemenang dari A (`core.cpu_threads`, decoder, atau `ingest.hwaccel`). Simpan ke `bench-out/lag-A2-dasar.csv` dan `lag-A2-pemenang.csv`. Log engine saat start mencetak `batas thread CPU: {...}`; pastikan `torch` dan `cv2` berisi angka yang diminta, bukan `None`/`gagal`. Bila `hwaccel: cuda`, log mencetak `decode lewat hwaccel cuda`.

Yang diharapkan: fps naik dari ±4 mendekati angka mode `none`, umur kotak tetap datar. Bila `ingest_ceiling` bilang OK tetapi engine penuh tetap 4 fps, `core.cpu_threads` tetap layak dicoba di engine penuh: beban tiruan hanya mendekati detector sungguhan.

Kolom `drift_s` di CSV = sisa bias offset jam per kamera (`clock_drift_seconds`). Dengan `offset_correction: slew`, angka ini harus turun ke |≤ 0,1| dtk dalam ±20–30 detik pertama lalu diam. Ringkasan probe mencetak `drift awal → akhir`. Bila drift tidak turun, atau turun lalu naik lagi terus, catat dan matikan koreksinya (lihat tombol mundur) untuk run berikutnya.

### C. Rekognisi wajah: async vs sync

Perlu model `scrfd_10g_bnkps.onnx` + `glintr100.onnx` dan minimal satu orang ter-enroll (supaya ada `track.identified`; tanpa enroll, perbandingan fps tetap sah). Salin config dan nyalakan recognizer:

```powershell
Copy-Item engine/config/dfine-m.yaml bench-out/dfine-m-face.yaml
# edit: recognition.enabled: true, recognizer: "onnx_face", dua path model, reference_db_path
# biarkan execution: "async"
Copy-Item bench-out/dfine-m-face.yaml bench-out/dfine-m-face-sync.yaml
# edit file kedua: execution: "sync"
```

Jalankan masing-masing 5 menit dengan probe (`lag-C-async.csv`, `lag-C-sync.csv`). Yang dibandingkan:

- fps analisis: async harus mendekati hasil B; sync diperkirakan turun setiap ada wajah.
- jumlah `identified` di ringkasan probe: async boleh sedikit lebih lambat mengenali (hasil diterapkan satu frame kemudian), tetapi jumlahnya tidak boleh jauh lebih kecil.
- `engine.health`: `queue_depth` tidak boleh terus naik; worker yang mati muncul sebagai `recognition_worker_stopped` dan engine melapor degraded.

### Tombol mundur

Semua perubahan bisa dimatikan dari config tanpa mengganti kode:

| Gejala | Config |
|---|---|
| Identifikasi hilang/aneh dengan async | `recognition.execution: "sync"` |
| `at` event melompat atau drift berayun | `ingest.offset_correction: "none"` |
| Track putus lebih cepat/lambat dari biasanya | `tracker.track_buffer_seconds` (IoU tracker sekarang menghitung detik PTS, bukan jumlah frame) |
| fps turun / aneh setelah membatasi thread | `core.cpu_threads: 0` |
| Engine gagal start atau gambar rusak dengan NVDEC | `ingest.hwaccel: "none"` |

## Yang dikirim balik ke tim

| Uji | Config | Kesimpulan probe | Umur kotak awal → akhir | Lag median | fps | drift awal → akhir | identified | Dashboard menit 1 / 5 |
|---|---|---|---|---|---|---|---|---|
| A | dfine-m (latest) | | | | | | — | — |
| B | tanpa buffer | | | | | — | — | — |
| A2 | latest + setelan pemenang (tulis setelannya) | | | | | | — | — |
| C-async | face, async | | | | | | | — |
| C-sync | face, sync | | | | | | | — |
| D | jalur lengkap | — | — | — | — | — | — | |

Lampirkan juga CSV dan JSON dari `bench-out/`, plus tabel `ingest_ceiling` (salin teks dari terminal).

## Keterbatasan probe

- Umur kotak memakai `at` dari engine. Dengan `offset_correction: slew` bias offset (P18) dikoreksi bertahap, jadi 30 detik pertama angka mutlaknya masih bergeser; baca **pola** setelah kolom `drift_s` diam. Tanpa thread pembaca (`live_buffer: none`) koreksi tidak aktif dan bias lama tetap ada.
- Umur negatif berarti `at` berada di masa depan: sumber diputar lebih cepat dari real-time atau jam berbeda. Probe menyatakan data **tidak valid** dalam kasus itu, bukan "segar".
- `lag_seconds` hanya terlapor dengan `live_buffer: latest`. Tanpa thread pembaca, lag bersembunyi di buffer socket dan hanya terlihat dari umur kotak yang bertambah.
