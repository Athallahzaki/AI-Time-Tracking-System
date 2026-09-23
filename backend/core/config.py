from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import os
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


class CameraConfigError(ValueError):
    """cameras.yaml is missing or invalid. Raised, never swallowed.

    The old loader returned `{}` on a parse error; the next reconnect then sent
    `set_cameras: []` and the declarative engine closed every camera.
    """


@dataclass
class CameraConfig:
    id: str
    code: str
    name: str
    source_uri: str
    stream_url: str = ""
    enabled_by_default: bool = False
    fps: float = 30.0
    # [x1, y1, x2, y2] normalised 0-1. Sent to the engine in set_cameras.
    door_region: Optional[List[float]] = None
    # Extra sources an operator may switch to through the API. The configured
    # `source_uri` is always allowed; nothing else is.
    allowed_sources: List[str] = field(default_factory=list)


def _door_region(camera_id: str, value: object) -> Optional[List[float]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise CameraConfigError(f"camera {camera_id}: door_region must be [x1, y1, x2, y2]")
    region = [float(v) for v in value]
    if not all(0.0 <= v <= 1.0 for v in region) or region[0] >= region[2] or region[1] >= region[3]:
        raise CameraConfigError(
            f"camera {camera_id}: door_region must be normalised 0-1 with x1<x2, y1<y2"
        )
    return region


def load_cameras_from_yaml(yaml_path: Path) -> Dict[str, CameraConfig]:
    """Load cameras.yaml. Raises CameraConfigError on any problem."""
    if not yaml_path.exists():
        raise CameraConfigError(f"Cameras config file not found: {yaml_path}")
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise CameraConfigError(f"Cannot parse {yaml_path}: {exc}") from exc

    cameras_data = data.get("cameras")
    if not isinstance(cameras_data, list) or not cameras_data:
        raise CameraConfigError(f"{yaml_path}: `cameras` must be a non-empty list")

    result: Dict[str, CameraConfig] = {}
    for item in cameras_data:
        if not isinstance(item, dict) or not item.get("id"):
            raise CameraConfigError(f"{yaml_path}: every camera needs an `id`")
        cam_id = str(item["id"])
        if cam_id in result:
            raise CameraConfigError(f"{yaml_path}: duplicate camera id {cam_id!r}")
        source_uri = item.get("source_uri")
        if not source_uri:
            raise CameraConfigError(f"camera {cam_id}: `source_uri` is required")
        allowed = item.get("allowed_sources") or []
        if not isinstance(allowed, list):
            raise CameraConfigError(f"camera {cam_id}: allowed_sources must be a list")
        result[cam_id] = CameraConfig(
            id=cam_id,
            code=str(item.get("code", cam_id.upper())),
            name=str(item.get("name", f"Camera {cam_id}")),
            source_uri=str(source_uri),
            stream_url=str(item.get("stream_url", "")),
            enabled_by_default=bool(item.get("enabled_by_default", item.get("enabled", False))),
            fps=float(item.get("fps", 30.0)),
            door_region=_door_region(cam_id, item.get("door_region")),
            allowed_sources=[str(uri) for uri in allowed],
        )
    return result


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    engine_config_path: Path = PROJECT_ROOT / "engine" / "config" / "default_config.yaml"
    cameras_yaml_path: Path = field(default_factory=lambda: Path(
        os.getenv("CAMERAS_CONFIG", str(PROJECT_ROOT / "backend" / "configs" / "cameras.yaml"))
    ))
    policy_yaml_path: Path = field(default_factory=lambda: Path(
        os.getenv("POLICY_CONFIG", str(PROJECT_ROOT / "backend" / "configs" / "policy.yaml"))
    ))
    headless: bool = True
    no_face_recognition: bool = False
    device: Optional[str] = None
    engine_host: str = field(default_factory=lambda: os.getenv("ENGINE_HOST", "127.0.0.1"))
    engine_port: int = field(default_factory=lambda: int(os.getenv("ENGINE_PORT", "8765")))
    engine_reconnect_seconds: float = field(
        default_factory=lambda: float(os.getenv("ENGINE_RECONNECT_SECONDS", "2"))
    )
    cors_origins: List[str] = field(default_factory=lambda: [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ])

    _cameras_cache: Optional[Dict[str, CameraConfig]] = field(default=None, repr=False)

    @property
    def cameras(self) -> Dict[str, CameraConfig]:
        """Parsed once; a broken file fails loudly instead of meaning "no cameras"."""
        if self._cameras_cache is None:
            self._cameras_cache = load_cameras_from_yaml(self.cameras_yaml_path)
        return self._cameras_cache

    def reload_cameras(self) -> Dict[str, CameraConfig]:
        """Re-read cameras.yaml. On error the previous (valid) set is kept."""
        self._cameras_cache = load_cameras_from_yaml(self.cameras_yaml_path)
        return self._cameras_cache


settings = Settings()
