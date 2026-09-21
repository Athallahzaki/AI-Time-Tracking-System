# Protokol Engine ↔ Backend & Spesifikasi Engine Palsu

**AI Time Tracking System** · v1 · 19 September 2026

Dokumen ini adalah **kontrak**, bukan penjelasan. Alasan di balik keputusannya ada di
`ARCHITECTURE.md`; yang ada di sini adalah bentuk pesan yang harus disepakati kedua
sisi, dan spesifikasi engine palsu yang membuat backend dan frontend bisa jalan tanpa
menunggu engine sungguhan.

**Pemilik skema:** satu orang, ditunjuk. Perubahan apa pun lewat dia. Kalau
kepemilikannya bersama, skema ini akan melar ke dua arah sekaligus dan tidak ada yang
tahu mana yang benar.

---

## 1. Aturan dasar

**Transport:** NDJSON di atas socket — satu objek JSON per baris, `\n` sebagai framing.
Unix domain socket kalau satu mesin, TCP kalau beda mesin.

**Tiga kanal terpisah**, boleh socket berbeda atau satu socket dengan field `channel`:

| Kanal | Arah | Jaminan |
| --- | --- | --- |
| `control` | Backend → Engine | Request/response, ack cepat |
| `events` | Engine → Backend | Andal, berurut, bisa diulang |
| `view` | Engine → Backend | Best-effort, boleh drop |

**Engine tidak pernah memblok menunggu backend.** Kalau backend lambat, kanal `view`
dibuang; kanal `events` masuk outbox dan menunggu.

**Aturan evolusi:** field tak dikenal **diabaikan diam-diam**. Penambahan field tidak
menaikkan versi. Perubahan yang memutus kompatibilitas menaikkan `protocol_version`
mayor dan kedua versi harus didukung selama satu siklus rilis.

**Satuan waktu:** semua `*_pts` dalam detik, float, relatif terhadap awal stream.
Semua `*_at` dalam RFC3339 UTC. Engine yang mengonversi; backend tidak pernah
menghitung durasi dari jamnya sendiri.

---

## 2. Amplop bersama

Setiap pesan punya:

```json
{ "type": "...", "v": 1, "ts": "2026-09-19T08:14:22.481Z" }
```

Pesan di kanal `events` menambahkan `seq` (integer monoton, mulai dari 1, tidak pernah
diulang kecuali saat replay).

---

## 3. Kanal `control` — Backend → Engine

### 3.1 `hello`

Dikirim backend setiap kali koneksi terbentuk. **Wajib pertama.**

```json
{ "type": "hello", "v": 1, "protocol_version": 1,
  "client": "backend-go/0.4.1",
  "last_event_seq": 10432 }
```

`last_event_seq: 0` berarti backend baru dan tidak minta replay.

Balasan:

```json
{ "type": "hello_ack", "v": 1, "protocol_version": 1,
  "engine_version": "0.9.0",
  "models": { "detector": "yolo11s", "embedder": "auraface-ir100",
              "embedding_version": "auraface-v1" },
  "oldest_available_seq": 9800 }
```

Kalau `last_event_seq` lebih kecil dari `oldest_available_seq`, engine tidak bisa
replay penuh. Ia tetap mengirim apa yang ada dan menandainya:

```json
{ "type": "replay_gap", "v": 1, "from_seq": 10432, "to_seq": 9800 }
```

Backend **wajib** memperlakukan ini sebagai lubang data, bukan sebagai tidak ada
kejadian.

### 3.2 `set_cameras`

Deklaratif. Berisi **seluruh** himpunan kamera yang diinginkan; engine mencocokkan
state-nya. Kamera yang tidak ada di daftar ditutup.

```json
{ "type": "set_cameras", "v": 1, "cameras": [
    { "camera_id": "r1",
      "uri": "rtsp://user:pass@10.0.0.11/Streaming/Channels/101",
      "door_region": [0.62, 0.10, 0.95, 0.55],
      "enabled": true },
    { "camera_id": "r2", "uri": "rtsp://...", "door_region": [...] }
] }
```

