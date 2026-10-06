# Perubahan: perbaikan bug hasil review backend 6 Okt

Dasar: zip repo 6 Okt (update backend: login, pelanggaran, notifikasi, email,
pengaturan). Isi paket ini juga mencakup paket engine r4 (power throttling),
yang sudah terpasang di repo itu.

## Backend

| # | Bug | Perbaikan |
|---|---|---|
| 1 | `routers/attendance.py`: dekorator `@router.post("/corrections")` nyasar menempel ke `get_active_sessions`. Karena terdaftar lebih dulu, setiap POST koreksi dijawab daftar sesi aktif (200) dan **koreksi tidak pernah tersimpan**. | Dekorator nyasar dihapus. |
| 1b | `routers/enrollments.py`: pola yang sama, membuat rute palsu `POST /api/enrollments/corrections`. | Dihapus. |
| 2 | `services/event_ingestion.py`: error di `violation_service.evaluate_event` membuat event yang sudah tersimpan masuk dead letter, dan `record_event` terlewat. `ingest()` juga tidak lagi mengembalikan `bool`. | Evaluasi dibungkus try/except (error di-log), `return inserted` dikembalikan. |
| 3 | `backend/.gitignore` mengabaikan `tests/`, sehingga tes backend tidak ikut commit. | Baris itu dihapus. |
| 4 | `PUT /api/settings/policy` menulis ulang `policy.yaml` dengan `safe_dump`, sehingga semua komentar HRD hilang (sudah terjadi di repo). | `policy_service._render` hanya mengganti nilai di baris `kunci: nilai`. `policy.yaml` dikembalikan berkomentar, dengan nilai tetap 30 / 5 menit. |
| 5 | Email pelanggaran: waktu ditampilkan sebagai epoch mentah, tidak ada tanggal, pemakaian, atau tautan dashboard (D6). | `EmailService.compose_notification`: ID, tanggal, jam lokal kebijakan, pemakaian "x dari y menit", jenis, tautan `DASHBOARD_URL`. Tanpa foto. |

Koreksi atas review sebelumnya: baris "Jenis" di email ternyata **tidak**
kosong. `save_notification` mengembalikan kunci `type`.

Tes baru `backend/tests/test_demo_backend_fixes.py` (8). Tujuh di antaranya
gagal di kode lama dan lulus di kode baru:

- tidak ada rute ganda;
- POST koreksi lewat HTTP: tanpa token 401, dengan token admin tersimpan;
- ingest tetap jalan walau evaluasi gagal;
- pelanggaran dan notifikasi tercatat sekali per orang per hari;
- komentar policy tetap ada;
- isi email lengkap.

Semua tes backend + engine lulus di sandbox. Catatan: tes di sandbox memakai
FastAPI 0.135 dari sumber; PyPI tidak bisa diakses dari sini.

## Frontend

| # | Bug | Perbaikan |
|---|---|---|
| 6 | `composables/useUnidentifiedAlerts.ts` terhapus, padahal masih di-import `UnidentifiedAlertPanel.vue`, sehingga Vite gagal memuat dashboard. | Dikembalikan dari snapshot 4 Okt (memakai `/api/attendance/active`, endpoint masih ada). |
| 7 | Backend sekarang meminta token admin untuk enrollment dan koreksi, tetapi frontend tidak punya login, sehingga **enrollment dari web 401**. | Login minimal (D7): `composables/useAuth.ts` (token di localStorage, `apiFetch` menambah `Authorization: Bearer`, 401 menghapus sesi), `views/LoginView.vue`, rute `/login`, guard `/enrollment` hanya untuk admin, tombol Masuk/Keluar di topbar. Enrollment dan koreksi memakai `apiFetch`. |

Frontend tidak bisa di-build di sandbox (npm diblokir). Bagian `<script>`
sudah diperiksa dengan TypeScript, tetapi template belum. Wajib jalankan
`npm run build` dan coba di browser.

## Cara pakai

```powershell
# .env / env sesi: admin pertama dibuat saat backend start
$env:INITIAL_ADMIN_PASSWORD = "minimal-8-karakter"
python -m pytest backend/tests engine/tests -q
cd frontend; npm run build; cd ..
python scripts/run_demo.py --mode mediamtx --engine-config engine/config/demo-4060.yaml --frontend
```

Buka `http://localhost:5173/enrollment`: diarahkan ke login, masuk sebagai
`admin`, lalu enroll seperti biasa.

## Belum dikerjakan (bukan bug, tapi masih kurang untuk demo)

- Kotak pesan di frontend (SSE `/api/notifications/stream` + badge) dan halaman
  pengaturan (batas jatah, tombol email uji). Backend-nya sudah ada.
- Endpoint GET (pelanggaran, notifikasi, daftar enrollment, policy) masih
  terbuka tanpa login. Tutup sebelum pilot.
- Email gagal kirim tidak dicoba ulang atau dicatat.
- `break_policy.classify` / `SessionDeriver` (model gap lama) hanya dipakai tes.
  Kandidat dihapus.
