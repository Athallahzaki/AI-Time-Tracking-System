# AI Time Tracking System

Sistem pemantauan kehadiran berbasis CCTV dengan proses engine visi, backend
FastAPI, dan frontend Vue yang terpisah. Engine mengirim NDJSON sesuai kontrak;
backend menyimpan event mentah dan menurunkan sesi/gap.

## Persyaratan dan instalasi

- Python 3.11/3.12, Node.js 20+, npm

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\\Scripts\\activate
pip install -r backend/requirements.txt
pip install -r contracts/validator/requirements.txt
pip install -r engine/requirements.txt
cd frontend && npm ci && cd ..
```

## Menjalankan

Buka tiga terminal dari root proyek.

```bash
# Terminal 1: engine
python -m engine.runtime --config engine/config/default_config.yaml --tcp 127.0.0.1:8765

# Terminal 2: backend
ENGINE_HOST=127.0.0.1 ENGINE_PORT=8765 python -m uvicorn backend.main:app --reload --port 8000

# Terminal 3: frontend
cd frontend && npm run dev
```

Buka `http://127.0.0.1:5173`. Dokumentasi API tersedia di
`http://127.0.0.1:8000/docs`. Backend tetap hidup jika engine belum tersedia.
Konfigurasi kamera berada di `backend/configs/cameras.yaml`; start/stop akan
mengirim seluruh `set_cameras` secara deklaratif ke engine.

Untuk mencoba tanpa CCTV/GPU, ubah `source_uri` kamera menjadi `mock` di
`backend/configs/cameras.yaml`, kemudian jalankan engine dan backend dengan
perintah di atas. Pemeriksaan integrasi otomatis tanpa kamera dapat dijalankan
dengan `python scripts/integration_smoke.py`.

## Testing

```bash
python -m pytest -q
python scripts/run_tests.py
cd frontend && npm run build
```

Tes `engine/tests/test_api.py` memakai Unix socket. Sandbox yang melarang
`AF_UNIX` akan memberi `PermissionError`; jalankan tes tersebut di host Linux/macOS
biasa. Tes runtime in-process dan kontrak tidak memerlukan socket.

Endpoint utama: `/api/system/status`, `/api/cameras`,
`/api/attendance/derived`, `/api/attendance/corrections`, `/api/enrollments`, dan
`/api/detections/stream`.

Proyek belum siap produksi penuh: model nyata, benchmark rekaman representatif,
kebijakan HRD, MediaMTX, autentikasi, dan deployment masih perlu diselesaikan.
Lihat `WORKPLAN_STATUS.md`.
