# engine/service/engine_service.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..vision_core.contracts.result import EngineResult
from ..vision_core.pipeline.engine import VisionEngine


@dataclass(frozen=True)
class EngineStatus:
    running: bool
    frame_count: int


class EngineService:
    """
    Public backend-facing facade for the vision engine.

    This class contains no vision-processing logic.
    It delegates runtime operations to VisionEngine.
    """

    def __init__(self, engine: VisionEngine) -> None:
        self._engine = engine

    def start(self) -> None:
        """Starts the vision engine."""
        self._engine.start()

    def stop(self) -> None:
        """Stops the vision engine."""
        self._engine.stop()

    def process_frame(self) -> Optional[EngineResult]:
        """
        Processes one frame and returns a backend-facing result.

        Returns None when no frame is available.
        """
        return self._engine.process_frame()

    def get_status(self) -> EngineStatus:
        """Returns the current engine status."""
        return EngineStatus(
            running=self._engine.is_running,
            frame_count=self._engine.metrics.total_frames,
        )