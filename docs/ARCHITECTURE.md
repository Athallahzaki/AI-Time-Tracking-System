# Arsitektur Engine & Backend — Spesifikasi & Rencana Perubahan

**AI Time Tracking System** · revisi 5 · 19 September 2026

Dokumen ini adalah acuan kerja untuk `engine/`, `backend/`, dan protokol di
antara keduanya. Isinya keputusan yang sudah diambil beserta alasannya, bug yang
harus diperbaiki, dan urutan pekerjaan. Angka performa apa pun di sini adalah
estimasi sampai `bench.py` ada.

> **Keputusan 23 September 2026 (menggantikan arah §4.1 untuk hitungan jatah):**
> kamera memantau **ruang fasilitas**, dan waktu karyawan **terlihat** di ruang itu
> memakai jatah 30 menit hariannya. Jatah dihitung backend
> (`backend/services/free_time.py`) dari event durabel — bukan dari celah antar
> interval dan bukan dari kanal `view`. Kegagalan pengenalan di model ini
> menyebabkan *kurang tagih*, bukan tuduhan palsu; risiko kebalikannya (salah
> orang ditagih) ditangani dengan koreksi HR yang mengecualikan satu kunjungan.
> Bagian di bawah tentang celah tetap berlaku untuk kualitas track, bukan untuk
> tagihan jatah.

**Perubahan dari revisi 2:** sistem ini bukan hanya absensi. Ada monitoring jatah
istirahat pribadi 30 menit di luar jam istirahat resmi, dan itu **membalik apa
yang diukur** — dari kehadiran jadi ketidakhadiran. Konsekuensinya masuk ke
bentuk output engine, katalog event, dan metrik benchmark.

**Perubahan dari revisi 3:** lapisan ingest (§5.5), topologi video lengkap dengan
siapa menarik dari mana (§6.7), dan FAQ istilah di §17.

**Perubahan dari revisi 4:** relay video tidak dibangun sendiri — MediaMTX menarik dan
menyajikan ulang, dengan HLS sebagai jalur utama (§6.7.1).

---

## 1. Ringkasan keputusan

1. **Engine dan backend dipisah jadi dua proses**, berkomunikasi lewat NDJSON.
   Backend bebas ditulis ulang dalam bahasa apa pun.
2. **Engine mengamati, backend memutuskan.** Engine melaporkan apa yang dilihat
   kamera lalu diam; semua semantik — sesi, istirahat, sanksi — milik backend.
3. **Output utama engine adalah interval kehadiran**, bukan event absensi dan
   bukan akumulasi harian. Penjumlahan interval adalah kebijakan yang menyamar
   sebagai aritmetika.
4. **Embedding milik engine, identitas orang milik backend**, disambung satu ID
   buram.
5. **Lapisan identitas bergeser** dari verifikasi berkala jadi tangkap-momen-baik
   lalu pegang-lewat-tracking, karena kamera di sudut ruangan.
6. **Ultralytics dilepas** karena AGPL-3.0, tracker dulu lalu detector.
7. **Enrollment diperketat** dengan quality gate, uji keberagaman, dan uji
   tabrakan antar karyawan.

Port dan contract internal engine — `FrameSource`, `ObjectDetector`,
`ObjectTracker`, `TrackListener`, pemisahan recognizer/policy/cache —
dipertahankan. Hampir semua perbaikan di bawah muat ke slot yang sudah ada.

---

## 2. Pemisahan engine dan backend

### 2.1 Garis pemisah: persepsi versus kebijakan

Engine adalah **sensor cerdas**. Ia melaporkan apa yang terlihat oleh kamera dan
tidak tahu apa pun tentang jam kerja, jatah istirahat, atau sanksi.

Kata "departed" menutupi dua hal berbeda, dan campur aduk di antara keduanya
adalah sumber kebingungan paling umum di desain seperti ini:

| | Departure perseptual | Departure kebijakan |
| --- | --- | --- |
| Artinya | Track mati; tidak ada kamera yang melihat orang ini lagi | Sesi kerja atau istirahat orang ini dianggap mulai/selesai |
| Pemilik | **Engine** | **Backend** |
| Alasan | Hanya engine tahu track lahir/mati, kepercayaan meluruh, kamera putus | Hanya backend tahu aturan perusahaan |

Yang perseptual **wajib tetap di engine**. Kalau didorong ke backend, backend
terpaksa merekonstruksi siklus hidup track dari observasi mentah — artinya
menulis ulang state machine tracker dalam bahasa apa pun backend nanti ditulis.
Itu persis kopling yang ingin dihindari, hanya melewati socket dulu supaya
terlihat seperti arsitektur.

Kalimat pemisahnya: **engine bilang "aku berhenti melihat orang ini pada detik
sekian"; backend memutuskan apakah itu berarti pulang atau ke toilet.**

Dan engine **melapor lalu diam.** Tidak ada ambang, tidak ada peringatan, tidak
ada notifikasi, tidak ada konsep penalti. Bahkan kalaupun secara teknis ia sanggup
menghitung bahwa seseorang sudah lewat tiga puluh menit, ia tidak boleh — karena
begitu engine tahu angka tiga puluh, angka itu ada di dua tempat, dan suatu hari
kebijakannya berubah jadi empat puluh lima sementara engine masih memakai yang
lama.

### 2.2 Kepemilikan

| Aset | Pemilik | Catatan |
| --- | --- | --- |
| Bobot model, GPU, worker pool | Engine | |
| Track, siklus hidupnya, ID kamera | Engine | |
| Vektor embedding + gambar referensi | Engine | Backend tidak bisa memakainya |
| Cache pengenalan | Engine | **Optimisasi, bukan catatan** — boleh hilang saat restart |
| Outbox event | Engine | Satu-satunya state durabel selain embedding |
| Catatan karyawan (nama, departemen, status) | Backend | |
| Pemetaan `camera_id` → ruangan | Backend | Kamera bisa dipindah tanpa engine tahu |
| Sesi kerja, jam istirahat, jatah 30 menit, sanksi | Backend | |
| Riwayat absensi & koreksi manual | Backend | |
| Konfigurasi kamera & roster | Backend | Didorong ke engine secara deklaratif |

Konsekuensi yang bagus: `AttendanceTracker` **pindah utuh ke backend**, dan engine
berhenti memelihara sesi sama sekali. Itu langsung membereskan bug tiga-sumber-
kebenaran di revisi 1 (§9, butir 6).

Konsekuensi menyenangkan yang kedua: **engine jadi hampir sepenuhnya stateless.**
Kalau ia restart jam sebelas siang, yang hilang cuma track yang sedang hidup —
seluruh riwayat aman di backend. Itu tanda garisnya ditarik di tempat yang benar.
Kalau restart engine berarti kehilangan data kehadiran, ada state yang salah tempat.

### 2.3 Apa yang engine harus pancarkan agar backend bisa memutuskan apa pun

Ini risiko desain terbesar dari pemisahan, dan gampang diremehkan. Kalau engine
hanya mengirim event "dikenali", backend tidak bisa membedakan **"orangnya pergi"**
dari **"orangnya berbalik dan pengenalan berhenti"** — dua hal yang di ruangan
dengan kamera sudut akan terjadi setiap beberapa menit, dan yang di §4 berubah
dari gangguan kecil jadi tuduhan.

Minimal yang harus dipancarkan: track lahir, track teridentifikasi (dengan
similarity dan margin, bukan hanya nama), heartbeat berkala selama track hidup,
dan track berakhir **beserta kode alasan dan zona tempat ia berakhir**.

Kode alasan bukan hiasan. Kalau satu kamera mati, semua track di kamera itu
berakhir serentak padahal tidak ada seorang pun yang pulang. Tanpa kode alasan,
backend akan menandai satu ruangan penuh orang sebagai pulang pada detik yang
sama — dan itu bug yang baru ketahuan saat penggajian.

---

## 3. Realitas pemasangan kamera

**Konfigurasi nyata: satu kamera per ruangan, dipasang di sudut, menghadap
diagonal ke dalam ruangan.** Orang akan sering membelakangi kamera.

Ini bukan detail deployment — ini asumsi yang menentukan bentuk arsitekturnya.

### 3.1 Konsekuensi: lapisan identitas berubah strategi

Kalau orang sering membelakangi kamera, **verifikasi ulang berkala tidak bisa
diandalkan** — kesempatan melihat wajah datang jarang dan tidak bisa dijadwalkan.
Strateginya bergeser jadi: **tangkap momen langka yang bagus, lalu pegang
identitasnya lewat tracking.**

Ini membalik satu kesimpulan revisi 1. Di sana tertulis bahwa lapisan identitas
yang baik membuat ID switch tidak fatal karena terkoreksi dalam beberapa detik.
Itu berlaku kalau koreksi bisa datang cepat. Di ruangan ini, track yang putus
berarti identitas hilang sampai orangnya kebetulan berbalik lagi — bisa dua puluh
menit. **Kualitas tracker jadi jauh lebih penting, bukan kurang penting.**

### 3.2 Momen masuk ruangan adalah emas

Orang yang masuk lewat pintu menghadap ke dalam ruangan, artinya menghadap ke arah
kamera sudut. Itu satu-satunya saat wajah frontal hampir dijamin.

Implikasi konkret: definisikan `door_region` per kamera di konfigurasi. Track yang
lahir di region itu mendapat **prioritas tertinggi** di antrian pengenalan dengan
anggaran percobaan lebih besar. Sisa waktunya, engine tidak perlu memaksakan
pengenalan pada punggung orang — buang lebih awal lewat quality gate dan hemat GPU.

Region yang sama dipakai lagi di §4.2 untuk arah sebaliknya.

### 3.3 Masker

Pengenalan periokular (hanya region mata dan alis) adalah bidang yang sudah
digarap serius, termasuk evaluasi khusus oleh NIST. Akurasinya turun jelas
dibanding wajah penuh tapi tidak jatuh ke nol. Masalahnya, model yang bagus untuk
itu adalah model yang **dilatih atau di-fine-tune dengan data bermasker**, dan
AuraFace bukan salah satunya. Di luar kotak, masker akan menghantam akurasi.

**Jalan pintas yang murah:** kalau seseorang memang selalu memakai masker, **enroll
dia dalam keadaan bermasker.** Pencocokan jadi bermasker-ke-bermasker, bukan
bermasker-ke-wajah-penuh, dan itu jauh lebih baik karena kedua sisi kehilangan
informasi yang sama. Embedder tidak berubah, hanya referensinya yang jujur
terhadap kondisi nyata.

Keputusan yang masih terbuka ada di §15.

---

## 4. Apa yang diukur: kehadiran dan ketidakhadiran