`door_region` dalam koordinat ternormalisasi `[x1, y1, x2, y2]`, rentang 0–1.

### 3.3 `set_roster`

Deklaratif, sama polanya. Hanya ID dan versi — vektornya tidak dikirim.

```json
{ "type": "set_roster", "v": 1, "persons": [
    { "person_id": "4471", "enrollment_version": 3 },
    { "person_id": "4802", "enrollment_version": 1 }
] }
```

Engine membuang vektor milik siapa pun yang tidak ada di daftar, lalu meminta yang
belum dipunyainya lewat event `enrollment_needed`.

### 3.4 `enroll`

```json
{ "type": "enroll", "v": 1, "request_id": "e-8812",
  "person_id": "4471", "enrollment_version": 4,
  "images": [ { "id": "img1", "jpeg_b64": "..." },
              { "id": "img2", "jpeg_b64": "..." } ] }
```

Balasan membawa hasil per gambar, bukan sekadar sukses/gagal:

```json
{ "type": "enroll_result", "v": 1, "request_id": "e-8812",
  "accepted": false,
  "reason": "collision",
  "collides_with": "4802", "collision_similarity": 0.83,
  "images": [
    { "id": "img1", "accepted": true,  "quality": 0.81 },
    { "id": "img2", "accepted": false, "reason": "duplicate_of:img1",
      "similarity": 0.94 } ] }
```

Nilai `reason` untuk gambar: `too_small`, `blurry`, `extreme_pose`, `bad_lighting`,
`no_face`, `multiple_faces`, `duplicate_of:<id>`.
Nilai `reason` untuk keseluruhan: `collision`, `insufficient_references`, `ok`.

### 3.5 `ack`

```json
{ "type": "ack", "v": 1, "in_reply_to": "set_cameras", "accepted": true }
```

**Ack hanya berarti perintah diterima, bukan selesai.** Hasil sebenarnya menyusul
sebagai event. Membuka RTSP bisa makan lima detik dan bisa gagal.

---

## 4. Kanal `events` — Engine → Backend

### 4.1 `presence.interval` — output utama

Inilah yang jadi dasar seluruh perhitungan backend.

```json
{ "type": "presence.interval", "v": 1, "seq": 10433,
  "interval_id": "r1-t7-a91c",
  "person_id": "4471", "camera_id": "r1",
  "start_pts": 1531.20, "end_pts": 4250.85,
  "start_at": "2026-09-19T02:15:31.200Z",
  "end_at":   "2026-09-19T03:00:50.850Z",
  "start_source": "face", "end_source": "track_lost",
  "start_zone": "door", "end_zone": "interior",
  "end_reason": "occluded_timeout",
  "identity_confidence": 0.91, "evidence_count": 4,
  "prev_interval_id": "r1-t3-55ee",
  "evidence_crop": { "start": "c-991a.jpg", "end": "c-991b.jpg" } }
```

| Field | Nilai | Arti |
| --- | --- | --- |
| `start_source` / `end_source` | `face` | Batas dari identifikasi wajah langsung — paling andal |
| | `tracking` | Identitas dipegang tracker tanpa wajah (state `HELD`) |
| | `forced` | Terminasi paksa, bukan pengamatan |
| `start_zone` / `end_zone` | `door` | Di region pintu — kemungkinan besar benar masuk/keluar |
| | `interior` | Di tengah ruangan — **curigai kegagalan tracking, bukan kepergian** |
| | `frame_edge` | Di tepi frame di luar region pintu |
| `end_reason` | `left_frame` | Keluar dari pandangan secara wajar |
| | `occluded_timeout` | Hilang terhalang, tidak kembali dalam batas waktu |
| | `merged_into_other_track` | Track digabung; lihat `prev_interval_id` di interval penerus |
| | `camera_lost` | **Kamera putus — bukan kepergian siapa pun** |
| | `engine_shutdown` | Engine berhenti |
| | `identity_released` | Klaim identitas dilepas karena bukti berlawanan |

`prev_interval_id` terisi kalau interval ini adalah kelanjutan yang disambung engine
(lihat `track.resumed`). Backend memperlakukan rantai ini sebagai satu kehadiran
berkelanjutan tanpa celah.

