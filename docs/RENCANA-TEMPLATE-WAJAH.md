# Rencana: template wajah dari CCTV (paket ea-r31 + be-r14 + fe-r9)

Status: **disetujui arahnya oleh Zena 12 Nov 2026**, dibangun di belakang saklar (default mati).
Kontrak `template.*` adalah perubahan kontrak: **perlu persetujuan EA** sebelum dinyalakan di pilot.

## 1. Masalah

Referensi enrollment adalah pas foto frontal dan jelas. Wajah dari CCTV pilot kecil, miring, dari atas,
pada jarak 4–10 m. Jarak keduanya di ruang embedding membuat wajah sering gagal lolos ambang, padahal setiap
wajah yang terkonfirmasi menyelesaikan seluruh kelompok ANON-nya secara mundur. Model tidak dilatih ulang.
Yang bertambah adalah **referensi**: embedding wajah dari kamera lokasi untuk orang yang sudah terkonfirmasi.
Matcher mengambil skor maksimum per orang, jadi template baru hanya bisa menaikkan skor orang itu.

Sisi gelapnya sama: **satu template salah sudah cukup untuk membajak**. Template Andi yang masuk atas nama
Budi membuat Andi tercatat sebagai Budi dengan skor tinggi dan margin meyakinkan. Seluruh rancangan di bawah
ditujukan untuk mencegah itu.

## 2. Keputusan

1. **Engine mengusulkan, backend memutuskan.** Engine tidak pernah menambah referensi tanpa perintah backend.
   Backend menyimpan kandidat, menimbang, menampilkan ke admin, dan menerapkan pada jadwal.
2. **Jangkar tidak pernah disentuh otomatis.** Referensi enrollment (`source = enroll`) tetap utuh. Template
   hasil belajar disimpan dengan `source = learned` dan hanya itu yang bisa dicabut otomatis.
3. **Template tidak belajar dari template.** Skor kandidat terhadap orangnya dihitung terhadap jangkar
   enrollment saja.
4. **Tidak diterapkan seketika.** Kandidat hari ini dipakai matcher setelah jadwal penerapan. Jeda itu adalah
   jendela tinjau (menggantikan rencana rollback 1–2 jam).
5. **Admin bukan satu-satunya penjaga.** Mode bawaan `otomatis`: yang lolos penimbang diterapkan kecuali
   dibuang admin; yang meragukan masuk antrean tinjau dan tidak diterapkan tanpa persetujuan. Mode `persetujuan`
   tersedia sebagai pilihan.
6. **Yang ditolak tidak disimpan gambarnya.** Alasan dan angka tetap ada.

## 3. Alur

```text
engine: bukti wajah dari track CONFIRMED
  -> gerbang tangkap (jangkar, margin, ukuran, skor, sudut, duplikat, jeda per orang)
  -> buffer kandidat di memori (maks. 200, yang tertua dibuang)
backend: tiap 60 dtk  template.pull  -> template.candidates  -> tabel face_template_candidates (pending)
  -> penimbang: duplikat antar kandidat, margin, pencilan, batas per orang per hari
  -> queued | review | rejected
admin: lihat gambar + angka, buang / setujui
jadwal (mis. 02:00): template.apply (queued [+ approved]) -> engine cek ulang -> referensi source=learned
  -> applied (reference_id) | failed (alasan)
  kedaluwarsa / dibuang admin setelah diterapkan: template.remove -> removed
```

## 4. Gerbang tangkap di engine (`face_templates`, config engine)

Dijalankan di thread kamera setelah arbiter menilai bukti, hanya untuk track `CONFIRMED` dari wajah.

| Syarat | Bawaan | Alasan |
|---|---|---|
| jeda per orang | 60 dtk | puluhan bukti per menit dari momen yang sama hanyalah satu bukti |
| ukuran wajah | ≥ 48 px | di bawahnya alignment 112×112 meng-upscale |
| skor detektor | ≥ 0,60 | |
| sudut (`yaw_ratio`) | ≤ 0,50 | sudut ekstrem memberi embedding yang tidak stabil |
| skor ke **jangkar** orang itu | ≥ ambang matcher | template harus cocok dengan pas foto sendiri |
| margin ke orang lain (seluruh roster) | ≥ 0,10 | kandidat yang dekat dengan orang lain berbahaya |
| mirip referensi orang itu sendiri | ≤ 0,90 | di atasnya mubazir: tidak menambah sudut baru |

Kandidat membawa: crop wajah diperluas 2× (JPEG, supaya bisa di-embed ulang saat model diganti), embedding,
`embedding_version`, kamera, waktu, `track_uuid`, skor jangkar, kandidat kedua dan skornya, margin, ukuran,
skor detektor, sudut.

## 5. Penimbang di backend

Dijalankan tiap siklus tarik atas kandidat `pending`; pembanding adalah kandidat orang yang sama 24 jam
terakhir yang masih hidup (`pending`, `queued`, `review`, `approved`).

