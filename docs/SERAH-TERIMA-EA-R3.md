# Serah terima EA — paket ea-r3 s.d. ea-r6: ReID, `schedule_off`, engine sebagai tugas Windows

9 Oktober 2026 · Jalur EA · Rincian: `docs/CHANGELOG.md` (ea-r3 s.d. ea-r6). File ini **tidak** menggantikan
`docs/SERAH-TERIMA.md` (status EB, paket eb-r10); keduanya berlaku.

## Selesai

- ONNX OSNet → embedder (`identity/reid/embedder_onnx.py`), gerbang crop (`identity/reid/quality.py`),
  worker batch (`pipeline/reid_worker.py`), koordinator + `identity.resolved` (`pipeline/reid_coordinator.py`),
  sisi kamera (`pipeline/reid_tap.py`), section config `reid`, blok `reid` (mati) di demo-4060,
  demo-4060-tick, dan demo-1060. `lag_probe.py --events-out` untuk memeriksa aliran tanpa backend.
- ea-r4: cache ReID (galeri tubuh, kelompok ANON, rentang) dikosongkan **terjadwal tiap hari** pada
  `reid.daily_purge_time` (jam lokal, default `"00:00"`), lewat ticker runtime, walau tidak ada orang terlihat.
- ea-r5: `schedule_off` di engine asli, di belakang `core.analysis_off_mode: "pause"` (default `"stop"` = lama).
  Jeda analisis: track ditutup `schedule_off` + forced, kamera tetap hidup, tanpa `camera.failed`/`camera.online` baru.
- ea-r6: `engine-watchdog.ps1` (hidup ulang bila keluar/macet via berkas detak, berhenti rapi via berkas stop)
  dan `install-engine-task.ps1` (Task Scheduler, auto-start saat boot). Engine: `--heartbeat-file`, `--stop-file`.
- Tes: 632 lulus / 7 dilewati (sama seperti sebelumnya) di `engine/tests`; 47 ReID + 5 `schedule_off` + 10 detak + 1 probe.
  Watchdog diuji di PowerShell 7 Linux (mati, macet, berhenti rapi); Task Scheduler belum pernah dijalankan.
  `policy_grep` bersih. **Default tidak berubah** (`reid.enabled: false`).

## Belum

1. **Ambang ditahan**: `match_threshold: null` = usulan 0,80 yang belum dikalibrasi. Butuh crop berlabel dari
   kamera lokasi (`eval_reid.py`), lalu EA menyetujui nilai di MODEL-CARD.
2. **Backend belum siap**: `backend/schemas/protocol.py` hanya mengenal `identity_source` face/tracking dan tidak
   punya handler `identity.resolved` (tugas BE dari ea-k1). **Jangan nyalakan ReID dengan backend sungguhan**:
   heartbeat/snapshot `reid` akan gagal validasi, dan interval `ANON-…` bisa terhitung sebagai kehadiran.
3. `forget_person` belum menghapus prototipe tubuh orang itu dari galeri harian (hilang pada purge harian berikutnya).
4. Waktu tempuh antar lokasi belum diukur (`travel_time_seconds: {}`, default ketat 30 dtk).
5. Mode `pause` belum aman dengan backend sungguhan: `EndReason` backend belum punya `schedule_off`, dan tombol
   start/stop operator memakai `enabled=false` yang sama (dengan `pause`, "stop" operator berarti stream tetap dibaca).
   BE perlu memutuskan: jadwal vs stop operator dibedakan, atau stop operator ikut berarti jeda.
6. Watchdog + tugas Windows belum pernah dijalankan di Windows (langkah 9). Belum diketahui apakah GPU/CUDA
   jalan dari tugas S4U (sesi 0) di laptop tim; bila tidak, pakai `-Trigger Logon` + login otomatis.
7. MediaMTX belum diawasi watchdog (hanya engine). Untuk kamera RTSP langsung tidak perlu.

## Keputusan

Disetujui EA (9 Okt):
- ANON di presence tanpa `track.identified` (event itu tetap milik bukti wajah). Interval ReID: `start_source tracking`,
  `identity_confidence 0`. Yang membedakan ReID bagi BE: `identity_source` di heartbeat/snapshot dan `identity.resolved`.
- `reid.enabled` mewajibkan rekognisi wajah (`recognition.recognizer: onnx_face`).
- `runtime/camera.py` disentuh (hook kecil, mati bila `reid` None). EB merombak file ini 19–23 Okt: rebase di pihak EB
  cukup memindah tiga titik panggil (`_build`, `_on_frame`, `_close_open_tracks`/`_on_reconnect`).
- Cache ReID dikosongkan terjadwal tiap hari (ea-r4).

Masih perlu disetujui:
- ID ANON `ANON-<YYYYMMDD><nonce 4 heksa><n>` (cocok pola kontrak), agar restart engine tidak mengulang ID.
- Crop terpotong tepi frame tidak di-embed.
- Jam purge default `00:00`. "Hari" ReID = tanggal lokal dari (waktu − jam purge): dengan purge 03:00, orang yang
  terlihat 01:00 masih masuk galeri hari sebelumnya. Track yang hidup saat purge tidak dicabut labelnya (kehadiran
  tidak hilang); ia dinilai ulang dari galeri kosong pada embedding berikutnya. Bila operasional melewati tengah
  malam, pindahkan jam purge ke luar jam operasional.
- Line ending: file baru mengikuti LF seperti seluruh repo (butir lama `* text=auto` di SERAH-TERIMA EB).
- ea-r5: jadwal analisis di belakang flag (default lama) sampai BE siap. Saat jeda, stream tetap di-decode (CPU)
  supaya kamera "tetap hidup" sesuai kontrak; biayanya perlu diukur di laptop (langkah 8).

