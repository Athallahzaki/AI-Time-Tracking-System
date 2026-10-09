# Engine bisa dihentikan: Ctrl+C, `q` + Enter, dan penjaga waktu (3 Okt 2026)

Ekstrak di root proyek di atas paket `perbaikan-onnxruntime-cuda12-pascal_tolak-rekognisi-diam-diam-cpu`.
Verifikasi: 489 tes lulus, integration smoke lulus.

## Gejala (Windows)
`python -m engine.runtime` tidak berhenti dengan Ctrl+C.

## Penyebab yang ditangani
1. Berhenti rapi bisa macet tanpa batas waktu:
   - thread kamera masih memuat model (±55 dtk di 1060);
   - thread terjebak di panggilan native (FFmpeg menunggu RTSP, CUDA, onnxruntime);
   - `camera.stop` menunggu 10 dtk per kamera.
2. Setelah `main()` selesai, finalisasi interpreter bisa menggantung di Windows karena thread daemon
   masih berada di dalam kode native. Selama finalisasi, handler Ctrl+C tidak jalan lagi.
3. Ctrl+C kadang tidak sampai ke Python di Windows:
   - pustaka native memasang penangan konsol sendiri;
   - jendela konsol dalam mode seleksi (QuickEdit) membekukan proses saat menulis log.

## Perbaikan (`engine/runtime/__main__.py`)
- Satu jalur berhenti (`_Stopper`):
  - Permintaan pertama: berhenti rapi di thread terpisah, plus penjaga waktu 20 dtk yang memaksa keluar
    bila rapi-nya macet.
  - Permintaan kedua: keluar paksa saat itu juga.
- Sumber permintaan berhenti: SIGINT (Ctrl+C), SIGTERM, SIGBREAK (Ctrl+Break di Windows), dan perintah
  terminal `q` / `quit` / `exit` / `stop` diikuti Enter.
- Setelah berhenti rapi, proses keluar dengan `os._exit` (log di-flush dulu), tanpa finalisasi
  interpreter yang bisa menggantung.

## Tes
`engine/tests/test_engine_shutdown.py` (3), termasuk proses engine sungguhan yang harus keluar dengan kode 0
setelah SIGINT.