**Yang tidak ada dan tidak akan pernah ada di sini: akumulasi harian.** Menjumlahkan
interval berarti memutuskan celah mana yang dianggap masih hadir — itu kebijakan, dan
itu milik backend.

### 4.2 Siklus hidup track

```json
{ "type": "track.started", "v": 1, "seq": 10420,
  "track_uuid": "r1-t7-a91c", "camera_id": "r1",
  "pts": 1531.20, "zone": "door" }

{ "type": "track.identified", "v": 1, "seq": 10423,
  "track_uuid": "r1-t7-a91c", "person_id": "4471",
  "pts": 1539.60, "track_started_pts": 1531.20,
  "similarity": 0.88, "margin": 0.11, "evidence_count": 3 }

{ "type": "track.heartbeat", "v": 1, "seq": 10428,
  "track_uuid": "r1-t7-a91c", "person_id": "4471",
  "pts": 1720.00, "identity_source": "tracking", "confidence": 0.74 }

{ "type": "track.resumed", "v": 1, "seq": 10441,
  "track_uuid": "r1-t9-b02d", "prev_track_uuid": "r1-t7-a91c",
  "person_id": "4471", "gap_seconds": 2.8, "pts": 4253.65 }

{ "type": "track.identity_changed", "v": 1, "seq": 10450,
  "track_uuid": "r1-t9-b02d", "from_person_id": "4471",
  "to_person_id": "4802", "reason": "sustained_disagreement",
  "disagreement_count": 3 }

{ "type": "track.ended", "v": 1, "seq": 10460,
  "track_uuid": "r1-t9-b02d", "pts": 5010.10,
  "reason": "left_frame", "exit_zone": "door" }
```

**`track_started_pts` di `track.identified` wajib ada.** Tanpa itu backend
menghitung kehadiran mulai dari saat wajah terbaca, bukan saat orangnya masuk — dan
selisih beberapa detik per kejadian menumpuk jadi menit di jatah yang cuma 30 menit.

### 4.3 Sinyal operasional

```json
{ "type": "person.unidentified_present", "v": 1, "seq": 10470,
  "track_uuid": "r1-t11-c3f0", "camera_id": "r1",
  "duration_seconds": 240, "attempts": 18,
  "reason": "no_face_detected" }
```

`reason`: `no_face_detected`, `quality_gate_rejected`, `below_threshold`,
`margin_too_narrow`.

Ini bukan noise. Di ruangan dengan kamera sudut, orang tak dikenal yang hadir lama
kemungkinan besar adalah karyawan yang membelakangi kamera — dan mungkin orang yang
sedang dihitung sebagai istirahat oleh backend.

### 4.4 Status kamera dan engine

```json
{ "type": "camera.online",  "v": 1, "seq": 10400, "camera_id": "r1", "fps": 10.2 }
{ "type": "camera.failed",  "v": 1, "seq": 10401, "camera_id": "r3",
  "reason": "connection_refused", "retry_in_seconds": 5 }
{ "type": "camera.degraded","v": 1, "seq": 10402, "camera_id": "r2",
  "reason": "fps_below_target", "fps": 3.1 }

{ "type": "camera.coverage", "v": 1, "seq": 10500, "camera_id": "r1",
  "observed_regions": [[0.1,0.2,0.9,0.95]],
  "never_observed": [[0.0,0.0,0.1,1.0]] }

{ "type": "engine.health", "v": 1, "seq": 10510,
  "models_loaded": true, "gpu_util": 0.62, "vram_mb": 3100,
  "queue_depth": 4, "drop_rate": 0.02,
  "cameras": { "r1": "online", "r2": "degraded", "r3": "failed" } }
```

`camera.failed` **bukan** alasan menandai orang pulang. Semua `track.ended` yang
menyertainya akan bertuliskan `reason: camera_lost`.

### 4.5 `snapshot`

Berkala, misalnya tiap 10 detik. Memberi backend jalan menyelaraskan diri tanpa
memutar ulang riwayat.

