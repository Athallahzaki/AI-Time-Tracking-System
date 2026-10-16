# 10 — Keterbatasan, Spesifikasi & Hal Terkait Klien

Versi 1.1 · diperbarui 8 Oktober 2026 · lihat dokumen 12 (kesepakatan) dan 13 (daftar pembaruan)

Dokumen ini berisi hal yang perlu diketahui dan disampaikan ke pihak luar (lewat communicator tim): apa yang **tidak bisa** dilakukan sistem, spesifikasi yang dibutuhkan, kebutuhan untuk perusahaan CCTV, dan keputusan yang menunggu klien.

## 1. Keterbatasan sistem

**Pengenalan wajah dari CCTV tidak pernah 100%.** Sistem dirancang untuk memilih "tidak dikenal" daripada menebak. Akibatnya sebagian kunjungan tidak tertagih (undercount), bukan tertagih ke orang yang salah. Tingkat identifikasi bergantung terutama pada posisi kamera, resolusi, dan pencahayaan, bukan pada model.

**Kondisi yang menurunkan identifikasi:** wajah tertutup (masker, helm, topi, tangan/rokok), membelakangi atau menunduk terus, cahaya balik (backlight) atau gelap, jarak jauh, mode malam IR, kerumunan dengan oklusi berat, serta karyawan yang sangat mirip (kembar).

**ReID berjangkar wajah (masuk prototype per 8 Oktober 2026).** Bila track seseorang hilang (membelakangi kamera, tertutup, pindah ruangan), sistem dapat melanjutkan pelacakan lewat cache penampilan tubuh harian yang **hanya diisi dari orang yang sudah dikenali lewat wajah**. ReID tidak pernah menetapkan identitas sendiri dan tidak membatalkan hasil wajah; tubuh tanpa wajah diberi ID sementara dan baru dikaitkan ke karyawan setelah wajahnya terkonfirmasi (atribusi mundur). Ambangnya ketat: lebih baik terpecah daripada tertukar. Menit yang sumbernya ReID ditandai di report, dan pelanggaran yang sebagian besar waktunya dari ReID ditandai "perlu dicek HR". (Dokumen 12 §3.6)

**Pengenalan dari bentuk tubuh saja tidak dijanjikan.** Mengenali orang murni dari bentuk tubuh, pakaian, atau cara berjalan tanpa wajah sama sekali masih masalah riset dan **tidak termasuk** lingkup. Orang yang wajahnya tidak pernah terlihat sepanjang hari ditangani lewat kamera jangkar dan alur "tidak dikenal" ke HR.

**Hanya waktu yang terlihat yang dihitung.** Waktu di area tanpa kamera (koridor, toilet, area lain) dan waktu berjalan antar-lokasi tidak dihitung. Jatah dapat terlihat lebih kecil dari kenyataan.

**"Pertama terlihat" bukan absensi.** Karyawan yang masuk lewat pintu lain atau tidak dikenali di kamera luar/lobby tidak tercatat.

**Sistem memberi tanda, bukan memutuskan.** Pelanggaran harus diverifikasi HR dengan bukti sebelum ada konsekuensi; keputusan sanksi tetap di tangan HR. Integrasi keuangan dan sanksi berada di luar sistem.

**Ketergantungan infrastruktur.** Listrik, jaringan, kamera, dan jam yang sinkron adalah prasyarat. Selama kamera mati atau kualitas observasi turun, sistem menandai rentang tersebut (`camera.degraded`) dan tidak mengisi celah dengan tebakan.

**Skala fase 1:** satu site, 5 kamera, asumsi 50–200 karyawan terdaftar. Prototype diuji beban dengan **100 orang terlihat sekaligus total di 5 kamera** dan **100 karyawan terdaftar** (dokumen 12 §2.2). Penambahan kamera didukung arsitektur, tetapi perlu pengukuran ulang kapasitas dan akurasi.

**Tidak termasuk fase 1:** aplikasi mobile native, kontrol PTZ/zoom optik, absensi resmi, multi-site, identifikasi murni dari bentuk tubuh/pakaian/gait tanpa wajah. (ReID berjangkar wajah tidak lagi dikecualikan; lihat di atas.)

