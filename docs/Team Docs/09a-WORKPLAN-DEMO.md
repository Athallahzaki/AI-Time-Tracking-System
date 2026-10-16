# 09a — Workplan Demo (Dadakan)

Versi 1.1 · diperbarui 8 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan) · Internal tim (versi 1.0: 28 September 2026)

Dokumen ini **tidak menggantikan** workplan utama (dokumen 09). Isinya jalur cepat untuk memenuhi permintaan demo klien. Semua pekerjaan di sini dipilih supaya **tidak dibuang** setelah demo: setiap item adalah potongan awal dari pekerjaan di workplan utama.

> **Status per 8 Oktober 2026.** Dokumen ini dipertahankan sebagai **rencana demo historis**. Bagian yang tidak berlaku lagi tidak dihapus, tetapi diberi catatan **"Diganti oleh"**. Arah prototype sesudah demo ada di dokumen 12; daftar perbedaannya di dokumen 13. Panduan demo jarak jauh yang berlaku ada di `docs/DEMO-REMOTE.md`.

## 1. Permintaan klien

Demo minimal menunjukkan:

1. Video berjalan **lewat MediaMTX** (bukan file langsung di browser).
2. Sistem **mendeteksi karyawan yang melewati batas waktu**, dengan batas yang **bisa diatur lewat konfigurasi** (30 menit untuk produksi, lebih singkat untuk demo).
3. Pelanggaran **ditampilkan di dashboard** (kotak pesan) dan **dikirim lewat email**; pengaturan email dapat diubah kemudian.

## 2. Asumsi

| Topik | Asumsi |
|---|---|
| Tanggal demo | Belum ditetapkan; rencana dihitung **10 hari kerja (±2 minggu)**. Bila lebih singkat, pakai urutan prioritas §6 |
| Jumlah kamera di demo | 1 (maksimal 2) lewat MediaMTX |
| Sumber video | Rekaman yang di-publish ke MediaMTX dengan ffmpeg (loop), atau 1 kamera nyata bila tersedia. Sejak gladi 8 Oktober: ffmpeg dipaksa `-r 25`, tanpa audio, `yuv420p`, tanpa B-frame (DEMO-REMOTE §3.3) |
| Orang yang dikenali | 2–3 anggota tim yang di-enroll |
| Batas waktu saat demo | 2–3 menit (diatur di config/halaman pengaturan), lalu ditunjukkan bahwa nilai produksi 30 menit |
| Penerima email | Daftar penerima global (belum per supervisor). **Diganti oleh** dokumen 12 §3.4: email per pelanggaran ke karyawan + CC HR (HR saja bila karyawan tanpa email), dan rekap harian ke daftar HR yang diatur dari web |
| Server | Mesin pengembang dengan GPU; boleh satu mesin untuk demo. **Diperbarui:** demo jarak jauh memakai engine + MediaMTX + ffmpeg di laptop (Windows), backend + frontend di server Portainer CE, tersambung lewat NetBird; penonton lewat Cloudflare → VPS (DEMO-REMOTE; dokumen 12 §6) |

## 3. Lingkup

**Masuk demo:**

