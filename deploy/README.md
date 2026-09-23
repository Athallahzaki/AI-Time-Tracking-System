# MediaMTX deployment

Setup ini membuat satu jalur video yang konsisten:

- MediaMTX menarik substream H.264 CCTV sebagai `cam01`.
- Engine membaca `rtsp://127.0.0.1:8554/cam01`.
- Frontend membaca `/whep/cam01/whep` atau `/hls/cam01/index.m3u8` melalui proxy Vite.

## Persyaratan

- Docker Desktop (Windows/macOS) atau Docker Engine + Compose plugin (Linux).
- CCTV dapat dijangkau dari komputer Docker.
- Gunakan substream H.264. MediaMTX melakukan relay/remux dan tidak mengubah H.265 menjadi H.264.

## Setup pertama

Windows PowerShell:

```powershell
Copy-Item deploy/.env.mediamtx.example deploy/.env.mediamtx
notepad deploy/.env.mediamtx
./deploy/start-mediamtx.ps1
```

Linux/macOS:

```bash
cp deploy/.env.mediamtx.example deploy/.env.mediamtx
# edit CAM01_SOURCE dan MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS
sh deploy/start-mediamtx.sh
```

`CAM01_SOURCE` harus berisi RTSP CCTV asli. Jangan commit `.env.mediamtx` karena
berisi username dan password. Jika dashboard dibuka dari perangkat lain, isi
`MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS` dengan IP LAN komputer server.

## Menjalankan seluruh aplikasi

Urutan proses:

1. `./deploy/start-mediamtx.ps1` atau `sh deploy/start-mediamtx.sh`
2. `python -m engine.runtime --config engine/config/dfine-m.yaml --tcp 127.0.0.1:8765`
3. Backend pada port 8000 dengan `ENGINE_HOST=127.0.0.1` dan `ENGINE_PORT=8765`
4. `cd frontend; npm run dev`

Atau, setelah MediaMTX dan `cam01` berstatus READY, jalankan seluruh aplikasi:

```powershell
python scripts/run_demo.py --mode mediamtx --frontend
```

Untuk video lokal tanpa MediaMTX gunakan:

```powershell
python scripts/run_demo.py --mode direct --frontend
```

## Pemeriksaan dan troubleshooting

```bash
python scripts/check_mediamtx.py
docker compose --env-file deploy/.env.mediamtx -f deploy/docker-compose.mediamtx.yml logs -f
```

Hasil sehat harus menunjukkan `Path cam01 : READY`. Endpoint yang tersedia:

- RTSP engine: `rtsp://127.0.0.1:8554/cam01`
- WHEP browser: `http://127.0.0.1:8889/cam01/whep`
- HLS browser: `http://127.0.0.1:8888/cam01/index.m3u8`
- API lokal: `http://127.0.0.1:9997/v3/paths/list`

Jika path `NOT READY`, periksa URL/kredensial CCTV, firewall, dan codec. Jika WHEP
gagal dari PC lain tetapi HLS bekerja, periksa IP `MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS`
dan pastikan UDP 8189 dibuka pada firewall server.

Untuk menghentikan MediaMTX:

```bash
docker compose --env-file deploy/.env.mediamtx -f deploy/docker-compose.mediamtx.yml down
```