Sistem ini bukan hanya absensi. Kantor memberi karyawan jatah **30 menit istirahat
pribadi di luar jam istirahat resmi**, dan pemakaian jatah itu ingin dimonitor.
Keputusan sanksi atau peringatan sepenuhnya milik backend; yang dibahas di sini
adalah apa yang harus engine sanggup ukur supaya keputusan itu punya dasar.

### 4.1 Ini membalik apa yang diukur

Absensi mengukur kehadiran: "apakah orang ini ada hari ini?" — toleran terhadap
lubang. Kalau engine kehilangan seseorang sepuluh menit, sesinya tetap menyatakan
hadir dan tidak ada yang rusak.

Monitoring istirahat mengukur hal yang berlawanan: **ia mengukur lubangnya.** Dan
begitu yang diukur adalah ketidakhadiran, setiap kegagalan pengenalan berhenti jadi
gangguan kecil dan langsung berubah jadi **tuduhan**.

| | Absensi | Monitoring istirahat |
| --- | --- | --- |
| Yang diukur | Interval kehadiran | Celah di antara interval |
| Gagal mengenali orang yang hadir | Sesi tetap terbuka; nyaris tak terlihat | **Menciptakan istirahat palsu** |
| Toleransi kesalahan | Menit | Jauh di bawah 30 menit |
| Siapa yang dirugikan | Tercatat absen, mudah dibantah | Kena peringatan, sulit dibantah |

Sekarang gabungkan dengan §3. Setiap kali track putus sementara orangnya masih
duduk di mejanya — teroklusi rekan yang lewat, membelakangi terlalu lama, tracker
gagal — engine melaporkan track berakhir dan backend melihat celah dua belas menit.
Karyawan itu kehilangan dua belas menit dari jatahnya **tanpa beranjak dari
kursinya.** Di absensi bug itu tidak terlihat; di sini ia menghasilkan surat
peringatan, dan beban pembuktian jatuh ke karyawan yang harus membantah sistem yang
tidak menyimpan apa pun untuk diperiksa.

### 4.2 Output utama engine: interval kehadiran

Engine **tidak pernah** memancarkan "orang ini absen". Ia memancarkan interval
kehadiran beserta kualitas batasnya, dan backend menurunkan ketidakhadiran dengan
pengurangan.

```json
{ "type": "presence.interval", "seq": 10433,
  "person_id": "4471", "camera_id": "r1",
  "start_pts": 1726712531.20, "end_pts": 1726715250.85,
  "start_source": "face", "end_source": "track_lost",
  "start_zone": "door", "end_zone": "interior",
  "end_reason": "occluded_timeout",
  "identity_confidence": 0.91, "evidence_count": 4,
  "prev_interval_seq": 10402 }
```

Tiga field yang menanggung beban paling berat:

**`end_zone`** — ini yang paling murah dan paling berdampak. `door_region` dari
§3.2 dipakai ulang untuk sisi sebaliknya. Track yang berakhir **di region pintu**
kemungkinan besar orangnya benar-benar keluar. Track yang berakhir **di tengah
ruangan** hampir pasti kegagalan tracking, bukan kepergian. Satu field, dan backend
bisa membedakan celah nyata dari celah palsu tanpa tahu apa pun tentang tracking.

**`start_source` / `end_source`** — `face`, `tracking`, atau `forced`. Batas yang
berasal dari identifikasi wajah langsung, dari tracking yang dipegang (state
`HELD`), dan dari terminasi paksa karena kamera putus punya keandalan yang sangat
berbeda. Backend harus bisa memperlakukannya berbeda.

**`end_reason`** — minimal `left_frame`, `occluded_timeout`,
`merged_into_other_track`, `camera_lost`, `engine_shutdown`.

Yang **tidak boleh** ada di sini: akumulasi harian. Kalau engine melaporkan "hari
ini dia 6 jam 20 menit di ruang 1", engine sudah diam-diam memutuskan celah mana
yang dianggap masih hadir dan mana yang dianggap pergi. Penjumlahan interval adalah
kebijakan yang menyamar sebagai aritmetika, dan itu milik backend.

### 4.3 Penyambungan track hanya atas bukti perseptual

Orang yang teroklusi tiga detik tidak boleh menghasilkan dua interval dan satu
celah. `track_buffer` ByteTrack menangani sebagian, tapi di atasnya engine perlu
penyambungan di level identitas: kalau `person_id` yang sama muncul lagi di kamera
yang sama dalam jendela N detik, engine menyambungnya dan **tidak melaporkan celah
sama sekali** — emit `track.resumed` yang menunjuk interval sebelumnya lewat
`prev_interval_seq`, bukan interval baru yang berdiri sendiri.

Garis halusnya: **engine menyambung karena punya bukti perseptual** bahwa ini
kehadiran yang sama berlanjut — orang yang sama, kamera yang sama, jeda dalam batas
wajar tracker. Engine **tidak boleh** menyambung karena "tiga menit terlalu singkat
untuk dihitung istirahat". Yang pertama persepsi, yang kedua kebijakan, dan begitu
yang kedua masuk ke engine kamu menyembunyikan aturan kantor di dalam sensor.

Nilai N adalah konstanta perseptual (berapa lama tracker masih bisa yakin), bukan
konstanta kebijakan. Ia ada di §15 sebagai keputusan terbuka.

### 4.4 Batas interval harus bisa dimundurkan

Orang masuk jam 10:00:00, wajahnya baru terbaca jam 10:00:08. Kalau engine hanya
melaporkan waktu identifikasi, backend menghitung istirahatnya delapan detik lebih
panjang. Kecil per kejadian — tapi kalau seseorang keluar-masuk lima belas kali
sehari, itu dua menit yang dicuri dari jatahnya oleh latensi pengenalan, dan jatah
itu cuma tiga puluh menit.

Jadi `track.identified` wajib membawa **`track_started_pts`** di samping waktu
identifikasinya, dan `presence.interval` memakai yang pertama sebagai `start_pts`.

### 4.5 Bukti visual di batas interval

Simpan satu crop kecil saat interval berakhir dan saat dimulai lagi — beberapa
kilobyte per kejadian. Itu perbedaan antara sistem yang bisa diaudit dan sistem yang
cuma menuduh. Kalau seorang karyawan membantah istirahat dua belas menit, kamu bisa
melihat apakah crop terakhirnya memperlihatkan orang menuju pintu atau punggung
orang yang duduk menghadap tembok.

Biayanya privasi — ini menambah penyimpanan gambar wajah, lihat §7.4. Tapi mengingat
sistem ini sudah berada di wilayah data biometrik, dan konsekuensi dari **tidak**
punya bukti di sistem yang menjatuhkan sanksi jauh lebih berat, menurut dokumen ini
crop bukti layak dibayar. Keputusan finalnya ada di §15.

### 4.6 Titik buta kamera menghukum meja tertentu secara sistematis

Kalau ada bagian ruangan yang tidak tercakup — di balik tiang, di luar FOV — orang
yang duduk di situ akan tampak absen terus-menerus. Di absensi ini tidak kelihatan,
karena mereka tetap terdeteksi saat lewat. Di monitoring istirahat, orang itu akan
kena peringatan **setiap hari karena posisi mejanya**.

Engine harus mengekspos peta cakupannya — minimal region yang pernah menghasilkan
track versus region yang tidak pernah — supaya ini ketahuan saat instalasi, bukan
setelah tiga orang dipanggil HRD.

### 4.7 Presisi pengukuran harus jauh di bawah toleransi kebijakan

Jatahnya tiga puluh menit. Kalau celah palsu rata-rata lima menit dan terjadi
beberapa kali sehari, sebagian besar jatah itu habis oleh derau, bukan oleh
istirahat.

Artinya ada satu angka yang menentukan apakah fitur ini layak dijalankan sama
sekali: **berapa lama rata-rata track bertahan sebelum putus padahal orangnya masih
di ruangan.** Kalau angkanya dua menit, tidak ada logika backend yang bisa
menyelamatkannya. Angka itu masuk ke §13 sebagai metrik benchmark wajib, dan rekaman
representatif di §13 menjawabnya bersamaan dengan pertanyaan §3.

---

## 5. Arsitektur engine

### 5.1 Dua bidang bersama, satu per kamera

| Bidang | Isi | Sifat |
| --- | --- | --- |
| Inference bersama | Bobot model, GPU, worker pool, dynamic batching | Stateless, dibagi semua kamera |
| Per-kamera | Source, tracker, track ID, state pengenalan lokal | Terisolasi, termasuk isolasi kegagalan |
| Fusi identitas lintas kamera | Penggabungan bukti dari kamera yang FOV-nya bertumpang tindih | Perseptual, tetap di engine |

Bidang ketiga di revisi 1 ("identitas & absensi global") **pecah**: fusi bukti
perseptual tetap di engine karena butuh embedding, sementara sesi dan absensi
pindah ke backend.

Konsekuensi terpenting dari bidang pertama: begitu detector jadi **layanan bersama**
dan bukan objek milik masing-masing engine, frame dari lima kamera bisa ditumpuk
jadi satu batch. Satu forward pass menggantikan lima. Ini menuntut perubahan
spesifik — `VisionEngine` sekarang *memiliki* detector-nya
(`self._detector.detect(frame)`); yang harus terjadi adalah engine mengirim frame
ke antrian layanan dan menunggu hasilnya, dengan `max_wait` sekitar 10 ms supaya
kamera tidak saling menyandera saat sepi.

### 5.2 Frame loop dan cabang asinkron

Frame loop hanya berisi **capture → detect → track**. Recognition adalah cabang,
bukan tahap.

```
Capture ──► Detect ──► Track ──► Identity State ──► presence.interval ──► Backend
                                     │      ▲
                       perlu dikenali │      │ bukti
                                     ▼      │
                           Bounded Queue ──► Worker Pool ──► Evidence Accumulator
                                              (head crop, face detect,
                                               quality gate, align, embed)
```

**Isi antrian.** Satu permintaan = `(track_uuid, camera_id, head_crop, pts, priority)`.

**`head_crop` wajib salinan, bukan view.** `BoundingBoxPersonCropper.crop`
mengembalikan `image[y1:y2, x1:x2]`, yang di numpy adalah *view* ke buffer frame.
Aman selama sinkron. Begitu crop masuk queue, capture thread menimpa buffer itu
sebelum worker sempat memproses, dan yang di-embed adalah potongan dari frame yang
sama sekali berbeda — tanpa error, hanya akurasi aneh yang tidak bisa dijelaskan.
Tambahkan `.copy()` di titik submit **sebelum** memindahkan recognition ke worker.

