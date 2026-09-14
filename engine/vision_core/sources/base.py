from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from ..contracts.frame import Frame

logger = logging.getLogger(__name__)


class BaseFrameSource(ABC):
    """Base class providing common helper routines for frame sources."""

    def __init__(self, source_id: str = "default") -> None:
        self._source_id = source_id
        self._is_running = False
        self._frame_count = 0

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def read(self) -> Optional[Frame]:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    @abstractmethod
    def fps(self) -> float:
        pass

    @property
    @abstractmethod
    def resolution(self) -> Tuple[int, int]:
        pass

    def __enter__(self) -> BaseFrameSource:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()
