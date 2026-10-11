"""Worker embedding tubuh ReID di luar loop frame (pola `recognition_worker.py`).

Sama prinsipnya dengan worker wajah P7:

- Loop frame kamera hanya menitipkan pekerjaan: crop badan yang SUDAH disalin
  (bukan frame utuh) plus data track saat itu. `submit` tidak pernah memblok;
  antrean penuh = ditolak seketika, kamera mencoba lagi nanti.
- Satu worker untuk semua kamera, karena ada satu GPU. Bedanya dengan worker
  wajah: crop dari beberapa kamera digabung jadi SATU batch (maks
  `max_batch`), karena OSNet murah per gambar tetapi mahal per panggilan.
- Pekerjaan yang terlalu lama mengantre dibuang tanpa diproses. Embedding dari
  crop dua detik lalu tetap benar orangnya, tetapi waktunya (`at`) dipakai
  aturan cannot-link dan waktu tempuh, jadi lebih baik tidak ada daripada basi.

Worker tidak memegang keadaan ReID apa pun: hasilnya diserahkan ke callback
`deliver(job, embedding_or_None)` (koordinator, `reid_coordinator.py`), yang
menerapkannya ke inti `PendingIdentities` di bawah kuncinya sendiri.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger("engine.pipeline.reid_worker")

Embed = Callable[[List[np.ndarray]], np.ndarray]


@dataclass(frozen=True)
class ReidJob:
    camera_id: str
    track_id: int
    track_uuid: str
    at: float                       # detik epoch UTC saat crop diambil
    crop: np.ndarray                # BGR, salinan milik job ini
    face_person_id: Optional[str]   # hanya identitas dari WAJAH di track ini
    zone: Optional[str]
    queued_at: float


Deliver = Callable[[ReidJob, Optional[np.ndarray]], None]


@dataclass
class ReidWorkerMetrics:
    submitted: int = 0
    rejected_full: int = 0
    processed: int = 0
    batches: int = 0
    dropped_stale: int = 0
    failed: int = 0
    busy_seconds: float = 0.0

    def as_dict(self, depth: int) -> Dict[str, float]:
        return {
            "queue_depth": float(depth),
            "submitted": float(self.submitted),
            "rejected_full": float(self.rejected_full),
            "processed": float(self.processed),
            "batches": float(self.batches),
            "dropped_stale": float(self.dropped_stale),
            "failed": float(self.failed),
            "avg_batch_ms": round(1000.0 * self.busy_seconds / max(1, self.batches), 1),
        }


class ReidWorker:
    def __init__(self, embed: Embed, deliver: Deliver, max_queue: int = 16,
                 max_batch: int = 8, max_age_seconds: float = 1.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if max_queue < 1 or max_batch < 1:
            raise ValueError("max_queue dan max_batch minimal 1")
        self._embed = embed
        self._deliver = deliver
        self._max_batch = int(max_batch)
        self._max_age = float(max_age_seconds)
        self._clock = clock
        self._jobs: "queue.Queue[Optional[ReidJob]]" = queue.Queue(maxsize=int(max_queue))
        self._lock = threading.Lock()
        self.metrics = ReidWorkerMetrics()
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()

    # -- siklus hidup -------------------------------------------------------

    def start(self) -> "ReidWorker":
        if self._thread is None:
            self._stopped.clear()
            self._thread = threading.Thread(target=self._run, name="reid-worker", daemon=True)
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
        # Sisa antrean dijawab None supaya kamera tidak menunggu selamanya.
        for job in self._drain_nowait(self._jobs.qsize() + 1):
            self._safe_deliver(job, None)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- dipanggil thread kamera --------------------------------------------

    def submit(self, camera_id: str, track_id: int, track_uuid: str, at: float,
               crop: np.ndarray, face_person_id: Optional[str] = None,
               zone: Optional[str] = None) -> bool:
        """Tidak pernah memblok. False = antrean penuh (atau worker berhenti)."""
        if self._stopped.is_set():
            return False
        job = ReidJob(camera_id, int(track_id), track_uuid, float(at), crop,
                      face_person_id, zone, self._clock())
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

    def _drain_nowait(self, limit: int) -> List[ReidJob]:
        out: List[ReidJob] = []
        while len(out) < limit:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None:
                out.append(job)
        return out

    def _run(self) -> None:
        while not self._stopped.is_set():
            first = self._jobs.get()
            if first is None:
                break
            batch = [first] + self._drain_nowait(self._max_batch - 1)
            self.process(batch)

    def process(self, batch: List[ReidJob]) -> None:
        """Satu putaran worker. Publik supaya tes bisa memanggilnya tanpa thread."""
        now = self._clock()
        fresh: List[ReidJob] = []
        for job in batch:
            if now - job.queued_at > self._max_age:
                with self._lock:
                    self.metrics.dropped_stale += 1
                self._safe_deliver(job, None)
            else:
                fresh.append(job)
        if not fresh:
            return
        started = self._clock()
        vectors: Optional[np.ndarray] = None
        try:
            vectors = np.asarray(self._embed([job.crop for job in fresh]), dtype=np.float32)
            if vectors.shape[0] != len(fresh):
                raise ValueError(f"embedder mengembalikan {vectors.shape[0]} baris untuk {len(fresh)} crop")
        except Exception:  # noqa: BLE001 -- satu batch rusak tidak boleh mematikan worker
            logger.exception("embedding ReID gagal untuk %d crop", len(fresh))
            vectors = None
            with self._lock:
                self.metrics.failed += len(fresh)
        with self._lock:
            self.metrics.batches += 1
            self.metrics.processed += len(fresh)
            self.metrics.busy_seconds += self._clock() - started
        for index, job in enumerate(fresh):
            self._safe_deliver(job, None if vectors is None else vectors[index])

    def _safe_deliver(self, job: ReidJob, vector: Optional[np.ndarray]) -> None:
        try:
            self._deliver(job, vector)
        except Exception:  # noqa: BLE001
            logger.exception("callback hasil ReID gagal untuk %s", job.track_uuid)