**`track_uuid`, bukan `track_id`.** Hasil recognition datang terlambat beberapa
frame. Track-nya mungkin sudah mati, atau lebih buruk, tracker sudah mendaur ulang
ID-nya untuk orang lain. Key-nya harus unik seumur hidup track: `track_id` +
generation counter, atau UUID saat track lahir. Saat hasil tiba, verifikasi track
masih hidup dan masih generasi yang sama; kalau tidak, buang.

**Kebijakan antrian.**

- Bounded, dengan kuota per kamera supaya satu kamera ramai tidak memonopoli.
- Drop berdasarkan **umur**, bukan posisi: permintaan lebih tua dari ~500 ms
  dibuang, karena orangnya masih di sana dan crop yang lebih baru lebih berguna.
- Jangan pernah membuang permintaan terbaru demi mempertahankan yang lama.
- Prioritas: **track baru di `door_region`** > track belum confirmed > confirmed
  yang TTL-nya habis > verifikasi ulang berkala.
- **Set in-flight**, di-key `track_uuid`. Tanpa ini, policy akan terus bilang
  "belum confirmed, kenali lagi" tiap frame dan queue meledak dalam dua detik.

**Ukuran pool.** Dengan satu GPU, menambah worker tidak menambah throughput — GPU
tetap serial. Satu sampai dua worker dengan batching internal lebih cepat daripada
delapan yang berebut. Paralelisme di sini gunanya menyembunyikan latency dari main
loop, bukan menambah kapasitas.

**Metrik wajib:** kedalaman antrian, laju drop, umur permintaan saat di-dequeue,
utilisasi worker.

**Kapan dikerjakan:** terakhir, dan hanya kalau `bench.py` menunjukkan FPS turun
linear terhadap jumlah orang di frame.

### 5.3 Evidence accumulator dan state identitas

Pengganti logika `min_confirmations` yang sekarang tidak menggerbangi apa pun.

Per track disimpan jendela bukti terbatas — misal lima entri terakhir berisi
`(embedding, pts, quality_score)`. Pencocokan **tidak** dilakukan per frame lalu
divoting. Yang dilakukan: embedding ter-L2-normalisasi dirata-ratakan dengan bobot
quality, dinormalisasi ulang, lalu dicocokkan **sekali** pada vektor gabungan itu.

Alasannya statistik. Policy sekarang mengizinkan retry tiap 0,1 detik, jadi dua
"konfirmasi" datang dari dua gambar nyaris identik dengan error berkorelasi penuh.
Voting atas sampel berkorelasi tidak menambah informasi. Averaging meredam noise
pose dan blur dengan cara yang voting tidak bisa.

| State | Masuk kalau | Dipancarkan ke backend |
| --- | --- | --- |
| `PENDING` | Track baru, belum ada bukti | `track.started` saja |
| `PROVISIONAL` | Ada match tapi belum memenuhi syarat | Tidak, atau dengan flag tentatif |
| `CONFIRMED` | ≥K bukti tersebar ≥T detik, lolos margin test | **`track.identified`** dengan `track_started_pts` |
| `HELD` | Pernah confirmed, wajah tidak lagi terlihat | Heartbeat dengan `identity_source: tracking` |
| `EXPIRED` | TTL habis, perlu verifikasi ulang | Heartbeat dengan kepercayaan menurun |

State `HELD` mengikuti langsung dari §3.1, dan **setelah §4 ia jadi load-bearing**:
di ruangan dengan kamera sudut, inilah state yang paling lama ditempati, dan
kemampuannya menahan identitas tanpa wajah adalah satu-satunya hal yang mencegah
banjir istirahat palsu. Backend perlu tahu bedanya identitas yang baru diverifikasi
dari wajah dan identitas yang sedang dipegang tracker, karena keandalannya berbeda
dan meluruh seiring waktu.

Syarat konfirmasi wajib menyebar dalam waktu (`≥T`, mulai dari 0,5 detik), bukan
sekadar jumlah.

**Verifikasi ulang yang tidak setuju harus menurunkan kepercayaan, bukan menukar
identitas.** Perilaku sekarang (`update_with_match` menukar identitas dan reset
counter begitu match berbeda datang) membuat satu frame buruk bisa merebut track
yang sudah stabil. Pelepasan klaim lama butuh D ketidaksetujuan berturut-turut,
mulai dari D = 3.

**Margin test.** Threshold tunggal tidak cukup. Syaratnya dua: `best >= threshold`
**dan** `best - second_best >= margin`, mulai dari margin 0,05–0,08. Tanpa ini,
orang asing yang mirip dua karyawan akan diberikan ke salah satunya dengan percaya
diri, dan risikonya naik seiring pertumbuhan roster.

**Dedup identitas per frame.** Dua track tidak boleh sama-sama mengklaim karyawan
yang sama di satu kamera. Tolak klaim dari track dengan similarity lebih rendah.

### 5.4 Multi-kamera

Target lima kamera, satu per ruangan. Sebagian besar pasangan kemungkinan besar
`disjoint`.

**Topologi tetap jadi konfigurasi eksplisit.** Untuk tiap pasang kamera:
`overlap`, `adjacent`, atau `disjoint`. Lima kamera berarti sepuluh pasang.

| Relasi | Observasi bersamaan berarti | Tindakan |
| --- | --- | --- |
| `overlap` | Korroborasi — dua sudut pandang satu ruangan | Fusi bukti di engine, naikkan kepercayaan |
| `adjacent` | Handoff sedang berlangsung | Engine memberi tahu; backend menyambung sesi |
| `disjoint` | Kontradiksi — salah satu keliru | Similarity tertinggi menang, yang lain diturunkan |

Pasangan `overlap` adalah **hadiah**, bukan sekadar masalah dedup: situasi di mana
pengenalan wajah paling sering gagal adalah wajah profil, dan kalau kamera A melihat
profil sementara kamera B melihat frontal, fusi bukti dari keduanya lebih akurat
daripada kamera mana pun sendirian. Setelah §4, ada alasan kedua yang lebih kuat:
**dua kamera di satu ruangan memangkas celah palsu secara drastis**, karena orang
yang membelakangi kamera A kemungkinan besar menghadap kamera B. Kalau anggaran
mengizinkan satu kamera tambahan, ruangan dengan jatah istirahat paling ketat adalah
tempat menaruhnya.

Pembagiannya: **fusi bukti perseptual di engine** (butuh embedding), **penyambungan
sesi lintas ruangan di backend** (butuh aturan bisnis).

**Jangan bangun ReID dulu.** Asosiasi lintas kamera berbasis identitas hasil
pengenalan, ditambah topologi dan waktu, sudah cukup untuk lima kamera di denah yang
dikenal. ReID penuh adalah model tambahan, biaya inference tambahan, dan masalah
akurasi tersendiri.

### 5.5 Lapisan ingest

OpenCV harus keluar dari sini. `cv2.VideoCapture.read()` mengembalikan frame dan
boolean — **PTS-nya dibuang**, dan tanpa PTS seluruh skema waktu di §6.6 tidak bisa
dibangun. OpenCV juga yang menghalangi pemakaian NVDEC dengan rapi. Jadi "pakai PTS"
dan "buang OpenCV dari ingest" adalah satu keputusan, bukan dua.

**PyAV adalah penggantinya.** Binding langsung ke libav*/FFmpeg, bukan wrapper tingkat
tinggi, jadi `frame.pts` dan `stream.time_base` adalah warga kelas satu:
`pts_detik = frame.pts * float(stream.time_base)`. Untuk RTSP, `time_base` biasanya
1/90000 karena itu satuan RTP.

**PTS dan NVDEC adalah dua hal terpisah**, dan PyAV hanya menjamin yang pertama. Wheel
PyAV dari PyPI membawa FFmpeg yang sudah dikompilasi, dan build itu umumnya **tidak**
menyertakan CUDA — `pip install av` memberi PTS dengan decode tetap di CPU. Jangan
percaya dokumentasi; cek sendiri:

```python
import av
print([c for c in av.codecs_available if 'cuvid' in c or 'nvdec' in c])
```

Kalau kosong: kompilasi PyAV terhadap FFmpeg sistem yang dibangun dengan
`--enable-cuda-nvcc --enable-cuvid --enable-nvdec`, atau turun ke **PyNvVideoCodec**
(binding resmi NVIDIA, penerus VideoProcessingFramework).

**Hadiah sebenarnya dari NVDEC bukan melepas beban CPU, tapi frame yang tetap tinggal
di VRAM.** Kalau hasil decode disalin ke memori host untuk jadi array numpy, kamu
membayar transfer PCIe dan konversi format tiap frame, lalu menyalinnya balik ke GPU
saat detector jalan — bolak-balik percuma. Pipeline yang benar-benar cepat men-decode
ke device memory dan menyuapkannya langsung ke ONNX Runtime lewat IO binding, tanpa
pernah menyentuh RAM. **Jangan kerjakan sekarang:** ambil PyAV dulu untuk PTS, ukur
dengan `bench.py`, baru putuskan apakah round-trip PCIe benar-benar muncul di profil.

**GStreamer** (`rtspsrc ! nvh264dec` lewat PyGObject) adalah opsi ketiga. Ekosistemnya
sendiri dan bindingnya canggung, tapi untuk RTSP 24/7 ia paling matang soal hal-hal
membosankan yang akan menggigit: reconnect otomatis, jitter buffer, stream putus-nyambung.
Kalau logika reconnect buatan sendiri mulai jadi beban, ke situlah larinya.

**Yang tidak cocok:** pipe subprocess ffmpeg ke rawvideo. Gampang dan bisa pakai
`-hwaccel cuda` penuh, tapi PTS-nya hilang — yang tersisa cuma menghitung frame dan
mengalikan fps, dan itu melenceng begitu ada frame yang di-drop. Persis kondisi yang
tidak boleh terjadi pada batas interval yang jadi dasar sanksi (§4).

**Dua flag yang praktis wajib untuk RTSP produksi:** `rtsp_transport=tcp` — UDP
kehilangan paket dan menghasilkan frame rusak yang akan merusak embedding tanpa
terlihat — dan timeout eksplisit, supaya kamera mati tidak menggantung thread selamanya.

---

## 6. Protokol engine ↔ backend

Menggantikan `EngineService` dan `EngineWorker` sepenuhnya.

### 6.1 Kondisi sekarang yang harus dibongkar

Fasadnya ada tapi mati: `EngineService` di `engine/app/engine_service.py` tidak
dipanggil siapa pun; `backend/engine_service.py` hanya shim yang meng-alias
`EngineWorker`. Sementara `EngineWorker` memalsukan `argparse.Namespace` untuk
memanggil `build_app` (entry point CLI), meng-import kelas event langsung dari
`engine.plugins.face_recognizer`, mengiterasi `self.engine._listeners` (atribut
privat), melakukan dispatch dengan `type(listener).__name__` (nama kelas sebagai
string), dan menyetel `self.engine._source._loop`.