| Urutan | Pemeriksaan | Hasil |
|---|---|---|
| 1 | `embedding_version` beda dari versi engine sekarang | `rejected: versi_berbeda` |
| 2 | mirip > 0,90 dengan kandidat hidup / template terpasang orang itu | `rejected: duplikat` |
| 3 | pencilan: rerata kemiripan ke kandidat lain orang itu < median − 0,15 (bila ≥ 3 pembanding) | `rejected: pencilan` |
| 4 | sudah 5 kandidat `queued`/`approved` orang itu hari ini | `rejected: batas_harian` |
| 5 | margin < 0,15 | `review` |
| 6 | selain itu | `queued` |

Semua angka **belum dikalibrasi**; diubah di menu, bukan di kode. Total template terpasang per orang dibatasi
30; umur template 30 hari, lalu dicabut otomatis pada jadwal.

## 6. Kontrak `template.*` (terpisah dari kontrak produksi)

Skema: `contracts/schema/face_template.schema.json`. Seperti kontrak debug, pesan ini ditangani backend
sebelum validasi kontrak produksi; engine lama atau engine dengan saklar mati menjawab `ack` ditolak.

| Pesan | Arah | Isi |
|---|---|---|
| `template.pull` | backend → engine | `request_id`, `max_items` |
| `template.candidates` | engine → backend | `request_id`, `embedding_version`, `items[]` (lihat §4) |
| `template.apply` | backend → engine | `request_id`, `items[]`: `candidate_id`, `person_id`, `jpeg_b64`, `embedding_b64`, `embedding_version`, `camera_id`, `captured_at` |
| `template.applied` | engine → backend | `request_id`, `items[]`: `candidate_id`, `accepted`, `reason`, `reference_id` |
| `template.remove` | backend → engine | `request_id`, `reference_ids[]` |
| `template.removed` | engine → backend | `request_id`, `removed` |

Engine memeriksa ulang setiap `template.apply` terhadap roster saat itu (versi, jangkar, margin, duplikat):
roster bisa berubah antara tangkap dan jadwal. Engine hanya menghapus referensi `source = learned` lewat
`template.remove`; jangkar enrollment tidak bisa dihapus dengan pesan ini.

## 7. Data

- Engine `references.sqlite3`: kolom baru `refs.source` (`enroll` | `learned`, bawaan `enroll`).
- Backend: tabel `face_template_candidates` (status, alasan, angka, `jpeg`, `embedding`, `reference_id`,
  siapa memutuskan). Gambar dan embedding dikosongkan saat `rejected`, `discarded`, `removed`.
- Pengaturan di `app_settings['face_templates']`: aktif, mode, jam jadwal, angka penimbang. Setiap perubahan
  dan setiap keputusan admin masuk `settings_audit`.

## 8. Menu admin ("Template Wajah")

Pengaturan (aktif, mode, jam, angka), tombol "Timbang sekarang" dan "Terapkan sekarang", filter status dan
karyawan, kartu per kandidat: crop, nama, kamera, waktu, skor jangkar, kandidat kedua + skornya, margin, ukuran,
sudut, status/alasan; tombol Setujui / Buang (dan Cabut untuk yang sudah diterapkan).

## 9. Saklar (semua default mati)

| Saklar | Di mana | Menyalakan |
|---|---|---|
| `face_templates.enabled: true` | config engine (restart) | gerbang tangkap + penangan `template.*` |
| `FACE_TEMPLATES_ENABLED=1` | env backend | rute `/api/face-templates`, penarik dan penjadwal |
| "Aktif" di menu | `app_settings` | penarikan dan penerapan terjadwal |

## 10. Uji di 4060

1. Enroll satu orang dari pas foto. Nyalakan ketiga saklar, mode `persetujuan`.
2. Berjalan di depan kamera 10 menit dari beberapa sudut. Kandidat muncul di menu ≤ 1 menit setelah
   terkonfirmasi, tidak lebih sering dari satu per menit.
3. Minta orang kedua berdiri di dekatnya: kandidat dengan margin tipis masuk `review`, bukan `queued`.
4. Setujui, "Terapkan sekarang" → `applied`. Ukur "identifikasi: ... median" sebelum dan sesudah, pada
   rekaman yang sama.
5. Cabut satu template → engine log `template.remove`; skor kembali seperti sebelumnya.
6. Matikan saklar engine: backend menulis "engine tidak melayani template" dan tidak ada yang rusak.

## 11. Yang sengaja tidak dikerjakan

- Embedding tubuh (ReID) lintas hari: mengenali pakaian, bukan orang; ditolak (lihat diskusi 12 Nov).
- Fine-tuning model dari data lokasi: label dari model sendiri menguatkan kesalahannya sendiri.
- **Data biometrik:** tabel kandidat berisi foto wajah karyawan dari CCTV. Perlu kesepakatan tertulis dengan
  klien (siapa tahu, berapa lama, siapa menghapus) sebelum dinyalakan di pilot.
