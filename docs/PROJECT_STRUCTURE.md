# Struktur Proyek

**AI Time Tracking System** · v1 · 19 September 2026

Struktur folder untuk tim empat orang: 2 engine, 1 backend, 1 frontend. Acuan
arsitekturnya `ARCHITECTURE.md`, kontraknya `ENGINE_PROTOCOL.md`, pembagian kerjanya
`WORKPLAN.md`.

Dokumen ini hanya mendefinisikan **folder dan tujuannya**, bukan nama file di dalamnya.

---

## 1. Prinsip

**Satu folder, satu mekanisme, satu pemilik.** Folder dibagi berdasarkan *apa yang
dikerjakan*, bukan berdasarkan lapisan teknis. Dua orang yang mengerjakan hal berbeda
tidak boleh berakhir di file yang sama.

**Kontrak adalah warga kelas satu di root**, sejajar dengan `engine/`, `backend/`, dan
`frontend/` — bukan milik salah satunya. Ia disentuh tiga jalur sekaligus, jadi ia
punya pemilik yang ditunjuk dan bukan wilayah bebas.

**Zona bersama dibuat sekecil mungkin.** Di engine hanya ada dua folder yang disentuh
dua orang; sisanya terbagi bersih.

**Batas folder mencerminkan batas proses.** Kalau sesuatu tidak boleh diketahui engine
(aturan istirahat, jam kerja), tidak ada folder di `engine/` yang bisa menampungnya.

---

## 2. Diagram

### Root

```
.
├── engine/          Pengamatan: kamera → identitas → event
├── backend/         Kebijakan: event → sesi → keputusan → API
├── frontend/        Tampilan: dashboard, overlay, enrollment, koreksi
├── contracts/       Kontrak antar-jalur (milik bersama, pemilik ditunjuk)
├── deploy/          Compose, konfigurasi MediaMTX, berkas lingkungan
└── docs/            Dokumen arsitektur dan rencana kerja
```

### Engine

```
engine/
├── ports/           Antarmuka abstrak — jarang berubah, ubah = kesepakatan
├── ingest/          Sumber frame: RTSP, PyAV, PTS, reconnect, offset waktu
├── perception/      Apa yang terlihat: deteksi, tracking, crop, align, gerbang mutu
├── identity/        Siapa orangnya: bukti, pencocokan, state, enrollment
├── api/             Permukaan keluar: skema, event, socket, outbox
├── pipeline/        Orkestrasi: frame loop, antrian, worker pool  [bersama]
├── store/           Penyimpanan lokal: vektor embedding, log outbox
├── config/          Muatan konfigurasi dan validasinya
├── tools/           Alat pengembangan: engine palsu, harness benchmark
└── tests/           Uji unit dan uji kesesuaian kontrak
```

### Backend

```
backend/
├── api/             Permukaan HTTP/WS: router, skema request/response, auth
├── engine_link/     Klien protokol engine: NDJSON, reconnect, replay, urutan
├── services/        Pemrosesan: turunkan sesi, hitung jatah, koreksi manual
├── policy/          Aturan perusahaan sebagai konfigurasi, terpisah dari logika
├── domain/          Kosakata bersama: entitas, nilai, tipe
├── store/           Akses basis data: skema, migrasi, repositori
├── media/           Integrasi MediaMTX: konfigurasi path, hook otorisasi
├── config/          Pengaturan aplikasi dan lingkungan
└── tests/           Uji unit dan uji skenario terhadap fixture
```

### Frontend

```
frontend/
└── src/
    ├── views/       Halaman utuh yang dipetakan ke rute
    ├── features/    Fitur mandiri: pemantauan, istirahat, enrollment, koreksi
    ├── components/  Elemen UI yang dipakai lintas fitur
    ├── composables/ Logika reaktif yang dipakai ulang
    ├── services/    Klien API dan langganan aliran data
    ├── stores/      State aplikasi (Pinia)
    ├── router/      Definisi rute dan penjagaan akses
    └── assets/      Berkas statis dan gaya global
```

### Contracts

```
contracts/
├── schema/          Definisi pesan protokol yang bisa divalidasi mesin
├── fixtures/        Rekaman NDJSON per skenario + hasil yang diharapkan
└── openapi/         Spesifikasi API backend ↔ frontend
```