| # | Item | Area | Kaitan workplan utama |
|---|---|---|---|
| D1 | Recognizer ONNX (SCRFD + AuraFace) menyala di engine asli; enrollment 2–3 orang lewat web; orang dikenali di video dari MediaMTX. Catatan: profil demo di repo (`demo-4060.yaml`, `demo-1060.yaml`) memakai embedder `glintr100.onnx`, sesuai komponen di dokumen 12 §1 | EA, EB | Minggu 3 (recognizer), keputusan SCRFD P20 |
| D2 | Jalur MediaMTX: video → MediaMTX → engine (RTSP) dan browser (WHEP/HLS); overlay tampil. **Diperbarui:** pada demo jarak jauh, **HLS menjadi default** (tembus Cloudflare); WebRTC opsional lewat TCP 8189 di IP publik VPS (DEMO-REMOTE §2, §7) | EB, FE, OPS | Minggu 2 (dua path), P19 |
| D3 | Batas jatah dari konfigurasi (`policy.yaml`) dan dapat diubah dari halaman pengaturan admin | BE, FE | P6, kebijakan berversi |
| D4 | Deteksi pelanggaran: saat pemakaian melewati batas, buat rekaman `violation` satu kali per karyawan per hari | BE | Minggu 4 (alerts) |
| D5 | Kotak pesan dashboard: notifikasi tersimpan, belum/sudah dibaca, dikirim real-time lewat SSE; badge jumlah belum dibaca | BE, FE | Minggu 4 (`notify` adapter dashboard) |
| D6 | Email: adapter SMTP; halaman pengaturan berisi konfigurasi SMTP, daftar penerima, tombol "kirim email uji"; email berisi nama, tanggal, pemakaian, tautan dashboard (tanpa foto). **Diganti oleh dokumen 12 §3.4:** penerima global tidak lagi dipakai untuk email pelanggaran; email pelanggaran ke karyawan + CC HR, rekap harian ke daftar HR (maks. 20, disimpan di database, `SMTP_TO` jadi nilai bawaan) | BE, FE | Minggu 4 (`notify` adapter email) |
| D7 | Login minimal: tabel `users` dengan kolom `role` (`admin`, `viewer`), password di-hash, sesi; halaman pengaturan hanya untuk admin; nginx berhenti menyuntikkan kunci API. **Arti peran diubah oleh dokumen 12 §3.2:** admin = HR (semua akses); viewer = **akun karyawan** yang hanya melihat notifikasi dan pemakaian free time miliknya hari ini, bukan staf yang melihat dashboard. Catatan: per repo 8 Oktober, template nginx (`deploy/frontend/nginx/templates/default.conf.template`) masih menyuntikkan `X-API-Key` untuk `/api/`; pengerasan akses mengikuti dokumen 12 §3.8 | BE, FE, OPS | Minggu 2 (auth, P1) — fondasi RBAC |
| D8 | Koneksi tahan gangguan: read timeout backend + pemutusan koneksi lama di handshake engine | EA, BE | Minggu 2 (P2) |
| D9 | Overlay tidak menampilkan kotak basi (toleransi ±1 detik). **Diperbarui:** paket r7 memperbaiki kotak hantu (overlay hanya track aktif + LOST ≤ 0,3 detik); kehalusan kotak kini lewat interpolasi di frontend (dokumen 12 §3.7) | FE | P16 |

**Tidak masuk demo (tetap di workplan utama):** RBAC penuh (peran HR/supervisor, pembatasan data per tim), data master karyawan dengan relasi supervisor dan email per supervisor, kategori lokasi dan pengecualian, ledger kunjungan dengan ID stabil, koreksi HR versi baru, 5 kamera + TensorRT/batching, frame terbaru + fps adaptif, koreksi drift, laporan terjadwal, pilot.

> **Catatan 8 Oktober 2026:** sebagian butir di atas kini masuk lingkup prototype (dokumen 12): data master karyawan **dengan email** (tanpa relasi supervisor; relasi supervisor dan peran HR/supervisor terpisah menjadi kandidat, dokumen 12 §4), rekap harian terjadwal dengan `.xlsx`, report, 5 kamera ≥ 6 fps, dan ReID berjangkar wajah.

### Status item demo per 8 Oktober 2026

Hanya yang tercatat di dokumen 12, 13, dan DEMO-REMOTE. Item lain **belum tercatat statusnya** di sumber tersebut.

| # | Status tercatat | Sumber |
|---|---|---|
| D1 | Profil demo memakai SCRFD + glintr100; uji rekognisi dengan model nyata di rekaman lokasi belum ada (akses CCTV/rekaman belum tersedia) | Repo; dok. 12 §8 |
| D2 | Gladi laptop 4060 (satu kamera) lulus: 10,00 fps, 0 drop, umur kotak p99 0,09 detik; demo jarak jauh memakai HLS default | Dok. 13 §4; DEMO-REMOTE §8 |
| D3 | Perubahan batas dari pengaturan tersimpan di volume `/data`, tidak hilang saat redeploy | DEMO-REMOTE §6 |
| D6 | Email memuat tautan dashboard (paket r6); penerima masih dari env `SMTP_TO`, tampil read-only di pengaturan | DEMO-REMOTE §0; dok. 13 §2 |
| D7 | Peran `admin`/`viewer` ada; arti viewer diubah (lihat D7) | Dok. 13 §2 |
| D9 | Kotak hantu diperbaiki di r7 | Dok. 13 §4 |

## 4. Rencana per hari kerja

