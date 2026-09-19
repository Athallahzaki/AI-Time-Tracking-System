"""
The report, and the promise attached to it.

§13.4: every run writes one JSON containing the git SHA, the **full effective
config** (its contents, not its path), model names and hashes, device, driver
version, the recording's name and hash, the mode, and the number of simulated
cameras. Without those, this week's number and next week's number cannot be
compared and §16 — "every step is measured with the same bench.py" — is
decoration.

**The schema is frozen here and may only gain fields.** The meaning of a field
that already exists never changes. Same rule as the protocol (§6.8), same
reason: two numbers that cannot be compared are as useless as no numbers.
`tests/test_b1_bench.py` asserts the frozen key set, so removing or renaming one
fails CI rather than quietly invalidating three months of baselines.

Captured but explicitly *not* trusted: `nvidia-smi` utilisation. §13.3 is right
that "gpu_util 62%" is the fraction of time some kernel was resident, not
headroom — it looks authoritative and predicts nothing. It is recorded under
`advisory_only: true` so it is there when debugging and cannot be mistaken for
a capacity figure. The number that *can* be divided by 150 (§8) is the detector
throughput probe.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.bench.report")

REPORT_SCHEMA_VERSION = 1

# Removing or renaming any of these breaks comparability with every baseline
# already committed. Adding one is fine. Enforced by a test.
FROZEN_TOP_LEVEL_KEYS = (
    "schema_version",
    "generated_at",
    "run",
    "engine",
    "config",
    "models",
    "recording",
    "streams",
    "environment",
    "metrics",
    "go_no_go",
    "caveats",
)

FROZEN_METRIC_KEYS = (
    "throughput",
    "latency",
    "track_lifetime",
    "identity_continuity",
    "false_gaps",
    "recognizable_faces",
    "end_to_end_accuracy",
    "detector_throughput_probe",
)


def sha256_file(path: Path, chunk: int = 1 << 20) -> Optional[str]:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_state(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """git SHA and whether the tree was dirty. Never fatal — a missing git is
    a worse report, not a failed run."""
    root = str(repo_root or Path.cwd())

    def run(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", "-C", root, *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    sha = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {
        "sha": sha,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": None if status is None else bool(status),
        # A dirty tree means the SHA does not describe the code that ran. Saying
        # so is the difference between a baseline and a rumour.
        "dirty_warning": (
            "working tree had uncommitted changes; this SHA does not fully "
            "describe the code that produced these numbers"
            if status
            else None
        ),
    }


# Module name -> the distribution names it could have been installed under.
# opencv and onnxruntime each ship under several, and which one is installed is
# itself worth recording: opencv-python and opencv-python-headless are not the
# same dependency footprint, and onnxruntime-gpu is not onnxruntime.
_DISTRIBUTIONS = {
    "numpy": ("numpy",),
    "cv2": ("opencv-python", "opencv-python-headless", "opencv-contrib-python"),
    "torch": ("torch",),
    "ultralytics": ("ultralytics",),
    "onnxruntime": ("onnxruntime-gpu", "onnxruntime"),
    "yaml": ("PyYAML",),
    "av": ("av",),
    "libreyolo": ("libreyolo",),
}


def package_versions() -> Dict[str, Any]:
    """
    Versions of the stack, read from installed metadata — never by importing.

    The first version of this function called `__import__(name)` to read
    `__version__`, which quietly defeated the one property the mock path exists
    for: importing the report module pulled torch and Ultralytics into the
    process, so `python -m engine.bench --mock` was no longer a run that proves
    it can survive without them. It did not fail on a machine with neither
    installed, which is exactly how a vacuous check survives review.

    `importlib.metadata` reads the dist-info on disk. Nothing is imported, the
    answer is the same, and it is better in one respect: a package that is
    *installed but not imported* is still reported, which is what the
    torch/AGPL caveat should be based on.
    """
    import sys
    from importlib import metadata

    versions: Dict[str, Optional[str]] = {}
    resolved_from: Dict[str, str] = {}

    for module_name, candidates in _DISTRIBUTIONS.items():
        # Free: if something else already imported it, believe the module.
        loaded = sys.modules.get(module_name)
        if loaded is not None and getattr(loaded, "__version__", None):
            versions[module_name] = str(loaded.__version__)
            resolved_from[module_name] = "already-imported module"
            continue

        versions[module_name] = None
        for distribution in candidates:
            try:
                versions[module_name] = metadata.version(distribution)
                resolved_from[module_name] = distribution
                break
            except metadata.PackageNotFoundError:
                continue
            except Exception:
                break

    return {"versions": versions, "resolved_from": resolved_from}


def gpu_state() -> Dict[str, Any]:
    """nvidia-smi, recorded and explicitly distrusted. §13.3."""
    state: Dict[str, Any] = {
        "advisory_only": True,
        "why_advisory": (
            "utilisation from nvidia-smi is the fraction of time a kernel was "
            "resident, not headroom (§13.3). Use detector_throughput_probe for "
            "anything that feeds a decision."
        ),
        "devices": [],
        "driver_version": None,
    }
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode != 0:
            return state
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 5:
                continue
            state["driver_version"] = parts[1]
            state["devices"].append(
                {
                    "name": parts[0],
                    "memory_total_mb": _as_int(parts[2]),
                    "memory_used_mb": _as_int(parts[3]),
                    "utilization_percent": _as_int(parts[4]),
                }
            )
    except (OSError, subprocess.SubprocessError):
        pass
    return state


def _as_int(text: str) -> Optional[int]:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def environment() -> Dict[str, Any]:
    packages = package_versions()
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        # Flat name -> version, so two baselines can be diffed field by field.
        "packages": packages["versions"],
        "package_distributions": packages["resolved_from"],
        "gpu": gpu_state(),
    }


def build_report(
    *,
    run: Dict[str, Any],
    config: Any,
    models: Dict[str, Any],
    recording: Dict[str, Any],
    streams: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    go_no_go: Dict[str, Any],
    caveats: List[str],
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    config_dict = (
        dataclasses.asdict(config) if dataclasses.is_dataclass(config) else dict(config)
    )
    config_json = json.dumps(config_dict, sort_keys=True, default=str)

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run": run,
        "engine": {
            "git": git_state(repo_root),
            "bench_module": "engine.bench",
        },
        "config": {
            # The contents, not the path. A path is not reproducible; a config
            # file changes without anyone noticing it invalidated a baseline.
            "effective": config_dict,
            "sha256": sha256_text(config_json),
        },
        "models": models,
        "recording": recording,
        "streams": streams,
        "environment": environment(),
        "metrics": metrics,
        "go_no_go": go_no_go,
        "caveats": caveats,
    }

    missing = [key for key in FROZEN_TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(
            f"report is missing frozen keys {missing}; the schema may only "
            f"gain fields (§13.4)"
        )
    return report


def write_report(report: Dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=False), encoding="utf-8")
    return path


def standard_caveats(
    *,
    mode: str,
    cameras: int,
    pts_source: str,
    recording_is_phone: bool,
    annotation_present: bool,
    face_probe_is_lower_bound: Optional[bool],
) -> List[str]:
    """
    The things a reader two months from now will otherwise assume away.

    §13.8: "in two months somebody will quote these as production numbers."
    Printing them in the report, rather than filing them in a document, is the
    only version of this that works.
    """
    caveats: List[str] = []

    caveats.append(
        "Baseline is measured on a stack that still carries torch and "
        "Ultralytics AGPL-3.0 in the tracker (§14 note on step 16). Step B7 "
        "removes both and that will show up in the memory profile."
    )

    if pts_source != "container_pts":
        caveats.append(
            "There is no real PTS yet: cv2.VideoCapture discards it (§5.5), so "
            "timestamps here are frame index / declared fps. Identical for a "
            "file played from disk, not identical for a live RTSP camera. "
            "Step B4 replaces ingest with PyAV."
        )

    if cameras > 1:
        caveats.append(
            f"N={cameras} simulated cameras is the same file played {cameras} "
            f"times at different offsets. Realistic for decode and detection "
            f"cost; NOT realistic for identity, because N copies of the same "
            f"person destroy the per-frame dedup of §5.3 and the cross-camera "
            f"fusion of §5.4. Identity and track-quality metrics are withheld "
            f"above for exactly that reason (§13.2)."
        )

    if mode == "realtime":
        caveats.append(
            "Realtime mode: dropped frames break tracks, so track lifetime, "
            "fragmentation and accuracy are withheld. They are valid from "
            "throughput mode only (§13.2)."
        )
    else:
        caveats.append(
            "Throughput mode: no frame is ever dropped, so drop rate and queue "
            "depth are withheld. They are valid from realtime mode only (§13.2)."
        )

    if recording_is_phone:
        caveats.append(
            "The recording is from a phone: wider lens, adaptive exposure, "
            "bitrate far above a CCTV substream, no rolling-shutter artefacts. "
            "Every number derived from it is an UPPER BOUND on what the "
            "installed camera will do (§13.8)."
        )

    if not annotation_present:
        caveats.append(
            "No annotation was supplied, so both product metrics (§4.7, §13.5) "
            "are unmeasured — not zero, unmeasured — and the verdict cannot be "
            "GO. The expensive part of B1 is the labelling, not the recording."
        )

    if face_probe_is_lower_bound:
        caveats.append(
            "The recognizable-face rate comes from OpenCV's frontal cascade, a "
            "lower bound. B0 did not port a face detector (SCRFD belongs to the "
            "identity layer), so the real rate will be higher. Re-run this pass "
            "with SCRFD once identity/ exists before quoting the figure."
        )

    return caveats
