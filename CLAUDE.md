# Instruksi untuk Claude — AI Time Tracking System (CCTV)

File ini dibaca otomatis di awal setiap sesi. Isinya aturan tetap; status kerja
ada di `docs/SERAH-TERIMA.md`. Ubah file ini hanya bila kesepakatan tim berubah.

## Mulai sesi

1. Baca `docs/SERAH-TERIMA.md` (status terakhir, langkah berikutnya).
2. Baca `docs/PETA-KODE.md` untuk menemukan file; jangan menjelajah repo.
3. Baca hanya file yang disebut tugas atau peta. Cari dengan grep dulu.

Jangan baca kecuali tugas memintanya: `docs/arsip/`, `frontend/package-lock.json`,
`docs/ARCHITECTURE.md` (74 KB, sebagian usang), dan `bench/`. `docs/CHANGELOG.md`
besar: baca hanya ±60 baris teratas, tambahkan entri baru di atas, jangan potong isinya.

## Proyek dan jalur

Sistem pemantauan free time karyawan dari 5 CCTV (luar, lobby, smoking, ruang
hiburan, biliar). Engine (Python, visi) → TCP NDJSON → backend (FastAPI, SQLite)
→ frontend (Vue). Jalur: **EA** kontrak, identitas, ReID, stabilitas operasional;
**EB** deteksi, tracker, struktur engine, performa; **BE** backend; **FE** frontend;
**COM** penghubung klien. Kesepakatan lingkup: dokumen tim 12; timeline: dokumen 14;
desain struktur engine: dokumen 04 §14. Kerjakan hanya jalur yang diminta tugas.

## Aturan keras

- Tidak ada import langsung `engine/` ↔ `backend/`; kontrak TCP adalah satu-satunya
  batas (`backend/tests/test_boundary.py`).
- Tidak ada kebijakan perusahaan di `engine/` (`python contracts/tools/policy_grep.py engine/`).
- Pesan engine ↔ backend mengikuti `contracts/schema/`. Mengubah skema = perubahan
  kontrak: catat di SERAH-TERIMA sebagai keputusan yang perlu disetujui EA.
- `engine/ports/` milik bersama EA–EB: jangan ubah tanpa disebut di tugas.
- Perilaku default tidak berubah diam-diam: fitur baru di belakang flag/config,
  default lama, kecuali tugas memintanya.
- Jangan pernah menambahkan ke repo: bobot model, video/rekaman, database
  (`*.sqlite3`, `*.db`, termasuk `engine/data/references.sqlite3`), `.env`, `stack.env`.

## Konvensi

- Bahasa Indonesia untuk dokumen, komentar baru, pesan log baru, dan nama tes baru.
- Line ending CRLF untuk semua file teks, **kecuali `*.sh` (LF)**.
- Setiap perubahan kode: satu entri baru di atas `docs/CHANGELOG.md` (tanggal ·
  paket — judul; apa yang berubah, alasan, file tersentuh, cara uji).
- Tidak ada file catatan baru di root (`PERUBAHAN-*.md` sudah dihentikan).
- File baru atau modul pindah → perbarui `docs/PETA-KODE.md`.
- Keluaran: **zip berisi hanya file yang berubah/baru, dengan struktur repo**,
  dinamai `<jalur>_<tanggal>-r<N>_<ringkas>.zip`. Zip tidak bisa memindah/menghapus
  file: untuk itu sertakan skrip `git mv`/`git rm` sekali jalan (contoh: paket r8).
  Jangan push ke repo kecuali tugas memintanya.

## Tes (jalankan yang relevan saja, keluaran dipangkas)

- Engine: `python -m pytest engine/tests -q 2>&1 | tail -5` (atau satu file tes)
- Backend: `python -m pytest backend/tests -q 2>&1 | tail -5`
- Kontrak: `python -m pytest contracts/tests -q 2>&1 | tail -5`
- Frontend: `cd frontend && npm run build 2>&1 | tail -15`
- Batas engine: `python contracts/tools/policy_grep.py engine/`

Lingkungan cloud tidak punya GPU, Windows, kamera, MediaMTX, atau NetBird. Tes yang
butuh itu dilewati; tulis langkah uji manualnya di SERAH-TERIMA untuk dijalankan
di laptop.

## Hemat konteks

- Grep/baca sebagian, jangan `cat` file besar. Keluaran perintah selalu dipangkas.
- Tugas di luar lingkup yang ditemukan di jalan: catat di SERAH-TERIMA, jangan
  dikerjakan.
- Kalau tes yang sama gagal dua kali dengan cara yang sama, berhenti dan laporkan
  dugaan penyebabnya; jangan terus mencoba.

## Akhir sesi (wajib)

1. Tulis ulang `docs/SERAH-TERIMA.md` (maks. ±40 baris): selesai, belum, keputusan
   yang perlu disetujui, uji manual di laptop, langkah berikutnya.
2. Entri `docs/CHANGELOG.md` dan pembaruan `docs/PETA-KODE.md` bila perlu.
3. Ketiganya ikut masuk zip keluaran.
