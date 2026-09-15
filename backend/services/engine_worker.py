from __future__ import annotations

import argparse
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2

from backend.core.state import system_state
from engine.app.main import build_app
from engine.app.attendance_tracker import (
    PersonConfirmedEvent,
    PersonDepartedEvent,
    PersonEnteredEvent,
    SessionLimitReachedEvent,
    SessionWarningEvent,
)
from engine.plugins.face_recognizer import (
    FaceRecognizedEvent,
    IdentityChangedEvent,
    PersonUnknownEvent,
    PluginEvent,
)

logger = logging.getLogger(__name__)


class EngineWorker:
    """Encapsulates a running VisionEngine instance for a specific camera channel."""

    def __init__(
        self,
        camera_id: str,
        source_uri: str,
        config_path: str = "engine/configs/default_config.yaml",
        device: Optional[str] = None,
        headless: bool = True,
        no_face_recognition: bool = False,
    ) -> None:
        self.camera_id = camera_id
        self.source_uri = source_uri
        self.config_path = config_path
        self.device = device
        self.headless = headless
        self.no_face_recognition = no_face_recognition

        self.engine = None
        self.thread: Optional[threading.Thread] = None
        self.running = False

        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_data: Optional[Dict[str, Any]] = None
        self._fps: float = 0.0

    @property
    def is_active(self) -> bool:
        return self.running and (self.engine is not None and getattr(self.engine, "is_running", False))

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, name=f"EngineWorker-{self.camera_id}", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception as e:
                logger.warning(f"[{self.camera_id}] Error stopping engine: {e}")

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_latest_data(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._latest_data

    def subscribe(self) -> queue.Queue:
        client_queue: queue.Queue = queue.Queue(maxsize=3)
        with self._lock:
            self._clients.append(client_queue)
        return client_queue

    def unsubscribe(self, client_queue: queue.Queue) -> None:
        with self._lock:
            if client_queue in self._clients:
                self._clients.remove(client_queue)

    def _broadcast(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._latest_data = data
            for q in list(self._clients):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        q.put_nowait(data)
                    except queue.Full:
                        pass

    def _setup_event_hooks(self) -> None:
        if not self.engine:
            return

        # Find attendance tracker in engine listeners
        for listener in getattr(self.engine, "_listeners", []):
            listener_name = type(listener).__name__
            if listener_name == "AttendanceTracker":
                def _handle_attendance_event(event: Any) -> None:
                    event_type = type(event).__name__
                    payload = {
                        "camera_id": self.camera_id,
                        "track_id": getattr(event, "track_id", None),
                        "employee_id": getattr(event, "employee_id", None),
                    }
                    if isinstance(event, (PersonConfirmedEvent, PersonDepartedEvent)):
                        payload["duration_seconds"] = getattr(event, "duration_seconds", getattr(event, "total_session_seconds", 0.0))
                    elif isinstance(event, (SessionWarningEvent, SessionLimitReachedEvent)):
                        payload["duration_minutes"] = getattr(event, "duration_minutes", 0.0)

                    system_state.record_event(event_type, payload)

                listener.add_event_handler(_handle_attendance_event)

            elif listener_name == "FaceRecognizerPlugin":
                def _handle_face_event(event: PluginEvent) -> None:
                    event_type = type(event).__name__
                    payload = {
                        "camera_id": self.camera_id,
                        "track_id": getattr(event, "track_id", None),
                        "similarity": getattr(event, "similarity", 0.0),
                    }
                    if isinstance(event, FaceRecognizedEvent):
                        payload["employee_id"] = event.employee_id
                    elif isinstance(event, IdentityChangedEvent):
                        payload["old_identity"] = event.old_identity
                        payload["new_identity"] = event.new_identity

                    system_state.record_event(event_type, payload)

                listener.add_event_handler(_handle_face_event)

    def _run_loop(self) -> None:
        logger.info(f"[{self.camera_id}] Starting AI Vision Engine worker for source: {self.source_uri}")

        args = argparse.Namespace(
            config=self.config_path,
            source=self.source_uri,
            device=self.device,
            mock=False,
            no_face_recognition=self.no_face_recognition,
            headless=self.headless,
            max_frames=None,
        )

        try:
            self.engine = build_app(args)
            self._setup_event_hooks()
            self.engine.start()

            # Ensure video file sources loop continuously if applicable
            if hasattr(self.engine, "_source") and hasattr(self.engine._source, "_loop"):
                self.engine._source._loop = True

            logger.info(f"[{self.camera_id}] Engine pipeline online.")

            while self.running and self.engine.is_running:
                frame, tracks = self.engine.step()

                if frame is None:
                    # If stream ended and didn't auto-loop, pause briefly
                    time.sleep(0.01)
                    continue

                width = frame.width
                height = frame.height
                fps = getattr(self.engine.metrics, "fps", 30.0)
                self._fps = fps

                people = []
                tracking_ids = []

                for track in tracks:
                    attrs = getattr(track, "attributes", {}) or {}
                    presence_status = attrs.get("presence_status", "PASSING")
                    identity = attrs.get("identity")
                    similarity = float(attrs.get("similarity", 0.0))
                    session_elapsed = float(attrs.get("session_elapsed", track.dwell_time))

                    tracking_ids.append(int(track.track_id))

                    system_state.update_track(
                        camera_id=self.camera_id,
                        track_id=int(track.track_id),
                        identity=identity,
                        similarity=similarity,
                        presence_status=presence_status,
                        dwell_time=float(track.dwell_time),
                        session_elapsed=session_elapsed,
                    )

                    people.append({
                        "track_id": int(track.track_id),
                        "bbox": {
                            "x1": float(track.bbox.x1),
                            "y1": float(track.bbox.y1),
                            "x2": float(track.bbox.x2),
                            "y2": float(track.bbox.y2),
                        },
                        "confidence": float(track.confidence),
                        "state": track.state.value if hasattr(track.state, "value") else str(track.state),
                        "dwell_time": float(track.dwell_time),
                        "presence_status": presence_status,
                        "identity": identity,
                        "similarity": similarity,
                        "session_elapsed": session_elapsed,
                    })

                # Update camera activity status in global state
                system_state.update_camera_status(
                    camera_id=self.camera_id,
                    fps=fps,
                    people_count=len(people),
                    tracking_ids=tracking_ids,
                    stream_status="Online & Streaming",
                )

                # Capture JPEG snapshot if subscribers or MJPEG clients might need it
                try:
                    ret, jpeg_buf = cv2.imencode(".jpg", frame.image, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                    if ret:
                        with self._lock:
                            self._latest_jpeg = jpeg_buf.tobytes()
                except Exception as e:
                    logger.debug(f"[{self.camera_id}] Error encoding frame to JPEG: {e}")

                # Prepare and broadcast SSE detection payload
                data = {
                    "camera_id": self.camera_id,
                    "frame_id": frame.frame_id,
                    "width": width,
                    "height": height,
                    "fps": round(fps, 1),
                    "people": people,
                }
                self._broadcast(data)

        except Exception as e:
            logger.exception(f"[{self.camera_id}] EngineWorker fatal error: {e}")
        finally:
            if self.engine is not None:
                try:
                    self.engine.stop()
                except Exception:
                    pass
            self.running = False
            logger.info(f"[{self.camera_id}] EngineWorker stopped.")
