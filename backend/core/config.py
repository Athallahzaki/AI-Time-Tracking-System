from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    id: str
    code: str
    name: str
    source_uri: str
    stream_url: str = ""
    enabled_by_default: bool = False
    fps: float = 30.0


def load_cameras_from_yaml(yaml_path: Path) -> Dict[str, CameraConfig]:
    """Loads camera configurations dynamically from cameras.yaml."""
    if not yaml_path.exists():
        logger.warning(f"Cameras config file not found at {yaml_path}, using defaults.")
        return {
            "cam-01": CameraConfig(
                id="cam-01",
                code="CAM-01",
                name="Camera 1",
                source_uri="rtsp://localhost:8554/cam01",
                stream_url="http://localhost:8889/cam01/whep",
                enabled_by_default=True,
            )
        }

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        cameras_data = data.get("cameras", [])
        result = {}
        for item in cameras_data:
            cam_id = item.get("id")
            if not cam_id:
                continue
            result[cam_id] = CameraConfig(
                id=cam_id,
                code=item.get("code", cam_id.upper()),
                name=item.get("name", f"Camera {cam_id}"),
                source_uri=item.get("source_uri", f"rtsp://localhost:8554/{cam_id}"),
                stream_url=item.get("stream_url", ""),
                enabled_by_default=item.get("enabled_by_default", item.get("enabled", False)),
                fps=float(item.get("fps", 30.0)),
            )
        return result
    except Exception as e:
        logger.error(f"Failed to parse cameras.yaml: {e}")
        return {}


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    engine_config_path: Path = PROJECT_ROOT / "engine" / "configs" / "default_config.yaml"
    cameras_yaml_path: Path = PROJECT_ROOT / "backend" / "configs" / "cameras.yaml"
    headless: bool = True
    no_face_recognition: bool = False
    device: Optional[str] = None
    cors_origins: List[str] = field(default_factory=lambda: [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ])

    @property
    def cameras(self) -> Dict[str, CameraConfig]:
        return load_cameras_from_yaml(self.cameras_yaml_path)


settings = Settings()
