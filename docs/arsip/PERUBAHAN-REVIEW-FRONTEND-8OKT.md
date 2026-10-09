# Perubahan: review frontend 8 Okt + perbaikan backend r5 dipasang ulang

## Temuan

1. **Perbaikan backend r5 tidak ikut terpasang.** Di zip 8 Okt, folder `backend/`
   sama persis dengan zip 6 Okt. Hanya `PERUBAHAN-BACKEND-FRONTEND-PERBAIKAN-REVIEW-6OKT.md`
   dan bagian frontend r5 yang masuk. Akibatnya:
   - POST koreksi masih dijawab daftar sesi aktif, dan koreksi tidak tersimpan;
   - halaman Pengaturan yang baru (PUT /api/settings/policy) akan **menghapus
     semua komentar di policy.yaml** setiap kali disimpan;
   - error evaluasi pelanggaran masih membuat event masuk dead letter;
   - `backend/.gitignore` masih mengabaikan `tests/`;
   - isi email masih berupa epoch mentah, tanpa tautan dashboard.

   File backend r5 dipasang ulang tanpa perubahan. Backend tidak berubah sejak
   6 Okt, jadi tidak ada konflik.
2. **Notifikasi: `read` vs `read_at`.** Backend mengirim `read_at` (epoch/null),
   tetapi frontend membaca `item.read`. Setelah halaman dimuat ulang, semua
   notifikasi terlihat belum dibaca, badge tidak pernah berkurang, dan tombol
   "Tandai dibaca" muncul lagi. Perbaikan di `useNotifications.ts`: `normalize()`
   menurunkan `read` dari `read_at` untuk daftar maupun SSE.

## Yang sudah baik (frontend 8 Okt)

- Login dan guard rute: semua halaman butuh login, `/enrollment` dan `/settings`
  hanya admin.
- Kotak notifikasi (popover) dengan SSE dan badge.
- Halaman Pengaturan (batas jatah, status SMTP, tombol email uji).
- Semua panggilan yang mengubah data memakai `apiFetch` (dengan token).

## Catatan kecil (tidak diubah)

- Menu "Enrollment" dan "Pengaturan Sistem" tetap tampil untuk viewer, lalu
  diam-diam dialihkan ke `/`. Lebih jelas bila disembunyikan (`isAdmin`).
- Nilai awal form pengaturan 60/10 sebelum data termuat. Lebih aman kosong /
  skeleton.

Tes: backend + engine lulus di sandbox (FastAPI 0.135 dari sumber).
`useNotifications.ts` lolos `tsc`. Template belum bisa di-build di sini;
jalankan `npm run build`.