| Hari | EA | EB | BE | FE |
|---|---|---|---|---|
| 1 | Pasang model AuraFace + SCRFD; cek hash SCRFD (P20); nyalakan `recognizer: onnx_face` | Publish rekaman ke MediaMTX (ffmpeg `-re -stream_loop -1 -bf 0`; sejak 8 Oktober ditambah `-r 25`); engine membaca RTSP | Skema: `users`, `violations`, `notifications`, `settings` (SMTP, penerima, batas) + migrasi | Halaman login; kerangka router |
| 2 | Enrollment end-to-end lewat web dengan model nyata | Pastikan resolusi wajah cukup di video demo; pilih/rekam video dengan wajah jelas | Login + sesi + dependency `require_admin`; nginx tanpa injeksi kunci | Halaman pengaturan (batas, SMTP, penerima) |
| 3 | Uji pengenalan 2–3 orang di video MediaMTX; catat similarity | Ukur fps dan lag 1–2 stream di mesin demo | Batas jatah dibaca dari `settings` (fallback `policy.yaml`) | Kotak pesan (daftar, badge, tandai dibaca) |
| 4 | Pemutusan koneksi lama di handshake + timeout kirim (D8) | Bantu D8 di sisi engine; stabilitas reconnect RTSP | Deteksi pelanggaran (D4) dari ledger yang ada | SSE notifikasi → kotak pesan real-time |
| 5 | Buffer / perbaikan | Buffer / perbaikan | Adapter email SMTP + tombol email uji (D6) | Toleransi overlay (D9) |
| 6 | **Integrasi penuh pertama**: video → MediaMTX → engine → backend → dashboard + email | ← | ← | ← |
| 7 | Perbaiki temuan integrasi | ← | Read timeout backend (D8); log dan pesan error yang jelas | Tampilan status koneksi sederhana (terhubung/menyambung/pemanasan) |
| 8 | Latihan demo #1 dengan skrip §5; catat semua kendala | ← | ← | ← |
| 9 | Perbaikan dari latihan #1; siapkan cadangan (§7) | ← | ← | ← |
| 10 | Latihan demo #2 (gladi bersih) di perangkat dan jaringan yang akan dipakai; **bekukan versi** | ← | ← | ← |

Panah (←) berarti seluruh tim mengerjakan bersama.

## 5. Skenario demo (usulan)

1. Login sebagai admin; tunjukkan halaman pengaturan: batas jatah (setel ke 2 menit untuk demo, jelaskan nilai produksi 30 menit), SMTP, penerima email.
2. Tunjukkan enrollment satu anggota tim lewat web (atau tunjukkan yang sudah terdaftar).
3. Buka monitoring: video dari MediaMTX dengan overlay; orang dikenali dan diberi nama.
4. Tunjukkan pemakaian berjalan di dashboard jatah.
5. Saat melewati batas: notifikasi muncul di kotak pesan secara real-time, lalu email masuk ke kotak surat penerima (tampilkan di layar).
6. Ubah daftar penerima email di pengaturan, picu email uji, tunjukkan bahwa penerima baru menerimanya. **Catatan:** pada build demo, penerima diambil dari env `SMTP_TO` dan tampil read-only, sehingga langkah ini tidak bisa diperagakan. Pengaturan penerima dari web kini berbentuk daftar HR untuk rekap harian (dokumen 12 §3.3).
7. Tutup dengan batasan yang jujur: demo 1 kamera, identitas dari wajah yang jelas; fase berikutnya mencakup 5 lokasi, peran HR/supervisor, laporan, dan pilot. **Diperbarui:** fase berikutnya mengikuti dokumen 12 (5 kamera ≥ 6 fps, data master karyawan, akun karyawan sebagai viewer, dua jenis email, report + Excel, ReID berjangkar wajah, uji operasional 3 hari, lalu pilot).

## 6. Prioritas bila waktu lebih singkat

Urutan dari yang paling wajib: **D1 → D2 → D4 → D5 → D3 → D6 → D7 → D8 → D9.** Bila D1 (pengenalan wajah) tidak siap tepat waktu, gunakan cadangan §7.

## 7. Rencana cadangan

