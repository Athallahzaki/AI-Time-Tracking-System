# 11 — FAQ

Versi 1.1 · diperbarui 8 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Jawaban singkat untuk pertanyaan yang sering muncul. Dokumen terkait ditunjuk di akhir jawaban. FAQ teknis lama di `ARCHITECTURE.md` §17 (PTS, remux, embedding, NVDEC, FP16, AGPL, dan lain-lain) tetap berlaku; kecuali §5.4 ARCHITECTURE ("jangan bangun ReID dulu"), yang diganti dokumen 12 §3.6.

## Produk

**Apa yang sebenarnya diukur sistem?**
Berapa lama seorang karyawan **terlihat** di lokasi rekreasi (smoking area, ruang hiburan, billiard) per hari, di luar jam istirahat resmi. Batasnya 30 menit. Jam istirahat resmi diatur HR dari web, per hari. (01 §6, 12 §3.3)

**Apakah lewat lobby atau berdiri di luar ikut memotong jatah?**
Tidak, secara default. Lobby berkategori transit dan kamera luar berkategori pintu masuk. Kategori dapat diubah per kamera bila klien menginginkan. (01 §3)

**Bagaimana dengan resepsionis, satpam, atau OB yang memang bekerja di lokasi itu?**
HR memberi pengecualian per karyawan per lokasi, dan pengecualian itu tercatat di jejak audit. (02 §3)

**Kalau karyawan pindah dari smoking area ke billiard, waktu jalannya dihitung?**
Tidak. Hanya waktu yang terlihat kamera yang dihitung. (01 §2)

**Apakah sistem langsung menghukum karyawan yang melewati 30 menit?**
Tidak. Sistem memberi peringatan dan menandai pelanggaran dengan bukti; HR memverifikasi dan memutuskan. Sanksi dan urusan keuangan di luar sistem. (01 §2, 12 §1)

**Apa bedanya "pertama terlihat" dengan absensi?**
"Pertama terlihat" adalah waktu pertama seseorang dikenali di kamera luar/lobby pada hari itu. Orang yang masuk lewat pintu lain atau tidak dikenali tidak tercatat, jadi ini bukan pengganti absensi resmi. (10 §1)

**Kenapa tidak pakai kartu/RFID yang lebih akurat?**
Klien meminta identifikasi dari kamera. Kartu di pintu memang lebih akurat dan murah; opsi ini dapat ditawarkan sebagai pelengkap di masa depan.

**Apakah ada laporan dan file Excel?**
Ya. Admin (HR) punya halaman report per karyawan per hari: free time terpakai, sisa jatah, jumlah kunjungan, rincian per lokasi, status, dan (setelah ReID) menit yang sumbernya ReID, dengan filter rentang tanggal. Ada dua jenis Excel dari satu pembuat file di backend: lampiran email rekap harian dan tombol "Export Excel" di halaman report. Formatnya `.xlsx`, bukan CSV, karena Excel berlokal Indonesia salah membaca pemisah CSV. (12 §3.5)

## Identifikasi & akurasi

**Seberapa akurat sistemnya?**
Belum ada angka yang jujur sampai pilot: model belum pernah dijalankan pada rekaman lokasi klien. Target pilot: nol (atau ≤ 1%) salah tagih ke orang lain dan ≥ 85% kunjungan teridentifikasi. Kriteria akurasi prototype (N jam uji tanpa salah tagih, minimal X% kunjungan teridentifikasi) **belum diputuskan**. (09 §5, 12 §2.3)

**Kenapa sistem lebih memilih "tidak dikenal"?**
Karena menagih karyawan A atas waktu karyawan B jauh lebih merugikan daripada tidak menagih. Kasus tidak dikenal diselesaikan lewat alur HR. (01 §2)

**Apakah sistem bisa mengenali orang tanpa wajah?**
Tidak, bila wajahnya tidak pernah terlihat sama sekali. Mengenali orang murni dari bentuk tubuh, pakaian, atau cara berjalan masih masalah riset dan tidak dijanjikan. Yang masuk prototype adalah **ReID berjangkar wajah**: setelah seseorang dikenali lewat wajah, penampilan tubuhnya disimpan untuk hari itu, sehingga ia tetap bisa dilacak saat membelakangi kamera, tertutup, atau pindah ruangan. Orang yang wajahnya tidak pernah terlihat sepanjang hari masuk alur "tidak dikenal" ke HR. (10 §1, 12 §3.6)

