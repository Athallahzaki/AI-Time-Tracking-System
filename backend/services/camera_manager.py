from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Dict, List, Optional

from backend.core.config import CameraConfig, settings
from backend.services.engine_worker import EngineWorker

logger = logging.getLogger(__name__)


class CameraManager:
    """Manages multi-camera EngineWorker instances and routing."""

    def __init__(self) -> None:
        self._cameras: Dict[str, CameraConfig] = dict(settings.cameras)
        self._workers: Dict[str, EngineWorker] = {}
        self._lock = threading.Lock()

    def start_default_cameras(self) -> None:
        for cam_id, cfg in self._cameras.items():
            if cfg.enabled_by_default:
                self.start_worker(cam_id)

    def start_worker(self, camera_id: str, source_uri: Optional[str] = None) -> bool:
        with self._lock:
            if camera_id not in self._cameras:
                logger.warning(f"Camera ID '{camera_id}' not found in configuration.")
                return False

            cfg = self._cameras[camera_id]
            actual_source = source_uri or cfg.source_uri

            # Stop existing if active
            if camera_id in self._workers:
                worker = self._workers[camera_id]
                if worker.is_active:
                    return True  # already running
                worker.stop()

            worker = EngineWorker(
                camera_id=camera_id,
                source_uri=actual_source,
                config_path=str(settings.engine_config_path),
                device=settings.device,
                headless=settings.headless,
                no_face_recognition=settings.no_face_recognition,
            )
            self._workers[camera_id] = worker
            worker.start()
            logger.info(f"Started camera worker [{camera_id}] with source: {actual_source}")
            return True

    def stop_worker(self, camera_id: str) -> bool:
        with self._lock:
            if camera_id in self._workers:
                worker = self._workers.pop(camera_id)
                worker.stop()
                logger.info(f"Stopped camera worker [{camera_id}]")
                return True
            return False

    def switch_source(self, camera_id: str, new_source_uri: str) -> bool:
        with self._lock:
            if camera_id not in self._cameras:
                return False
            self._cameras[camera_id].source_uri = new_source_uri

        # Restart worker with new source
        self.stop_worker(camera_id)
        return self.start_worker(camera_id, new_source_uri)

    def get_worker(self, camera_id: str) -> Optional[EngineWorker]:
        with self._lock:
            return self._workers.get(camera_id)

    def get_camera_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            result = []
            for cam_id, cfg in self._cameras.items():
                worker = self._workers.get(cam_id)
                is_online = worker is not None and worker.is_active
                latest_data = worker.get_latest_data() if worker else None

                people_count = len(latest_data.get("people", [])) if latest_data else 0
                fps_val = latest_data.get("fps", 0.0) if latest_data else 0.0

                result.append({
                    "id": cfg.id,
                    "code": cfg.code,
                    "name": cfg.name,
                    "src": f"/videos/{cfg.id}.mp4" if "public" in cfg.source_uri else cfg.source_uri,
                    "source_uri": cfg.source_uri,
                    "fps": str(fps_val) if fps_val > 0 else f"{cfg.fps:.1f}",
                    "latency": "18ms" if is_online else "—",
                    "model": cfg.model,
                    "fov": cfg.fov,
                    "streamStatus": "Online & Streaming" if is_online else "Standby / Offline",
                    "is_running": is_online,
                    "active_people": people_count,
                })
            return result

    def get_active_workers(self) -> List[EngineWorker]:
        with self._lock:
            return [w for w in self._workers.values() if w.is_active]

    def shutdown(self) -> None:
        logger.info("Shutting down CameraManager...")
        with self._lock:
            for worker in self._workers.values():
                worker.stop()
            self._workers.clear()


# Global camera manager instance
camera_manager = CameraManager()
