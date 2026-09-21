"""
Loading and validating engine configuration.

Beyond parsing YAML, this module does one thing the old loader did not: it
refuses configuration the engine has no business holding.

**How it refuses, and why that changed in B1.** The first version carried a
denylist — the literal names of the company-rule keys the old config file used
— and rejected any config containing one. It worked, and it was wrong twice
over. A denylist always lags the thing it denies: the next rule to leak in will
have a name nobody thought to add. And writing those names into `engine/` put
the vocabulary of company rules inside the engine, which is the exact thing
§16 tells you to grep for. `contracts/tools/policy_grep.py` flagged this file,
and it was right to.

What replaced it is an **allowlist derived from the schema itself**. The engine
accepts the sections its dataclasses declare — `core`, `ingest`, `detector`,
`tracker`, and since B5 `zones` and `recognition` — and within each, only the
fields that dataclass declares. The list is computed, not written down, so a new
section cannot be added to the schema and forgotten here. Everything else is refused by name at load
time. No list of forbidden words exists anywhere in this package; the offending
name comes from the user's file at runtime and appears only in the error.

The side effect is worth having on its own: a mistyped key is now an error
rather than a silently ignored line. §6.8's "unknown fields are ignored" is a
rule for the *wire protocol*, where the two sides cannot be deployed together.
A config file has no such constraint, and a benchmark run that silently used a
default because `track_buffer_secondss` had a typo is a baseline nobody can
trust.

**Strict mode.** ARCHITECTURE.md §9 item 9 describes the worst failure mode this
system has: a component swallows an exception, degrades to something harmless-
looking, and the logs stay clean while the data goes wrong. In B's territory
there are two such swallows, and strict_mode turns both into startup failures
rather than surprises discovered in a benchmark report.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Union

from .schema import (
    DetectorConfig,
    EngineConfig,
    IngestConfig,
    RecognitionConfig,
    TrackerConfig,
    ZoneConfig,
    resolve_engine_path,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "default_config.yaml"


class ConfigBoundaryError(ValueError):
    """The config file asks the engine to hold something outside its remit."""


# The name this used to have, kept so callers and tests that catch it still
# work. Refusal is no longer specific to company rules — an unknown key is
# refused the same way, because both are "the engine does not own this".
PolicyLeakError = ConfigBoundaryError


def _field_names(cls: type) -> Set[str]:
    return {field.name for field in dataclasses.fields(cls)}


# Derived from the dataclasses, so the schema cannot drift from what the loader
# accepts. These are nested objects on EngineConfig and sections in the file,
# not keys inside `core`.
_NESTED = {"ingest", "detector", "tracker", "zones", "recognition"}
_CORE_KEYS = _field_names(EngineConfig) - _NESTED
_SECTIONS: Dict[str, Set[str]] = {
    "core": _CORE_KEYS,
    "ingest": _field_names(IngestConfig),
    "detector": _field_names(DetectorConfig),
    "tracker": _field_names(TrackerConfig),
    "zones": _field_names(ZoneConfig),
    "recognition": _field_names(RecognitionConfig),
}


def _assert_within_the_engines_remit(raw: Dict[str, Any]) -> None:
    """Refuses any section or key the schema does not declare."""
    problems = []

    for section in raw:
        if section not in _SECTIONS:
            problems.append(
                f"section '{section}' (the engine accepts only: "
                f"{', '.join(sorted(_SECTIONS))})"
            )

    for section, allowed in _SECTIONS.items():
        body = raw.get(section)
        if body is None:
            continue
        if not isinstance(body, dict):
            problems.append(f"section '{section}' must be a mapping")
            continue
        for key in body:
            if key not in allowed:
                problems.append(f"'{section}.{key}'")

    if problems:
        raise ConfigBoundaryError(
            "Engine config contains settings the engine does not own: "
            + "; ".join(problems)
            + ". The engine may hold perceptual constants only — how long "
            "before a track counts as gone, how much evidence confirms an "
            "identity, what similarity counts as a match. Company rules live "
            "in backend/policy/ and measurement thresholds in bench/ "
            "(ARCHITECTURE.md §16). If this is a typo, it is now an error "
            "rather than a silently ignored line."
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

    _assert_within_the_engines_remit(raw)

    core = raw.get("core", {}) or {}
    ing = raw.get("ingest", {}) or {}
    det = raw.get("detector", {}) or {}
    trk = raw.get("tracker", {}) or {}
    zon = raw.get("zones", {}) or {}
    rec = raw.get("recognition", {}) or {}

    return EngineConfig(
        source_uri=str(core.get("source_uri", "0")),
        source_type=str(core.get("source_type", "opencv")),
        detection_interval=int(core.get("detection_interval", 1)),
        target_fps=core.get("target_fps"),
        auto_warmup=bool(core.get("auto_warmup", True)),
        strict_mode=bool(core.get("strict_mode", True)),
        ingest=IngestConfig(
            backend=str(ing.get("backend", "pyav")),
            rtsp_transport=str(ing.get("rtsp_transport", "tcp")),
            timeout_seconds=float(ing.get("timeout_seconds", 8.0)),
            reconnect_attempts=int(ing.get("reconnect_attempts", 0)),
            reconnect_backoff_seconds=float(
                ing.get("reconnect_backoff_seconds", 1.0)
            ),
            max_reconnect_backoff_seconds=float(
                ing.get("max_reconnect_backoff_seconds", 30.0)
            ),
            measure_timeline_fidelity=bool(
                ing.get("measure_timeline_fidelity", True)
            ),
            decoder_thread_type=str(ing.get("decoder_thread_type", "AUTO")),
            decoder_threads=int(ing.get("decoder_threads", 0)),
            colour_conversion=str(ing.get("colour_conversion", "to_ndarray")),
        ),
        detector=DetectorConfig(
            model_path=str(det.get("model_path", "ustc-community/dfine-nano-coco")),
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
        zones=ZoneConfig(
            # Kept as given, including the camera ids, which are the backend's
            # names for rooms and not something this loader may normalise.
            door_regions=dict(zon.get("door_regions") or {}),
            edge_margin=float(zon.get("edge_margin", 0.03)),
        ),
        recognition=RecognitionConfig(
            enabled=bool(rec.get("enabled", False)),
            max_age_seconds=_optional_float(rec.get("max_age_seconds")),
            retry_interval_seconds=_optional_float(rec.get("retry_interval_seconds")),
            reverify_interval_seconds=_optional_float(
                rec.get("reverify_interval_seconds")
            ),
            per_camera_quota=_optional_int(rec.get("per_camera_quota")),
            max_requests_per_frame=int(rec.get("max_requests_per_frame", 2)),
        ),
    )


def _optional_float(value: Any) -> Optional[float]:
    """None stays None: it means "use the scheduler's own default", not zero."""
    return None if value is None else float(value)


def _optional_int(value: Any) -> Optional[int]:
    return None if value is None else int(value)
