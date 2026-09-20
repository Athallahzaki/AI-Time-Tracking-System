"""
Orchestration: run N cameras in one of two modes, then compute everything.

The division of labour matters. This module starts threads, collects files and
calls the analysis; it does not know how a track lifetime is computed, and the
analysis does not know a thread ever existed. That is what lets the same
`metrics.py` be re-run against an old track log after a bug is found in it —
which will happen, because bench code is code.

`engine/bench` never imports `pipeline.engine` (§13.9). It goes through
`ports.observation.TrackStream`, satisfied today by the in-process adapter and
at step 6 by a reader over the NDJSON `events` channel, with no change here.
"""

from __future__ import annotations

import dataclasses
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..config import EngineConfig, load_config
from . import metrics as M
from . import report as R
from .annotation import Annotation, load_annotation
from .pacing import OffsetSource, RealtimeSource
from .spans import SpanRecorder
from .thresholds import Thresholds, load_thresholds, verdict
from .tracklog import TrackLogWriter, segments_from_log

logger = logging.getLogger("engine.bench")

MODES = ("throughput", "realtime")


@dataclass
class BenchOptions:
    config_path: Optional[str] = None
    source: Optional[str] = None
    mock: bool = False
    mode: str = "throughput"
    cameras: int = 1
    frames: Optional[int] = None
    seed: int = 1337
    out_dir: Path = Path("bench-out")
    annotation_path: Optional[str] = None
    thresholds_path: Optional[str] = None
    face_probe: bool = False
    face_sample_interval: float = 1.0
    detector_probe_iters: int = 0
    span_capacity: int = 500_000
    track_gap_seconds: float = 0.5
    max_camera_offset_seconds: float = 10.0
    recording_is_phone: bool = True
    label: str = ""

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        if self.cameras < 1:
            raise ValueError("cameras must be >= 1")
        self.out_dir = Path(self.out_dir)


@dataclass
class CameraRun:
    camera_id: str
    recorder: SpanRecorder
    track_log: Path
    descriptor: Any = None
    frames: int = 0
    error: Optional[BaseException] = None
    offset_frames: int = 0
    queue_metrics: Optional[Dict[str, Any]] = None


def _build_config(options: BenchOptions) -> EngineConfig:
    config = load_config(options.config_path)
    changes: Dict[str, Any] = {}
    if options.mock:
        changes["source_type"] = "mock"
    if options.source:
        changes["source_uri"] = options.source
        if not options.mock:
            changes["source_type"] = "video_file"
    return dataclasses.replace(config, **changes) if changes else config


def _run_one_camera(
    config: EngineConfig,
    run: CameraRun,
    options: BenchOptions,
    barrier: threading.Barrier,
) -> None:
    from ..streams.local import LocalTrackStream

    def wrap(source: Any, fps: float) -> Any:
        wrapped = source
        if run.offset_frames:
            wrapped = OffsetSource(wrapped, run.offset_frames)
        if options.mode == "realtime":
            wrapped = RealtimeSource(wrapped, fps=fps, recorder=run.recorder)
        return wrapped

    stream = LocalTrackStream(
        config,
        camera_id=run.camera_id,
        max_frames=options.frames,
        recorder=run.recorder,
        wrap_source=wrap,
    )
    writer: Optional[TrackLogWriter] = None
    try:
        run.descriptor = stream.open()
        writer = TrackLogWriter(run.track_log, run.camera_id)
        # All cameras start the clock together, so a five-camera aggregate FPS
        # is not inflated by four of them having finished warming up first.
        barrier.wait(timeout=300)
        for observation in stream.observations():
            writer.write(observation)
            run.frames += 1
    except BaseException as exc:  # noqa: BLE001 — recorded and re-raised by the caller
        run.error = exc
        try:
            barrier.abort()
        except Exception:
            pass
    finally:
        if writer is not None:
            writer.close()
        stream.close()
        # Re-read after close: timeline fidelity and the reconnect count are
        # accumulated while running, so the descriptor taken at open() is a
        # snapshot of the beginning, not of the run.
        if stream.descriptor is not None:
            run.descriptor = stream.descriptor
        run.queue_metrics = stream.recognition_queue_metrics


