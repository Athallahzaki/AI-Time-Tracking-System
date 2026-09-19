# contracts/

Kontrak antar-jalur. Tidak dimiliki satu jalur; pemilik skema ditunjuk (Engine A).
Acuan prosa ada di `docs/ENGINE_PROTOCOL.md`; **yang berlaku kalau keduanya
bertentangan adalah `schema/engine_protocol.schema.json`**, karena ia yang
dieksekusi mesin dan dokumen tidak.

```
contracts/
├── schema/engine_protocol.schema.json   # satu berkas, self-contained, tanpa $ref lintas berkas
├── validator/                           # validasi bentuk (skema) + aturan aliran (conformance)
├── tools/policy_grep.py                 # penegakan "engine mengamati, backend memutuskan" di CI
├── fixtures/                            # rekaman NDJSON per skenario, DIHASILKAN fake_engine
└── tests/                               # tes yang memastikan validatornya benar-benar menolak
```

## Fixture

`fixtures/` dihasilkan `engine/tools/fake_engine`, bukan ditulis tangan:

```bash
python -m engine.tools.fake_engine --all --record contracts/fixtures
```

Tiga berkas per skenario — `<nama>.events.ndjson`, `<nama>.expected.json`, dan
untuk `happy-path` juga `<nama>.view.ndjson`. Semuanya di-commit, dan CI
merekam ulang lalu `git diff --exit-code`: fixture yang dihasilkan ulang saat
tes berjalan tidak menguji apa pun.

`<nama>.expected.json` **observasional, bukan kesimpulan kebijakan**. Ia
melaporkan celah beserta bukti batasnya — `end_zone`, `end_reason`,
`end_source`, dan apakah engine sudah menyambungnya — dan berhenti di situ.
Tes backend memutar ulang `.ndjson`, menurunkan sesi menurut kebijakan kalian,
lalu membandingkan celah yang ditemukan dengan `gaps[]`. Kalau jumlah dan
batasnya berbeda, yang salah parser kalian; kalau perlakuannya yang berbeda,
itu kebijakan. Dua kegagalan yang sangat berbeda, dan selama ini tercampur.

## Pakai

```bash
pip install 'jsonschema>=4.18'

# validasi rekaman
python -m contracts.validator contracts/fixtures/berbalik-lama.events.ndjson --channel events

# engine palsu / engine asli, langsung dari pipa
fake_engine --scenario berbalik-lama.yaml | python -m contracts.validator - --channel events

# penegakan batas engine (diharapkan MERAH sampai AttendanceTracker pindah)
python contracts/tools/policy_grep.py engine/

# tes
pytest contracts/tests -q
```

Kode keluar 1 kalau ada pelanggaran, jadi ketiganya bisa langsung dipasang di CI
tanpa dibungkus apa pun.

## Dua lapis, dan lapis kedua yang penting

`validator/schema_validator.py` menjawab "apakah satu pesan berbentuk benar".
`validator/conformance.py` menjawab "apakah sebuah aliran masuk akal" — dan di
situlah bug yang menarik tinggal. JSON Schema tidak akan pernah bisa tahu bahwa
`track.ended` setelah `camera.failed` seharusnya berbunyi `camera_lost`, atau
bahwa `track_started_pts` yang dikarang membuat backend menghitung kehadiran
dari saat wajah terbaca alih-alih saat orangnya masuk.

Conformance bekerja atas rekaman NDJSON, jadi ia berlaku sama untuk
`fake_engine` dan engine sungguhan. Itu memang tujuannya: satu alat, dua
produsen, dan tidak ada ruang bagi engine asli menyimpang dari engine palsu
tanpa ketahuan di CI.

## Empat kontradiksi yang diputuskan di sini

Dokumen sebelumnya bertengkar sendiri di empat titik. Sebagai pemilik skema,
keputusannya diambil begini. **Tolak per butir kalau tidak setuju — sebelum M0,
bukan sesudah.**

**1. `prev_interval_id`, bukan `prev_interval_seq`.** `seq` adalah ordinal
transport yang maknanya bergeser saat replay. Menyambung objek domain dengan
pencacah pengiriman berarti graf kehadiran ikut rusak setiap kali mekanisme
pengirimannya berubah. Interval disambung dengan identitasnya sendiri.

**2. `*_pts` adalah detik relatif terhadap awal stream, bukan unix epoch.**
`ENGINE_PROTOCOL.md` §1 benar; contoh di `ARCHITECTURE.md` §4.2 yang memakai
`1726712531.20` salah. Skema memasang `minimum: 0` dan conformance memperingatkan
kalau ada pts tanpa offset yang mendahuluinya.

**3. `end_source` hanya `face` | `tracking` | `forced`.** Nilai `track_lost` yang
muncul di contoh kedua dokumen itu adalah `end_reason`, bukan `end_source`. Kalau
backend menulis tes dari contoh itu, ketidakcocokannya baru ketahuan di M3.

