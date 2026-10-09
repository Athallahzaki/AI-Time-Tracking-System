# Serah-terima EA — paket ea-k1: kontrak ReID dan jadwal analisis

Tanggal: 9 Oktober 2026 · Pemilik: EA · Dasar: dokumen 12 §3.3, §3.6 · Changelog: `docs/CHANGELOG.md`

Batasan paket: `backend/` dan `engine/` (selain `engine/tools/fake_engine`) **tidak disentuh**.
Yang di bawah ini adalah daftar yang harus BE/EB/FE sesuaikan sendiri.

## 1. Daftar perubahan skema (untuk diumumkan)

Semua di `contracts/schema/engine_protocol.schema.json`. Tidak ada field wajib baru di event
lama, dan fixture 14 skenario lama tidak berubah (dikunci tes).

| # | Perubahan | Jenis |
|---|---|---|
| 1 | Event baru `identity.resolved` (kanal events, engine→backend) | tambahan |
| 2 | `identity_source` jadi `face \| tracking \| reid \| reid_retro` di `track.heartbeat`, `snapshot.live[]`, `view.frame.boxes[]` (kini satu `$defs.identity_source`) | enum diperluas |
| 3 | `end_reason` + `schedule_off` (di `track.ended.reason` dan `presence.interval.end_reason`) | enum diperluas |
| 4 | `$defs.anon_id`, pola `^ANON-[A-Za-z0-9]{1,32}$` | tambahan |

### `identity.resolved`

```json
{ "type": "identity.resolved", "v": 1, "ts": "...", "seq": 16,
  "anon_id": "ANON-0001", "person_id": "4471",
  "at": "2025-09-19T00:02:30.200Z", "reason": "face_confirmed",
  "trigger_track_uuid": "tr_r2-t2",
  "track_uuids": ["tr_r1-t1", "tr_r2-t2"],
  "moved_intervals": ["iv_r1-0001"] }
```

Wajib: `anon_id`, `person_id`, `at`, `reason`, `track_uuids` (min. 1), `moved_intervals` (boleh `[]`).
`reason`: `face_confirmed` | `group_merged`. Sengaja **tanpa** `pts`/`stream_epoch`: kelompok bisa
melintasi kamera, dan `pts` hanya sebanding dalam satu (kamera, epoch). Waktu kejadian = `at`.

### Cara ANON muncul di aliran (keputusan EA, perlu persetujuan BE)

`ANON-xxxx` cocok dengan pola `person_id`, jadi **selama belum diselesaikan** ia muncul apa
adanya sebagai `person_id` di `presence.interval`, `track.heartbeat`, `snapshot` dan `view.frame`,
dengan `identity_source: "reid"`. Alasan: tidak ada field wajib baru dan tidak ada tipe yang
dilonggarkan jadi nullable, jadi penerima lama tidak pecah. Harga yang dibayar: **BE harus
menolak awalan `ANON-` sebagai `person_id` karyawan** dan tidak boleh menghitung interval
ANON sebagai kehadiran karyawan sebelum `identity.resolved`. Bila BE lebih suka field terpisah
(`anon_id` opsional + `person_id` nullable), itu perubahan kontrak berikutnya; katakan sebelum
EB mulai memancarkan.

Urutan yang dijamin (dicek `ConformanceChecker`): interval ANON → `identity.resolved` (memuat
semua interval ANON itu di `moved_intervals`) → interval berikutnya langsung berlabel karyawan
dan **tidak** masuk daftar. Satu `anon_id` hanya diselesaikan sekali dan tidak dipakai lagi.

### Makna `identity_source`

- `face`: wajah terkonfirmasi. `tracking`: identitas dipegang tracker tanpa wajah.
- `reid`: dari kecocokan tubuh ke galeri harian, termasuk kelompok `ANON-xxxx`.
- `reid_retro`: identitas yang diketahui mundur lewat `identity.resolved` (track hidup anggota
  kelompok selain track pemicu; track pemicu tetap `face`).
- `boundary_source` (`face|tracking|forced`, batas interval) **tidak diubah**. Interval yang
  berasal dari ReID tetap `tracking` di sana. Pelabelan "perlu dicek HR" (§3.6 butir 6) dihitung
  BE dari `identity_source`/`moved_intervals`, bukan dari field baru di interval.

### `schedule_off`

Track yang hidup saat analisis kamera dimatikan jadwal (`set_cameras enabled=false`, field itu
sudah ada) ditutup `track.ended.reason = schedule_off` dan interval `end_reason = schedule_off`,
**selalu `end_source = forced`** (dicek conformance). Bukan `left_frame` (orang pulang), bukan
`camera_lost` (kamera putus; conformance menolak `schedule_off` saat kamera sedang putus).
Kamera tetap hidup: tidak ada `camera.failed`, dan tidak ada `camera.online` baru saat
analisis dinyalakan lagi.