## 2. Spesifikasi server (estimasi teoretis)

Estimasi untuk 5 kamera 1080p @25 fps, D-FINE m di input 640, rekognisi wajah aktif. Angka final diambil dari benchmark 5 stream (dokumen 09); jangan membeli hardware sebelum benchmark itu.

> **Diperbarui 8 Oktober 2026:** target kecepatan analisis bukan lagi 12 fps, melainkan **≥ 6 fps stabil per kamera**, dengan frontend **menginterpolasi** posisi kotak antar frame analisis. 10–12 fps menjadi target lanjutan, hanya bila ruang performa tersisa (dokumen 12 §2.1, §3.7). Tabel spesifikasi di bawah tetap dipertahankan sebagai rekomendasi teoretis; dasar perhitungannya disesuaikan.

**Perhitungan dasar (target ≥ 6 fps):** 5 × 6 fps = 30 inferensi detector per detik. D-FINE m dengan TensorRT FP16 ±5–6 ms per gambar (acuan T4; RTX 4060 kurang lebih setara atau lebih cepat) → ±15–20% waktu GPU. Tanpa TensorRT/batching (PyTorch, ±15–25 ms) → 0,45–0,75 detik kerja per detik video, sudah terkejar di atas kertas tetapi menyisakan sedikit ruang untuk rekognisi dan ReID. Decode penuh 5 stream (125 frame 1080p per detik) tetap memerlukan beberapa core CPU, atau beban kecil di NVDEC, karena decode tidak berkurang meskipun analisis diturunkan.

**Perhitungan target lanjutan (12 fps):** 5 × 12 fps = 60 inferensi per detik → ±30–40% waktu GPU dengan TensorRT FP16; tanpa TensorRT/batching 0,9–1,5 detik kerja per detik video, tidak terkejar.

Catatan: perhitungan di atas belum memasukkan beban inference model ReID; besarnya belum diukur.

| Komponen | Mesin A — Engine | Mesin B — Backend, Frontend, MediaMTX |
|---|---|---|
| GPU | NVIDIA RTX 4060 8 GB (minimum); RTX 4060 Ti 16 GB / 4070 bila kamera akan ditambah | Tidak perlu |
| CPU | 8 core / 16 thread (Ryzen 7 / Core i7 generasi terkini) | 4 core |
| RAM | 32 GB | 16 GB |
| Penyimpanan | SSD NVMe 512 GB–1 TB | SSD 256–512 GB (+ ruang snapshot sesuai retensi) |
| OS | Ubuntu Server LTS / Debian stable, headless | Sama |
| Jaringan | Gigabit Ethernet | Gigabit Ethernet |
| Listrik | UPS | UPS |

Catatan: GTX 1060 tidak dipakai untuk produksi atau untuk angka keputusan (FP16 lambat di arsitektur Pascal); laptop 1060 hanya cadangan demo. Dengan TensorRT, satu RTX 4060 secara teori masih punya ruang untuk ±10–15 kamera; angka ini paling spekulatif dan wajib diukur.

**Mesin benchmark yang dipakai saat ini (dokumen 12 §6).** Berbeda dari rekomendasi di atas; dipakai untuk uji prototype dan demo, bukan keputusan pembelian.

| Mesin | Spesifikasi | Peran |
|---|---|---|
| Server benchmark | Intel i5-3470 (gen 3), iGPU, 16 GB DDR3 | Backend + frontend (Portainer CE) |
| Laptop engine | Intel i7-13700HX (8P+8E), RTX 4060 Laptop, 16 GB DDR5 | Engine + MediaMTX + ffmpeg |

- Server cukup untuk backend/frontend; pastikan disk SSD. CPU gen 3 tidak lagi menerima pembaruan microcode; perlu dipertimbangkan untuk produksi.
- Laptop untuk operasi harian berjam-jam: engine dijalankan sebagai service yang hidup ulang otomatis, sleep dimatikan, jam aktif Windows Update diatur, dicolok charger. RAM 16 GB untuk 5 kamera + ReID harus diukur.
- Hasil terukur sejauh ini (8 Oktober, laptop 4060, satu kamera): run bersih 10,00 fps, 0 drop, umur kotak p99 0,09 detik, setelah ffmpeg `-r 25`, afinitas P-core, dan pengecualian power throttling. **5 kamera belum pernah diuji** (dokumen 12 §8).
- Pada demo, laptop dan server berjauhan dan tersambung lewat NetBird (`docs/DEMO-REMOTE.md`). Topologi produksi (mesin A + B satu LAN, Linux headless) **belum diputuskan ulang**.

