"""Satu detector untuk semua kamera, dengan batching opsional.

Sebelumnya setiap `CameraSupervisor` memuat D-FINE sendiri: 5 kamera = 5
salinan bobot di GPU, 5x waktu muat (±55 dtk masing-masing di GTX 1060), dan 5
thread yang memanggil model bergantian tanpa koordinasi. GPU memang hanya bisa
mengerjakan satu inferensi pada satu waktu, jadi kelimanya saling antre di
dalam driver tanpa ada yang bisa menggabungkan pekerjaan mereka.

Di sini:

- **Satu model, satu thread dispatcher.** Kamera mengirim frame dan menunggu
  hasilnya; hanya dispatcher yang memanggil model. Tidak ada dua thread yang
  menyentuh model bersamaan.
- **Batching.** Setelah permintaan pertama datang, dispatcher menunggu paling
  lama `batch_wait_ms` untuk permintaan kamera lain, lalu menjalankan semuanya
  dalam satu panggilan (`predict_images`). Bila hanya satu kamera yang aktif,
  ia tidak menunggu sama sekali.
- **Handle per kamera.** ByteTrack membaca `last_result` / `last_result_frame_id`
  dari detector. Kalau detector-nya dipakai bersama, nilai itu akan saling
  menimpa antar kamera. Jadi setiap kamera mendapat `DetectorHandle` dengan
  state miliknya sendiri; hanya model yang dibagi.

Detector yang tidak punya `predict_images` / `postprocess` (MockDetector) tidak
dibagi: `wrap_shared` mengembalikan None dan setiap kamera memuat miliknya.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..ports.detection import Detection
from ..ports.frame import Frame

logger = logging.getLogger("engine.perception.shared_detector")

STOP_POLL_SECONDS = 0.2
WAIT_TIMEOUT_SECONDS = 30.0   # satu inferensi tidak pernah selama ini; lebih = dispatcher mati


@dataclass
class _Request:
    image: Any
    confidence: Optional[float]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Optional[BaseException] = None


@dataclass
class SharedMetrics:
    batches: int = 0
    images: int = 0
    largest_batch: int = 0
    busy_seconds: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "batches": float(self.batches),
            "images": float(self.images),
            "mean_batch": round(self.images / self.batches, 2) if self.batches else 0.0,
            "largest_batch": float(self.largest_batch),
            "ms_per_image": round(1000.0 * self.busy_seconds / self.images, 1) if self.images else 0.0,
        }


class SharedDetector:
    def __init__(self, inner: Any, max_batch: int = 8, batch_wait_ms: float = 4.0) -> None:
        if not supports_sharing(inner):
            raise TypeError(f"{type(inner).__name__} tidak punya predict_images/postprocess")
        self.inner = inner
        self._max_batch = max(1, int(max_batch))
        self._wait = max(0.0, float(batch_wait_ms)) / 1000.0
        self._requests: "queue.Queue[_Request]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._warmed = False
        self._handles: Dict[str, "DetectorHandle"] = {}
        self.metrics = SharedMetrics()

    # -- siklus hidup -------------------------------------------------------

    def start(self) -> "SharedDetector":
        with self._lock:
            if self._thread is None:
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="detector-dispatch", daemon=True)
                self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
        # Yang masih menunggu dijawab dengan error, bukan dibiarkan menggantung.
        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                break
            request.error = RuntimeError("detector bersama sudah dihentikan")
            request.done.set()

    def warmup(self) -> None:
        with self._lock:
            if self._warmed:
                return
            self.inner.warmup()
            self._warmed = True

    def handle(self, camera_id: str) -> "DetectorHandle":
        with self._lock:
            handle = self._handles.get(camera_id)
            if handle is None:
                handle = DetectorHandle(self, camera_id)
                self._handles[camera_id] = handle
            return handle

    def release(self, camera_id: str) -> None:
        with self._lock:
            self._handles.pop(camera_id, None)

    @property
    def active_cameras(self) -> int:
        with self._lock:
            return len(self._handles)

    # -- dipanggil thread kamera -------------------------------------------

    def infer(self, image: Any, confidence: Optional[float] = None) -> Any:
        if self._thread is None:
            self.start()
        request = _Request(image, confidence)
        self._requests.put(request)
        if not request.done.wait(WAIT_TIMEOUT_SECONDS):
            raise RuntimeError("detector bersama tidak menjawab dalam %.0f dtk" % WAIT_TIMEOUT_SECONDS)
        if request.error is not None:
            raise request.error
        return request.result

    # -- thread dispatcher ---------------------------------------------------

    def _collect(self, first: _Request) -> List[_Request]:
        batch = [first]
        # Satu kamera: tidak ada yang perlu ditunggu.
        wait = self._wait if self.active_cameras > 1 else 0.0
        deadline = time.monotonic() + wait
        while len(batch) < self._max_batch:
            remaining = deadline - time.monotonic()
            try:
                batch.append(self._requests.get(timeout=remaining) if remaining > 0
                             else self._requests.get_nowait())
            except queue.Empty:
                break
        return batch

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._requests.get(timeout=STOP_POLL_SECONDS)
            except queue.Empty:
                continue
            batch = self._collect(first)
            # Kepercayaan berbeda (predict_raw ByteTrack) tidak boleh satu panggilan.
            groups: Dict[Optional[float], List[_Request]] = {}
            for request in batch:
                groups.setdefault(request.confidence, []).append(request)
            for confidence, requests in groups.items():
                self._execute(requests, confidence)

    def _execute(self, requests: List[_Request], confidence: Optional[float]) -> None:
        started = time.perf_counter()
        try:
            results = self.inner.predict_images([r.image for r in requests], confidence=confidence)
            if len(results) != len(requests):
                raise RuntimeError(f"predict_images mengembalikan {len(results)} hasil untuk {len(requests)} gambar")
            for result in results[:1]:
                self.inner.note_result(result)
        except BaseException as error:  # noqa: BLE001 -- dikembalikan ke kamera pemanggil
            for request in requests:
                request.error = error
                request.done.set()
            return
        elapsed = time.perf_counter() - started
        self.metrics.batches += 1
        self.metrics.images += len(requests)
        self.metrics.largest_batch = max(self.metrics.largest_batch, len(requests))
        self.metrics.busy_seconds += elapsed
        for request, result in zip(requests, results):
            request.result = result
            request.done.set()


class DetectorHandle:
    """Port detector untuk satu kamera di atas `SharedDetector`.

    Punya `last_result` sendiri, sehingga ByteTrack kamera A tidak pernah
    membaca hasil kamera B.
    """

    def __init__(self, shared: SharedDetector, camera_id: str) -> None:
        self._shared = shared
        self.camera_id = camera_id
        self._last_result: Any = None
        self._last_result_frame_id: Optional[int] = None
        self.last_spans: List[Any] = []

    def warmup(self) -> None:
        self._shared.warmup()

    def detect(self, frame: Frame) -> List[Detection]:
        image = frame.image
        t0 = time.perf_counter()
        result = self._shared.infer(image)
        t1 = time.perf_counter()
        self._remember(frame, result)
        detections = self._shared.inner.postprocess(frame, result)
        # Antre + pra-proses + inferensi di thread dispatcher, lalu pasca-proses di sini.
        self.last_spans = [("detector_shared_infer", t0, t1), ("detector_post", t1, time.perf_counter())]
        return detections

    def predict_raw(self, frame: Frame, confidence: Optional[float] = None) -> Any:
        result = self._shared.infer(frame.image, confidence=confidence)
        self._remember(frame, result)
        return result

    def _remember(self, frame: Frame, result: Any) -> None:
        self._last_result = result
        self._last_result_frame_id = frame.frame_id

    @property
    def last_result(self) -> Any:
        return self._last_result

    @property
    def last_result_frame_id(self) -> Optional[int]:
        return self._last_result_frame_id

    @property
    def class_names(self) -> Dict[int, str]:
        return self._shared.inner.class_names

    @property
    def device(self) -> Any:
        return getattr(self._shared.inner, "device", None)


def supports_sharing(detector: Any) -> bool:
    return all(hasattr(detector, name) for name in ("predict_images", "postprocess", "note_result", "warmup"))
