from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from ....vision_core.pipeline.config import resolve_engine_path


@dataclass
class FaceRecognizerConfig:
    """Configuration for Face Recognition Plugin."""
    detector_model_path: str = "engine/models/detector/scrfd_10g_bnkps.onnx"
    embedder_model_path: str = "engine/models/embedder/glintr100.onnx"
    employees_dir: str = "engine/data/employees"
    embeddings_dir: str = "engine/data/embeddings"

    detector_input_size: Tuple[int, int] = (640, 640)
    detector_confidence_threshold: float = 0.50
    alignment_output_size: Tuple[int, int] = (112, 112)
    embedding_dimension: int = 512
    similarity_threshold: float = 0.37

    cache_ttl_seconds: float = 60.0
    min_confirmations: int = 2
    unknown_retry_interval_sec: float = 1.0
    max_unknown_retries: int = 5
    backoff_retry_interval_sec: float = 5.0
    min_person_crop_width: int = 40
    min_person_crop_height: int = 80

    providers: List[str] = field(default_factory=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])

    def __post_init__(self) -> None:
        self.detector_model_path = resolve_engine_path(self.detector_model_path)
        self.embedder_model_path = resolve_engine_path(self.embedder_model_path)
        self.employees_dir = resolve_engine_path(self.employees_dir)
        self.embeddings_dir = resolve_engine_path(self.embeddings_dir)
