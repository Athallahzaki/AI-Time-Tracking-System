# `fake_engine`

Memancarkan protokol engine↔backend dari skenario tertulis. Tanpa kamera, tanpa
GPU, tanpa model, tanpa torch. Satu-satunya dependensi di luar pustaka standar
adalah `pyyaml`.

Ini alat pembuka blokir utama: begitu ada, backend dan frontend jalan penuh
kecepatan tanpa menunggu engine sungguhan. Dan ia memberi sesuatu yang engine
sungguhan **tidak bisa** — skenario patologis sesuai permintaan. Kamera mati di
tengah sesi, identitas tertukar, backend reconnect minta replay. Di hardware
asli kalian menunggu kebetulan; di sini tinggal menulis berkas.

## Pakai

```bash
# lihat apa saja yang ada
python -m engine.tools.fake_engine --list

# layani backend lewat unix socket, 60x lebih cepat dari waktu nyata
python -m engine.tools.fake_engine --scenario berbalik-lama --socket /tmp/engine.sock --speed 60

# lewat TCP, kalau backend beda mesin
python -m engine.tools.fake_engine --scenario kamera-mati --tcp 0.0.0.0:9701

# lihat alirannya begitu saja
python -m engine.tools.fake_engine --scenario stitching --stdout | head -20

# rekam ulang seluruh fixture (lihat "drift" di bawah)
python -m engine.tools.fake_engine --all --record contracts/fixtures

# buang 30% kanal view, untuk menguji bahwa overlay boleh bolong
python -m engine.tools.fake_engine --scenario happy-path --socket /tmp/e.sock --chaos drop_view=0.3
```

Klien contoh ada di `example_client.py` — enam puluh baris tanpa library, dan
ia menunjukkan seluruh jabat tangan. Backend boleh menyalinnya apa adanya
sebagai titik awal `engine_link/`.

```bash
python -m engine.tools.fake_engine.example_client /tmp/engine.sock
python -m engine.tools.fake_engine.example_client /tmp/engine.sock --last-seq 12   # minta replay
```

## Apa yang ditulis tangan, apa yang diturunkan

Penulis skenario menuliskan **kejadian penting** saja: track lahir, dikenali,
berakhir; kamera hidup, putus. Yang diturunkan otomatis: `presence.interval`,
`track.heartbeat`, `snapshot`, `engine.health`, `view.frame`, seluruh timestamp
jam dinding, penomoran `seq`, dan `stream_epoch`.

Pembagian itu ditegakkan — menulis `presence.interval` di timeline adalah error
saat memuat, bukan peringatan. Alasannya: skenario yang mengisi intervalnya
sendiri akan mengisinya dengan apa yang penulisnya *kira* engine hitung, dan
berhenti menguji apa pun. Dengan diturunkan, aturan penurunannya ada di satu
tempat dan sama untuk keempat belas skenario.

Loader juga menolak track yang ditutup sebelum dibuka, orang yang tidak ada di
`persons`, dan kamera yang tidak dideklarasikan. Skenario yang salah harus
gagal saat dimuat, bukan menghasilkan aliran aneh yang di-debug tiga hari.

## Tiga hal yang dimodelkan sungguhan

**Outbox, seq, replay.** Event bernomor urut disimpan; `hello` membawa
`last_event_seq` dan engine mengulang dari nomor berikutnya. Kalau outbox sudah
dipangkas melewati titik itu, `replay_gap` dikirim lebih dulu. Skenario
`replay-gap` memangkasnya dengan sengaja, jadi backend yang memperlakukan
lubang sebagai "tidak ada kejadian" ketahuan di sini, bukan di produksi.

**Skenario jalan terus, tidak peduli backend ada.** Posisi pemutaran
dipertahankan lintas koneksi. Engine sungguhan tidak mengulang harinya dari
pagi setiap kali backend di-deploy ulang, dan kalau di sini ia mengulang,
`reconnect-replay` menguji sesuatu yang tidak akan pernah terjadi.