def _recognition_queue_metrics(
    runs: Sequence[CameraRun], config: EngineConfig
) -> Dict[str, Any]:
    """
    What B5's priority queue did, aggregated across cameras.

    Withheld rather than zeroed when the queue is off, because "no queue ran"
    and "a queue ran and never dropped anything" are different facts and only
    one of them is good news. §5.2 asks for four numbers; worker utilisation is
    absent until there are workers, and the report says so instead of reporting
    a zero that reads like an idle pool.
    """
    if not config.recognition.enabled:
        return M.withheld(
            "recognition.enabled is false, so no queue ran. It is off by "
            "default: B1's baseline was measured without one, and turning it on "
            "in the same commit that introduced it would move the numbers every "
            "later step is compared against (§16)"
        )

    per_camera = {
        run.camera_id: run.queue_metrics
        for run in runs
        if run.queue_metrics is not None
    }
    if not per_camera:
        return M.withheld(
            "the queue was enabled but reported nothing, which usually means "
            "the source has no PTS (a mock run): request ages are measured in "
            "PTS (§6.6) and a fabricated clock would produce fabricated queue "
            "numbers"
        )

    def total(key: str) -> float:
        return round(sum(float(m.get(key) or 0.0) for m in per_camera.values()), 4)

    return {
        "per_camera": per_camera,
        "submitted_total": total("submitted_total"),
        "handed_out_total": total("handed_out_total"),
        "dropped_stale_total": total("dropped_stale"),
        "depth_at_end": total("queue_depth"),
        "worker_utilisation": M.withheld(
            "there is no worker pool yet (§5.2, last step in the B track), so "
            "there is no utilisation to report. Left out rather than 0.0, which "
            "would read as an idle pool"
        ),
        # Read this before reading dropped_stale_total. The scheduler drops a
        # stale request when one is POPPED; with no consumer nothing is popped,
        # so a zero here means "nothing was ever examined", not "nothing went
        # stale". `depth_at_end` and the per-camera `oldest_queued_age` are the
        # numbers that describe what actually happened.
        "had_consumer": any(
            bool(m.get("has_consumer")) for m in per_camera.values()
        ),
        "priority_order_is_door_first": True,
    }


def _detector_throughput_probe(
    config: EngineConfig, iterations: int
) -> Dict[str, Any]:
    """
    Inferences per second on one frame, repeated.

    §8 needs one number that can be divided by 150 (5 cameras × 30 fps) to say
    whether the box is big enough. §13.3 says not to get it from nvidia-smi.
    This is that number, and it is measured separately from the pipeline so
    decode and tracking do not contaminate it.
    """
    if iterations <= 0:
        return M.withheld("not requested (--detector-probe-iters 0)")

    import numpy as np

    from .. import factory
    from ..ports.frame import Frame, FrameMetadata

    detector = factory.build_detector(config)
    if hasattr(detector, "warmup"):
        detector.warmup()

    width = config.detector.image_size
    image = np.zeros((width, width, 3), dtype=np.uint8)
    frame = Frame(
        image=image,
        metadata=FrameMetadata(frame_id=1, width=width, height=width, fps=0.0),
    )

    for _ in range(min(5, iterations)):
        detector.detect(frame)

    durations: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        detector.detect(frame)
        durations.append((time.perf_counter() - t0) * 1000.0)

    mean_ms = sum(durations) / len(durations)
    return {
        "detector_class": type(detector).__name__,
        "iterations": iterations,
        "input_size": width,
        "mean_ms": round(mean_ms, 4),
        "p95_ms": M.round_opt(M.percentile(durations, 95)),
        "inferences_per_second": round(1000.0 / mean_ms, 2) if mean_ms > 0 else None,
        "note": (
            "synthetic blank frame at the configured input size; measures the "
            "forward pass, not decode or postprocess of a real scene"
        ),
    }