Konsekuensi konkret: rename satu kelas listener, dan `getattr` dengan default kosong
membuat event hook diam-diam tidak terpasang — tanpa error, tanpa log, absensi hanya
berhenti tercatat.

Akar masalahnya bukan disiplin, tapi fasadnya yang tidak cukup: `process_frame()`
adalah API **pull** yang memaksa pemanggil menggerakkan loop, dan single-camera.

### 6.2 Bentuk dan kanal

**NDJSON di atas socket.** Satu objek JSON per baris, newline sebagai framing.
Setiap bahasa bisa membacanya dalam sepuluh baris tanpa library, tanpa codegen, dan
bisa di-debug dengan `nc` dan mata telanjang. gRPC lebih rapi secara tipe tapi
menambah codegen dan build step — dan tujuannya justru **menurunkan** biaya ganti
bahasa.

Volumenya bukan alasan khawatir: 5 kamera × 10 fps × 3 orang ≈ 150 pesan/detik.
**Yang jadi masalah di arsitektur ini bukan performa, tapi ketahanan.**

| Kanal | Arah | Jaminan | Isi |
| --- | --- | --- | --- |
| `control` | Backend → Engine | Request/response, ack cepat | Config kamera, roster, enrollment |
| `events` | Engine → Backend | **Andal, berurut, bisa diulang** | Interval kehadiran, siklus hidup track, status kamera |
| `view` | Engine → Backend | **Best-effort, boleh drop** | Bbox per frame untuk overlay browser |

Pemisahan `events` dan `view` bukan kerapian: kalau backend lambat, engine
**membuang** bbox dan jalan terus, tapi **tidak pernah** membuang event domain. Yang
haram adalah engine memblok menunggu backend, karena pencatatan kehadiran adalah
produknya sementara dashboard hanya tampilan.

### 6.3 Handshake dan rekonsiliasi deklaratif

**Jangan pakai perintah imperatif.** Bukan `add_camera` / `remove_camera`. Backend
mengirim **seluruh himpunan yang diinginkan**, engine mencocokkan state-nya dengan
itu — buka yang belum ada, tutup yang tidak ada di daftar, biarkan yang cocok.

Perintah imperatif akan desync begitu satu pesan hilang atau satu sisi restart, dan
kamu tidak akan tahu sampai ada kamera hantu yang masih diproses padahal sudah
dihapus dari UI. Deklaratif kebal terhadap itu.

```
backend → engine   { "type": "hello", "protocol_version": 1,
                     "last_event_seq": 10432 }
engine  → backend  { "type": "hello_ack", "engine_version": "...",
                     "models": {...}, "protocol_version": 1 }

backend → engine   { "type": "set_cameras", "cameras": [
                       { "camera_id": "r1", "uri": "rtsp://...",
                         "door_region": [x1,y1,x2,y2] }, ... ] }
engine  → backend   { "type": "ack", "accepted": true }
                    ... lalu per kamera, menyusul:
                    { "type": "camera.online",  "camera_id": "r1" }
                    { "type": "camera.failed",  "camera_id": "r3",
                      "reason": "connection_refused" }

backend → engine   { "type": "set_roster", "persons": [
                       { "person_id": "4471", "enrollment_version": 3 }, ... ] }
engine  → backend   { "type": "enrollment_needed", "person_ids": ["4471"] }
```

**Perintah di-ack segera, hasilnya datang sebagai event.** Membuka RTSP bisa makan
lima detik dan bisa gagal. Kalau `set_cameras` adalah RPC yang menunggu sampai semua
stream tersambung, backend menggantung di startup.

Roster memakai pola yang sama dengan kamera — **satu mekanisme rekonsiliasi, dua
kegunaan.** Yang dikirim cuma ID dan versi, bukan vektornya.

### 6.4 Katalog event

Kosakatanya **domain, bukan vision**. Tidak ada `FaceRecognizedEvent` di permukaan
publik — itu detail bahwa identifikasi kebetulan dilakukan lewat wajah. Kalau nanti
ada sumber identitas kedua (kartu RFID), event-event ini tetap valid.

| Event | Isi penting |
| --- | --- |
| **`presence.interval`** | **Output utama — lihat §4.2** |
| `track.started` | `track_uuid`, `camera_id`, `pts`, `zone` |
| `track.identified` | `track_uuid`, `person_id`, `similarity`, `margin`, `evidence_count`, **`track_started_pts`** |
| `track.resumed` | `track_uuid` baru, `prev_interval_seq`, jeda dalam detik |
| `track.identity_changed` | Identitas lama, identitas baru, alasan |
| `track.heartbeat` | `track_uuid`, `person_id?`, `identity_source` (`face`/`tracking`), `confidence` |
| `track.ended` | `track_uuid`, `pts`, **`reason`**, **`exit_zone`** |
| `person.unidentified_present` | Track hidup > N detik tanpa identitas — lihat §12.1 |
| `camera.online` / `camera.failed` / `camera.degraded` | `camera_id`, `reason`, `fps` |
| `camera.coverage` | Peta region yang pernah/tidak pernah menghasilkan track (§4.6) |
| `engine.health` | Model termuat, GPU, kedalaman antrian, laju drop |
| `snapshot` | Daftar lengkap track hidup + identitasnya, berkala |

**`snapshot` berkala** memberi backend jalan menyelaraskan diri tanpa memutar ulang
seluruh riwayat — murah, dan menyelamatkan saat backend melewatkan satu event atau
baru restart.

### 6.5 Outbox, sequence, dan pemulihan

Dulu penyerahan event cuma pemanggilan fungsi yang tidak bisa gagal. Sekarang ada
socket yang bisa putus dan backend yang bisa di-deploy ulang di tengah hari kerja.
Tanpa penanganan, **setiap restart backend = kehilangan event diam-diam.**

Mekanismenya kecil: engine menomori tiap event kanal `events` dengan sequence
monoton, menyimpannya di log lokal, dan saat backend menyambung ia mengirim
`last_event_seq` di `hello`; engine mengulang dari nomor berikutnya. Lima puluh
baris, dan ia mengubah deploy backend dari operasi berisiko jadi hal yang tidak
perlu dipikirkan.

Retensi log outbox: cukup beberapa hari, dipangkas setelah backend meng-ack.

### 6.6 Waktu: PTS, bukan wall clock

Jangan menyinkronkan dua jam. **Sudah ada referensi waktu bersama yang datang dari
sumber yang sama** — RTP timestamp / PTS dari kamera. Engine menempelkan PTS di tiap
pesan, dan seluruh aritmetika interval dikerjakan dalam satuan itu: tidak ada NTP,
tidak ada drift, tidak ada yang perlu disepakati antar proses.

Untuk overlay di browser, jembatannya bukan PTS melainkan **jam dinding**, karena
MediaMTX menyajikan HLS dengan `EXT-X-PROGRAM-DATE-TIME` (§6.7.1). Karena itu pesan
`view.frame` membawa PTS **dan** waktu absolut — yang pertama untuk menyambung ke
event engine, yang kedua untuk menyambung ke segmen HLS.

Prasyaratnya ada di §5.5: PTS hanya tersedia kalau ingest pindah dari OpenCV ke PyAV.

**Tapi PTS itu relatif, bukan waktu absolut.** RTP memulai timestamp dari offset acak,
jadi `frame.pts` tidak memberitahu jam berapa sekarang — ia hanya konsisten di dalam
satu stream. Untuk menyelaraskan video dengan overlay di browser itu sudah cukup. Tapi
interval kehadiran akhirnya harus berbunyi "10:15 sampai 10:35", dan itu butuh jam
dinding.

Polanya: **tetapkan offset PTS→wallclock sekali saat stream dibuka**, lakukan semua
aritmetika interval dalam PTS — presisi, tanpa drift — dan konversi ke waktu absolut
hanya di tepi, saat event dipancarkan.

**Offset itu wajib ditetapkan ulang setiap reconnect**, karena stream baru berarti
offset baru. Ini satu baris kode yang kalau terlewat menghasilkan bug yang sangat
membingungkan: setiap kamera yang sempat putus akan melaporkan interval di tahun yang
salah, dan hanya kamera itu.

FFmpeg punya `-use_wallclock_as_timestamps 1` yang menimpa PTS dengan waktu terima.
**Jangan pakai untuk ini** — ia memasukkan jitter jaringan ke dalam timestamp, menukar
presisi dengan kenyamanan yang tidak dibutuhkan.

**Aturan kepemilikan jam:** engine memiliki waktu untuk semua yang dilaporkannya, dan
**backend tidak pernah menghitung durasi sendiri dari jamnya**. Ini naik dari saran
jadi keharusan setelah §4: jatah tiga puluh menit yang diakumulasi dari dua puluh
celah kecil akan mengumpulkan kesalahan batas, dan kesalahan itu memihak satu arah.

**Bedakan dua kebutuhan sinkronisasi.** Overlay bbox butuh sinkron ketat tapi murni
kosmetik — kotak telat 150 ms cuma terlihat sedikit meleset. Event domain tidak butuh
sinkron sama sekali. Kerjakan yang kosmetik seadanya dan jangan biarkan ia menyandera
yang penting.

### 6.7 Topologi video

**Kamera tidak mengirim ke mana-mana.** RTSP itu pull, bukan push — kamera adalah
server yang diam sampai ada klien menyambung dan meminta. Jadi yang menentukan
topologi bukan "kamera kirim ke siapa", tapi "siapa yang menarik".

```
   ┌────────────┐
   │  Kamera    │  RTSP server, diam sampai ditarik
   └─────┬──────┘
         │
    ┌────┴──────────────────────┐
    ▼                           ▼
┌─────────┐              ┌────────────┐
│ ENGINE  │              │  MEDIAMTX  │  remux saja, on-demand
│ decode  │              │            │  (tidak pernah decode)
│ analisa │              └──────┬─────┘
└────┬────┘                     │
     │ NDJSON events            │
     ▼                          │
┌──────────┐   "boleh lihat?"   │
│ BACKEND  │◄───────────────────┤
└────┬─────┘                    │
     │ API + bbox JSON          │ HLS
     ▼                          ▼
   ┌────────────────────────────┐
   │         FRONTEND           │  gambar kotak sendiri
   └────────────────────────────┘
```

**Frontend tidak pernah menyentuh kamera.** Video datang dari MediaMTX, data datang
dari backend, dan backend tetap yang memutuskan siapa boleh melihat apa.