**Jaringan:** 5 mainstream ±4–8 Mbps per kamera ke MediaMTX dan engine, ditambah substream untuk penonton. LAN gigabit cukup.

## 3. Kebutuhan untuk perusahaan CCTV

Disampaikan **sebelum kamera dipasang permanen**. Mengubah posisi sebelum pemasangan hampir tanpa biaya; sesudahnya bisa lebih mahal daripada semua upaya menaikkan akurasi model.

| Kebutuhan | Detail |
|---|---|
| Posisi | Menghadap pintu masuk setiap ruangan, sehingga wajah terlihat saat orang masuk; untuk ruang hiburan, sebaiknya juga menghadap area duduk |
| Tinggi & sudut | Setinggi mungkin mendekati wajah (±2–2,5 m), sudut tunduk kecil; hindari sudut plafon yang melihat ubun-ubun |
| Resolusi | Mainstream minimal 1080p; wajah di area pintu ±60–80 px lebar |
| Cahaya | Hindari backlight dari jendela/pintu kaca; pencahayaan cukup di pintu billiard dan smoking area |
| Stream | Dua profil aktif: mainstream (H.264/H.265) untuk analisis, substream **H.264** untuk tampilan |
| Waktu | NTP diarahkan ke server lokal (mesin B) |
| Akses | RTSP dapat dijangkau dari mesin B; kredensial khusus untuk sistem |
| Stabilitas | Firmware stabil, keyframe interval 1–2 detik |

## 4. Rekomendasi retensi data (keputusan klien)

| Data | Rekomendasi | Alasan |
|---|---|---|
| Rekap jatah harian per karyawan | 1–2 tahun | Bukti sengketa/evaluasi; kecil dan tidak sensitif |
| Detail kunjungan (per lokasi, jam) | 3–6 bulan | Cukup untuk menelusuri keberatan |
| Snapshot bukti pelanggaran | 30–90 hari, atau sampai diverifikasi + 30 hari | Gambar wajah paling sensitif; hanya untuk verifikasi dan keberatan |
| Referensi wajah & foto enrollment | Selama karyawan aktif; dihapus saat nonaktif | Tidak ada alasan menyimpan setelah karyawan keluar |
| Cache penampilan tubuh (ReID) | Satu hari; dihapus otomatis di akhir hari (ditetapkan, dokumen 12 §3.6, §5) | Hanya dibutuhkan untuk melanjutkan pelacakan di hari yang sama |
| Event mentah engine | 30–90 hari | Pemulihan dan audit teknis |
| Log sistem | 30 hari | Diagnosis |
| Jejak audit | Sama dengan rekap harian | Harus bertahan selama data yang diubahnya |

Prinsip: simpan rekap selama mungkin karena kecil; simpan data mentah dan gambar sesingkat mungkin karena besar dan paling sensitif.

## 5. Asumsi yang dipakai selama pengembangan

Semua berupa konfigurasi atau pengaturan dan dapat diubah tanpa mengubah kode. Asumsi tambahan per 8 Oktober 2026 dicatat di dokumen 12 §5; asumsi di tabel ini yang tidak disebut di sana tetap berlaku.