**Bagaimana bila orang terlihat lebih dulu dari belakang, baru kemudian wajahnya?**
Tubuhnya diberi ID sementara (`ANON-xxxx`). Saat wajahnya terkonfirmasi, seluruh waktu yang terkait dipindahkan ke karyawan itu (atribusi mundur). ReID tidak pernah menetapkan identitas sendiri dan tidak membatalkan hasil wajah; pelanggaran yang sebagian besar waktunya dari ReID ditandai "perlu dicek HR". (12 §3.6)

**Kenapa hasilnya bisa berbeda di tiap lokasi?**
Karakter lokasi berbeda: billiard (wajah menunduk), smoking area (cahaya berubah, wajah tertutup), luar (backlight, jarak). Posisi kamera adalah faktor terbesar. (04 §9)

**Bagaimana menambah karyawan baru?**
HR membuat data karyawan di web (ID karyawan, nama, divisi, email, status aktif), lalu melakukan enrollment: karyawan dipilih lewat combobox dengan pencarian, kemudian 3–5 foto diambil lewat kamera browser atau unggah file. Engine menilai kualitas foto dan memberi alasan bila ditolak. Bila diperlukan, HR membuat akun login karyawan dari halaman data karyawan ("Buat akun"). (02 §5, 03 §4, 12 §3.1–3.2)

**Kenapa foto enrollment bisa ditolak?**
Wajah terlalu kecil, buram, terlalu miring, pencahayaan buruk, lebih dari satu wajah, atau terlalu mirip dengan karyawan lain. Foto yang lolos menentukan kualitas pengenalan selanjutnya.

**Apa itu enrollment dari CCTV?**
HR memilih orang tak dikenal di rekaman dan menetapkannya sebagai karyawan tertentu. Wajah dari sudut CCTV itu ditambahkan sebagai referensi, sehingga pengenalan berikutnya lebih baik. Selalu lewat konfirmasi manusia.

**Kenapa threshold harus dikalibrasi ulang bila jumlah karyawan bertambah banyak?**
Semakin banyak orang di database, semakin besar peluang menemukan orang lain yang "cukup mirip". Threshold yang aman untuk 50 orang belum tentu aman untuk 300. Untuk prototype, threshold dikalibrasi dengan wajah karyawan, bukan nilai bawaan ArcFace. (12 §2.3)

**Apa yang terjadi bila ada tamu di billiard?**
Tamu tercatat sebagai orang tak dikenal. HR dapat mematikan alert orang tak dikenal di kamera itu untuk durasi tertentu; alert aktif kembali otomatis. Pencatatan tetap berjalan. (02 §6)

## Real-time & video

**Apakah video di dashboard real-time?**
Ya untuk live (WebRTC/HLS dari MediaMTX). Pada demo jarak jauh, **HLS menjadi default** (tertinggal beberapa detik dari kejadian, itu normal); WebRTC (sub-detik) opsional. Overlay kotak deteksi bisa sedikit tertinggal. Bila tertinggal lebih dari ±1 detik, kotak disembunyikan dan ditampilkan penanda "analisis tertinggal". (03 §3, DEMO-REMOTE §6–7)

**Berapa fps analisis, dan kenapa kotaknya tetap halus?**
Target prototype **≥ 6 fps stabil per kamera** untuk 5 kamera; 10–12 fps menjadi target lanjutan bila ruang performa tersisa. Frontend menginterpolasi posisi kotak antar frame analisis, sehingga kotak digambar ulang tiap frame layar dan tidak melompat; kotak hilang paling lama 0,3 detik setelah orangnya hilang. (12 §2.1, §3.7)

**Kenapa satu orang sempat tampil dengan 2–3 kotak?**
Engine lama ikut menggambar track yang sudah hilang (LOST) dengan posisi beku. Ini sudah diperbaiki di paket r7: overlay hanya menampilkan track aktif dan track LOST paling lama 0,3 detik. (13 §4, DEMO-REMOTE §10)

**Kenapa video demo (file MP4) bisa melambat?**
Di mode file, video sengaja diperlambat mengikuti kecepatan engine supaya setiap frame punya kotak deteksinya. Perilaku ini hanya untuk demo dan tidak berlaku pada kamera live. (03 §3)

