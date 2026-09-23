# Live timer and backend completion

## Implemented

- Real `view.frame` messages now update the backend `SystemState`.
- Every active track gets a backend-owned `first_seen` time and a live
  `session_elapsed` value.
- `/api/attendance/active` calculates duration at request time, so its timer
  continues between detection frames.
- Detection SSE boxes carry `session_elapsed`, `dwell_time`, and
  `presence_status`.
- The frontend continues each displayed timer from the last backend value.
- `/api/cameras` reports runtime FPS, online state, and active-person count.
- `/api/stats` now receives state from the real TCP engine path.
- Added `GET /api/attendance/breaks?date=YYYY-MM-DD` for the existing break
  allowance panel.
- Real protocol events are included in the recent backend event history.
- Fixed `snapshot.live[].stream_epoch` generation and backend schema support.
- Removed the duplicate dashboard `useDetectionStream()` owner to prevent SSE
  reconnect storms.
- Removed the duplicate case-only `useUnIdentifiedAlerts.ts` file that broke
  Linux builds.

## Timer behavior

- A timer is keyed by `camera_id + track_uuid`, not by identity. Identifying a
  track later therefore does not reset or duplicate its timer.
- A session becomes stale after 12 seconds without a new frame for that track.
- Completed usage is capped at the last observed time rather than including the
  stale grace period.

## Verification

- 54 selected backend, contract, and runtime tests passed.
- Frontend TypeScript and production Vite build passed.
- Three existing Unix-domain-socket tests could not run in the build sandbox
  because `AF_UNIX` socket creation is blocked there; this is environment
  specific and unrelated to the timer implementation.
- The complete test suite additionally needs the optional OpenCV dependency.
# Aturan timer free time

- Kehadiran harus berlanjut selama 20 detik sebelum dianggap sebagai kunjungan; orang yang keluar sebelum itu tidak memakai jatah.
- Pemakaian baru dimulai setelah 20 detik tersebut, bukan dihitung mundur dari `first_seen`.
- Pukul 12:00–13:00 zona `Asia/Jakarta`, validasi dan pemakaian sama-sama dijeda.
- Jatah pemakaian adalah 30 menit per pegawai per tanggal lokal dan pemakaian kunjungan yang selesai disimpan di SQLite.
- Overlay video menampilkan fase validasi, pemakaian harian, jeda istirahat, peringatan, dan batas tercapai, termasuk pada grid compact.