| Topik | Asumsi | Diubah bila |
|---|---|---|
| Kategori lokasi | Luar = pintu masuk; lobby = transit; smoking, hiburan, billiard = rekreasi | Klien menetapkan lain |
| Jam istirahat resmi | **Diatur HR dari web, per hari** (misalnya Jumat berbeda); perubahan berlaku mulai hari berikutnya dan dicatat. Nilai awal konfigurasi: 12:00–13:00 | HR mengubah dari halaman pengaturan |
| Jadwal operasional engine | Analisis kamera aktif/nonaktif otomatis sesuai jadwal per hari di pengaturan; proses engine tetap hidup. Jam operasionalnya **belum diputuskan** | Klien/HR menetapkan jam |
| Kunjungan singkat | < 20 detik tidak ditagih; 20 detik pertama gratis | Klien menetapkan lain |
| Peringatan dini | Sisa 5 menit | Klien menetapkan lain |
| "Pertama masuk" | Pertama terlihat di kamera luar/lobby | Klien meminta absensi resmi (scope baru) |
| Pintu per ruangan | Satu zona pintu per kamera; bisa ditambah | Denah menunjukkan lebih |
| Jumlah karyawan | 50–200; stress test prototype 100 karyawan terdaftar | Data klien tersedia (kalibrasi ulang threshold) |
| Pelanggaran | Diverifikasi HR, bukan sanksi otomatis; pelanggaran yang sebagian besar waktunya dari ReID ditandai "perlu dicek HR" | — |
| Notifikasi | **Diputuskan (8 Oktober 2026):** kotak pesan dashboard real-time (admin: semua; viewer/karyawan: miliknya); **email per pelanggaran ke karyawan + CC HR**, atau **ke HR saja** bila karyawan tanpa email (nama dan ID di subjek); **email rekap harian** ke daftar HR (maks. 20 alamat, diatur dari web) dengan lampiran `.xlsx`, jam kirim diatur di pengaturan (dokumen 12 §3.4) | Klien meminta saluran atau penerima lain (misalnya per supervisor, kandidat dokumen 12 §4) |
| Peran | HR = admin (semua akses, termasuk report); viewer = akun karyawan, hanya data miliknya | Klien meminta peran HR/supervisor terpisah |
| Interval ReID | Berbasis kejadian; pembaruan galeri default 15 detik | Beban terlalu berat |
| Retensi | Tabel §4 | Klien menetapkan |
| Pengecualian lokasi | Kosong; diisi HR | — |

Asumsi yang tidak dijawab klien sampai go-live dianggap disetujui dan dicatat demikian.

## 6. Pertanyaan terbuka untuk klien (lewat COM)

Status per 8 Oktober 2026 ditandai di akhir butir.

1. Jam istirahat resmi: sama setiap hari? Ada shift atau jadwal Jumat berbeda? — **Sebagian terjawab:** sistem kini mendukung jam istirahat per hari yang diatur HR dari web; nilai jamnya diisi HR.
2. Lokasi mana yang memotong jatah, terutama lobby dan smoking area? — Masih terbuka.
3. Smoking area di dalam atau di luar gedung? — Masih terbuka.
4. Siapa saja karyawan yang lokasi kerjanya di salah satu area (resepsionis, satpam, OB)? — Masih terbuka.
5. "Pertama masuk" cukup "pertama terlihat", atau harus setara absensi resmi? — Masih terbuka.
6. Jumlah karyawan yang akan di-enroll, dan apakah ada tamu/vendor rutin di area rekreasi? — Masih terbuka (prototype diuji dengan 100 karyawan terdaftar).
7. Peringatan ke siapa (karyawan sendiri, supervisor, atasan)? Saluran sudah diputuskan (email + dashboard); yang dibutuhkan: akun SMTP pengirim dan daftar email supervisor/atasan. — **Terjawab sebagai asumsi tercatat:** email pelanggaran ke karyawan + CC HR (HR saja bila karyawan tanpa email), rekap harian ke HR. Yang masih dibutuhkan: akun SMTP pengirim dan ketersediaan email karyawan untuk data master.
8. Pelanggaran diverifikasi supervisor dulu, atau langsung dicatat? — **Sebagian terjawab:** keputusan sanksi di tangan HR, dan HR = admin; alur verifikasi rinci belum ditetapkan.
9. Retensi data yang diinginkan (rekomendasi §4). — Masih terbuka (kecuali cache ReID: satu hari).
10. Siapa kontak pilot dan pemeriksa sampel di pihak klien? — Masih terbuka.
11. Denah dan jumlah pintu tiap ruangan. — Masih terbuka.
12. Dukungan setelah masa maintenance: siapa, bagaimana, dan dengan biaya apa. — Masih terbuka.

