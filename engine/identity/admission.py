"""Siapa yang dicoba dikenali, kapan, dan dalam urutan apa.

Pengganti `StandardRecognitionPolicy` lama, yang punya satu cacat struktural
yang tidak bisa ditambal: ia menjawab pertanyaan per track secara terpisah
("track ini perlu dikenali?") padahal pertanyaan sebenarnya bersifat global
("dari sepuluh track di lima kamera, mana yang GPU kerjakan berikutnya?").
Kebijakan per track tidak punya cara menyatakan bahwa orang yang baru masuk
pintu lebih berharga daripada punggung orang yang sudah duduk dua jam.

Tiga hal yang diperbaiki di sini, dan semuanya lahir dari §3.2 dan §5.2:

**Himpunan in-flight.** Tanpa ini, kebijakan lama akan terus menjawab "belum
confirmed, kenali lagi" di setiap frame selama hasilnya belum kembali, dan
antrian meledak dalam dua detik. Satu track hanya boleh punya satu permintaan
yang sedang berjalan.

**Prioritas, bukan urutan kedatangan.** Momen orang masuk lewat pintu adalah
satu-satunya saat wajah frontal hampir dijamin, karena pintu menghadap kamera
sudut. Track yang lahir di `door_region` mendapat anggaran percobaan lebih
besar; sisa waktunya engine tidak perlu memaksakan pengenalan pada punggung
orang.

**Pembuangan berdasarkan UMUR, bukan posisi.** Permintaan yang lebih tua dari
beberapa ratus milidetik dibuang, karena orangnya masih di sana dan crop yang
lebih baru lebih berguna. Yang tidak boleh terjadi sebaliknya: membuang
permintaan terbaru demi mempertahankan yang lama adalah cara paling rapi untuk
selalu mengenali wajah dari posisi yang sudah ditinggalkan.
"""

from __future__ import annotations

import enum
import heapq
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ports import IdentityState, TrackIdentity

# Konstanta perseptual: seberapa basi sebuah crop sebelum tidak berguna, dan
# seberapa sering sebuah klaim yang sudah mapan perlu diperiksa ulang.
DEFAULT_MAX_AGE_SECONDS = 0.5
DEFAULT_RETRY_INTERVAL_SECONDS = 1.0
DEFAULT_BACKOFF_INTERVAL_SECONDS = 5.0
DEFAULT_ATTEMPTS_BEFORE_BACKOFF = 5
DEFAULT_REVERIFY_INTERVAL_SECONDS = 60.0
DEFAULT_PER_CAMERA_QUOTA = 4


class Priority(enum.IntEnum):
    """Lebih kecil dikerjakan lebih dulu."""

    DOOR_NEW = 0        # Track baru di region pintu: wajah frontal hampir dijamin
    UNIDENTIFIED = 1    # Sudah lama di ruangan, belum punya identitas
    EXPIRED = 2         # Klaim lama, TTL habis, perlu diperiksa ulang
    REVERIFY = 3        # Klaim sehat, pemeriksaan berkala


@dataclass(order=True)
class _Queued:
    priority: int
    requested_pts: float
    tiebreak: int
    track_uuid: str = field(compare=False)
    camera_id: str = field(compare=False)


@dataclass(frozen=True)
class Request:
    track_uuid: str
    camera_id: str
    priority: Priority
    requested_pts: float

    def age(self, now_pts: float) -> float:
        return max(0.0, now_pts - self.requested_pts)


