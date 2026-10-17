# End-to-End Checklist (Windows)

## 1. Siapkan dependency

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
pip install -r engine\requirements-dfine.txt
pip install -r requirements-dev.txt
cd frontend
npm ci
cd ..
```

Salin `.env.example` menjadi `.env`, kemudian isi admin pertama. Jangan commit
`.env`. Untuk HTTPS deployment set `AUTH_COOKIE_SECURE=true`.

## 2. Regression

```powershell
python scripts\run_tests.py
python scripts\integration_smoke.py
cd frontend
npm run build
cd ..
```

## 3. Demo direct MP4

```powershell
python scripts\run_demo.py --mode direct --model m --frontend
```

Login, lalu verifikasi video bergerak, bounding box mengikuti PTS video, timer
baru menagih setelah 20 detik, dan official break tidak ditagih.

## 4. Demo MediaMTX

Terminal 1:

```powershell
.\deploy\mediamtx\start-mediamtx.ps1
```

Terminal 2:

```powershell
.\scripts\publish_test_video.ps1 -Video .\frontend\public\videos\video2.mp4
```

Terminal 3:

```powershell
python scripts\run_demo.py --mode mediamtx --model m --frontend
```

Untuk menguji nginx `auth_request`, gunakan compose:

```powershell
cd deploy
Copy-Item .env.example .env
docker compose --profile mediamtx up -d --build
```

Ekspektasi: tanpa login `/hls/...`, `/whep/...`, dan `/videos/...` mendapat
401; setelah login browser menerima cookie HttpOnly dan stream dapat dimainkan.

## 5. SMTP nyata

Isi credential hanya di `.env`, aktifkan `SMTP_ENABLED=true`, lalu gunakan
`POST /api/settings/email/test`. Setelah berhasil, picu satu violation dan satu
daily report. Periksa inbox employee, CC HR, attachment XLSX, spam, dan log.

Atau jalankan ketiga pemeriksaan sekaligus dari terminal yang sudah memuat env:

```powershell
python scripts\smtp_smoke.py --person-id EMP-001
```