Pertanyaan baru (dokumen 12 §9):

13. Nilai **N** (jam uji rekaman tanpa salah tagih) dan **X%** (minimal kunjungan teridentifikasi) untuk kriteria akurasi prototype.
14. Jam operasional engine per hari dan jam kirim email rekap harian.
15. Ketersediaan email karyawan untuk data master.
16. Persetujuan biometrik karyawan dari pihak klien, termasuk data penampilan tubuh untuk ReID (§7).

## 7. Hal hukum dan persetujuan (risiko terbuka)

Tim adalah **pemroses** data atas nama klien (**pengendali**). Kontrak kerja umum antara klien dan karyawan belum tentu mencakup pemrosesan **data biometrik** (wajah) untuk pemantauan, yang di bawah UU 27/2022 tentang Pelindungan Data Pribadi diperlakukan sebagai data pribadi spesifik. Dengan masuknya ReID ke prototype, sistem juga memproses **data penampilan tubuh** (embedding tubuh dari beberapa sudut) yang dikaitkan ke karyawan yang dikenali. Kewajibannya dapat mencakup tujuan yang spesifik, dasar pemrosesan yang sah, penilaian dampak (DPIA) untuk pemantauan sistematis dan biometrik, serta hak karyawan atas datanya. Tim bukan konsultan hukum; hal ini disampaikan sebagai **risiko untuk ditinjau legal klien**, dengan rekomendasi:

- Adendum atau persetujuan khusus biometrik dari karyawan, dan pemberitahuan privasi. Persetujuan dan pemberitahuan **mencakup juga data penampilan tubuh untuk ReID**, bukan hanya wajah.
- Kebijakan retensi tertulis (§4), termasuk penghapusan harian cache ReID.
- Kontrak tim–klien yang menyatakan peran pemroses.

Dari sisi sistem, fase 1 tetap menyediakan: penghapusan data wajah saat karyawan nonaktif, enkripsi referensi, akses berbasis peran, jejak audit, dan retensi terbatas untuk snapshot. Tambahan per 8 Oktober 2026: cache penampilan tubuh ReID **dihapus otomatis setiap hari**; karena dashboard kini dapat diakses dari internet, semua endpoint data wajib login dan disaring per peran di backend, dan video live hanya untuk admin (dokumen 12 §3.8).

## 8. Lingkup dukungan

| Periode | Dukungan |
|---|---|
| Pengembangan (6 minggu) | Tim pengembang |
| Pilot = maintenance (2–3 minggu) | Perbaikan bug, kalibrasi, pemantauan jarak jauh lewat VPN |
| Setelah maintenance | **Belum disepakati.** Perlu dituliskan di kontrak: cakupan, waktu respons, biaya, dan pembaruan model/keamanan |

## Riwayat perubahan

- Menambahkan baris versi 1.1 (8 Oktober 2026) dengan rujukan dokumen 12 dan 13.
- §1: ReID tidak lagi dikecualikan; ditambahkan penjelasan ReID berjangkar wajah dan penegasan bahwa identifikasi murni dari bentuk tubuh tidak dijanjikan; skala uji beban 100 orang/100 karyawan; verifikasi oleh HR.
- §2: dasar perhitungan diubah dari 12 fps ke ≥ 6 fps + interpolasi kotak (12 fps tetap sebagai target lanjutan); tabel spesifikasi teoretis dipertahankan; ditambahkan mesin benchmark dokumen 12 §6, hasil uji 4060 satu kamera, dan catatan topologi demo.
- §4: menambahkan baris retensi cache penampilan tubuh ReID (satu hari, dihapus otomatis).
- §5: jam istirahat kini diatur per hari dari web; ditambahkan jadwal operasional engine, peran, interval ReID; aturan notifikasi diganti (email per pelanggaran ke karyawan + CC HR, fallback HR, rekap harian).
- §6: menandai status tiap pertanyaan dan menambahkan empat pertanyaan terbuka dari dokumen 12 §9.
- §7: persetujuan dan pemberitahuan mencakup data penampilan tubuh untuk ReID; ditambahkan penghapusan harian cache ReID dan pengerasan akses.