## Catatan untuk dokumen tim (belum diubah; tidak ada di repo)

- **Dok 05 §5** (model pihak ketiga): ReID = OSNet (`osnet_ain_x1_0` default kit), **dilatih tim** pada RandPerson
  (sintetis, Apache-2.0); init `<imagenet | scratch>` dan SHA-256 ONNX diisi dari MODEL-CARD saat model dipilih.
  Bila init imagenet: catat SHA bobot ImageNet dan status lisensinya (MODEL-CARD, bagian Inisialisasi).
- **Dok 04 §11**: status "rencana" → "terpasang, default mati (paket ea-r3); ambang belum dikalibrasi".

## Uji manual di laptop (PowerShell, dari root repo; 1060 atau 4060)

1. `mkdir engine\models\reid`, salin ONNX hasil `export_onnx.py` ke `engine\models\reid\osnet_reid.onnx`
   (bukan ke git; folder di-ignore). `Get-FileHash engine\models\reid\osnet_reid.onnx -Algorithm SHA256`.
2. Salin profil ke file lokal (mis. `engine\config\lokal-reid.yaml`, jangan di-commit), di blok `reid`: isi
   `model_sha256` (huruf kecil), biarkan `match_threshold: null` (ditahan), `enabled: true`.
3. Cek tolak-start: SHA diubah satu huruf → engine berhenti dengan pesan "SHA-256 ... tidak sama". Kembalikan.
4. Publish `.\scripts\publish_test_video.ps1 -Video <video> -Count 5`, jalankan engine dengan profil lokal, lalu
   `python scripts/lag_probe.py --minutes 15 --camera cam01=rtsp://127.0.0.1:8554/cam01 ... (5 kamera) --events-out bench-out\reid-events.ndjson`
   (**tanpa backend**). Lalu `python -m contracts.validator bench-out\reid-events.ndjson --channel events`.
   Harap: 0 galat; peringatan "ANON punya interval tapi tidak pernah identity.resolved" wajar.
5. Log engine: baris `ReID: embedding ...` tiap laporan health, `kelompok ANON-... dibuka`, `... diselesaikan ke ...`.
   Dengan video yang sama di 5 path, satu kelompok ANON **tidak boleh** berisi track dari dua kamera pada waktu yang
   sama (cannot-link); `identity.resolved` muncul saat wajah terbaca pada track yang sudah ANON.
6. Biaya: ulangi langkah 4 dengan `enabled: false`, bandingkan fps/umur kotak (`summarize_gladi.py`) dan VRAM
   (`nvidia-smi`). Di 1060 jalankan juga dengan 1 kamera bila 5 kamera sudah di bawah target tanpa ReID.
7. Purge terjadwal: set `daily_purge_time` ±2 menit dari jam laptop, jalankan engine dengan orang di depan kamera.
   Harap di log tepat pada jam itu: `ReID: cache hari ... dikosongkan (...)`, sekali saja; sesudahnya `kelompok ANON-...`
   baru bertanggal hari berikutnya. Orang yang masih terlihat tetap berlabel (tidak ada interval yang hilang).

8. `schedule_off` (tanpa backend): profil lokal dengan `core.analysis_off_mode: pause`; jalankan engine, sambung
   `lag_probe.py --events-out`, dan dari klien kirim `set_cameras` dengan `enabled: false` untuk cam01 lalu `true`.
   Harap: `track.ended reason schedule_off` hanya di cam01, tidak ada `camera.failed`, satu `camera.online` per
   kamera; validator 0 galat. Catat CPU proses engine saat cam01 dijeda (decode tetap jalan).

9. Watchdog + auto-start (Windows, PowerShell Admin; isi `-Python` dengan path python.exe env engine):
   a. Manual dulu: `.\deploy\laptop\engine-watchdog.ps1 -BindIp 127.0.0.1 -Config <profil> -Python <path>`.
      Harap `logs\engine\heartbeat.json` diperbarui tiap 5 dtk. Matikan python.exe di Task Manager: log
      `engine keluar ...`, hidup lagi ±5 dtk. Resource Monitor → klik kanan python.exe → Suspend: sesudah ±60 dtk
      `detak basi ... engine macet`, lalu hidup lagi. Ctrl+C: engine berhenti rapi, tak ada python.exe tersisa.
   b. Pasang: `.\deploy\laptop\install-engine-task.ps1 -BindIp <IP> -Config <profil> -Python <path> -StartNow`.
      Restart laptop TANPA login: engine harus menjawab (`lag_probe.py` dari mesin lain / backend tersambung);
      `nvidia-smi` harus menunjukkan python.exe memakai GPU. Bila tidak: pasang ulang dengan `-Trigger Logon`.
   c. `-Stop` lalu `-Uninstall`: tugas hilang, tak ada python.exe/powershell.exe watchdog tersisa.

## Langkah berikutnya

BE: `IdentitySource` reid/reid_retro + handler `identity.resolved` (SERAH-TERIMA-EA-K1 §2) sebelum ReID dinyalakan
dengan backend; `EndReason.SCHEDULE_OFF` + keputusan stop operator vs jadwal sebelum `analysis_off_mode: pause`.
EA: uji watchdog/tugas di Windows (langkah 9), kalibrasi ambang dari crop lokasi, ukur waktu tempuh,
`forget_person` → galeri ReID, lalu uji operasional 3 hari (10–12 Nov) memakai tugas ini.