class RecognitionScheduler:
    def __init__(
        self,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        retry_interval_seconds: float = DEFAULT_RETRY_INTERVAL_SECONDS,
        backoff_interval_seconds: float = DEFAULT_BACKOFF_INTERVAL_SECONDS,
        attempts_before_backoff: int = DEFAULT_ATTEMPTS_BEFORE_BACKOFF,
        reverify_interval_seconds: float = DEFAULT_REVERIFY_INTERVAL_SECONDS,
        per_camera_quota: int = DEFAULT_PER_CAMERA_QUOTA,
    ) -> None:
        self._max_age = max_age_seconds
        self._retry_interval = retry_interval_seconds
        self._backoff_interval = backoff_interval_seconds
        self._attempts_before_backoff = attempts_before_backoff
        self._reverify_interval = reverify_interval_seconds
        self._per_camera_quota = per_camera_quota

        self._queue: List[_Queued] = []
        self._counter = itertools.count()
        self._queued_tracks: Dict[str, _Queued] = {}
        # (pts, camera_id). Kamera disimpan di sini, BUKAN dicari ulang lewat
        # antrian: begitu permintaan di-pop ia keluar dari antrian, jadi
        # pencarian balik selalu gagal dan kuota per kamera diam-diam jadi
        # tak terbatas -- kegagalan yang tidak memunculkan error apa pun.
        self._in_flight: Dict[str, Tuple[float, str]] = {}
        self._last_attempt: Dict[str, float] = {}
        self._attempts: Dict[str, int] = {}
        self._dropped_stale = 0

    # ---------------- keputusan per track ----------------

    def priority_for(
        self,
        identity: Optional[TrackIdentity],
        now_pts: float,
        zone: str = "interior",
        track_age_seconds: float = 0.0,
    ) -> Optional[Priority]:
        """Prioritas kalau track ini layak dicoba sekarang; `None` kalau tidak.

        Ini murni kebijakan perseptual: seberapa besar peluang percobaan ini
        menghasilkan wajah yang berguna, dan seberapa perlu klaimnya diperiksa.
        """
        track_uuid = identity.track_uuid if identity else None

        if track_uuid and track_uuid in self._in_flight:
            return None

        if track_uuid and not self._interval_elapsed(track_uuid, now_pts):
            return None

        if identity is None or identity.state is IdentityState.PENDING:
            return Priority.DOOR_NEW if zone == "door" else Priority.UNIDENTIFIED

        if identity.state is IdentityState.PROVISIONAL:
            # Baru di pintu tetap didahulukan: jendelanya sempit dan tidak
            # akan datang lagi sampai orangnya keluar-masuk.
            if zone == "door" and track_age_seconds < 10.0:
                return Priority.DOOR_NEW
            return Priority.UNIDENTIFIED

        if identity.state is IdentityState.EXPIRED:
            return Priority.EXPIRED

        if identity.state is IdentityState.HELD:
            # Wajah tidak terlihat. Mencoba terus di sini persis pekerjaan yang
            # quality gate ada untuk mencegah, tapi sesekali tetap perlu supaya
            # orang yang berbalik lagi langsung tertangkap.
            return Priority.REVERIFY

        since_face = now_pts - (identity.last_face_pts or now_pts)
        if since_face >= self._reverify_interval:
            return Priority.REVERIFY

        return None

    def _interval_elapsed(self, track_uuid: str, now_pts: float) -> bool:
        last = self._last_attempt.get(track_uuid)
        if last is None:
            return True
        attempts = self._attempts.get(track_uuid, 0)
        interval = (
            self._retry_interval
            if attempts < self._attempts_before_backoff
            else self._backoff_interval
        )
        return (now_pts - last) >= interval

    # ---------------- antrian ----------------

    def submit(self, track_uuid: str, camera_id: str, priority: Priority, now_pts: float) -> bool:
        if track_uuid in self._in_flight:
            return False

        existing = self._queued_tracks.get(track_uuid)
        if existing is not None:
            # Satu track, satu tempat di antrian. Permintaan yang lebih baru
            # menggantikan yang lama: crop-nya lebih segar, dan mengantre dua
            # kali cuma memakai kuota kamera untuk pekerjaan yang sama.
            if priority <= existing.priority:
                existing.priority = int(priority)
                existing.requested_pts = now_pts
                heapq.heapify(self._queue)
            return False

        item = _Queued(int(priority), now_pts, next(self._counter), track_uuid, camera_id)
        heapq.heappush(self._queue, item)
        self._queued_tracks[track_uuid] = item
        return True

    def pop(self, now_pts: float) -> Optional[Request]:
        """Ambil permintaan paling layak, buang yang sudah basi."""
        in_flight_per_camera: Dict[str, int] = {}
        for _, camera_id in self._in_flight.values():
            in_flight_per_camera[camera_id] = in_flight_per_camera.get(camera_id, 0) + 1

        deferred: List[_Queued] = []
        chosen: Optional[_Queued] = None

        while self._queue:
            item = heapq.heappop(self._queue)

            if now_pts - item.requested_pts > self._max_age:
                # Dibuang karena umur, bukan karena posisi di antrian. Orangnya
                # masih di sana; crop berikutnya lebih berguna daripada crop
                # dari tempat yang sudah ia tinggalkan.
                self._queued_tracks.pop(item.track_uuid, None)
                self._dropped_stale += 1
                continue

            used = in_flight_per_camera.get(item.camera_id, 0)
            if used >= self._per_camera_quota:
                # Satu kamera ramai tidak boleh memonopoli GPU dan membuat
                # empat kamera lain buta.
                deferred.append(item)
                continue

            chosen = item
            break

        for item in deferred:
            heapq.heappush(self._queue, item)

        if chosen is None:
            return None

        self._queued_tracks.pop(chosen.track_uuid, None)
        self._in_flight[chosen.track_uuid] = (now_pts, chosen.camera_id)
        self._last_attempt[chosen.track_uuid] = now_pts
        self._attempts[chosen.track_uuid] = self._attempts.get(chosen.track_uuid, 0) + 1

        return Request(chosen.track_uuid, chosen.camera_id, Priority(chosen.priority), chosen.requested_pts)

    def complete(self, track_uuid: str, produced_evidence: bool = True) -> None:
        """Hasil sudah kembali. Percobaan yang berhasil mereset backoff."""
        self._in_flight.pop(track_uuid, None)
        if produced_evidence:
            self._attempts[track_uuid] = 0

    def forget(self, track_uuid: str) -> None:
        self._in_flight.pop(track_uuid, None)
        self._last_attempt.pop(track_uuid, None)
        self._attempts.pop(track_uuid, None)
        item = self._queued_tracks.pop(track_uuid, None)
        if item is not None and item in self._queue:
            self._queue.remove(item)
            heapq.heapify(self._queue)

    # ---------------- metrik ----------------

    @property
    def depth(self) -> int:
        return len(self._queue)

    @property
    def in_flight(self) -> int:
        return len(self._in_flight)

    @property
    def dropped_stale(self) -> int:
        return self._dropped_stale

    def metrics(self, now_pts: float) -> Dict[str, float]:
        """Empat angka yang §5.2 sebut wajib.

        Diambil dari sini dan bukan dari worker pool karena di sinilah
        keputusannya dibuat; worker cuma menjalankannya.
        """
        ages = [now_pts - item.requested_pts for item in self._queue]
        return {
            "queue_depth": float(len(self._queue)),
            "in_flight": float(len(self._in_flight)),
            "dropped_stale": float(self._dropped_stale),
            "oldest_queued_age": round(max(ages), 4) if ages else 0.0,
        }
