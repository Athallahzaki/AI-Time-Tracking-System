"""
The engine as a running process (integration, M3).

`engine/tools/run.py` runs one camera through the pipeline and prints a summary.
`engine/bench/` measures it. Neither speaks the protocol, so until now the only
thing the backend could connect to was `fake_engine` — which is what it is for,
and also why nobody noticed that the real engine had never once been asked to
produce a `presence.interval` over a socket.

    python -m engine.runtime --tcp 127.0.0.1:8765

Then the backend connects as usual and sends `set_cameras`. Nothing starts
before that message arrives: cameras are the backend's to declare (§2.2), and an
engine that opened streams from its own config file would be a second source of
truth for what the rooms are.
"""

from .camera import CameraSpec, CameraStats, CameraSupervisor
from .service import EngineRuntime, RuntimeOptions

__all__ = [
    "CameraSpec",
    "CameraStats",
    "CameraSupervisor",
    "EngineRuntime",
    "RuntimeOptions",
]
