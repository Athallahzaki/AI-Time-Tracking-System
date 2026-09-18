from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union


def resolve_engine_path(raw_path: Union[str, Path]) -> str:
    """
    Robustly resolves a relative file or directory path within the project.
    Checks:
      1. Direct path from current working directory.
      2. Relative to the 'engine' root directory.
      3. Relative to workspace root.
    """
    p = Path(raw_path)
    if p.exists():
        return str(p.resolve())

    # Check relative to engine directory
    engine_root = Path(__file__).resolve().parents[1]  # engine/
    candidate1 = engine_root / p
    if candidate1.exists():
        return str(candidate1.resolve())

    # Check if p starts with 'engine/' when called from inside engine/
    if str(p).startswith("engine/") or str(p).startswith("engine\\"):
        sub_p = Path(*p.parts[1:])
        candidate2 = engine_root / sub_p
        if candidate2.exists():
            return str(candidate2.resolve())

    # Check relative to workspace root (parent of engine)
    workspace_root = engine_root.parent
    candidate3 = workspace_root / p
    if candidate3.exists():
        return str(candidate3.resolve())

    return str(p)


@dataclass
class VisionCoreConfig:
    """Configuration parameters for the Vision Core engine."""
    source_uri: str = "0"
    source_type: str = "opencv"                   # opencv, video_file, mock
    model_path: str = "LibreDFINEs.pt"           # D-FINE small model — auto-downloaded on first run (MIT license)
    detection_interval: int = 1                   # Run object detector every N frames (1 = every frame)
    device: Union[str, int] = "auto"              # "auto", 0, "cuda", "cpu"
    target_fps: Optional[float] = None
    enable_profiling: bool = True
    auto_warmup: bool = True
