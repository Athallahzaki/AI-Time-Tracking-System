from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple, Union
import cv2
import numpy as np

from .base import BaseFrameSource
from ..contracts.frame import Frame, FrameMetadata

logger = logging.getLogger(__name__)


class OpenCVStreamSource(BaseFrameSource):
    """
    Threaded, buffer-free frame source for live RTSP streams, IP cameras, and webcams.
    Runs a lightweight background thread that continually grabs the latest frame to prevent
    network queue lag and frame drift in real-time inference pipelines.
    Includes auto-reconnect logic with configurable retry intervals.
    """

    def __init__(
        self,
        uri: Union[str, int],
        source_id: str = "rtsp_stream",
        reconnect_interval_sec: float = 2.0,
        max_reconnect_attempts: int = 0,  # 0 means infinite retries
        target_fps: Optional[float] = None,
    ) -> None:
        super().__init__(source_id=source_id)
        self._uri = uri
        self._reconnect_interval = reconnect_interval_sec
        self._max_reconnect_attempts = max_reconnect_attempts
        self._target_fps = target_fps

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._latest_frame: Optional[np.ndarray] = None
        self._latest_timestamp: float = 0.0
        self._frame_id = 0
        self._measured_fps: float = 30.0
        self._width: int = 0
        self._height: int = 0

    def start(self) -> None:
        if self._is_running:
            return

        self._stop_event.clear()
        self._is_running = True
        self._open_capture()

        self._thread = threading.Thread(
            target=self._capture_worker,
            name=f"CaptureWorker-{self._source_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[{self._source_id}] Stream source started for URI: {self._uri}")

    def _open_capture(self) -> bool:
        """Opens or reopens the cv2.VideoCapture device."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        logger.info(f"[{self._source_id}] Connecting to video source: {self._uri}...")
        cap = cv2.VideoCapture(self._uri)

        if not cap.isOpened():
            logger.warning(f"[{self._source_id}] Failed to open stream: {self._uri}")
            return False

        # Query video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps and fps > 0:
            self._measured_fps = fps
        elif self._target_fps:
            self._measured_fps = self._target_fps

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if w > 0 and h > 0:
            self._width = w
            self._height = h

        self._cap = cap
        logger.info(
            f"[{self._source_id}] Connected. Resolution: {self._width}x{self._height} @ {self._measured_fps:.1f} FPS"
        )
        return True

    def _capture_worker(self) -> None:
        """Dedicated background loop to fetch frames at wire speed, discarding stale buffers."""
        reconnect_attempts = 0

        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                if 0 < self._max_reconnect_attempts <= reconnect_attempts:
                    logger.error(f"[{self._source_id}] Exceeded max reconnect attempts ({self._max_reconnect_attempts}). Stopping.")
                    break

                logger.info(f"[{self._source_id}] Attempting reconnect in {self._reconnect_interval}s (attempt {reconnect_attempts + 1})...")
                time.sleep(self._reconnect_interval)
                if self._stop_event.is_set():
                    break

                if self._open_capture():
                    reconnect_attempts = 0
                else:
                    reconnect_attempts += 1
                continue

            # Read frame from stream
            ret, frame = self._cap.read()
            now = time.time()

            if not ret or frame is None:
                logger.warning(f"[{self._source_id}] Stream read returned empty/error. Triggering reconnect...")
                if self._cap is not None:
                    self._cap.release()
                    self._cap = None
                continue

            with self._lock:
                self._latest_frame = frame
                self._latest_timestamp = now
                self._frame_id += 1
                self._width = frame.shape[1]
                self._height = frame.shape[0]

        logger.info(f"[{self._source_id}] Capture worker thread terminated.")

    def read(self) -> Optional[Frame]:
        """Returns the most recent frame captured by the background worker."""
        if not self._is_running:
            return None

        with self._lock:
            if self._latest_frame is None:
                return None
            img = self._latest_frame
            fid = self._frame_id
            ts = self._latest_timestamp

        metadata = FrameMetadata(
            frame_id=fid,
            timestamp=ts,
            source_id=self._source_id,
            fps=self._measured_fps,
            width=self._width,
            height=self._height,
        )
        return Frame(image=img, metadata=metadata)

    def stop(self) -> None:
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as e:
                logger.warning(f"Error releasing VideoCapture: {e}")
            self._cap = None

        logger.info(f"[{self._source_id}] Stream source stopped.")

    @property
    def fps(self) -> float:
        return self._measured_fps

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self._width, self._height)
