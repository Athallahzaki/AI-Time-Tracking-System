# Frontend — AI Time Tracking System (CCTV)

Vue 3 + TypeScript + Vite + Tailwind 4 + shadcn-vue (reka-ui).

```bash
npm ci
npm run dev      # http://localhost:5173, /api diproksikan ke 127.0.0.1:8000
npm run build    # vue-tsc + vite build
```

## Halaman

| Path | Peran | Isi |
|---|---|---|
| `/` | admin | Dashboard live (kamera, jatah, alert, koreksi manual) |
| `/employees` | admin | Data karyawan: tambah/ubah, nonaktifkan (hapus referensi wajah), **Buat akun** |
| `/enrollment` | admin | Enrollment wajah, karyawan dipilih lewat **combobox** (`?employee=<uid>` untuk pilihan awal) |
| `/users` | admin | Manajemen pengguna: tambah admin, ubah peran, nonaktifkan, reset password |
| `/reports` | admin | Report free time per karyawan per hari + **Export Excel** |
| `/reviews` | admin | Antrean tinjauan HR (pelanggaran dominan ReID) |
| `/settings` | admin | Tab: jatah, jam istirahat per hari, jadwal engine, email rekap, riwayat |
| `/me` | viewer | Pemakaian free time hari ini + notifikasi milik sendiri |
| `/change-password` | semua | Ganti password; dipaksa bila `must_change_password` |

Peran: **admin = HR** (semua menu), **viewer = akun karyawan** (dok. 12 §3.2). Guard di
router hanya kenyamanan UI; penyaringan data sesungguhnya wajib di backend (dok. 12 §3.8).

## Mode data: backend asli vs simulasi

Banyak endpoint fitur dok. 12 belum ada di backend. Semua panggilan baru lewat
`src/api/*` dengan pengganti simulasi di `src/api/mock/`.

| `VITE_API_MODE` | Perilaku |
|---|---|
| `auto` (bawaan) | Coba backend. Bila route belum ada (FastAPI `404 {"detail":"Not Found"}` / `405`), domain itu pindah ke data simulasi. Bila route pertama di domain itu ada, domain dikunci ke backend dan endpoint lain yang belum ada menampilkan error jelas (tidak dicampur data palsu). |
| `mock` | Selalu simulasi (login tetap lewat backend). |
| `real` | Tidak pernah simulasi. Pakai ini untuk uji integrasi. |

Halaman yang memakai data simulasi menampilkan banner ungu **"Data simulasi"**. Data simulasi
disimpan di `localStorage` browser; reset di **Pengaturan → Riwayat → Reset data simulasi**.

Cadangan yang memakai endpoint lama yang **sudah ada**:

- "Buat akun" → `POST /api/auth/users` (peran viewer, username = ID karyawan).
- Pemakaian viewer → `GET /api/attendance/break-usage?person_id=<ID karyawan>`.
- Export Excel → file dibuat di browser (`src/lib/xlsx.ts`) dengan akhiran `-simulasi`
  bila data report juga simulasi. Begitu `GET /api/reports/daily.xlsx` ada, file dari BE
  yang diunduh (dok. 12 §3.5: satu generator di BE).

## Kontrak API yang ditunggu dari backend

Nama field mengikuti `src/api/types.ts`.

| Domain | Endpoint |
|---|---|
| employees | `GET /api/employees?q=&status=&division=` → `{items}`; `POST /api/employees`; `PATCH /api/employees/{uid}`; `POST /api/employees/{uid}/activate\|deactivate`; `POST /api/employees/{uid}/account` → `{username, temporary_password}` |
| users | `GET/POST /api/auth/users` (ada); `PATCH /api/auth/users/{id}` `{role?, enabled?}`; `POST /api/auth/users/{id}/reset-password` → `{temporary_password}` |
| auth | `GET /api/auth/me` + `employee_uid, employee_id, name, must_change_password`; `POST /api/auth/change-password` `{old_password, new_password}` |
| break-hours | `GET /api/settings/break-hours` → `{current:{effective_from,days}, pending}`; `PUT` `{days}` (berlaku besok); `DELETE /api/settings/break-hours/pending` |
| engine-schedule | `GET/PUT /api/settings/engine-schedule` `{days:{mon:{enabled,start,end},…}}`; GET + `now_active, next_change_at` |
| email-config | `GET/PUT /api/settings/email/recap` `{recap_recipients[≤20], recap_send_time}`; GET + `default_from_env` |
| settings-audit | `GET /api/settings/audit?limit=` → `{items:[{id,at,actor,setting,old_value,new_value}]}` |
| reports | `GET /api/reports/daily?from&to&division&employee_uid&status&page&size` → `{summary, items, total}`; `GET /api/reports/daily/{uid}/{date}/visits` → `{items}` |
| reports-xlsx | `GET /api/reports/daily.xlsx?(filter sama)` → file, nama dari `Content-Disposition` |
| reviews | `GET /api/reviews?status&from&to` → `{items}`; `GET /api/reviews/{id}`; `POST /api/reviews/{id}/decision` `{decision: confirm\|reject, note}` |
| me | `GET /api/me/usage-today` (karyawan ditentukan dari sesi, bukan parameter) |
| stream deteksi | field opsional baru per kotak: `identity_source` (`face\|tracking\|reid\|reid_retro`) |

Hari dalam jadwal memakai kunci `mon tue wed thu fri sat sun`; jam `"HH:MM"`.

## Interpolasi kotak

`src/composables/useBoxInterpolation.ts` (dok. 12 §3.7). Kotak di-lerp per `track_uuid`
antar dua frame analisis; track baru tidak diinterpolasi; track hilang ditahan ≤ 0,3 dtk;
celah > 0,5 dtk atau lompatan > 25% frame → tanpa interpolasi. Bandingkan dengan
`?interp=0` di URL dashboard.

Butuh `track_uuid` (atau `track_id` stabil) di setiap kotak. Kotak tanpa ID stabil tetap
tampil, tetapi tidak diinterpolasi.
