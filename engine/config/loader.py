"""
Loading and validating engine configuration.

Beyond parsing YAML, this module does one thing the old loader did not: it
refuses configuration that would let the engine lie. Two guards.

**The policy guard.** If a config file still carries the dead `attendance:`
block — break hours, session limits, warning thresholds — loading fails with a
message naming the keys. contracts/tools/policy_grep.py catches these in CI;
this catches them at runtime, for the config files nobody remembered to commit.

**Strict mode.** ARCHITECTURE.md §9 item 9 describes the worst failure mode this
system has: a component swallows an exception, degrades to something harmless-
looking, and the logs stay clean while the data goes wrong. In B's territory
there are two such swallows, and strict_mode turns both into startup failures
rather than surprises discovered in a benchmark report.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .schema import DetectorConfig, EngineConfig, TrackerConfig, resolve_engine_path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "default_config.yaml"

# Keys that must never appear in an engine config file. These are company rules,
# and they belong to backend/policy/. See ARCHITECTURE.md §16.
FORBIDDEN_SECTIONS = ("attendance", "policy", "break", "shift", "penalty")
FORBIDDEN_KEYS = (
    "break_start_hour",
    "break_end_hour",
    "warning_minutes",
    "max_session_minutes",
    "total_facilities",
)


class PolicyLeakError(ValueError):
    """Raised when an engine config file carries a company policy constant."""


def _assert_no_policy(raw: Dict[str, Any]) -> None:
    found = [s for s in FORBIDDEN_SECTIONS if s in raw]
    for section in raw.values():
        if isinstance(section, dict):
            found.extend(k for k in FORBIDDEN_KEYS if k in section)

    if found:
        raise PolicyLeakError(
            "Engine config contains company policy, which belongs to "
            "backend/policy/ (ARCHITECTURE.md §16). Offending keys: "
            + ", ".join(sorted(set(found)))
            + ". The engine may only hold perceptual constants."
        )


def load_config(path: Optional[Union[str, Path]] = None) -> EngineConfig:
    """Reads a YAML config file into an EngineConfig, or the defaults if absent."""
    import yaml

    config_path = Path(resolve_engine_path(path)) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config root must be a mapping, got {type(raw).__name__}.")

    _assert_no_policy(raw)

    core = raw.get("core", {}) or {}
    det = raw.get("detector", {}) or {}
    trk = raw.get("tracker", {}) or {}

    return EngineConfig(
        source_uri=str(core.get("source_uri", "0")),
        source_type=str(core.get("source_type", "opencv")),
        detection_interval=int(core.get("detection_interval", 1)),
        target_fps=core.get("target_fps"),
        auto_warmup=bool(core.get("auto_warmup", True)),
        strict_mode=bool(core.get("strict_mode", True)),
        detector=DetectorConfig(
            model_path=str(det.get("model_path", "LibreDFINEs.pt")),
            confidence_threshold=float(det.get("confidence_threshold", 0.50)),
            iou_threshold=float(det.get("iou_threshold", 0.45)),
            image_size=int(det.get("image_size", 640)),
            device=det.get("device", "auto"),
            half=bool(det.get("half", False)),
        ),
        tracker=TrackerConfig(
            backend=str(trk.get("backend", "bytetrack")),
            track_threshold=float(trk.get("track_threshold", 0.45)),
            match_threshold=float(trk.get("match_threshold", 0.8)),
            track_buffer_seconds=float(trk.get("track_buffer_seconds", 1.0)),
        ),
    )