**4. `interval_id` dan `track_uuid` dua ruang nama terpisah, ditegakkan lewat
prefix.** `tr_` dan `iv_`. Di contoh lama nilainya identik, padahal satu track
bisa menghasilkan lebih dari satu interval begitu `track.identity_changed`
terjadi di tengah track — dan saat itu id-nya bentrok.

## Satu field baru yang tidak ada di dokumen mana pun: `stream_epoch`

`ARCHITECTURE.md` §6.6 mewajibkan offset PTS→wallclock ditetapkan ulang setiap
reconnect kamera, lalu tidak memberi backend cara apa pun untuk tahu **offset
mana yang berlaku untuk pesan mana**. Itu lubang, bukan detail: pesan yang
datang di sekitar reconnect akan dikonversi dengan offset yang salah, dan
gejalanya bukan error melainkan satu kamera melaporkan interval di tahun yang
salah — persis bug membingungkan yang dokumen itu sendiri khawatirkan.

`stream_epoch` naik satu setiap koneksi RTSP dibangun ulang, ikut di setiap pesan
yang membawa `pts`, dan `camera.online` membawa pasangan
(`stream_epoch`, `pts_wallclock_offset`). Aturannya jadi bisa dinyatakan dalam
satu kalimat: **pts hanya sebanding di dalam satu `(camera_id, stream_epoch)`.**
Conformance menegakkannya.

`snapshot.pts_wallclock_offset` ikut berubah bentuk: dari `{camera_id: offset}`
jadi `{camera_id: {stream_epoch, offset}}`. Tanpa itu, snapshot bisa membawa
offset epoch lama untuk track yang sudah hidup di epoch baru.

## Aturan evolusi

Field tak dikenal **diabaikan diam-diam**; tidak ada `additionalProperties:
false` di mana pun, dan itu disengaja. Penambahan field tidak menaikkan versi.
Perubahan yang memutus kompatibilitas menaikkan `protocol_version` mayor, dan
kedua versi didukung selama satu siklus rilis.

Pengecualian tunggal: `seq` di kanal `view` **ditolak**, bukan diabaikan.
Kehadirannya berarti seseorang memasukkan `view.frame` ke outbox, dan retensi
outbox akan habis oleh bbox per frame.

`reason` per gambar di `enroll_result` sengaja string bebas, bukan enum tertutup.
Alasan baru akan muncul saat enrollment diperketat, dan UI tidak boleh pecah
karenanya. Daftar yang dikenal sekarang: `too_small`, `blurry`, `extreme_pose`,
`bad_lighting`, `no_face`, `multiple_faces`, `duplicate_of:<id>`. UI menampilkan
yang tidak dikenal apa adanya.

## Catatan untuk yang mengimplementasikan margin test

`track.identified.margin` adalah `best - second_best` yang dihitung atas skor
**per orang**, bukan per vektor referensi. Kalau dihitung per referensi, kandidat
kedua hampir selalu referensi lain milik orang yang sama, margin-nya selalu
mendekati nol, dan seluruh roster akan ditolak. Reduksi dulu ke satu skor per
`person_id`, baru ambil selisihnya.

Ini bukan hipotesis: `engine/plugins/face_recognizer/matching/matcher.py` versi
sekarang mengambil `best` dengan mengiterasi setiap vektor referensi, jadi siapa
pun yang menambahkan margin test di atasnya akan menabrak ini di percobaan
pertama. Efek sampingnya yang lain juga nyata — karyawan dengan lima referensi
punya lima undian melawan karyawan dengan tiga.

## Kenapa satu berkas skema, bukan per kanal

Tujuan NDJSON adalah menurunkan biaya mengganti bahasa backend. `$ref` lintas
berkas menuntut resolver dan konfigurasi registry yang berbeda di tiap bahasa —
tepat biaya yang sedang dihindari. Satu berkas bisa dimuat siapa pun dengan satu
`open()`.

Keanggotaan kanal tetap ada, sebagai anotasi `x-channel` per definisi pesan.
Validator menurunkannya dari situ, bukan dari daftar kedua di Python; menambah
pesan di JSON otomatis membuatnya dikenal, dan tidak ada dua sumber kebenaran
yang bisa berselisih.

## Temuan saat menulis ini

`engine/configs/default_config.yaml` baris 35–36 menyetel `break_start_hour: 12`
dan `break_end_hour: 13` dengan komentar **"detection paused"**. Jadi masalahnya
lebih dari sekadar engine mengetahui kebijakan: engine **berhenti mengamati**
antara jam 12 dan 13. Backend tidak akan punya data apa pun di jam itu, dan
lubangnya tidak bisa direkonstruksi belakangan karena tidak pernah ada
observasinya. Untuk sistem yang mengukur ketidakhadiran, lubang harian yang
dibuat sendiri adalah hal terakhir yang kalian inginkan.