Alasannya bukan preferensi arsitektur tapi kenyataan teknis: **browser tidak bisa
memutar RTSP.** Harus ada yang menerjemahkan ke sesuatu yang bisa dimainkan `<video>`,
dan kredensial kamera tidak boleh pernah keluar dari sisi server. Kalau frontend
menarik langsung dari kamera, setiap orang yang membuka dashboard punya akses penuh
ke CCTV kantor.

### 6.7.1 MediaMTX, bukan relay buatan sendiri

**Remux, bukan transcode.** Byte H.264 yang sudah jadi dibungkus ulang ke container
lain — tidak pernah di-decode, tidak pernah di-encode. CPU nyaris nol, kualitas
identik. Kalau dua pihak sama-sama men-decode, kamu membayar decode 1080p lima kamera
**dua kali**: 6–10 core untuk pekerjaan yang hasilnya tidak dipakai.

**Yang melakukannya adalah MediaMTX**, bukan kode backend. Satu binary Go statis,
lisensi MIT, satu file YAML. Ia menarik RTSP dari kamera dan menyajikannya ulang
sebagai HLS dan WebRTC sekaligus, punya HTTP API untuk menambah/menghapus path saat
jalan, dan `sourceOnDemand` membuatnya **hanya menarik saat ada yang menonton** —
dashboard kosong berarti nol koneksi ke kamera, bukan lima yang menyala sepanjang hari.

**Jalur utamanya HLS**, dan pilihan itu sengaja:

| | HLS | WebRTC | Relay sendiri (fMP4/MSE) |
| --- | --- | --- | --- |
| Latensi | 2–10 detik | < 1 detik | ~1 detik |
| Penyelarasan ke waktu | `EXT-X-PROGRAM-DATE-TIME` | **Timestamp ditulis ulang, jejak hilang** | Penuh kendali |
| Bisa di-seek / diputar ulang | Ya | **Tidak ada konsepnya** | Perlu dibangun |
| Biaya pengerjaan | Konfigurasi | Konfigurasi | 1–2 minggu orang backend |

Latensi adalah sumbu **paling tidak penting** di sini. Yang menonton dashboard ini
adalah HR dan supervisor yang mengecek siapa hadir atau memeriksa sanggahan istirahat;
tidak ada kasus pakai yang peka terhadap lag tiga detik. Ini bukan satpam memelototi
layar mencari penyusup.

Dan ada alasan kedua yang lebih menentukan: **overlay yang bernilai bukan yang live,
tapi yang playback.** Nilai produk sesungguhnya ada di "tunjukkan apa yang kamera lihat
jam 10:15 saat sistem bilang dia pergi" — itu memutar ulang dan men-seek ke timestamp,
yang HLS lakukan secara alami dan WebRTC tidak punya konsepnya. Overlay di tampilan
live sebagian besar dekorasi; "ada 3 orang, 2 dikenali" tersampaikan sama baiknya lewat
daftar nama di samping video.

Kalau nanti tetap ada yang menginginkan tampilan live responsif, WebRTC tinggal
endpoint kedua dari **tarikan yang sama** — tanpa koneksi tambahan ke kamera, tanpa
kode baru. Itu keuntungan yang hilang kalau relaynya dibangun sendiri.

**Otorisasi tetap di backend.** Byte video mengambil jalan pintas lewat MediaMTX, tapi
keputusan akses tidak: pakai hook autentikasi eksternal, di mana MediaMTX bertanya ke
backend "user ini boleh melihat `r1`?" sebelum mengizinkan. Memakai daftar user internal
MediaMTX berarti dua sistem izin yang harus disinkronkan, dan suatu hari keduanya akan
berbeda pendapat.

**Jangan gambar bounding box di server.** Kirim video apa adanya, kirim koordinat lewat
kanal `view`, dan biarkan **browser** menggambar overlay di atas `<video>` pakai canvas.
Menggambar di server berarti decode, gambar, encode ulang — tiga operasi mahal untuk
sesuatu yang di browser cuma `ctx.strokeRect`.

**Satu hal yang wajib diuji di minggu pertama:** akurasi `EXT-X-PROGRAM-DATE-TIME` dari
MediaMTX terhadap waktu event engine. Ini satu-satunya hal yang bisa memaksa kembali ke
relay buatan sendiri, dan kamu ingin tahu selagi masih murah. Kalau ternyata meleset,
jalan keluarnya **bukan** langsung menulis relay — terima penyelarasan perkiraan dengan
offset tetap yang disetel dengan mata, karena overlay itu kosmetik dan event domain
tidak terpengaruh sama sekali.

### 6.7.2 Yang wajib dicek sebelum instalasi

**Codec kamera harus H.264 untuk stream dashboard.** Banyak kamera modern default ke
H.265/HEVC untuk menghemat bandwidth, dan browser sebagian besar tidak bisa
memutarnya. Kalau itu terjadi kamu terpaksa **transcode** — decode plus encode untuk
lima stream — yang mengubah anggaran CPU secara total dan bisa memakan GPU yang
seharusnya untuk inference. Ini setting di kamera, gratis, dan kalau terlewat kamu
akan menemukannya di minggu terakhir.

**Batas koneksi RTSP bersamaan**, sering 2–4 per kamera:

| Penarik | Stream | Kapan menarik | Untuk apa |
| --- | --- | --- | --- |
| Engine | mainstream | Selalu | Crop wajah butuh resolusi penuh |
| MediaMTX | **substream** | **Hanya saat ditonton** | Dashboard tidak butuh 1080p |

MediaMTX sengaja mengambil substream — biasanya 640×480 atau 720p, lebih dari cukup
untuk memantau ruangan, dan memangkas bandwidth serta beban remux. Dengan
`sourceOnDemand`, sebagian besar waktu kamera hanya melayani satu klien, yaitu engine.

Ini juga alasan kedua kenapa koordinat bbox harus **ternormalisasi [0,1]** (§12):
engine melihat mainstream, browser melihat substream, dan kalau koordinatnya dalam
piksel, kotaknya meleset di resolusi yang berbeda.

Kalau nanti engine juga ingin substream untuk deteksi (dual-stream di §12), itu jadi
tiga koneksi per kamera dan batas kamera mulai jadi nyata. Alternatifnya engine
menarik mainstream sekali lalu men-downscale sendiri di memori.

### 6.8 Versi protokol

Begitu ini jadi protokol kabel lintas bahasa, kamu tidak bisa lagi refactor kedua
sisi sekaligus. Perlu field `protocol_version`, aturan evolusi **hanya-menambah**,
dan kesepakatan bahwa **field tak dikenal diabaikan diam-diam**.

**Aturan dependensi, ditegakkan dengan tes:** setelah pemisahan, `backend/` tidak
boleh meng-import apa pun dari `engine/`. Tes sepuluh baris yang memindai import
menangkap setiap pelanggaran.

---

## 7. Embedding dan penyimpanan

### 7.1 Pembagian

**Engine menyimpan vektor, backend menyimpan orangnya, disambung satu ID buram.**

Backend tidak bisa melakukan apa pun dengan 512 angka float — tidak bisa mencocokkan,
tidak bisa menampilkan, tidak bisa memvalidasi. Kalau backend menyimpannya, ia cuma
jadi tempat penitipan yang membuat setiap pengenalan harus melewati jaringan untuk
mengambil sesuatu yang seharusnya sudah ada di RAM engine.

Backend tahu `person_id: 4471` bernama Budi, departemen produksi, masih aktif. Engine
tahu `person_id: 4471` punya lima vektor dengan skor kualitas sekian. Ini bertahan
saat backend ditulis ulang dalam bahasa lain.

### 7.2 Jangan pakai vector database

Hitung dulu: 200 karyawan × 5 referensi × 512 float32 ≈ **2 MB**. Muat di RAM dengan
sisa sangat banyak, dan brute-force GEMV di numpy menyelesaikannya dalam mikrodetik.
FAISS, Milvus, atau pgvector di skala ini justru **lebih lambat** karena overhead
index dan panggilan jaringan, sambil menambah layanan yang harus dioperasikan,
dimonitor, dan di-backup. Ambang di mana ANN mulai masuk akal ada di ratusan ribu
vektor — sekitar dua puluh ribu karyawan.

Dan jangan bangun pemilih adaptif antara keduanya: keputusannya satu dimensi dan
monoton, jadi itu satu konstanta yang ditemukan sekali dengan benchmark dua puluh
baris, bukan model yang harus dilatih dan di-debug untuk menggantikan sebuah `if`.

**Yang dipakai:** SQLite sebagai sumber kebenaran di sisi engine — satu file, tanpa
server, binding di semua bahasa, transaksional — plus satu matriks `(M, 512)` kontigu
di RAM yang dibangun ulang saat roster berubah.

### 7.3 Versi model — yang akan menggigit

Setiap vektor **wajib** disimpan dengan tag model yang menghasilkannya. Embedding dari
iResNet100 dan dari R50 hidup di ruang vektor yang berbeda; cosine similarity antara
keduanya bukan angka yang salah, itu angka yang **tidak punya arti apa pun**. Tanpa
tag, suatu hari kamu mengganti embedder, sistem tetap jalan tanpa satu pun error, dan
akurasinya jatuh ke level acak tanpa petunjuk kenapa.

Aturannya: **versi tidak cocok berarti tolak mencocokkan**, bukan diam-diam bandingkan.

Ini juga alasan kuat untuk **menyimpan gambar referensi aslinya**. Ganti model, dan
semua vektor jadi sampah; dengan gambar asli kamu tinggal hitung ulang dalam beberapa
menit, tanpa itu kamu harus memanggil seluruh karyawan untuk foto ulang.

### 7.4 Privasi

Menyimpan vektor dan bukan foto **bukan** pembelaan privasi. Template inversion bisa
merekonstruksi wajah yang dikenali dari embedding ArcFace 512 dimensi — vektor itu
bukan data anonim, dan di bawah UU 27/2022 (PDP) ia tetap data biometrik. Keduanya
butuh enkripsi at-rest, kontrol akses lebih ketat dari data lain, dan jadwal retensi.

Crop bukti dari §4.5 masuk kategori yang sama dan menambah volumenya; retensinya
sebaiknya lebih pendek dari referensi enrollment — cukup sampai jendela sanggahan
karyawan lewat.

Pemisahan engine/backend justru membantu: seluruh data biometrik terkumpul di satu
proses dengan satu permukaan akses, terpisah fisik dari data HR. Penghapusan karyawan
jadi dua langkah jelas — backend membuang catatannya, lalu rekonsiliasi roster
otomatis membuat engine membuang vektornya.

---

## 8. Keputusan model & lisensi