**Apa yang terjadi bila engine kewalahan?**
Engine menurunkan fps analisis secara bertahap, dan bila perlu melompat ke frame terbaru, supaya tidak tertinggal. Rentang dengan kualitas observasi turun ditandai `camera.degraded` dan terlihat di sistem. (04 §6)

**Kenapa jam di semua perangkat harus disinkronkan?**
Jam event berasal dari kamera dan mesin engine, video dan "sekarang" dari mesin lain. Tanpa NTP yang sama, overlay meleset dan waktu "pertama terlihat" bergeser. (04 §7)

**Kenapa browser memakai substream, sedangkan engine memakai mainstream?**
Engine butuh resolusi tinggi untuk melihat wajah; browser butuh stream ringan dan H.264 yang didukung semua browser. (04 §10)

**Bisakah kamera di-zoom dari dashboard?**
Zoom digital (memperbesar gambar di browser) bisa. Zoom optik/PTZ tidak termasuk fase 1, karena menggerakkan kamera analisis akan merusak zona pintu dan pelacakan. (03 §3)

## Operasional

**Apakah engine menyala 24 jam?**
Proses engine tetap hidup, tetapi **analisis kamera** aktif dan nonaktif otomatis sesuai jadwal operasional per hari yang diatur admin di web. Di luar jam operasional, backend menonaktifkan kamera (`set_cameras` dengan `enabled: false`), dan track yang masih hidup ditutup dengan alasan `schedule_off`, sehingga tidak dibaca sebagai "semua orang pulang". Jam operasionalnya sendiri belum diputuskan. (12 §3.3, §9)

**Apa yang terjadi bila listrik atau jaringan mati?**
Event yang belum terkirim tersimpan di outbox engine dan dikirim ulang setelah koneksi pulih. Selama kamera/engine mati, tidak ada observasi, dan sistem tidak mengisi celah dengan tebakan. UPS di kedua mesin sangat disarankan. (06 §3)

**Kenapa setelah engine mati/macet, backend tidak langsung tersambung lagi?**
Pada build saat ini ada tiga penyebab: (1) engine hang atau mesinnya mati listrik tanpa sinyal penutupan, sehingga backend menunggu selamanya karena tidak ada read timeout; (2) engine sudah hidup lagi tetapi masih tertahan oleh koneksi lama yang setengah mati, sehingga handshake tidak pernah selesai; (3) engine sedang memuat model dan memanaskan kamera, yang wajar dan pulih sendiri. Perbaikannya: read timeout + keepalive, pemutusan koneksi lama saat handshake, restart otomatis engine yang hang, dan status koneksi bertahap di dashboard. (06 P2, P27, P28)

**Apa yang terjadi bila kamera menampilkan gambar beku?**
Tanpa deteksi, orang di gambar beku akan terus terhitung hadir. Deteksi frame beku dijadwalkan (E4) dan menandai kamera sebagai degraded.

**Apakah data bisa diakses dari luar kantor?**
Ya, dashboard kini dapat diakses dari internet (pada demo: Cloudflare → VPS → NetBird → server). Karena itu semua endpoint data wajib login dan disaring per peran di backend, notifikasi dan SSE disaring per pengguna, dan video live (`/hls/`, `/whep/`) serta stream deteksi hanya untuk admin lewat `auth_request` nginx. Engine dan MediaMTX tidak dibuka langsung ke internet; jalurnya lewat NetBird dengan ACL. (12 §3.8, DEMO-REMOTE §1)

**Siapa yang bisa melihat data siapa?**
Dua peran: **admin = HR**, dengan akses penuh (monitoring, report, data karyawan, manajemen pengguna, pengaturan); **viewer = akun karyawan**, yang hanya melihat notifikasi pelanggaran miliknya dan pemakaian free time miliknya hari ini. Peran HR/supervisor terpisah dari admin masih kandidat fitur. Semua perubahan tercatat di jejak audit. (12 §3.2, §4)

**Berapa lama data disimpan?**
Ditentukan klien; rekomendasi: rekap 1–2 tahun, detail kunjungan 3–6 bulan, snapshot 30–90 hari, data wajah selama karyawan aktif. Cache penampilan tubuh untuk ReID hanya satu hari dan dihapus otomatis. (10 §4, 12 §5)