---

## 3. Versi paragraf

Bagian ini menjelaskan hal yang sama dalam prosa, supaya bisa dibaca tanpa menafsirkan
diagram. Isinya lengkap dan berdiri sendiri.

### Tingkat root

Repositori berisi enam folder tingkat atas. `engine/` adalah proses pengamatan yang
mengubah aliran kamera menjadi event identitas. `backend/` adalah proses kebijakan yang
mengubah event itu menjadi sesi kerja, perhitungan jatah istirahat, dan API. `frontend/`
adalah aplikasi Vue yang menampilkan hasilnya. `contracts/` berisi kontrak yang
disepakati antar-jalur dan sengaja diletakkan di root karena tidak dimiliki satu jalur
pun. `deploy/` berisi berkas orkestrasi dan konfigurasi MediaMTX. `docs/` berisi dokumen
arsitektur, protokol, rencana kerja, dan struktur ini.

### Engine

`ports/` berisi antarmuka abstrak yang menjadi sendi seluruh engine — sumber frame,
detektor, tracker, pendengar track. Isinya jarang berubah dan perubahan di sini
memengaruhi semua orang, jadi butuh kesepakatan lebih dulu.

`ingest/` menangani pengambilan frame dari kamera: koneksi RTSP, pembacaan lewat PyAV,
pengambilan PTS, penanganan putus-sambung, dan penetapan offset PTS ke jam dinding
beserta penetapan ulangnya setiap reconnect. Semua yang berhubungan dengan "bagaimana
frame sampai ke sini" tinggal di sini.

`perception/` berisi semua yang menjawab "apa yang terlihat" tanpa peduli siapa orangnya:
deteksi objek, tracking, pemotongan region orang dan kepala, penyelarasan wajah, dan
gerbang mutu yang membuang wajah kabur atau terlalu menyamping. Ini murni penglihatan,
tanpa konsep identitas.

`identity/` berisi semua yang menjawab "siapa orangnya": akumulasi bukti sepanjang umur
track, peleburan embedding, pencocokan matriks beserta uji margin, mesin state identitas
termasuk keadaan saat identitas dipegang tracker tanpa wajah terlihat, dan alur
enrollment dengan gerbang mutu referensi, uji keberagaman, serta uji tabrakan antar
karyawan.

`api/` adalah satu-satunya permukaan engine yang menghadap keluar: definisi skema pesan,
pembentukan event, server socket NDJSON, penomoran urutan, dan mekanisme outbox dengan
pemutaran ulang. Tidak ada modul lain yang boleh menulis langsung ke socket.

`pipeline/` berisi orkestrasi yang menyatukan semuanya: frame loop, antrian terbatas
beserta kebijakan prioritas dan pembuangan berdasarkan umur, worker pool pengenalan, dan
abstraksi jam. Ini zona bersama yang disentuh kedua orang engine, jadi sengaja dibuat
setipis mungkin.

`store/` berisi penyimpanan lokal milik engine: basis data vektor embedding beserta
gambar referensi dan tag versi model, ditambah log outbox. Tidak ada catatan kehadiran di
sini — itu milik backend.

`config/` memuat pembacaan dan validasi konfigurasi. `tools/` berisi alat pengembangan,
yaitu engine palsu beserta berkas skenarionya dan harness benchmark. `tests/` berisi uji
unit dan uji kesesuaian terhadap kontrak.

### Backend

`api/` adalah permukaan HTTP dan WebSocket: router FastAPI, skema request dan response,
serta autentikasi. Semua yang berbau komunikasi dengan dunia luar lewat sini.

`engine_link/` adalah klien protokol engine: pembacaan NDJSON, penyambungan ulang,
pengiriman konfigurasi kamera dan roster secara deklaratif, pelacakan nomor urut, dan
permintaan pemutaran ulang saat backend baru tersambung. Ia dipisah dari `api/` karena ia
klien, bukan server, dan siklus hidupnya berbeda.

`services/` berisi pemrosesan data: menurunkan sesi kerja dari interval kehadiran,
memutuskan celah mana yang dianggap kepergian nyata, menghitung pemakaian jatah
istirahat, dan menangani koreksi manual sebagai event tambahan. Ini inti produknya.

