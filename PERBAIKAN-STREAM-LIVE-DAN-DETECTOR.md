# Perbaikan: stream live (MediaMTX) dan biaya detector

Gejala yang diperbaiki: video WebRTC di browser lancar, tapi bounding box
patah-patah dan telat. Log MediaMTX: `reader is too slow, discarding N frames`.
Engine: `PTS went backwards`.

## Akar masalah

1. **Engine membaca RTSP di thread yang sama dengan inferensi.** Selama detector
   berjalan, socket tidak dibaca, antrean kirim MediaMTX penuh, lalu paket dibuang
   di tengah GOP. Decoder menerima bitstream bolong.
2. **Frame yang dibuang decimation tetap dikonversi YUV→BGR resolusi penuh.**
   Di 30→12 fps, ~2,5 konversi 1080p (6 MB tiap frame) per frame yang dianalisis
   langsung dibuang. Ini sebagian besar dari `source_ingest` 50 ms di RTX 4060.
3. **Preprocessing LibreYOLO untuk D-FINE berjalan di CPU via PIL pada resolusi
   penuh**: 4–5 salinan 1080p per frame sebelum resize. Ini sebagian besar dari
   "detector" 110 ms di RTX 4060 (dicek langsung di kode LibreYOLO 1.6.0).
4. **`half: true` tidak berpengaruh.** LibreYOLO mengabaikan `half=` (no-op), dan
   `quantize(recipe="fp16")` tidak mendukung keluarga D-FINE.
5. **ByteTrack tidak pernah menerima kotak skor rendah** (P8): model dipanggil
   dengan `conf=0.50`, jadi asosiasi tahap kedua ByteTrack selalu kosong.
6. **Profil runtime `dfine-*.yaml` punya `reconnect_attempts: 0`**, sehingga RTSP
   yang putus sedetik mati permanen. README juga menyuruh menjalankan runtime
   dengan `default_config.yaml`, yaitu baseline bench 30 fps.

## Perubahan

| File | Isi |
| --- | --- |
| `engine/ingest/pyav_source.py` | `LazyFrame`: piksel BGR baru dibuat saat `frame.image` disentuh. Mode `live_buffer: latest` untuk stream jaringan: reader thread menguras dan men-decode stream dengan kecepatan kamera, menyimpan satu frame terbaru, dan menangani reconnect. Frame yang terlewat dihitung di `describe()["live_reader"]`. File lokal tidak berubah perilaku. |
| `engine/perception/dfine_detector.py` | `pre_resize`: resize ke `image_size²` dengan OpenCV INTER_AREA sebelum LibreYOLO, lalu kotak dipetakan balik pada objek `Results` (yang juga dimakan ByteTrack). `half` sekarang benar-benar FP16 via `torch.autocast`, dengan peringatan di GPU Pascal. `raw_confidence`: model diminta kotak sampai batas bawah ByteTrack, sedangkan `detect()` tetap memfilter di `confidence_threshold`. Kwarg no-op (`half`, `verbose`) tidak dikirim lagi. |
| `engine/factory.py` | Meneruskan `live_buffer` dan `pre_resize`. `raw_confidence=0.1` hanya kalau tracker = bytetrack. |
| `engine/config/schema.py`, `loader.py` | Field baru `ingest.live_buffer` (default `none`) dan `detector.pre_resize` (default `false`), dengan validasi. |
| `engine/config/dfine-{m,s,m-bytetrack}.yaml` | `live_buffer: latest`, `reconnect_attempts: 10`, `pre_resize: true`. |
| `engine/config/dfine-n.yaml`, `default_config.yaml` | `live_buffer: latest` (hanya berlaku untuk jaringan), `pre_resize: false` supaya baseline bench tidak bergeser. |
| `README.md` | Perintah runtime memakai `dfine-m.yaml`, bukan `default_config.yaml`. |
| `engine/tests/test_live_ingest_and_detector_prep.py` | 17 tes baru. |
| `engine/tests/test_b4_ingest.py` | Tes reformatter sekarang menyentuh `frame.image`, karena konversi kini lazy. |

Hasil tes: seluruh `contracts/tests` dan `engine/tests` lulus.

## Yang harus diverifikasi di mesin kalian

Saya tidak punya GPU, PyAV, atau LibreYOLO asli di lingkungan kerja. Logikanya
diuji dengan fake, tapi angka performa dan akurasi harus kalian ukur sendiri.

1. **Bench ulang di 4060**, dengan video dan config yang sama seperti sebelumnya:
   `python -m engine.bench --config engine/config/dfine-m-bytetrack.yaml --source <video 1080p> --mode throughput --label prep`.
   Bandingkan `source_ingest` dan `detector` dengan run lama (50 ms / 112 ms).
2. **Akurasi pre_resize**: di CPU saya, beda piksel rata-rata 1,35/255
   (p99 8/255) dibanding resize PIL, sementara preprocessing 1080p turun dari
   ~39 ms ke ~10 ms. Bandingkan jumlah deteksi dan kotaknya pada klip yang sama
   dengan `pre_resize: true` dan `false`.
3. **FP16 di 4060**: setel `half: true`, bench lagi, dan pastikan deteksinya
   tidak berubah berarti. Jangan aktifkan di 1060.
4. **Live**: jalankan `python -m engine.runtime --config engine/config/dfine-m.yaml --tcp 0.0.0.0:8765`
   dengan MediaMTX. Kriteria lulus: tidak ada lagi `reader is too slow` dan
   `PTS went backwards` ≈ 0. Saat engine berhenti, log menunjukkan berapa frame
   yang di-decode, diambil, dan dilewati.
5. **ByteTrack**: perilakunya berubah karena tahap kedua sekarang hidup. Track
   seharusnya lebih jarang putus saat orang teroklusi. Bandingkan umur track
   sebelum dan sesudah.

## Yang belum dikerjakan

- **Sinkronisasi box vs video WebRTC di frontend.** Jalur box tetap lebih lambat
  daripada video. Perlu PTS/`requestVideoFrameCallback`, `jitterBufferTarget`,
  atau interpolasi per track ID.
- NVDEC, TensorRT, dan overlap decode/inferensi di thread terpisah untuk file.
