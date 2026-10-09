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
`tracker`, since B5 `zones` and `recognition`, and since ea-r3 `reid` — and within each, only the
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
    ReidSettings,
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
_NESTED = {"ingest", "detector", "tracker", "zones", "recognition", "reid"}
_CORE_KEYS = _field_names(EngineConfig) - _NESTED
_SECTIONS: Dict[str, Set[str]] = {
    "core": _CORE_KEYS,
    "ingest": _field_names(IngestConfig),
    "detector": _field_names(DetectorConfig),
    "tracker": _field_names(TrackerConfig),
    "zones": _field_names(ZoneConfig),
    "recognition": _field_names(RecognitionConfig),
    "reid": _field_names(ReidSettings),
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
    rid = raw.get("reid", {}) or {}

    return EngineConfig(
        source_uri=str(core.get("source_uri", "0")),
        source_type=str(core.get("source_type", "opencv")),
        detection_interval=int(core.get("detection_interval", 1)),
        target_fps=core.get("target_fps"),
        auto_warmup=bool(core.get("auto_warmup", True)),
        strict_mode=bool(core.get("strict_mode", True)),
        cpu_threads=int(core.get("cpu_threads", 0) or 0),
        scheduler=str(core.get("scheduler", "free")),
        tick_fps=(float(core["tick_fps"]) if core.get("tick_fps") is not None else None),
        analysis_off_mode=str(core.get("analysis_off_mode", "stop")),
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
            live_buffer=str(ing.get("live_buffer", "none")),
            offset_correction=str(ing.get("offset_correction", "slew")),
            hwaccel=str(ing.get("hwaccel", "none")),
        ),
        detector=DetectorConfig(
            model_path=str(det.get("model_path", "LibreDFINEn.pt")),
            confidence_threshold=float(det.get("confidence_threshold", 0.50)),
            iou_threshold=float(det.get("iou_threshold", 0.45)),
            image_size=int(det.get("image_size", 640)),
            device=det.get("device", "auto"),
            half=bool(det.get("half", False)),
            pre_resize=bool(det.get("pre_resize", False)),
            cudnn_benchmark=bool(det.get("cudnn_benchmark", False)),
            cuda_graph=_cuda_graph(det.get("cuda_graph", False)),
            fast_preprocess=bool(det.get("fast_preprocess", False)),
            swscale_resize=bool(det.get("swscale_resize", False)),
            share_across_cameras=bool(det.get("share_across_cameras", True)),
            batch_inference=bool(det.get("batch_inference", False)),
            max_batch=int(det.get("max_batch", 8)),
            batch_wait_ms=float(det.get("batch_wait_ms", 4.0)),
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
            recognizer=str(rec.get("recognizer", "none") or "none"),
            face_detector_model=rec.get("face_detector_model"),
            face_embedder_model=rec.get("face_embedder_model"),
            embedding_version=str(rec.get("embedding_version", "auraface-v1")),
            reference_db_path=str(rec.get("reference_db_path", "engine/data/references.sqlite3")),
            onnx_providers=(
                tuple(str(p) for p in rec["onnx_providers"]) if rec.get("onnx_providers") else None
            ),
            onnx_gpu_mem_limit_mb=_optional_int(rec.get("onnx_gpu_mem_limit_mb")),
            face_detection_threshold=float(rec.get("face_detection_threshold", 0.5)),
            face_detector_input_size=int(rec.get("face_detector_input_size", 640)),
            execution=str(rec.get("execution", "async")),
            worker_queue=int(rec.get("worker_queue", 8)),
            min_face_px=float(rec.get("min_face_px", 40.0)),
            match_threshold=_optional_float(rec.get("match_threshold")),
            match_margin=_optional_float(rec.get("match_margin")),
        ),
        reid=_reid_settings(rid),
    )


def _reid_settings(rid: Dict[str, Any]) -> ReidSettings:
    """Blok `reid`. Kunci yang tidak ditulis memakai default dataclass."""
    defaults = ReidSettings()
    sha = rid.get("model_sha256")
    return ReidSettings(
        enabled=bool(rid.get("enabled", False)),
        model_path=str(rid.get("model_path") or defaults.model_path),
        model_sha256=(str(sha).strip() if sha else None),
        match_threshold=_optional_float(rid.get("match_threshold")),
        match_margin=_optional_float(rid.get("match_margin")),
        min_crop_height_px=float(rid.get("min_crop_height_px", defaults.min_crop_height_px)),
        min_aspect=float(rid.get("min_aspect", defaults.min_aspect)),
        max_aspect=float(rid.get("max_aspect", defaults.max_aspect)),
        edge_margin_px=float(rid.get("edge_margin_px", defaults.edge_margin_px)),
        embed_interval_seconds=float(rid.get("embed_interval_seconds", defaults.embed_interval_seconds)),
        max_batch=int(rid.get("max_batch", defaults.max_batch)),
        worker_queue=int(rid.get("worker_queue", defaults.worker_queue)),
        max_age_seconds=float(rid.get("max_age_seconds", defaults.max_age_seconds)),
        onnx_providers=(
            tuple(str(p) for p in rid["onnx_providers"]) if rid.get("onnx_providers") else None
        ),
        onnx_gpu_mem_limit_mb=_optional_int(rid.get("onnx_gpu_mem_limit_mb")),
        travel_time_seconds=dict(rid.get("travel_time_seconds") or {}),
        default_travel_time_seconds=float(
            rid.get("default_travel_time_seconds", defaults.default_travel_time_seconds)
        ),
        # YAML membaca 00:00 tanpa kutip sebagai angka sexagesimal; terima keduanya.
        daily_purge_time=_hhmm(rid.get("daily_purge_time", defaults.daily_purge_time)),
    )


def _hhmm(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value // 60:02d}:{value % 60:02d}"
    return str(value)


def _optional_float(value: Any) -> Optional[float]:
    """None stays None: it means "use the scheduler's own default", not zero."""
    return None if value is None else float(value)


def _optional_int(value: Any) -> Optional[int]:
    return None if value is None else int(value)


def _cuda_graph(value):
    """false / true / "auto". Teks lain ditolak di DetectorConfig."""
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "auto":
            return "auto"
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0", ""):
            return False
        return value
    return bool(value)