`policy/` memuat aturan perusahaan sebagai konfigurasi, bukan kode: panjang jatah, jam
istirahat resmi, ambang toleransi, perlakuan shift. Dipisah supaya perubahan aturan dari
HRD tidak menyentuh logika di `services/`, dan supaya pekerjaan bisa jalan dengan aturan
sementara sebelum kebijakan resminya selesai.

`domain/` berisi kosakata bersama yang dipakai lintas folder: entitas, tipe nilai, dan
enumerasi. `store/` berisi akses basis data: skema, migrasi, dan repositori. `media/`
berisi integrasi MediaMTX, yaitu pengelolaan path dan endpoint yang menjawab pertanyaan
otorisasi. `config/` memuat pengaturan aplikasi. `tests/` berisi uji unit dan uji skenario
yang memutar ulang fixture dari `contracts/`.

### Frontend

Seluruh kode aplikasi ada di `src/`. `views/` berisi halaman utuh yang dipetakan ke rute.
`features/` berisi fitur mandiri yang masing-masing menyatukan komponen, state, dan
logikanya sendiri — pemantauan langsung, pemantauan istirahat, enrollment, dan koreksi
manual. `components/` berisi elemen UI yang dipakai lintas fitur. `composables/` berisi
logika reaktif yang dipakai ulang. `services/` berisi klien API dan langganan aliran data
dari backend. `stores/` berisi state aplikasi. `router/` berisi definisi rute dan
penjagaan akses. `assets/` berisi berkas statis dan gaya global.

### Contracts

`schema/` berisi definisi pesan protokol dalam bentuk yang bisa divalidasi mesin, supaya
engine dan backend tidak menafsirkan tabel dokumen secara berbeda. `fixtures/` berisi
rekaman NDJSON untuk tiap skenario beserta hasil yang seharusnya diturunkan backend —
inilah jaring pengaman untuk logika kebijakan. `openapi/` berisi spesifikasi API backend
ke frontend.

---

## 4. Kepemilikan

| Folder | Pemilik | Catatan |
| --- | --- | --- |
| `engine/api`, `engine/identity`, `engine/store` | **Engine A** | Kontrak dan lapisan identitas |
| `engine/tools` (engine palsu) | **Engine A** | Ditulis orang engine, bukan backend |
| `engine/ingest`, `engine/perception` | **Engine B** | Pipeline dan performa |
| `engine/tools` (benchmark) | **Engine B** | |
| `engine/ports`, `engine/pipeline` | **Bersama** | Zona konflik — beri tahu sebelum mengubah |
| `backend/**` | **Backend** | Frontend membantu di `api/` sejak awal |
| `frontend/**` | **Frontend** | |
| `contracts/**` | **Pemilik skema** | Satu orang ditunjuk; perubahan diumumkan ke tiga jalur |
| `deploy/`, `docs/` | **Bersama** | |

---

## 5. Aturan

**Zona bersama diberi tahu, bukan direbut.** Perubahan di `engine/ports` atau
`engine/pipeline` diumumkan ke orang engine satunya sebelum dikerjakan, karena keduanya
menyentuh pekerjaan berjalan.

**`contracts/` tidak diubah sepihak.** Setelah milestone integrasi pertama, perubahan
skema lewat pemilik skema dan diumumkan ke tiga jalur.

**Tidak ada aturan perusahaan di `engine/`.** Tidak ada folder di engine yang boleh
menampung panjang jatah istirahat, jam kerja, atau ambang sanksi. Pemeriksaannya:
pemindaian konstanta kebijakan di `engine/` sebagai bagian dari CI.

**Tidak ada import silang antar proses.** `backend/` tidak meng-import apa pun dari
`engine/`, dan sebaliknya. Satu-satunya hal yang dibagi adalah `contracts/`. Ditegakkan
dengan uji yang memindai import.

**Folder baru butuh alasan yang bisa dikalimatkan.** Kalau tujuan sebuah folder tidak
bisa dijelaskan dalam satu kalimat tanpa kata "dan", ia sebenarnya dua folder — atau
bukan folder sama sekali.
