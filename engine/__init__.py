"""
Production Real-Time AI Vision Engine
- vision_core: Generic, reusable detection and tracking engine.
- plugins.face_recognizer: Decoupled face recognition extension.
- app: Business logic, attendance tracking, and HUD visualization.
"""

from . import vision_core
from . import plugins
from . import app

__all__ = ["vision_core", "plugins", "app"]
