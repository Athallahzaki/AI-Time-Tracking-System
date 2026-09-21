# Deployment

Folder ini sengaja belum mengunci satu topologi deployment. Engine, backend, dan
frontend adalah proses terpisah; backend berkomunikasi dengan engine hanya lewat
TCP NDJSON dan frontend hanya lewat HTTP/SSE backend.

Sebelum menambahkan Docker Compose, MediaMTX, service Windows, atau service
Linux, tentukan terlebih dahulu:

1. ketiga proses berjalan di satu komputer atau komputer berbeda;
2. video hanya untuk demo MP4 atau juga RTSP/CCTV;
3. browser memakai file statis, HLS, atau WebRTC untuk menampilkan video;
4. alamat jaringan, TLS, autentikasi, dan penyimpanan rahasia;
5. target operasi utama: Windows, Linux, atau keduanya.

MediaMTX tidak dibutuhkan untuk demo MP4 yang disajikan frontend sebagai file
statis. MediaMTX baru relevan jika sumber live perlu diubah menjadi HLS/WebRTC
yang dapat diputar browser.

## Aturan lintas mesin

- `source_uri` dibuka oleh **mesin engine**, bukan backend.
- Path relatif/absolut MP4 harus tersedia di mesin engine.
- Untuk mesin berbeda, gunakan URI RTSP/HTTP yang dapat dijangkau engine atau
  salin video ke mesin engine; jangan berbagi path source-code antar proses.
- `stream_url` dibuka oleh browser dan harus dapat dijangkau dari komputer
  pengguna.
- Jangan menaruh kredensial RTSP dalam berkas yang di-commit.