def run_bench(options: BenchOptions) -> Dict[str, Any]:
    config = _build_config(options)
    options.out_dir.mkdir(parents=True, exist_ok=True)

    annotation: Optional[Annotation] = None
    if options.annotation_path:
        annotation = load_annotation(Path(options.annotation_path))
        logger.info("annotation loaded: %s", annotation.summary())

    thresholds: Optional[Thresholds] = None
    if options.thresholds_path:
        thresholds = load_thresholds(Path(options.thresholds_path))

    rng = random.Random(options.seed)
    runs: List[CameraRun] = []
    for index in range(options.cameras):
        camera_id = f"cam{index}"
        run = CameraRun(
            camera_id=camera_id,
            recorder=SpanRecorder(camera_id, capacity=options.span_capacity),
            track_log=options.out_dir / f"tracks_{camera_id}.ndjson",
        )
        if index > 0 and config.source_type == "video_file":
            # Random time offsets, so N cameras are not decoding the same
            # keyframe in lockstep. Seeded, so the run is reproducible.
            run.offset_frames = int(
                rng.uniform(0.0, options.max_camera_offset_seconds) * 30.0
            )
        runs.append(run)

    barrier = threading.Barrier(options.cameras + 1)
    threads = [
        threading.Thread(
            target=_run_one_camera,
            args=(config, run, options, barrier),
            name=f"bench-{run.camera_id}",
            daemon=True,
        )
        for run in runs
    ]

    wall_start = time.perf_counter()
    for thread in threads:
        thread.start()
    try:
        barrier.wait(timeout=300)
    except threading.BrokenBarrierError:
        pass
    for thread in threads:
        thread.join()
    wall_seconds = time.perf_counter() - wall_start

    failures = [run for run in runs if run.error is not None]
    if failures:
        # One camera failing invalidates the aggregate. Reporting the survivors
        # as if they were the run is precisely the flattering partial result
        # §13.1 is about.
        raise RuntimeError(
            f"{len(failures)} of {len(runs)} camera(s) failed; the aggregate is "
            f"meaningless. First error from {failures[0].camera_id}: "
            f"{failures[0].error!r}"
        ) from failures[0].error

    for run in runs:
        run.recorder.write_ndjson(
            options.out_dir / f"spans_{run.camera_id}.ndjson", t_zero=wall_start
        )

    recorders = [run.recorder for run in runs]
    results: Dict[str, Any] = {
        "throughput": M.throughput(recorders, options.mode),
        "latency": M.latency_by_stage(recorders, mode=options.mode),
    }

    # --- which metrics this run is entitled to report (§13.2) --------------
    identity_ok = options.mode == "throughput" and options.cameras == 1
    if not identity_ok:
        reason = (
            "valid in throughput mode only: dropped frames break tracks and "
            "what gets measured is the test machine (§13.2)"
            if options.mode != "throughput"
            else "reported for N=1 only: N copies of one person destroy the "
            "dedup of §5.3 and the cross-camera fusion of §5.4 (§13.2)"
        )
        results["track_lifetime"] = M.withheld(reason)
        results["identity_continuity"] = M.withheld(reason)
        results["false_gaps"] = M.withheld(reason)
        segments = []
    else:
        segments = segments_from_log(
            runs[0].track_log, max_gap_seconds=options.track_gap_seconds
        )
        results["track_lifetime"] = M.track_lifetime(segments, annotation)
        results["identity_continuity"] = M.identity_continuity(segments, annotation)
        results["false_gaps"] = M.false_gaps(
            segments,
            annotation,
            workday_hours=thresholds.workday_hours if thresholds else None,
        )

    # --- recognizable faces (§3.1, §13.5) ----------------------------------
    face_is_lower_bound: Optional[bool] = None
    if options.face_probe and identity_ok and config.source_type == "video_file":
        from .faceprobe import HaarFrontalFaceProbe, run_face_probe

        probe = HaarFrontalFaceProbe()
        face_is_lower_bound = probe.is_lower_bound
        face_result = run_face_probe(
            video_path=Path(config.source_uri),
            track_log=runs[0].track_log,
            probe=probe,
            sample_interval_seconds=options.face_sample_interval,
            annotation=annotation,
        )
        results["recognizable_faces"] = face_result.as_dict(annotation)
    elif options.face_probe:
        results["recognizable_faces"] = M.withheld(
            "the face probe needs a real recording, throughput mode and N=1"
        )
    else:
        results["recognizable_faces"] = M.withheld(
            "not requested (--face-probe). B0 did not port a face detector; "
            "until identity/ lands this pass uses OpenCV's frontal cascade, "
            "which is a lower bound"
        )

    results["end_to_end_accuracy"] = M.withheld(
        "waits for enrollment and the identity layer (§10, step A8). The slot "
        "is reserved so adding it later is a field gaining a value, never a "
        "field changing meaning (§13.4)"
    )
    results["detector_throughput_probe"] = _detector_throughput_probe(
        config, options.detector_probe_iters
    )

    # close() refreshes each descriptor with what the source accumulated while
    # running — timeline fidelity and the reconnect count are measured, not
    # declared, so they are only complete now.
    descriptors = [dataclasses.asdict(run.descriptor) for run in runs if run.descriptor]
    pts_source = descriptors[0]["pts_source"] if descriptors else "unknown"
    results["timeline"] = M.timeline_summary(descriptors, segments)

    # --- B5: where appearances ended, and what the queue did ---------------
    # Zone exits are valid under the same restriction as every other track
    # metric (§13.2): in realtime mode a dropped frame ends an appearance
    # wherever the person happened to be, so the zone describes the test machine
    # rather than the room.
    if identity_ok:
        results["zone_exits"] = M.zone_exits(
            segments,
            annotation,
            door_configured=bool(config.zones.door_regions),
        )
    else:
        results["zone_exits"] = M.withheld(
            "valid in throughput mode with N=1 only: a dropped frame ends an "
            "appearance wherever the person happened to be, so the exit zone "
            "would describe the test machine (§13.2)"
        )
    results["recognition_queue"] = _recognition_queue_metrics(runs, config)

    # Every frozen key must be present before the report is built — a run that
    # silently omits one produces a baseline that cannot be compared with the
    # others, which is the whole thing §13.4 exists to prevent.
    missing = [key for key in R.FROZEN_METRIC_KEYS if key not in results]
    if missing:
        raise RuntimeError(f"metrics block is missing frozen keys {missing}")

    recording_path = Path(config.source_uri) if config.source_type != "mock" else None
    recording = {
        "source_type": config.source_type,
        "uri": config.source_uri,
        "sha256": R.sha256_file(recording_path) if recording_path else None,
        "size_bytes": (
            recording_path.stat().st_size
            if recording_path and recording_path.exists()
            else None
        ),
        "annotation": annotation.summary() if annotation else None,
    }

    model_path = Path(config.detector.model_path)
    models = {
        "detector": {
            "path": config.detector.model_path,
            "sha256": R.sha256_file(model_path),
            "class": descriptors[0]["detector_class"] if descriptors else None,
        },
        "tracker": {
            "backend_requested": config.tracker.backend,
            "class": descriptors[0]["tracker_class"] if descriptors else None,
        },
    }

    report = R.build_report(
        run={
            "label": options.label,
            "mode": options.mode,
            "cameras": options.cameras,
            "frames_requested": options.frames,
            "frames_processed": sum(run.frames for run in runs),
            "wall_seconds": round(wall_seconds, 4),
            "seed": options.seed,
            "track_gap_seconds": options.track_gap_seconds,
            "stitch_windows_seconds": list(M.STITCH_WINDOWS_SECONDS),
            "out_dir": str(options.out_dir),
        },
        config=config,
        models=models,
        recording=recording,
        streams=descriptors,
        metrics=results,
        go_no_go=verdict(results, thresholds),
        caveats=R.standard_caveats(
            mode=options.mode,
            cameras=options.cameras,
            pts_source=pts_source,
            source_type=config.source_type,
            recording_is_phone=options.recording_is_phone
            and config.source_type == "video_file",
            annotation_present=annotation is not None,
            face_probe_is_lower_bound=face_is_lower_bound,
        ),
    )
    return report