```json
{ "type": "snapshot", "v": 1, "seq": 10520,
  "pts_wallclock_offset": { "r1": 1758240000.0 },
  "live": [
    { "track_uuid": "r1-t9-b02d", "camera_id": "r1", "person_id": "4471",
      "identity_source": "tracking", "since_pts": 4253.65 },
    { "track_uuid": "r1-t11-c3f0", "camera_id": "r1", "person_id": null,
      "since_pts": 4890.00 } ] }
```

`pts_wallclock_offset` **berubah setiap reconnect kamera.** Backend harus memakai
yang terbaru, bukan yang di-cache dari awal hari.

### 4.6 `enrollment_needed`

```json
{ "type": "enrollment_needed", "v": 1, "seq": 10530,
  "person_ids": ["4471", "5120"] }
```

---

## 5. Kanal `view` — Engine → Backend

Best-effort. Boleh di-drop, boleh di-throttle, tidak masuk outbox, **tidak punya
`seq`**.

```json
{ "type": "view.frame", "v": 1, "camera_id": "r1",
  "pts": 4900.33, "at": "2026-09-19T03:21:40.330Z",
  "boxes": [
    { "track_uuid": "r1-t9-b02d", "bbox": [0.31,0.22,0.44,0.78],
      "person_id": "4471", "identity_source": "tracking" },
    { "track_uuid": "r1-t11-c3f0", "bbox": [0.60,0.30,0.71,0.81],
      "person_id": null } ] }
```

**Dua timestamp, dan keduanya wajib.** `pts` menyambungkan pesan ini ke event engine;
`at` menyambungkannya ke video, karena MediaMTX menyajikan HLS dengan
`EXT-X-PROGRAM-DATE-TIME` yang berbasis jam dinding. Browser menyelaraskan overlay
lewat `at`, bukan `pts`.

`bbox` ternormalisasi `[x1,y1,x2,y2]` — **wajib**, karena engine melihat mainstream
sementara browser menampilkan substream.

Penyelarasan overlay **tidak wajib presisi**. Kotak yang telat 150 ms cuma terlihat
sedikit meleset, dan tidak ada event domain yang terpengaruh. Jangan biarkan kanal ini
menyandera keputusan arsitektur mana pun.

---

## 6. Engine palsu (`fake_engine`)

Program yang memancarkan protokol di atas dari skenario tertulis, tanpa kamera, tanpa
GPU, tanpa model. Ia adalah **alat pembuka blokir utama**: begitu ada, backend dan
frontend jalan penuh kecepatan tanpa menunggu engine sungguhan.

Ia juga memberi sesuatu yang engine sungguhan tidak bisa: **skenario patologis sesuai
permintaan.** Kamera mati di tengah sesi, identitas tertukar, backend reconnect minta
replay — di hardware asli kalian menunggu kebetulan; di sini tinggal menulis file.

### 6.1 CLI

```
fake_engine --socket /tmp/engine.sock \
            --scenario scenarios/berbalik-lama.yaml \
            [--speed 10]        # percepat waktu skenario
            [--loop]            # ulangi terus
            [--seed 42]         # untuk jitter yang reprodusibel
            [--chaos drop_view=0.3,disconnect_after=120]
```

`--speed 10` penting: skenario 30 menit selesai dalam 3 menit saat tes.

### 6.2 Format skenario

```yaml
name: berbalik-lama
description: Track putus di interior padahal orangnya masih di ruangan
protocol_version: 1

cameras:
  - id: r1
    online_at: 0.0
    pts_offset: 1758240000.0

persons: ["4471", "4802"]

timeline:
  - at: 2.0
    emit: track.started
    track: t7
    camera: r1
    zone: door

  - at: 2.4
    emit: track.identified
    track: t7
    person: "4471"
    similarity: 0.88
    margin: 0.11

  - at: 180.0
    emit: track.ended
    track: t7
    reason: occluded_timeout
    zone: interior            # ← celah palsu dimulai di sini

  - at: 195.0
    emit: track.started
    track: t9
    camera: r1
    zone: interior            # ← muncul lagi di tengah ruangan

  - at: 196.0
    emit: track.identified
    track: t9
    person: "4471"
```