**`stream_epoch`.** Setiap `camera.online` menaikkannya, `pts` kembali ke nol,
dan `pts_wallclock_offset` yang baru dihitung supaya jam dinding tetap kontinu.
Skenario `kamera-reconnect` ada khusus untuk ini: setelah reconnect, `pts`
interval kedua LEBIH KECIL dari `pts` interval pertama sementara `at`-nya lebih
besar. Backend yang membandingkan `pts` lintas epoch akan menyimpulkan waktu
berjalan mundur.

## Keempat belas skenario

Ini sekaligus daftar uji integrasi (`ENGINE_PROTOCOL.md` §6.3). Tanpa semuanya
hijau, jangan anggap backend selesai.

| Berkas | Yang diuji |
|---|---|
| `01-happy-path` | Jalur normal. Juga satu-satunya yang merekam kanal `view` |
| `02-berbalik-lama` | Celah palsu: kedua batasnya di `interior` |
| `03-istirahat-asli` | Celah nyata: kedua batasnya di `door`. Bandingkan dengan 02 |
| `04-kamera-mati` | Tiga track berakhir serentak, semuanya `camera_lost` |
| `05-identitas-tertukar` | Satu track, dua interval, id-nya wajib berbeda |
| `06-reconnect-replay` | Backend putus, menyambung, tidak ada event hilang |
| `07-replay-gap` | Outbox sudah dipangkas: lubang data, bukan ketidakhadiran |
| `08-orang-tak-dikenal` | Hadir tanpa identitas: nol interval, tapi orangnya ada |
| `09-dua-orang-mirip` | Margin tipis: tidak ada yang boleh diklaim |
| `10-enrollment-ditolak` | Tabrakan, duplikat, kualitas buruk (kanal control) |
| `11-roster-berubah` | Rekonsiliasi deklaratif (kanal control) |
| `12-stitching` | Teroklusi 3 detik: `prev_interval_id`, bukan celah |
| `13-kamera-reconnect` | `stream_epoch` naik, `pts` mundur, `at` maju |
| `14-lintas-ruangan` | Handoff: engine TIDAK menyambung, itu milik backend |

Dua skenario kanal control (10 dan 11) hanya berarti terhadap socket. Balasan
`enroll` deterministik dari isi permintaannya: id gambar yang memuat `blurry`,
`too_small`, `extreme_pose`, `bad_lighting`, `no_face`, `multiple_faces` atau
`dup` ditolak dengan alasan itu, dan `person_id` berakhiran `9` dianggap
bertabrakan. Jadi frontend bisa membangun seluruh tampilan penolakan tanpa satu
pun model.

## Drift fixture

`contracts/fixtures/*.ndjson` **di-commit**, dan CI memeriksanya dengan merekam
ulang lalu menjalankan `git diff --exit-code`. Tes yang membandingkan dengan
keluaran yang dihasilkan saat itu juga tidak menguji apa-apa.

Kalau CI merah di langkah itu, pertanyaannya bukan "bagaimana cara
menghijaukannya" tapi **"aku memang bermaksud mengubah arti fixture untuk tiga
jalur sekaligus?"** Kalau ya: rekam ulang, dan tulis di commit apa yang berubah
artinya untuk backend.

Satu perubahan besar sudah dijadwalkan: saat engine sungguhan memancarkan
protokol ini (A6), fixture-nya direkam ulang **sekali**, dari engine asli.
Nilai `.expected.json` tidak boleh ikut berubah dalam rekaman ulang itu — kalau
berubah, engine asli dan engine palsu tidak sepakat, dan itu bug, bukan
penyesuaian.

## Yang TIDAK ada di sini, dan tidak akan pernah

Tidak ada jatah tiga puluh menit, tidak ada jam istirahat resmi, tidak ada
ambang toleransi. `<nama>.expected.json` melaporkan bahwa ada celah 195 detik
yang batasnya di `interior` dan tidak disambung engine; apakah itu dihitung
sebagai ketidakhadiran diputuskan backend.

`contracts/tools/policy_grep.py` memindai folder ini dan akan benar kalau suatu
hari ia berubah merah. Satu-satunya pengecualian adalah `scenarios/`, yang
data uji dan bukan kode yang dijalankan engine — carve-out itu sempit dengan
sengaja, dan `emitter.py` maupun `server.py` tetap dipindai.
