"""Rekognisi wajah di luar loop frame (P7, 04 §5).

Sebelumnya `recognize(track, frame)` (SCRFD + AuraFace) dipanggil langsung dari
loop frame setiap kamera, di belakang satu kunci global. Satu wajah yang butuh
80 ms berarti loop frame kamera itu berhenti 80 ms, dan karena kuncinya global,
kamera lain ikut menunggu giliran. Dengan lima ruangan, setiap orang dikenali
ulang di setiap ruangan, jadi beban ini menjatuhkan fps semua kamera sekaligus.

Pembagian kerja di sini sengaja sempit:

- **Worker hanya menjalankan bagian yang mahal**: `recognize(snapshot, frame)`
  -> `Evidence` atau `None`. Fungsi murni terhadap gambar.
- **Semua yang mengubah state tetap di thread kamera**: arbiter, assembler,
  scheduler, dan pemancaran event. Hasil worker diantrekan kembali ke kamera
  asalnya dan diterapkan di frame berikutnya (`EngineBinding.drain_results`).
  Dengan begitu urutan `track.started` -> `track.identified` -> `track.ended`
  tidak bisa dikacaukan oleh thread lain, dan arbiter tidak perlu kunci.

Satu worker untuk semua kamera, karena ada satu GPU. Antrean dibatasi: bila
penuh, permintaan ditolak SEKETIKA (bukan menunggu) dan scheduler mencobanya
lagi nanti. Pekerjaan yang terlalu lama mengantre dibuang tanpa diproses,
karena crop wajah setengah detik lalu lebih buruk daripada crop berikutnya.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("engine.pipeline.recognition_worker")

Recognize = Callable[[Any, Any], Any]
Done = Callable[[str, Any], None]

DEFAULT_QUEUE_SIZE = 8
DEFAULT_MAX_AGE_SECONDS = 0.5


@dataclass(frozen=True)
class BoxSnapshot:
    """Salinan kotak saat permintaan dibuat. Track asli terus diubah tracker."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class TrackSnapshot:
    """Yang dibutuhkan recognizer dari sebuah track, dibekukan di thread kamera."""

    track_id: int
    bbox: BoxSnapshot
    attributes: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, track: Any) -> "TrackSnapshot":
        box = track.bbox
        return cls(
            track_id=int(getattr(track, "track_id", -1)),
            bbox=BoxSnapshot(float(box.x1), float(box.y1), float(box.x2), float(box.y2)),
            attributes=dict(getattr(track, "attributes", {}) or {}),
        )


@dataclass
class _Job:
    uuid: str
    camera_id: str
    track: TrackSnapshot
    frame: Any
    done: Done
    queued_at: float


@dataclass
class WorkerMetrics:
    submitted: int = 0
    rejected_full: int = 0
    processed: int = 0
    dropped_stale: int = 0
    failed: int = 0
    busy_seconds: float = 0.0
    wait_seconds: float = 0.0

    def as_dict(self, depth: int) -> Dict[str, float]:
        done = max(1, self.processed)
        return {
            "queue_depth": float(depth),
            "submitted": float(self.submitted),
            "rejected_full": float(self.rejected_full),
            "processed": float(self.processed),
            "dropped_stale": float(self.dropped_stale),
            "failed": float(self.failed),
            "avg_recognize_ms": round(1000.0 * self.busy_seconds / done, 1),
            "avg_wait_ms": round(1000.0 * self.wait_seconds / max(1, self.processed + self.dropped_stale), 1),
        }


class RecognitionWorker:
    def __init__(
        self,
        recognize: Recognize,
        max_queue: int = DEFAULT_QUEUE_SIZE,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_queue < 1:
            raise ValueError("max_queue minimal 1")
        self._recognize = recognize
        self._max_age = float(max_age_seconds)
        self._clock = clock
        self._jobs: "queue.Queue[Optional[_Job]]" = queue.Queue(maxsize=int(max_queue))
        self._lock = threading.Lock()
        self.metrics = WorkerMetrics()
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()

    # -- siklus hidup -------------------------------------------------------

    def start(self) -> "RecognitionWorker":
        if self._thread is None:
            self._stopped.clear()
            self._thread = threading.Thread(target=self._run, name="recognition-worker", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stopped.set()
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        # Pekerjaan yang tertinggal tetap dijawab, supaya scheduler tidak
        # menganggap track-nya "sedang diproses" selamanya.
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None:
                self._deliver(job, None)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- dipanggil thread kamera --------------------------------------------

    def submit(self, uuid: str, camera_id: str, track: Any, frame: Any, done: Done) -> bool:
        """Tidak pernah memblok. False = antrean penuh; coba lagi frame lain."""
        if self._stopped.is_set():
            return False
        job = _Job(uuid, camera_id, TrackSnapshot.of(track), frame, done, self._clock())
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            with self._lock:
                self.metrics.rejected_full += 1
            return False
        with self._lock:
            self.metrics.submitted += 1
        return True

    def snapshot_metrics(self) -> Dict[str, float]:
        with self._lock:
            return self.metrics.as_dict(self._jobs.qsize())

    # -- thread worker --------------------------------------------------------

    def _run(self) -> None:
        while not self._stopped.is_set():
            job = self._jobs.get()
            if job is None:
                break
            waited = self._clock() - job.queued_at
            if waited > self._max_age:
                with self._lock:
                    self.metrics.dropped_stale += 1
                    self.metrics.wait_seconds += waited
                self._deliver(job, None)
                continue
            started = self._clock()
            evidence = None
            try:
                evidence = self._recognize(job.track, job.frame)
            except Exception:  # noqa: BLE001 -- satu wajah rusak tidak boleh mematikan worker
                logger.exception("pengenalan gagal untuk %s", job.uuid)
                with self._lock:
                    self.metrics.failed += 1
            with self._lock:
                self.metrics.processed += 1
                self.metrics.busy_seconds += self._clock() - started
                self.metrics.wait_seconds += waited
            self._deliver(job, evidence)

    @staticmethod
    def _deliver(job: _Job, evidence: Any) -> None:
        try:
            job.done(job.uuid, evidence)
        except Exception:  # noqa: BLE001
            logger.exception("callback hasil rekognisi gagal untuk %s", job.uuid)