Satu-satunya masalah lisensi nyata di stack adalah **Ultralytics (AGPL-3.0)**, dipakai
untuk detector *dan* tracker. AGPL punya klausul copyleft jaringan, dan sistem ini
diekspos lewat jaringan.

Sisi pengenalan wajah sudah bersih: bobotnya dari `fal/AuraFace-v1`, Apache-2.0,
eksplisit untuk penggunaan komersial.

| Komponen | Sekarang | Keputusan | Pertimbangan |
| --- | --- | --- | --- |
| Detektor objek | YOLO11s via Ultralytics | D-FINE resmi via Transformers | Checkpoint COCO Apache-2.0; adapter engine tidak bergantung Ultralytics |
| Tracker | ByteTrack via Ultralytics | Vendor ByteTrack asli (MIT) atau `supervision` | Sumber AGPL yang sama; algoritma aslinya MIT |
| Detektor wajah | SCRFD-10G (pack AuraFace) | Pertahankan; head-crop + input 320 dulu | Lisensi bersih; YuNet hanya kalau benchmark menuntut |
| Aligner | 5-point affine, template ArcFace | Pertahankan | Konvensi landmark terikat ke detector |
| Embedder | AuraFace-v1 iResNet100 | Pertahankan | Apache-2.0; R50 diuji belakangan |
| Matcher | Loop Python | Matriks `(M,512)` + margin test | Dua orde magnitudo; margin menurunkan false accept |
| Runtime | torch + ultralytics + onnxruntime | numpy + opencv + onnxruntime | Image jauh lebih kecil |

**Hindari BoxMOT.** Library tracker yang paling sering direkomendasikan, dan lisensinya
AGPL-3.0 — persis masalah yang sedang dihindari.

**Ganti tracker lebih dulu, sendirian.** Vendor empat file inti dari ByteTrack asli —
`byte_tracker.py`, `kalman_filter.py`, `matching.py`, `basetrack.py`, sekitar 600 baris,
pertahankan header lisensinya. Dependensinya numpy, scipy, dan `lap`/`lapx`;
`cython_bbox` bisa diganti IoU numpy sepuluh baris. Perilakunya hampir identik dengan
yang sekarang, jadi risiko regresi nyaris nol.

Ingat §3.1 dan §4.7: dengan kamera sudut **dan** monitoring istirahat, umur track
sebelum putus adalah metrik produk, bukan metrik teknis. Benchmark ID switch dan
ketahanan track di langkah ini bukan formalitas.

**Baru setelah itu ganti detector.** Dua catatan saat itu terjadi. Postprocess D-FINE
NMS-free, jadi adapter-nya bukan salinan adapter YOLO — ini justru menghemat satu tahap
CPU. Dan **kalibrasi confidence keluarga DETR berbeda** dari detektor berbasis NMS,
jadi `track_high_thresh`, `new_track_thresh`, dan `match_thresh` wajib disetel ulang.
Lebih dalam: seluruh trik ByteTrack adalah asosiasi tahap kedua memakai deteksi berskor
rendah, dengan asumsi skor rendah berarti objek teroklusi. Di DETR, skor rendah
kebanyakan query duplikat dan background — tahap kedua berpotensi menambah noise, bukan
recall. Ukur, dan siap mematikan `track_low_thresh`.

### Catatan hardware

**FP16 adalah jebakan di GTX 1060.** Pascal (GP106) menjalankan FP16 di rasio 1/64 dari
FP32 — dilumpuhkan sengaja di kartu consumer. `half=True` di 1060 **menurunkan**
performa. Di RTX 4060 (Ada, dengan tensor core) barulah FP16 jadi default yang benar.

Konsekuensinya: pakai 1060 hanya untuk memvalidasi **kebenaran**. Semua angka yang jadi
dasar keputusan beli server harus dari **4060**.

### Anggaran kasar, 5 kamera 1080p

Estimasi, harus diukur:

| | RTX 4060 mobile | GTX 1060 Max-Q |
| --- | --- | --- |
| YOLO11s @640 per gambar | ~3–5 ms (FP16) | ~18–25 ms (FP32) |
| SCRFD-10G @640 | ~4–6 ms | ~15–25 ms |
| iResNet100 embed | ~3–5 ms | ~15–20 ms |

Pada 30 fps × 5 kamera = 150 inferensi deteksi per detik, 4060 sudah terpakai 50–75%
**hanya untuk deteksi**. Ini sebelum menghitung decode: lima stream 1080p H.264
di-decode CPU itu sekitar 3–5 core, berjalan di capture thread di mana profiler tidak
akan melihatnya. **Gunakan NVDEC** — prasyarat untuk lima kamera, bukan optimisasi.

Kabar baiknya, §3.1 memberi kelonggaran: dengan strategi tangkap-momen-baik, engine
tidak perlu mencoba mengenali setiap orang di setiap frame.

---

## 9. Bug kebenaran

Semua di bawah ini membuat sistem mencatat data yang salah **tanpa memunculkan error**.
Kerjakan lebih dulu dari optimisasi apa pun.

1. **`min_confirmations` tidak menggerbangi apa pun.**
   `cache/recognition_cache.py::update_with_match` menyetel `state.identity` dan
   `CONFIRMED` pada match pertama; `pipeline/plugin.py` menyalinnya ke
   `track.attributes["identity"]`; sesi terbuka atas nama karyawan itu. Satu frame
   tunggal cukup untuk tercatat hadir.

2. **Tidak ada margin test.** `matching/matcher.py` mengambil best match dari seluruh
   roster dengan threshold 0,37 — longgar untuk cosine ArcFace — tanpa uji jarak ke
   kandidat kedua.

3. **Konfirmasi berasal dari frame berkorelasi.** Retry 0,1 detik membuat dua
   konfirmasi datang dari dua gambar nyaris identik. Ganti dengan fusi embedding (§5.3).

4. **Verifikasi ulang yang tidak setuju membajak identitas.** Satu frame buruk bisa
   merebut track yang sudah stabil.

5. **Tidak ada dedup identitas antar track.** Dua track bisa sama-sama mengklaim
   karyawan yang sama.

6. **Tiga sumber kebenaran untuk "siapa hadir".** `RecognitionCache`,
   `AttendanceTracker._sessions` (key `employee_id`, global), dan
   `SystemState._active_sessions` (key `camera_id + identity`, per kamera, dengan jam
   dan aturan prune sendiri) saling bertentangan. **Diselesaikan oleh §2** — engine
   berhenti memelihara sesi sama sekali.

7. **`detection_interval` memberi deteksi basi ke tracker.**
   `vision_core/pipeline/engine.py` menyuapkan `self._cached_detections` dari frame
   sebelumnya saat frame di-skip, jadi ByteTrack mengasosiasi ke posisi lama dan
   velocity jadi sampah. Pola yang benar: tracker melakukan predict-only tanpa update.
   Sampai diperbaiki, `detection_interval: 1` satu-satunya nilai aman.

8. **Dua jam dalam satu sistem**, dan setelah pemisahan proses berpotensi jadi tiga.
   Diselesaikan oleh aturan kepemilikan jam di §6.6.

9. **Gagal diam-diam pada model yang hilang.** `SCRFDDetector._init_model` dan
   `GLINTR100Embedder._init_session` menelan exception dan menyetel model ke `None`;
   `detect()` lalu mengembalikan `[]` selamanya. Log bersih, dashboard hidup, nol data
   tercatat — mode kegagalan terburuk: bukan mati, tapi berbohong. Tambahkan
   `strict_mode` yang menggagalkan startup, plus health flag di `engine.health`.

10. **`crop()` mengembalikan view, bukan salinan.** Aman selama sinkron, korupsi data
    diam-diam begitu asinkron (§5.2).

11. **`_is_break_time()` dengan jam 12–13 di-hardcode di lapisan transport**, bersama
    `total_facilities=4` di `get_dashboard_stats`. Kebijakan di tempat yang salah dua
    kali. Setelah §2, keduanya pindah ke backend sebagai konfigurasi.

**Satuan waktu.** Semua parameter temporal di config harus dalam **detik**, dikonversi
ke frame saat konstruksi memakai fps efektif. `ByteTrackTracker` sekarang hardcode
`frame_rate=30` dan `track_buffer=30` — di 10 fps, buffer itu berubah arti dari 1 detik
jadi 3 detik dan model gerak Kalman jadi salah kalibrasi.

---

## 10. Enrollment

Kualitas enrollment menentukan langit-langit akurasi seluruh sistem. Tidak ada
threshold, fusi, atau margin test yang bisa memperbaiki referensi yang buruk. Kondisi
sekarang: `EnrollmentService` menerima gambar, menolak kalau ada nol atau lebih dari
satu wajah, lalu meng-embed. Itu saja.

**Alurnya melintasi batas proses.** Alur upload dan persetujuan ada di backend, tapi
model ada di engine. Jadi: backend meneruskan gambar ke engine lewat kanal `control`;
engine menjalankan seluruh gerbang di bawah lalu membalas diterima atau ditolak beserta
alasan dan skor per gambar; backend menyimpan catatan orang dan metadata audit, engine
menyimpan vektor. Base64 di JSON cukup — enrollment terjadi sekali per karyawan seumur
hidup.

**Quality gate per gambar referensi.** Lebih ketat daripada gate runtime, karena
referensi buruk merusak permanen sementara frame buruk hanya merusak satu percobaan.

- Ukuran face bbox minimal — cukup besar sehingga alignment ke 112×112 tidak meng-upscale.
- Ketajaman: variance of Laplacian di atas ambang.
- Pose: yaw kasar dari asimetri 5 landmark, tolak profil ekstrem.
- Pencahayaan: tolak yang terlalu gelap, terlalu terang, atau kontras rendah.
- Confidence detector di atas ambang yang lebih tinggi dari runtime.

**Uji keberagaman.** Lima foto dari sesi yang sama dengan pose identik adalah satu
referensi efektif yang menyamar jadi lima. Hitung cosine antar referensi yang lolos
gate: kalau sepasang terlalu mirip (mulai dari ambang 0,9), yang kedua ditolak sebagai
duplikat. Wajibkan minimal tiga referensi yang lolos.

**Uji tabrakan antar karyawan.** Sebelum menyimpan, cocokkan embedding gabungan karyawan
baru terhadap **seluruh** referensi yang sudah terdaftar. Kalau similarity tertinggi
melewati ambang tabrakan (threshold pengenalan + margin), **tolak enrollment** dan
sebutkan karyawan mana yang bentrok. Tanpa ini, dua orang mirip akan tertukar selamanya.

