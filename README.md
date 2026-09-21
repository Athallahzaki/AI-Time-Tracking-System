# AI Time Tracking System

Sistem pemantauan kehadiran berbasis CCTV dengan proses engine visi, backend
FastAPI, dan frontend Vue yang terpisah. Engine mengirim NDJSON sesuai kontrak;
backend menyimpan event mentah dan menurunkan sesi/gap.

## Persyaratan dan instalasi

- Python 3.11/3.12, Node.js 20+, npm

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
pip install -r contracts/validator/requirements.txt
pip install -r engine/requirements.txt
pip install -r requirements-dev.txt     # hanya untuk testing/development
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

### Menjalankan di Windows PowerShell

Buka tiga PowerShell pada root proyek setelah instalasi di atas:

```powershell
# Terminal 1
.venv\Scripts\Activate.ps1
python -m engine.runtime --config engine/config/default_config.yaml --tcp 127.0.0.1:8765

# Terminal 2
.venv\Scripts\Activate.ps1
$env:ENGINE_HOST = "127.0.0.1"
$env:ENGINE_PORT = "8765"
python -m uvicorn backend.main:app --reload --port 8000

# Terminal 3
cd frontend
npm run dev
```

Jika PowerShell menolak aktivasi virtual environment, jalankan sekali untuk
akun pengguna: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Alternatif
tanpa mengubah policy adalah memanggil `.venv\Scripts\python.exe` langsung.

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

## Mode demo satu perintah

```bash
python scripts/run_demo.py
```

Tambahkan `--frontend` untuk ikut menjalankan Vite. Mode ini memakai
`backend/configs/cameras.demo.yaml`, otomatis reconnect ke engine, lalu mengirim
`set_cameras` dan `set_roster` setiap koneksi baru.

## Konfigurasi

- Kamera: `backend/configs/cameras.yaml`, atau set `CAMERAS_CONFIG` ke YAML lain.
- Kebijakan: `backend/configs/policy.yaml`, atau set `POLICY_CONFIG`.
- Engine: `ENGINE_HOST`, `ENGINE_PORT`, dan `ENGINE_RECONNECT_SECONDS`.
- Pemakaian istirahat: `GET /api/attendance/break-usage?person_id=4471&date=2026-09-20`.

`source_uri` dapat berupa `mock`, path video, atau URL RTSP. Untuk RTSP gunakan
`rtsp://user:password@alamat:554/path` dan jangan commit password produksi.
Nilai `policy.yaml` masih template dan wajib disahkan HRD sebelum dipakai.

`source_uri` selalu dibuka oleh proses engine. Jika engine berada di komputer
berbeda, jangan gunakan path lokal milik backend: gunakan URI jaringan yang bisa
diakses engine atau letakkan MP4 pada mesin engine. `stream_url` sebaliknya dibuka
oleh browser. Lihat `deploy/README.md` sebelum menentukan topologi deployment.

Tidak boleh ada import kode langsung antara `backend` dan `engine`; kontrak TCP
NDJSON adalah satu-satunya batas runtime. Tes arsitektur akan menggagalkan build
jika aturan ini dilanggar.
