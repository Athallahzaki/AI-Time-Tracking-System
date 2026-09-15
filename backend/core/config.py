import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CameraConfig:
    id: str
    code: str
    name: str
    source_uri: str
    fov: str = "114° N-W Angle"
    model: str = "YOLOv8x-Pose + ActionNet v2"
    enabled_by_default: bool = False
    fps: float = 30.0


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    engine_config_path: Path = PROJECT_ROOT / "engine" / "configs" / "default_config.yaml"
    headless: bool = True
    no_face_recognition: bool = False
    device: Optional[str] = None  # None for auto, 'cuda', 'cpu', '0'
    cors_origins: List[str] = field(default_factory=lambda: [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ])
    cameras: Dict[str, CameraConfig] = field(default_factory=lambda: {
        "cam-01": CameraConfig(
            id="cam-01",
            code="CAM-01",
            name="Entertainment Room",
            source_uri=str(PROJECT_ROOT / "frontend" / "public" / "videos" / "video2.mp4"),
            fov="114° N-W Angle",
            model="YOLOv8x-Pose + ActionNet v2",
            enabled_by_default=True,
        ),
        "cam-02": CameraConfig(
            id="cam-02",
            code="CAM-02",
            name="Carport Area",
            source_uri=str(PROJECT_ROOT / "frontend" / "public" / "videos" / "video1.mp4"),
            fov="98° N Angle",
            model="YOLOv8x-Pose + ActionNet v2",
            enabled_by_default=False,
        ),
        "cam-03": CameraConfig(
            id="cam-03",
            code="CAM-03",
            name="Lobby Entrance",
            source_uri=str(PROJECT_ROOT / "frontend" / "public" / "videos" / "video3.mp4"),
            fov="120° Wide Angle",
            model="YOLOv8x-Pose + ActionNet v2",
            enabled_by_default=False,
        ),
        "cam-04": CameraConfig(
            id="cam-04",
            code="CAM-04",
            name="Rooftop Terrace (Smoking Area)",
            source_uri=str(PROJECT_ROOT / "frontend" / "public" / "videos" / "video4.mp4"),
            fov="90° N-E Angle",
            model="YOLOv8x-Pose + ActionNet v2",
            enabled_by_default=False,
        ),
    })


settings = Settings()
