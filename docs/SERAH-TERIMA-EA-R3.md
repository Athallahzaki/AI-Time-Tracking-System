# Serah terima EA — paket ea-r3: model ReID OSNet ONNX dirakit ke engine

9 Oktober 2026 · Jalur EA · Rincian: `docs/CHANGELOG.md` (ea-r3). File ini **tidak** menggantikan
`docs/SERAH-TERIMA.md` (status EB, paket eb-r10); keduanya berlaku.

## Selesai

- ONNX OSNet → embedder (`identity/reid/embedder_onnx.py`), gerbang crop (`identity/reid/quality.py`),
  worker batch (`pipeline/reid_worker.py`), koordinator + `identity.resolved` (`pipeline/reid_coordinator.py`),
  sisi kamera (`pipeline/reid_tap.py`), section config `reid`, blok `reid` (mati) di demo-4060,
  demo-4060-tick, dan demo-1060. `lag_probe.py --events-out` untuk memeriksa aliran tanpa backend.
- Tes: 607 lulus / 7 dilewati (sama seperti sebelumnya) di `engine/tests`; 37 tes ReID baru + 1 tes probe.
  `policy_grep` bersih. **Default tidak berubah** (`reid.enabled: false`).

## Belum

1. **Ambang ditahan**: `match_threshold: null` = usulan 0,80 yang belum dikalibrasi. Butuh crop berlabel dari
   kamera lokasi (`eval_reid.py`), lalu EA menyetujui nilai di MODEL-CARD.
2. **Backend belum siap**: `backend/schemas/protocol.py` hanya mengenal `identity_source` face/tracking dan tidak
   punya handler `identity.resolved` (tugas BE dari ea-k1). **Jangan nyalakan ReID dengan backend sungguhan**:
   heartbeat/snapshot `reid` akan gagal validasi, dan interval `ANON-…` bisa terhitung sebagai kehadiran.
3. `forget_person` belum menghapus prototipe tubuh orang itu dari galeri harian (hilang sendiri tengah malam).
4. Waktu tempuh antar lokasi belum diukur (`travel_time_seconds: {}`, default ketat 30 dtk).

## Keputusan yang perlu disetujui

- ANON di presence tanpa `track.identified` (event itu tetap milik bukti wajah). Interval ReID: `start_source tracking`,
  `identity_confidence 0`. Yang membedakan ReID bagi BE: `identity_source` di heartbeat/snapshot dan `identity.resolved`.
- ID ANON kini `ANON-<YYYYMMDD><nonce 4 heksa><n>` (masih cocok pola kontrak), agar restart engine tidak mengulang ID.
- `reid.enabled` mewajibkan rekognisi wajah. Crop terpotong tepi frame tidak di-embed.
- `runtime/camera.py` disentuh (hook kecil, mati bila `reid` None). EB merombak file ini 19–23 Okt: rebase di pihak EB
  cukup memindah tiga titik panggil (`_build`, `_on_frame`, `_close_open_tracks`/`_on_reconnect`).
- Line ending: file baru mengikuti LF seperti seluruh repo (butir lama `* text=auto` di SERAH-TERIMA EB).

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

## Langkah berikutnya

BE: `IdentitySource` reid/reid_retro + handler `identity.resolved` (SERAH-TERIMA-EA-K1 §2) sebelum ReID dinyalakan
dengan backend. EA: kalibrasi ambang dari crop lokasi, ukur waktu tempuh, `forget_person` → galeri ReID.