| Masalah saat demo | Cadangan |
|---|---|
| Pengenalan wajah belum stabil | Demo dengan **fake engine** (skenario sudah ada) untuk alur pelanggaran → pesan → email, disampaikan terbuka ke klien sebagai simulasi; tunjukkan pengenalan wajah asli secara terpisah bila sebagian berjalan |
| Email tidak terkirim (SMTP/jaringan/spam) | Akun SMTP cadangan yang sudah diuji; tunjukkan riwayat notifikasi dan log kirim |
| MediaMTX/WebRTC bermasalah di jaringan lokasi demo | Mode LL-HLS; bila perlu semua komponen di satu laptop. **Diperbarui:** pada demo jarak jauh HLS sudah default; bila mode WebRTC dipakai dan video hitam, kembalikan ke `cameras.remote-hls.yaml` (DEMO-REMOTE §7) |
| Engine macet | Restart engine; backend menyambung ulang otomatis (D8) |
| Tidak ada internet di lokasi | SMTP tidak bisa; tunjukkan email dari rekaman layar yang disiapkan, dan kotak pesan dashboard tetap berjalan |
| Laptop engine utama bermasalah (tambahan 8 Oktober) | Laptop 1060 dengan `-Config engine/config/demo-1060.yaml` dan mode HLS (DEMO-REMOTE §9) |

## 8. Checklist siap demo

Untuk demo jarak jauh (laptop + server Portainer + NetBird), pakai juga checklist hari demo di DEMO-REMOTE §9.

- [ ] Model dan hash tercatat; recognizer menyala; 2–3 orang ter-enroll dan dikenali di video demo.
- [ ] ffmpeg → MediaMTX → engine dan browser berjalan stabil minimal 1 jam tanpa intervensi.
- [ ] Batas jatah dapat diubah dan langsung berlaku.
- [ ] Pelanggaran muncul satu kali per orang per hari di kotak pesan (real-time) dan di email.
- [ ] Email uji berhasil ke alamat penerima di jaringan lokasi demo; dicek juga folder spam.
- [ ] Login admin/viewer; halaman pengaturan tertutup untuk viewer. (Catatan: arti viewer kini akun karyawan, dokumen 12 §3.2.)
- [ ] Engine dimatikan dan dinyalakan lagi: backend tersambung ulang tanpa restart manual.
- [ ] Dua kali latihan dengan skrip §5; versi dibekukan.

## 9. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Recognizer belum pernah diuji dengan model nyata | Tidak ada yang melewati batas di demo | Kerjakan hari 1–3; cadangan fake engine |
| Video demo dengan wajah terlalu kecil/buram | Tidak dikenali | Rekam video demo sendiri: wajah jelas, kamera setinggi wajah, cahaya cukup |
| Loop video membuat track/identitas aneh di titik sambungan | Tampilan janggal | Pilih video yang awal dan akhirnya kosong (tanpa orang) |
| SMTP diblokir jaringan kantor/lokasi | Email gagal | Uji di lokasi sebelum hari H; SMTP cadangan |
| Demo mendorong fitur "sementara" ikut ke produksi | Utang teknis | Semua item demo dipetakan ke workplan utama (§3); pengaturan global penerima email diganti per supervisor saat RBAC. **Diganti oleh dokumen 12 §3.4:** penerima global diganti email ke karyawan + CC HR dan rekap ke daftar HR; penerima per supervisor menjadi kandidat fitur (dokumen 12 §4) |

## Riwayat perubahan

- Memperbarui baris versi ke 1.1 (8 Oktober 2026) dengan rujukan dokumen 12 dan 13; versi 1.0 dan audiens tetap dicatat.
- Menambahkan catatan status di awal: dokumen dipertahankan sebagai rencana demo historis dengan penanda "Diganti oleh".
- §2: asumsi penerima email ditandai diganti oleh dokumen 12 §3.4; asumsi server dan sumber video diperbarui sesuai demo jarak jauh dan gladi 8 Oktober.
- §3: D6 ditandai diganti oleh dokumen 12 §3.4; arti peran viewer di D7 diubah menjadi akun karyawan (dokumen 12 §3.2) dengan catatan injeksi `X-API-Key` di nginx; D1, D2, D9 diberi catatan (glintr100, HLS default, perbaikan r7 dan interpolasi).
- §3: menambahkan catatan butir "tidak masuk demo" yang kini masuk prototype, dan tabel status item demo berdasarkan dokumen 12/13 dan DEMO-REMOTE.
- §4–§5: menambahkan `-r 25` pada hari 1 EB; catatan bahwa langkah 6 skenario tidak bisa diperagakan pada build demo dan pembaruan penutup skenario.
- §7–§9: menambahkan cadangan laptop 1060 dan kembali ke HLS, rujukan checklist DEMO-REMOTE §9, catatan arti viewer, dan mitigasi risiko penerima email yang diganti.