**Enrollment dari frame CCTV, bukan pas foto.** Kalau referensi dari foto KTP sementara
pengenalan dari kamera sudut ruangan, ada domain gap yang tidak bisa ditutup threshold
apa pun. Sediakan mode enrollment yang menangkap langsung dari kamera yang akan dipakai,
di posisi yang akan dipakai — idealnya dari `door_region` (§3.2), karena di situlah
kondisi runtime terbaiknya berada.

**Kalau masker umum, enroll bermasker** (§3.3).

**Metadata per referensi.** Simpan `camera_id`, timestamp, skor kualitas, dan versi
model.

**Jalur re-enrollment.** Akurasi bisa menurun karena potong rambut, kacamata baru, atau
kamera dipindah. Harus ada cara menambah referensi baru dan membuang yang lama tanpa
menghapus riwayat.

---

## 11. Keselamatan operasional

### 11.1 Dua mode kegagalan yang melukai orang

**Absen palsu.** Seseorang bekerja delapan jam, pengenalannya gagal terus, sistem
mencatat tidak hadir. Gajinya dipotong oleh bug.

**Istirahat palsu.** Seseorang duduk di mejanya, track-nya putus dua belas menit, dan
jatah tiga puluh menitnya terpakai tanpa dia beranjak. Ini yang lebih berbahaya, karena
lebih sulit dibantah dan lebih sering terjadi (§4.1).

Tiga hal yang wajib ada:

**Sinyal operasional.** Event `person.unidentified_present` untuk track yang hidup
melewati ambang tanpa identitas. Itu bukan noise — dan setelah §4 ia jadi masukan
langsung: kalau engine melaporkan lima orang terdeteksi dan empat teridentifikasi
sementara backend mengira si A sedang istirahat, kemungkinan besar yang kelima itu si A
sedang membelakangi kamera.

**Jalur koreksi manual yang bisa diaudit.** Koreksi harus jadi **event baru yang
ditambahkan, bukan menimpa catatan lama**: siapa yang mengoreksi, kapan, alasannya. Log
yang bisa diedit diam-diam tidak layak dipakai sebagai dasar penggajian atau sanksi.

**Bukti visual di batas interval** (§4.5), supaya sanggahan bisa diperiksa dan bukan
sekadar adu klaim.

### 11.2 Simpan observasi mentah, bukan hanya kesimpulan

Kalau backend menyimpan aliran interval dari engine dan bukan hanya sesi yang sudah jadi,
kamu bisa **memutar ulang seluruh riwayat** saat logika diperbaiki. Bug §9 butir 1
berarti semua data yang sudah terkumpul salah — dengan observasi mentah itu bisa dihitung
ulang; tanpa itu, data lamamu hilang begitu saja. Untuk sistem yang menjatuhkan sanksi,
kemampuan menghitung ulang bukan kemewahan.

---

## 12. Optimisasi

Semua di bawah ini menunggu `bench.py`.

**Turunkan FPS — tuas terbesar yang belum dipakai.** `target_fps: 30.0` adalah
pemborosan tiga kali lipat. Pada 10 fps, orang berjalan 1,4 m/s masih tersampel tiap
14 cm dan ByteTrack tetap bekerja baik. Memangkas seluruh anggaran deteksi jadi
sepertiga, harganya satu angka di YAML — asal parameter temporal sudah dalam detik (§9).
*Perhatikan:* ID switch **dan umur track** tidak boleh memburuk; setelah §4.7 itu metrik
produk.

**Matcher jadi matriks.** Stack semua referensi jadi satu array `(M, 512)` plus array
index→`person_id`, lalu `sims = R @ q` dan `argmax`. Satu GEMV BLAS menggantikan ribuan
iterasi interpreter. Gabungkan dengan margin test yang butuh `second_best` — gratis
begitu hasilnya berbentuk vektor.

**Head-crop plus `detector_input_size` 640→320.** SCRFD sekarang menerima crop seluruh
badan yang di-letterbox ke 640×640 untuk mencari objek sebesar 40 piksel. Crop region
kepala (30–40% teratas dari person bbox) sebagai implementasi `PersonCropper` baru.
Ukuran input adalah suku kuadratik.
*Perhatikan:* recall wajah tidak boleh turun — ukur akurasi end-to-end.

**Quality gate antara face detect dan embed.** Ukuran face bbox, variance of Laplacian,
yaw kasar dari landmark. **Dengan kamera sudut ini naik prioritas** — ia yang membuang
punggung orang sebelum membayar biaya embed.

**Batching di tahap embed.** Tumpuk aligned face jadi `(N, 3, 112, 112)` dalam satu
`session.run`. **Verifikasi dulu** graf ONNX punya dynamic batch axis — buka dengan
`onnx.load` dan lihat shape input, jangan percaya dokumentasi. Kalau batch-nya statis di
1, rencana cross-camera batching mati dan model harus di-export ulang.

**Koordinat ternormalisasi.** Pindahkan `BoundingBox` ke [0,1] di seluruh contract
**sebelum** view kedua ditambahkan. Ini juga menyederhanakan overlay di browser dan
definisi `door_region` yang tidak bergantung resolusi.

**Dual-stream decode.** Deteksi dan tracking di substream resolusi rendah, crop wajah
dari mainstream. `FrameSource` mendeklarasikan dua view; adapter dengan substream
memenuhi keduanya praktis gratis.

*Catatan:* `imgsz=640` di Ultralytics **sudah** melakukan letterbox resize dan memetakan
koordinat kembali. Men-downscale sendiri ke 640 tidak menghemat apa pun. Penghematan
datang dari turun **di bawah** ukuran yang dipakai model, atau dari menghindari decode
resolusi penuh sama sekali.

**Worker pool recognition.** Terakhir, dan hanya kalau bench menuntut (§5.2).

---

## 13. Benchmark harness

`bench.py` adalah langkah pertama. Terlalu banyak keputusan menunggu angka.

Putar video tetap lewat N pipeline simulasi dan laporkan:

- FPS agregat dan per kamera
- Latency p95 per tahap (ingest, detect, track, recognize, emit)
- Utilisasi GPU dan memori
- **Jumlah ID switch**
- **Umur track sebelum putus padahal orangnya masih di ruangan** — metrik produk (§4.7)
- **Berapa sering wajah yang layak dikenali muncul, per orang per jam** (§3.1)
- Kedalaman antrian dan laju drop, kalau worker pool sudah ada
- Akurasi pengenalan end-to-end terhadap set berlabel kecil

Dua metrik yang di-bold adalah yang menentukan apakah monitoring istirahat layak
dibangun sama sekali. Kalau umur track rata-rata dua menit, tidak ada logika backend yang
bisa menyelamatkannya, dan lebih baik tahu sekarang.

Poin metodologis yang paling sering dilanggar: **jangan bandingkan detector wajah pakai
metrik deteksi.** Tugas detector di pipeline ini bukan menemukan wajah — tugasnya
menyerahkan crop 112×112 yang ter-align rapi ke embedder. Kualitas 5 landmark menentukan
kualitas warp affine, dan warp yang sedikit meleset merusak embedding lebih parah
daripada satu wajah yang terlewat.

### Rekaman representatif tanpa pengadaan

Asumsi di §3 dan §4.7 belum teruji, dan itu bukan soal tuning — itu menentukan bentuk
arsitekturnya dan kelayakan satu fitur utuh.

Tidak perlu kamera asli dan tidak perlu pengadaan: **taruh ponsel di sudut ruangan, di
ketinggian rencana kamera, rekam tiga puluh menit jam kerja normal.** Satu sore, nol
rupiah, dan ia menjawab dua pertanyaan sekaligus.

---

## 14. Urutan pekerjaan

| # | Tahap | Selesai kalau |
| --- | --- | --- |
| 1 | `bench.py` + rekaman representatif (§13) | Melaporkan FPS, ID switch, umur track, frekuensi wajah layak |
| 2 | Bug kebenaran §9 butir 1–5, 7, 9, 10 | Satu match tunggal tidak lagi membuka sesi; margin test aktif |
| 3 | Protokol §6 + pemisahan proses | Backend tidak meng-import apa pun dari `engine/`; tes aturan import hijau |
| 4 | `AttendanceTracker` + `_is_break_time` pindah ke backend | Tidak ada konstanta kebijakan tersisa di `engine/` (§16) |
| 5 | `presence.interval` + `exit_zone` + `track_started_pts` | Backend bisa membedakan celah nyata dari celah palsu |
| 6 | Outbox + sequence + replay | Restart backend tidak kehilangan satu event pun |
| 7 | Ganti tracker ke ByteTrack MIT, sendirian | Ultralytics tidak lagi di-import tracker; umur track tidak memburuk |
| 8 | Parameter temporal jadi detik + turun ke 10 fps | FPS naik ~3× tanpa kenaikan ID switch |
| 9 | Matcher matriks + head-crop + input 320 + quality gate | Latency p95 recognition turun; akurasi tidak turun |
| 10 | Prioritas `door_region` + state `HELD` + `track.resumed` | Identitas tertangkap saat masuk dan bertahan saat membelakangi kamera |
| 11 | Crop bukti di batas interval (§4.5) | Sanggahan karyawan bisa diperiksa visual |
| 12 | Enrollment diperketat (§10) | Referensi duplikat dan tabrakan antar karyawan ditolak dengan pesan jelas |
| 13 | Ingest pindah ke PyAV (§5.5) + offset PTS→wallclock | PTS tersedia di event; offset ditetapkan ulang tiap reconnect |
| 13b | NVDEC, kalau profil menunjukkan decode jadi hambatan | CPU decode turun drastis |
| 14 | Normalized bbox + dual-view `FrameSource` | Adapter lama tetap lulus tes tanpa perubahan perilaku |
| 15 | Ganti detector ke D-FINE resmi, retune threshold tracker | mAP person dan ID switch setara atau lebih baik |
| 16 | Topologi kamera + fusi lintas kamera + peta cakupan | Handoff tersambung; titik buta ketahuan sebelum produksi |
| 17 | Worker pool recognition — hanya kalau bench menuntut | FPS tidak lagi turun linear terhadap jumlah orang |

---

## 15. Keputusan yang masih terbuka