`fake_engine` menurunkan `presence.interval`, `heartbeat`, dan `snapshot` secara
otomatis dari timeline ini. Penulis skenario hanya menuliskan kejadian pentingnya.

### 6.3 Skenario yang wajib ada

Ini sekaligus daftar tes integrasi. Tanpa semuanya hijau, jangan anggap backend
selesai.

| # | Skenario | Yang diuji |
| --- | --- | --- |
| 1 | `happy-path` | Masuk lewat pintu, dikenali, kerja, keluar lewat pintu |
| 2 | `berbalik-lama` | Track putus di interior → backend **tidak boleh** menghitung istirahat |
| 3 | `istirahat-asli` | Keluar lewat pintu, kembali 12 menit → **harus** dihitung |
| 4 | `kamera-mati` | 3 orang di ruangan, kamera putus → tidak seorang pun dianggap pulang |
| 5 | `identitas-tertukar` | `identity_changed` setelah 3 ketidaksetujuan → koreksi riwayat |
| 6 | `reconnect-replay` | Backend putus di seq 10432, minta ulang, tidak ada event hilang |
| 7 | `replay-gap` | Backend putus terlalu lama → lubang data harus terdeteksi, bukan diabaikan |
| 8 | `orang-tak-dikenal` | Hadir 20 menit tanpa identitas → alert muncul |
| 9 | `dua-orang-mirip` | Margin tipis → tidak ada yang diklaim |
| 10 | `enrollment-ditolak` | Tabrakan, duplikat, kualitas buruk → pesan spesifik ke UI |
| 11 | `roster-berubah` | `set_roster` saat jalan → vektor dibuang, enrollment diminta |
| 12 | `stitching` | Teroklusi 3 detik → `track.resumed`, **bukan** interval baru |
| 13 | `kamera-reconnect` | `pts_wallclock_offset` berubah → backend pakai yang baru |
| 14 | `lintas-ruangan` | Keluar r1 masuk r2 dalam 8 detik → handoff, bukan dua kehadiran |

### 6.4 Fixture

Setiap skenario di atas direkam sebagai file NDJSON dan **di-commit ke repo**:

```
fixtures/
  berbalik-lama.ndjson
  berbalik-lama.expected.json     # sesi & istirahat yang seharusnya diturunkan
```

Tes backend memutar ulang `.ndjson` lalu membandingkan hasilnya dengan
`.expected.json`. Ini jaring pengaman untuk logika kebijakan — satu-satunya cara
memastikan refactor tidak diam-diam mengubah cara istirahat dihitung.

**Saat engine sungguhan sudah jalan**, rekam alirannya ke format yang sama dan
jadikan fixture tambahan. Fixture dari engine asli menangkap hal-hal yang tidak
terpikir saat menulis skenario.

---

## 7. Daftar periksa kesesuaian

Engine sungguhan dianggap memenuhi kontrak kalau:

- [ ] Semua pesan lolos validasi skema
- [ ] `seq` monoton, tidak pernah mundur kecuali saat replay eksplisit
- [ ] Replay dari `last_event_seq` menghasilkan aliran identik dengan aslinya
- [ ] `replay_gap` dipancarkan saat outbox tidak cukup jauh ke belakang
- [ ] `track.identified` selalu membawa `track_started_pts`
- [ ] `track.ended` selalu membawa `reason` **dan** `exit_zone`
- [ ] `presence.interval` tidak pernah berisi akumulasi lintas interval
- [ ] `bbox` selalu ternormalisasi 0–1
- [ ] Kamera putus menghasilkan `reason: camera_lost`, bukan `left_frame`
- [ ] `pts_wallclock_offset` diperbarui setiap reconnect kamera
- [ ] Engine tidak pernah memblok karena backend lambat
- [ ] `grep` konstanta kebijakan di `engine/` tidak menemukan apa pun

Backend dianggap memenuhi kontrak kalau keempat belas skenario di §6.3 menghasilkan
`.expected.json` yang benar.
