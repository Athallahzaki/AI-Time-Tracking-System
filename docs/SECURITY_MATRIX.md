# Security Matrix

`POST /api/auth/login`, `/`, dan health nginx adalah public. Seluruh API bisnis
lain membutuhkan sesi. Browser menyimpan bearer token untuk REST dan menerima
cookie HttpOnly untuk SSE/HLS/WHEP.

| Domain | Anonymous | Viewer | Admin |
|---|---|---|---|
| Employee read | 401 | employee sendiri | semua |
| Employee mutation | 401 | 403 | diizinkan |
| User management | 401 | 403 | diizinkan |
| Attendance/free-time | 401 | employee sendiri | semua |
| Violations/notifications | 401 | employee sendiri | semua |
| Detection SSE | 401 | box employee sendiri | semua box |
| Notification SSE | 401 | employee sendiri | semua |
| Daily report | 401 | employee sendiri | semua |
| Settings read/write | 401 | terbatas / 403 | diizinkan |
| HR review | 401 | 403 | diizinkan |
| HLS/WHEP/video | 401 | kamera terdaftar | kamera terdaftar |

## Pemeriksaan wajib

- Viewer yang mengirim `person_id` milik orang lain harus menerima 403.
- User disabled harus langsung ditolak walaupun cookie/token belum kedaluwarsa.
- Admin aktif terakhir tidak boleh dinonaktifkan, dihapus, atau diturunkan.
- SSE tanpa token/cookie harus menerima 401 dan queue selalu dibersihkan.
- nginx hanya meneruskan HLS/WHEP/video setelah `auth_request` mengembalikan 204.
- `.env`, password SMTP, token sesi, model weights, dan database tidak boleh
  masuk source control atau paket distribusi.

