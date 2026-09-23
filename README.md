# AI Time Tracking System

Sistem pemantauan kehadiran berbasis CCTV dengan proses engine visi, backend
FastAPI, dan frontend Vue yang terpisah. Engine mengirim NDJSON sesuai kontrak;
backend menyimpan event mentah dan menurunkan sesi/gap.

## Persyaratan dan instalasi

- Python 3.11/3.12, Node.js 20+, npm, dan Docker untuk CCTV live

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
pip install -r contracts/validator/requirements.txt
pip install -r engine/requirements-dfine.txt
pip install -r requirements-dev.txt     # hanya untuk testing/development
cd frontend && npm ci && cd ..
```

## Menjalankan

Buka terminal dari root proyek. Untuk CCTV live, siapkan MediaMTX dahulu
sesuai `deploy/README.md`, kemudian jalankan `./deploy/start-mediamtx.ps1` pada
Windows atau `sh deploy/start-mediamtx.sh` pada Linux/macOS. Setelah sehat,
jalankan tiga proses aplikasi:

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

Engine asli menyimpan outbox di `engine/data/outbox.sqlite3` (ubah dengan
`--outbox` atau `ENGINE_OUTBOX_PATH`) supaya nomor urut event bertahan melintasi
restart. Event yang gagal diproses backend tidak memutus koneksi; ia disimpan
dan terlihat di `GET /api/system/dead-letters`.

Tes `engine/tests/test_api.py` memakai Unix socket. Sandbox yang melarang
`AF_UNIX` akan memberi `PermissionError`; jalankan tes tersebut di host Linux/macOS
biasa. Tes runtime in-process dan kontrak tidak memerlukan socket.

Endpoint utama: `/api/system/status`, `/api/cameras`,
`/api/attendance/derived`, `/api/attendance/corrections`, `/api/enrollments`, dan
`/api/detections/stream`.

Proyek belum siap produksi penuh: benchmark rekaman representatif, kebijakan HRD,
autentikasi, TLS, dan hardening deployment masih perlu diselesaikan. Setup MediaMTX
lokal/lapangan dasar tersedia di `deploy/`.
Lihat `WORKPLAN_STATUS.md`.

Detector nyata adalah D-FINE lewat **LibreYOLO** (MIT), bukan
Ultralytics/YOLO. Ukuran dipilih lewat config engine:
`engine/config/dfine-m.yaml` (Medium, default) atau `engine/config/dfine-s.yaml`
(Small). Launcher: `python scripts/run_demo.py --model m` atau `--model s`.
Untuk CI atau demo mock tanpa model, cukup pasang `engine/requirements.txt`;
LibreYOLO hanya dipasang pada mesin engine nyata melalui
`engine/requirements-dfine.txt`.

## Recognizer wajah (slot, default mati)

Engine punya slot recognizer (SCRFD + AuraFace lewat onnxruntime) yang
**dimatikan secara default**. Selama mati, enrollment dijawab
`recognizer_disabled` dan semua track tanpa nama. Untuk menyalakan, di config
engine isi:

```yaml
recognition:
  enabled: true
  recognizer: "onnx_face"
  face_detector_model: "models/scrfd_10g_bnkps.onnx"
  face_embedder_model: "models/auraface_v1.onnx"
```

lalu `pip install -r engine/requirements-face.txt`. Model tidak dibundel. Kalau
diminta tapi tidak bisa dimuat, engine menolak start (tidak jalan diam-diam
tanpa identitas).

## Jatah free time (logika bisnis di backend)

Model: kamera memantau **ruang fasilitas**; waktu karyawan terlihat di sana
memakai jatah harian. Semua angka ada di `backend/configs/policy.yaml`.
Hitungan dilakukan `backend/services/free_time.py` dari **event durabel**
(`presence.interval` + track yang masih terbuka), digabung lintas kamera, dengan
20 detik pertama tiap kunjungan gratis dan jam istirahat resmi tidak dihitung.
Kanal `view` hanya untuk tampilan. Koreksi HR (append-only) langsung diterapkan.

## Mode runtime satu perintah

```bash
python scripts/run_demo.py --mode mock --frontend
python scripts/run_demo.py --mode direct --frontend
python scripts/run_demo.py --mode mediamtx --frontend
```

`mock` tidak memerlukan video atau model nyata. `direct` membuka
`frontend/public/videos/video2.mp4` pada engine dan browser lalu menyelaraskan
bbox melalui PTS. `mediamtx` memakai RTSP untuk engine dan HLS untuk frontend;
launcher melakukan preflight API dan path `cam01` sebelum memulai aplikasi.
Ketiga mode otomatis memilih profil kamera dan memakai D-FINE Medium secara
eksplisit. Opsi `--frontend` ikut menjalankan Vite.

Pada Windows launcher otomatis memakai `npm.cmd` dan menghentikan seluruh proses
dengan process group Windows. Jika muncul `npm tidak ditemukan`, instal Node.js,
buka terminal baru, lalu jalankan `cd frontend; npm ci` sebelum mengulang demo.

## Konfigurasi

- Kamera default: `backend/configs/cameras.yaml`.
- Profil runtime: `cameras.demo.yaml`, `cameras.direct.yaml`, dan
  `cameras.mediamtx.yaml`; launcher mengatur `CAMERAS_CONFIG` otomatis.
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
NDJSON adalah satu-satunya batas runtime. `backend/tests/test_boundary.py`
menggagalkan build jika aturan ini dilanggar (tes integrasi socket dikecualikan).