| Topik | Pertanyaan | Kenapa penting sekarang |
| --- | --- | --- |
| Masker | Umum atau jarang di lingkungan ini? | Kalau umum, mengubah pilihan model dan harus masuk anggaran sekarang (§3.3) |
| Anti-spoofing | Terima risikonya, atau tambah liveness check? | Terhubung penggajian; serangannya jelas. Yang tidak boleh adalah tidak memilih |
| Jendela penyambungan N (§4.3) | Berapa detik jeda masih dianggap kehadiran yang sama? | Konstanta perseptual, tapi menentukan berapa banyak celah palsu lolos ke backend |
| Crop bukti | Simpan atau tidak? | Trade-off privasi vs kemampuan membantah sanksi (§4.5, §7.4) |
| Retensi data biometrik | Berapa lama, siapa yang boleh akses? | Perlu verifikasi hukum; desainnya sebaiknya ada sejak awal |
| Penempatan kamera final | Masih bisa menambah satu kamera per ruangan? | Kamera kedua di ruangan memangkas celah palsu jauh lebih efektif daripada optimisasi mana pun (§5.4) |
| Codec kamera | Sudah dipastikan H.264, bukan H.265? | Kalau H.265, dashboard butuh transcode dan seluruh anggaran CPU berubah (§6.7.2) |
| Batas koneksi RTSP | Berapa klien bersamaan yang didukung tiap kamera? | Menentukan apakah dual-stream untuk engine masih muat (§6.7.2) |
| Akurasi `PROGRAM-DATE-TIME` | Seberapa meleset terhadap waktu event engine? | **Uji minggu pertama.** Satu-satunya hal yang bisa memaksa kembali ke relay buatan sendiri (§6.7.1) |

---

## 16. Aturan yang mengikat

**Satu variabel per langkah.** Jangan pernah mengganti detector dan tracker bersamaan.

**Tiap langkah diukur dengan `bench.py` yang sama**, supaya perbandingannya berarti.

**Kebenaran sebelum kecepatan.** Sistem yang lambat itu kelihatan; sistem yang mencatat
data orang yang salah dengan percaya diri itu tidak.

**Engine mengamati, backend memutuskan.** Cara mengeceknya konkret: **grep konstanta
kebijakan di `engine/`.** Kalau ada angka 30, ada string "istirahat", ada jam 12–13, ada
kata "penalty" — garisnya sudah bocor. Engine cuma boleh punya konstanta perseptual:
berapa detik sebelum track dianggap hilang, berapa bukti sebelum identitas dikonfirmasi,
ambang similarity. Semuanya tentang penglihatan, tidak satu pun tentang peraturan kantor.

**Engine melapor, tidak menindak.** Tidak ada ambang, peringatan, atau notifikasi yang
lahir di engine.

**Field tak dikenal diabaikan; protokol hanya bertambah.** Dua sisi tidak lagi bisa
di-deploy bersamaan.

---

## 17. FAQ

Istilah dan keputusan yang paling sering ditanyakan. Jawaban singkat di sini,
detailnya di bagian yang ditunjuk.

**Apa itu PTS?**
Presentation Timestamp — angka yang menempel di tiap frame, artinya "frame ini
ditampilkan pada saat ini". Bukan jam dinding; satuannya `time_base` milik stream,
untuk RTSP biasanya 1/90000 detik. Ia ada karena frame tidak datang dalam jarak rapi
dan, pada H.264 dengan B-frame, urutan decode berbeda dari urutan tampil. Lihat §6.6.

**Kenapa pakai PTS, bukan jam atau hitungan frame?**
Karena PTS adalah **identitas frame yang sama di dua tempat sekaligus**. Engine dan
backend menarik stream yang sama, jadi untuk frame yang sama keduanya membaca angka
yang identik — angkanya datang dari sumber, tidak perlu disepakati. Menghitung frame
melenceng begitu ada frame yang hilang; jam saat penerimaan memasukkan jitter jaringan
dan berbeda di tiap penerima. Ibarat nomor halaman yang tercetak di buku: dua orang
dengan eksemplar berbeda tetap paham maksud "halaman 214".

**Kalau PTS bukan jam dinding, bagaimana laporan bisa berbunyi "10:15"?**
PTS relatif terhadap offset acak saat stream dibuka. Tetapkan pemetaan PTS→wallclock
sekali saat koneksi terbentuk, hitung semua interval dalam PTS, konversi ke waktu
absolut hanya saat event dipancarkan. **Offset wajib ditetapkan ulang tiap reconnect.**
§6.6.

**Apa bedanya remux dan transcode?**
Remux membungkus ulang byte video yang sudah jadi ke container lain — tidak ada decode,
tidak ada encode, CPU nyaris nol, kualitas identik. Transcode membongkar gambarnya dan
menyandikan ulang — mahal. Backend hanya boleh remux. §6.7.1.

**Kenapa frontend tidak menarik langsung dari kamera?**
Dua alasan. Browser tidak bisa memutar RTSP sama sekali, dan kalau bisa pun, setiap
orang yang membuka dashboard akan punya kredensial CCTV kantor. §6.7.

**Apa itu embedding, dan kenapa backend tidak menyimpannya?**
Vektor 512 angka hasil model wajah; kemiripan dua wajah diukur dari sudut antar vektor.
Backend tidak bisa melakukan apa pun dengannya — tidak bisa mencocokkan, menampilkan,
atau memvalidasi. Jadi vektor tinggal di engine, catatan orangnya di backend, disambung
satu ID buram. §7.1.

**Kenapa tidak pakai vector database?**
200 karyawan × 5 referensi × 512 float32 ≈ 2 MB. Brute-force di numpy selesai dalam
mikrodetik; FAISS atau pgvector di skala ini justru lebih lambat karena overhead, plus
satu layanan lagi yang harus dioperasikan. Ambangnya ada di ratusan ribu vektor. §7.2.

**Apa bedanya track dan identitas?**
Track adalah "ada satu orang yang sama bergerak di frame-frame ini" — murni geometri,
tanpa nama. Identitas adalah "orang itu person_id 4471". Track bisa hidup tanpa
identitas (orang membelakangi kamera), dan identitas bisa dipegang tanpa wajah terlihat
lewat state `HELD`. §5.3.

**Kenapa threshold similarity saja tidak cukup?**
Karena threshold hanya bertanya "cukup mirip?", bukan "mirip siapa lagi?". Orang asing
yang mirip dua karyawan akan lolos threshold dan diberikan ke salah satunya dengan
percaya diri. Margin test menambah syarat kedua: jarak ke kandidat terbaik harus cukup
jauh dari kandidat kedua. §5.3.

**Kenapa engine tidak boleh tahu jatah 30 menit?**
Karena begitu angka itu ada di engine, ia ada di dua tempat, dan suatu hari kebijakan
berubah jadi 45 menit sementara engine masih memakai yang lama. Engine hanya boleh
punya konstanta perseptual. Cara mengeceknya: grep `engine/` untuk angka kebijakan.
§2.1, §16.

**Apa bedanya "departed" perseptual dan kebijakan?**
Perseptual: track mati, tidak ada kamera yang melihat orang itu lagi — milik engine.
Kebijakan: sesi kerjanya dianggap selesai — milik backend. Engine bilang "aku berhenti
melihat dia"; backend memutuskan itu berarti pulang atau ke toilet. §2.1.

**Kenapa engine boleh kehilangan cache tapi tidak boleh kehilangan event?**
Cache cuma optimisasi — hilang saat restart, dibangun ulang dalam detik, tidak ada
informasi yang lenyap. Event adalah satu-satunya jejak bahwa seseorang pernah terlihat;
kalau hilang, tidak ada yang bisa merekonstruksinya. Itu sebabnya ada outbox dengan
sequence dan replay. §6.5.

**Kenapa NDJSON, bukan gRPC atau REST?**
Tujuannya menurunkan biaya mengganti bahasa backend. NDJSON bisa dibaca sepuluh baris
di bahasa apa pun, tanpa codegen, dan bisa di-debug dengan `nc`. Volumenya ~150
pesan/detik — performa bukan masalah di sini, ketahanan yang jadi masalah. §6.2.

**Apa itu NVDEC, dan kenapa bukan sekadar "pakai GPU"?**
NVDEC adalah unit decoder video khusus di GPU NVIDIA, terpisah dari unit yang
menjalankan model. Ia membebaskan CPU dari decode lima stream 1080p (3–5 core). Hadiah
sebenarnya bukan itu, tapi frame yang bisa tetap tinggal di VRAM tanpa bolak-balik
PCIe — dan itu refactor yang ditunda sampai profil membuktikannya perlu. §5.5.

**Kenapa FP16 tidak selalu lebih cepat?**
Di GTX 1060 (Pascal), FP16 berjalan di 1/64 kecepatan FP32 — dilumpuhkan sengaja di
kartu consumer. `half=True` di situ justru **menurunkan** performa. Di RTX 4060 (Ada,
punya tensor core) barulah FP16 jadi default yang benar. §8.

**Kenapa AGPL jadi masalah padahal kita tidak menjual software-nya?**
AGPL-3.0 punya klausul copyleft jaringan: menyediakan software lewat jaringan dihitung
sebagai distribusi, dan backend FastAPI mengekspos sistem ini lewat jaringan. Ultralytics
memakai lisensi itu untuk detector dan tracker. §8.

**Kenapa enrollment tidak boleh dari pas foto?**
Domain gap. Pas foto studio dan kamera sudut ruangan berbeda pose, jarak, pencahayaan,
dan karakteristik lensa — dan tidak ada threshold yang bisa menutup selisih itu.
Referensi harus datang dari kamera yang akan dipakai, di posisi yang akan dipakai. §10.

**Kenapa lima foto referensi belum tentu lima referensi?**
Kalau kelimanya dari sesi yang sama dengan pose identik, informasinya satu, cuma disalin
lima kali. Karena itu ada uji keberagaman: referensi yang terlalu mirip satu sama lain
ditolak sebagai duplikat. §10.

**Kenapa `crop()` harus `.copy()`?**
`image[y1:y2, x1:x2]` di numpy adalah *view* ke buffer frame, bukan salinan. Aman selama
sinkron. Begitu crop masuk antrian, capture thread menimpa buffer itu sebelum worker
memprosesnya — dan yang di-embed adalah potongan frame yang sama sekali berbeda, tanpa
error apa pun. §5.2, §9 butir 10.

---

## Sumber

- [fal/AuraFace-v1](https://huggingface.co/fal/AuraFace-v1) — Apache-2.0, `glintr100.onnx` dan `scrfd_10g_bnkps.onnx`
- [D-FINE](https://github.com/Peterande/D-FINE) — implementasi resmi D-FINE, Apache-2.0
- [LibreFaceRec](https://www.libreyolo.com/docs/models/librefacerec) — AuraFace + YuNet
- [FoundationVision/ByteTrack](https://github.com/FoundationVision/ByteTrack) — MIT, sumber untuk di-vendor
- [mikel-brostrom/boxmot](https://github.com/mikel-brostrom/boxmot) — AGPL-3.0, **hindari**
- [ByteTrack, arXiv:2110.06864](https://arxiv.org/abs/2110.06864)
