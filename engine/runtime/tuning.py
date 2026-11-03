"""Pengaturan realtime dari backend (`set_tuning`, overhaul 3 Nov).

Deklaratif, sama seperti `set_cameras`: pesan membawa SELURUH override yang
diinginkan admin. Engine selalu menghitung dari config file saat start
(`base`) ditambah override itu, jadi `{}` = kembali ke file. Backend menyimpan
override-nya dan mengirim ulang setiap kali tersambung, sehingga engine yang
restart tidak kehilangan kalibrasi.

Hanya kunci di `TUNABLE` yang boleh diubah saat jalan; semuanya konstanta
perseptual. Validasi memakai `__post_init__` dataclass config yang sama dengan
saat file dimuat, ditambah batas di `_check`. Satu nilai salah = seluruh pesan
ditolak dan engine tetap memakai pengaturan sebelumnya (tidak ada setengah jadi).

Butuh restart (tidak ada di sini): `tracker.track_threshold` dan kunci tracker
lain (ByteTrack LibreYOLO dibangun sekali dengan TrackConfig-nya), model, ukuran
input, dan semua yang menyentuh GPU.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Mapping

from ..config.schema import EngineConfig

TUNABLE: Dict[str, tuple] = {
    "recognition": ("match_threshold", "match_margin", "cross_camera_claims", "overlapping_cameras"),
    "reid": ("match_threshold", "match_margin", "travel_time_seconds",
             "default_travel_time_seconds", "reevaluate"),
    "analysis_trigger": tuple(f.name for f in dataclasses.fields(EngineConfig().analysis_trigger)),
    "detector": ("confidence_threshold", "nms_iou_threshold"),
    "core": ("idle_fps", "idle_after_seconds"),
}
RESTART_ONLY = ("tracker.*", "detector.model_path", "detector.image_size", "recognition.recognizer",
                "reid.model_path")


class TuningError(ValueError):
    pass


def tuned_config(base: EngineConfig, overrides: Mapping[str, Any]) -> EngineConfig:
    """`base` + override. TuningError bila ada bagian/kunci/nilai yang tidak sah."""
    if not isinstance(overrides, Mapping):
        raise TuningError("tuning harus objek {bagian: {kunci: nilai}}")
    problems = []
    for section, values in overrides.items():
        if section not in TUNABLE:
            problems.append(f"bagian '{section}' tidak bisa diubah saat jalan")
        elif not isinstance(values, Mapping):
            problems.append(f"'{section}' harus objek")
        else:
            problems += [f"'{section}.{key}' tidak bisa diubah saat jalan"
                         for key in values if key not in TUNABLE[section]]
    if problems:
        raise TuningError("; ".join(problems))
    try:
        changes: Dict[str, Any] = {}
        for section, values in overrides.items():
            values = {k: _coerce(section, k, v) for k, v in values.items()}
            for key, value in values.items():
                _check(section, key, value)
            if section == "core":
                changes.update(values)
            else:
                changes[section] = dataclasses.replace(getattr(base, section), **values)
        return dataclasses.replace(base, **changes)
    except TuningError:
        raise
    except (TypeError, ValueError) as error:
        raise TuningError(str(error)) from error


def effective(config: EngineConfig) -> Dict[str, Dict[str, Any]]:
    """Nilai yang sedang berlaku untuk setiap kunci TUNABLE, dalam bentuk JSON."""
    out: Dict[str, Dict[str, Any]] = {}
    for section, keys in TUNABLE.items():
        holder = config if section == "core" else getattr(config, section)
        out[section] = {key: _jsonable(getattr(holder, key)) for key in keys}
    return out


def _coerce(section: str, key: str, value: Any) -> Any:
    if section == "recognition" and key == "overlapping_cameras":
        if not isinstance(value, (list, tuple)):
            raise TuningError("recognition.overlapping_cameras harus daftar pasangan [cam_a, cam_b]")
        return tuple(tuple(str(c) for c in pair) for pair in value)
    if isinstance(value, bool) or value is None or isinstance(value, (dict, str)):
        return value
    if isinstance(value, (int, float)):
        field_type = _field_type(section, key)
        return int(value) if field_type is int and float(value).is_integer() else value
    raise TuningError(f"{section}.{key}: tipe {type(value).__name__} tidak didukung")


def _field_type(section: str, key: str) -> Any:
    holder = EngineConfig() if section == "core" else getattr(EngineConfig(), section)
    return type(getattr(holder, key))


def _check(section: str, key: str, value: Any) -> None:
    def number(low: float, high: float, nullable: bool = False) -> None:
        if value is None and nullable:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise TuningError(f"{section}.{key}={value!r} harus angka {low}..{high}"
                              + (" atau null" if nullable else ""))

    if key == "match_threshold":
        number(-1.0, 1.0, nullable=True)
    elif key == "match_margin":
        number(0.0, 1.0, nullable=True)
    elif key == "overlapping_cameras":
        for pair in value:
            if len(pair) != 2 or pair[0] == pair[1]:
                raise TuningError(f"recognition.overlapping_cameras: pasangan harus 2 kamera berbeda, bukan {list(pair)!r}")
    elif key in ("cross_camera_claims", "reevaluate", "enabled"):
        if not isinstance(value, bool):
            raise TuningError(f"{section}.{key} harus true/false")
    elif (section, key) == ("detector", "confidence_threshold"):
        number(0.05, 0.95)
    elif (section, key) == ("detector", "nms_iou_threshold"):
        number(0.01, 1.0, nullable=True)
    elif (section, key) == ("core", "idle_fps"):
        number(0.1, 30.0, nullable=True)
    elif (section, key) == ("core", "idle_after_seconds"):
        number(0.0, 3600.0)
    elif (section, key) == ("reid", "default_travel_time_seconds"):
        number(0.0, 3600.0)


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def apply_detector_tuning(detector: Any, cfg: Any) -> None:
    """Ambang detector D-FINE saat jalan. Objek lain (mock, handle bersama) dilewati.

    `_raw_conf` = yang diminta dari model (lantai ByteTrack). Diturunkan bersama
    `confidence_threshold` bila perlu, tidak pernah dinaikkan di atas lantai start.
    """
    if detector is None or not hasattr(detector, "_conf"):
        return
    startup_raw = detector.__dict__.setdefault("_startup_raw_conf", detector._raw_conf)
    detector._conf = float(cfg.confidence_threshold)
    detector._raw_conf = min(startup_raw, detector._conf)
    detector._nms_iou = cfg.nms_iou_threshold
