from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from backend.core.config import CameraConfig, settings
from backend.services.engine_worker import EngineWorker

logger = logging.getLogger(__name__)


def _load_break_config(config_path: str) -> tuple[int, int]:
    """Read break_start_hour / break_end_hour from the engine YAML. Defaults: 12, 13."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        att = raw.get("attendance", {})
        return int(att.get("break_start_hour", 12)), int(att.get("break_end_hour", 13))
    except Exception as e:
        logger.warning(f"Could not read break config from {config_path}: {e}. Using defaults (12–13).")
        return 12, 13


class CameraManager:
    """Manages multi-camera EngineWorker instances and routing."""

    def __init__(self) -> None:
        self._workers: Dict[str, EngineWorker] = {}
        self._lock = threading.Lock()

    def get_configured_cameras(self) -> Dict[str, CameraConfig]:
        return settings.cameras

    def start_default_cameras(self) -> None:
        cameras = self.get_configured_cameras()
        for cam_id, cfg in cameras.items():
            if cfg.enabled_by_default:
                self.start_worker(cam_id)

    def start_worker(self, camera_id: str, source_uri: Optional[str] = None) -> bool:
        with self._lock:
            cameras = self.get_configured_cameras()
            if camera_id not in cameras:
                logger.warning(f"Camera ID '{camera_id}' not found in configuration.")
                return False

            cfg = cameras[camera_id]
            actual_source = source_uri or cfg.source_uri

            if camera_id in self._workers:
                worker = self._workers[camera_id]
                if worker.is_active:
                    return True
                worker.stop()

            config_path = str(settings.engine_config_path)
            break_start, break_end = _load_break_config(config_path)

            worker = EngineWorker(
                camera_id=camera_id,
                source_uri=actual_source,
                config_path=config_path,
                device=settings.device,
                headless=settings.headless,
                no_face_recognition=settings.no_face_recognition,
                break_start_hour=break_start,
                break_end_hour=break_end,
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
        self.stop_worker(camera_id)
        return self.start_worker(camera_id, new_source_uri)

    def get_worker(self, camera_id: str) -> Optional[EngineWorker]:
        with self._lock:
            return self._workers.get(camera_id)

    def get_camera_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            cameras = self.get_configured_cameras()
            result = []
            for cam_id, cfg in cameras.items():
                worker = self._workers.get(cam_id)
                is_online = worker is not None and worker.is_active
                latest_data = worker.get_latest_data() if worker else None

                people_count = len(latest_data.get("people", [])) if latest_data else 0
                fps_val = latest_data.get("fps", 0.0) if latest_data else (cfg.fps if is_online else 0.0)

                result.append({
                    "id": cfg.id,
                    "code": cfg.code,
                    "name": cfg.name,
                    "source_uri": cfg.source_uri,
                    "stream_url": cfg.stream_url,
                    "fps": round(float(fps_val), 1),
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