## 2. Yang harus dilakukan tiap tim

**BE** (`backend/schemas/protocol.py`, parser dan penyimpanan)
- `EndReason` + `SCHEDULE_OFF`; `IdentitySource` + `REID`, `REID_RETRO` (kini hanya `face`/`tracking`,
  baris 22 dan 43). Tanpa ini pesan baru gagal validasi pydantic.
- Model dan handler untuk `identity.resolved`: pindahkan `moved_intervals` dari ANON ke `person_id`,
  tandai `reid_retro`, idempoten terhadap replay (event yang sama bisa datang dua kali).
- Tolak awalan `ANON-` di `set_roster`/`enroll`; jangan hitung interval ANON sebagai kehadiran.
- Perlakukan `schedule_off` sebagai penutupan di luar jam operasional, bukan kepergian dan bukan
  celah/istirahat. Celah di fixture `jadwal-mati` (910 detik, `end_reason: schedule_off`) harus
  tidak masuk hitungan istirahat.
- Penerima lama yang meng-ignore tipe tak dikenal akan membuang `identity.resolved` diam-diam
  dan interval ANON tidak pernah dipindah: pastikan handler terdaftar sebelum EB memancarkannya.

**EB** (emitter engine asli)
- Pancarkan sesuai urutan di atas; `moved_intervals` harus lengkap (conformance menolak yang
  terlewat atau yang bukan milik `anon_id`).
- Track pemicu: `identity_source: face`; anggota hidup lain: `reid_retro`.
- Saat jadwal mati: tutup track dengan `schedule_off` + `forced`, jangan `left_frame`/`camera_lost`.
- Validasi keluaran dengan `python -m contracts.validator <rekaman>.ndjson --strict`.

**FE**
- Kotak `view.frame` bisa berisi `person_id: "ANON-xxxx"` dan `identity_source: reid|reid_retro`:
  tampilkan sebagai "belum dikenali (ANON-xxxx)", jangan sebagai nama karyawan. Tangani nilai
  `identity_source` yang tak dikenal tanpa pecah (aturan evolusi enum).
- Label alasan penutupan `schedule_off` ("analisis dimatikan jadwal") di forensik/timeline.
- Pakai skenario `reid-tertunda` dan `jadwal-mati` di `fake_engine` untuk membangun tampilannya.

## 3. Fixture dan skenario baru

`python -m engine.tools.fake_engine --scenario reid-tertunda|jadwal-mati --socket /tmp/engine.sock`

- `reid-tertunda`: r1 `ANON-0001` (60 dtk, tanpa wajah) → pindah ke r2 → wajah terbaca di dtk 150
  → `identity.resolved` memindahkan `iv_r1-0001` ke 4471; interval r2 sesudahnya langsung 4471.
- `jadwal-mati`: dua kamera; r1 dimatikan jadwal (4471 `schedule_off`), r2 (4472) tak terpengaruh;
  r1 dinyalakan lagi dan 4471 muncul sebagai track baru.

## 4. Verifikasi

- `python -m pytest contracts/tests -q`: 151 lulus. Seluruh repo: 731 lulus, 7 skip (sudah ada sebelumnya).
- Kedua skenario baru lolos `python -m contracts.validator ... --strict` (tanpa pelanggaran).
- Fixture lama: `--all --record` tidak mengubah satu berkas lama pun.
- Skema lama tetap valid: `contracts/tests/required_baseline.json` + tes
  `test_event_lama_tidak_mendapat_field_wajib_baru`.

## 5. Terbuka / sengaja tidak dikerjakan

1. `engine.health.cameras` hanya `online|degraded|failed`; belum ada status "analisis mati".
   Mengubah enum itu = mematahkan penerima lama; ditunda sampai BE memutuskan butuh atau tidak.
2. Dokumen 07 dan `docs/ENGINE_PROTOCOL.md` belum diperbarui (doc 12 §10.4); bukan dalam daftar
   berkas paket ini.
3. Penggabungan dua kelompok ANON (`reason: group_merged`) ada di skema tapi belum ada skenario
   yang menurunkannya; semantik detailnya (anon yang hilang, `moved_intervals` gabungan) perlu
   disepakati dengan EB bersamaan dengan logika ReID.
4. Tidak ada pesan "ANON baru terbentuk"; BE mengetahuinya dari `person_id` ANON pertama. Kalau FE
   butuh daftar kelompok tak dikenal secara langsung, itu event tambahan.
