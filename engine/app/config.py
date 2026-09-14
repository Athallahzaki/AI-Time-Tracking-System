from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from ..vision_core.pipeline.config import VisionCoreConfig, resolve_engine_path
from ..plugins.face_recognizer.pipeline.config import FaceRecognizerConfig


@dataclass
class AttendanceConfig:
    """Business logic configuration for time tracking and room presence."""
    min_present_seconds: float = 60.0       # PASSING -> CONFIRMED threshold
    warning_minutes: float = 25.0           # CONFIRMED -> WARNING threshold
    max_session_minutes: float = 30.0       # WARNING -> LIMIT threshold
    max_missing_seconds: float = 10.0       # Session closure threshold after person departs


@dataclass
class VisualizerConfig:
    """Configuration for OpenCV HUD and visualization output."""
    enabled: bool = True
    window_name: str = "AI Vision Engine - Real-Time Tracking"
    draw_landmarks: bool = False
    draw_velocity: bool = True
    draw_history: bool = True
    show_metrics_overlay: bool = True
    window_scale: float = 1.0


@dataclass
class AppConfig:
    """Composite configuration for the entire vision engine application."""
    core: VisionCoreConfig = field(default_factory=VisionCoreConfig)
    face_recognizer: FaceRecognizerConfig = field(default_factory=FaceRecognizerConfig)
    attendance: AttendanceConfig = field(default_factory=AttendanceConfig)
    visualizer: VisualizerConfig = field(default_factory=VisualizerConfig)

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> AppConfig:
        """Loads configuration from YAML file with automatic path resolution."""
        resolved_config_path = resolve_engine_path(path)
        config_path = Path(resolved_config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path} (resolved: {config_path})")

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        core_dict = raw.get("core", {})
        face_dict = raw.get("face_recognizer", {})
        att_dict = raw.get("attendance", {})
        vis_dict = raw.get("visualizer", {})

        model_path = resolve_engine_path(core_dict.get("model_path", "engine/models/yolo/yolo11s.pt"))
        detector_model = resolve_engine_path(face_dict.get("detector_model_path", "engine/models/detector/scrfd_10g_bnkps.onnx"))
        embedder_model = resolve_engine_path(face_dict.get("embedder_model_path", "engine/models/embedder/glintr100.onnx"))
        emp_dir = resolve_engine_path(face_dict.get("employees_dir", "engine/data/employees"))
        emb_dir = resolve_engine_path(face_dict.get("embeddings_dir", "engine/data/embeddings"))

        return cls(
            core=VisionCoreConfig(
                source_uri=str(core_dict.get("source_uri", "0")),
                source_type=str(core_dict.get("source_type", "opencv")),
                model_path=model_path,
                detection_interval=int(core_dict.get("detection_interval", 1)),
                device=core_dict.get("device", "auto"),
                target_fps=core_dict.get("target_fps"),
                enable_profiling=bool(core_dict.get("enable_profiling", True)),
                auto_warmup=bool(core_dict.get("auto_warmup", True)),
            ),
            face_recognizer=FaceRecognizerConfig(
                detector_model_path=detector_model,
                embedder_model_path=embedder_model,
                employees_dir=emp_dir,
                embeddings_dir=emb_dir,
                detector_confidence_threshold=float(face_dict.get("detector_confidence_threshold", 0.50)),
                similarity_threshold=float(face_dict.get("similarity_threshold", 0.37)),
                cache_ttl_seconds=float(face_dict.get("cache_ttl_seconds", 60.0)),
                min_confirmations=int(face_dict.get("min_confirmations", 2)),
                unknown_retry_interval_sec=float(face_dict.get("unknown_retry_interval_sec", 1.0)),
                max_unknown_retries=int(face_dict.get("max_unknown_retries", 5)),
            ),
            attendance=AttendanceConfig(
                min_present_seconds=float(att_dict.get("min_present_seconds", 60.0)),
                warning_minutes=float(att_dict.get("warning_minutes", 25.0)),
                max_session_minutes=float(att_dict.get("max_session_minutes", 30.0)),
                max_missing_seconds=float(att_dict.get("max_missing_seconds", 10.0)),
            ),
            visualizer=VisualizerConfig(
                enabled=bool(vis_dict.get("enabled", True)),
                window_name=str(vis_dict.get("window_name", "AI Vision Engine - Real-Time Tracking")),
                draw_velocity=bool(vis_dict.get("draw_velocity", True)),
                draw_history=bool(vis_dict.get("draw_history", True)),
                show_metrics_overlay=bool(vis_dict.get("show_metrics_overlay", True)),
            ),
        )