**Bagaimana notifikasi dikirim?**
Tiga jenis: (1) **kotak pesan dashboard** real-time (admin melihat semua, karyawan melihat miliknya); (2) **email per pelanggaran** ke karyawan dengan CC HR, atau ke HR saja bila karyawan tidak punya email (nama dan ID karyawan di subjek); (3) **email rekap harian** ke daftar HR dengan lampiran `.xlsx`, pada jam yang diatur di pengaturan. Rekap yang terlewat karena server mati dikirim saat server hidup dan tidak pernah ganda. Email tidak memuat foto wajah, hanya tautan ke dashboard. (12 §3.4, 05 §4)

**Kalau HR atau karyawan tidak sedang membuka dashboard, apakah peringatan hilang?**
Tidak. Notifikasi dashboard tersimpan dan terlihat saat login berikutnya; pelanggaran juga dikirim lewat email.

**Kenapa server memakai Linux?**
Driver GPU, NVDEC, TensorRT, dan kontainer NVIDIA paling stabil di Linux. Engine sudah divalidasi berjalan di Linux. Untuk demo dan benchmark saat ini, engine berjalan di laptop Windows (RTX 4060) dan backend + frontend di server Portainer CE; topologi produksi belum diputuskan ulang. (05 §6, 12 §6)

**Bisakah kamera ditambah nanti?**
Bisa secara arsitektur (tambah kamera di dashboard admin, atur kategori). Kapasitas GPU dan akurasi perlu diukur ulang saat jumlah kamera naik signifikan. (10 §2)

## Tim

**Kenapa engine tidak boleh tahu jatah 30 menit atau kategori lokasi?**
Supaya perubahan kebijakan tidak menyentuh kode pengamatan, dan engine bisa diuji tanpa aturan bisnis. Batas ini diperiksa otomatis oleh `policy_grep.py`. (04, 08)

**Kenapa pilot dibagi minggu kalibrasi dan minggu pengukuran?**
Angka akurasi hanya bermakna bila versi sistemnya tetap. Perubahan di minggu pengukuran membuat angka bercampur dari beberapa versi. (09 §5)

**Kenapa ID kunjungan harus stabil?**
Koreksi HR merujuk ke ID kunjungan. Bila ID berubah saat kunjungan ditutup, koreksi hilang tanpa error; ini sudah terbukti di build saat ini (P5).

**Kenapa pemindahan folder dan perubahan logika tidak boleh satu commit?**
Supaya bila ada yang rusak, jelas apakah penyebabnya pemindahan atau logika. (08 §9)

**Di mana catatan perubahan kode ditulis sekarang?**
Di satu file `docs/CHANGELOG.md`, entri terbaru di atas, satu bagian per paket. Tidak ada lagi file `PERUBAHAN-*.md` baru di root; catatan lama dipindah ke `docs/arsip/`. Kode dikirim sebagai zip kumulatif. (12 §10.1–10.3)

## Riwayat perubahan

- Menambahkan baris versi 1.1 (8 Oktober 2026) dan catatan bahwa ARCHITECTURE §5.4 diganti dokumen 12 §3.6.
- Produk: jam istirahat per hari dari web; verifikasi pelanggaran oleh HR; Q&A baru tentang report dan Excel.
- Identifikasi: menambahkan kriteria akurasi prototype yang belum diputuskan; Q&A baru "Apakah sistem bisa mengenali orang tanpa wajah?" dan identitas tertunda ReID; enrollment memakai data master + combobox; kalibrasi threshold dengan wajah karyawan.
- Real-time: HLS default pada demo jarak jauh; Q&A baru tentang target ≥ 6 fps + interpolasi kotak dan perbaikan kotak ganda (r7).
- Operasional: Q&A baru jadwal on/off analisis engine; akses dari luar kantor kini lewat internet dengan pengerasan akses; peran admin = HR dan viewer = karyawan; tiga jenis notifikasi (kotak pesan, email per pelanggaran + CC HR, rekap harian `.xlsx`); retensi cache ReID; catatan mesin demo Windows.
- Tim: Q&A baru tentang `docs/CHANGELOG.md` dan zip kumulatif.
