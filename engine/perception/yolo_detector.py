"""Compatibility name for the engine's LibreYOLO-backed detector.

Historically this module contained a separate YOLO adapter.  Keep the file and
import path intact for downstream users, but make the implementation a thin
alias so there is only one model/runtime path: LibreYOLO D-FINE.
"""

from __future__ import annotations

from .dfine_detector import DFINEDetector


class YOLODetector(DFINEDetector):
    """Backward-compatible alias for the LibreYOLO D-FINE detector."""


__all__ = ["YOLODetector", "DFINEDetector"]
