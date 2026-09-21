"""
Acceptance tests for B1.

These do not test that the engine is fast. They test that the benchmark cannot
lie — which is the property ARCHITECTURE.md §13.1 says matters more than the
benchmark existing at all:

  * a metric the run cannot justify is null with a reason, never 0
  * a missing measurement can never produce a GO
  * the report schema is frozen and may only gain fields
  * the go/no-go thresholds are not hardcoded anywhere in engine/
  * the bench does not reach into pipeline internals
  * attaching the recorder does not change what the pipeline produces

Plus the arithmetic, on a scenario whose answer is known by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from engine.bench import metrics as M
from engine.bench.annotation import AnnotationError, load_annotation, parse_time
from engine.bench.report import FROZEN_METRIC_KEYS, FROZEN_TOP_LEVEL_KEYS
from engine.bench.runner import BenchOptions, run_bench
from engine.bench.thresholds import GO, INCONCLUSIVE, NO_GO, ThresholdError
from engine.bench.thresholds import load_thresholds, verdict
from engine.bench.tracklog import segments_from_log

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parent


# --------------------------------------------------------------------------
# A scenario with a known answer
# --------------------------------------------------------------------------
#
# 60 seconds at 10 fps. One person, P1, in the room the whole time.
# Track 1 covers 0.0–20.0s. Track 2 covers 25.0–60.0s.
# So: exactly one false gap, exactly 5.0 seconds long.
#
#   raw false gap            5.0 s over 60 s of presence
#   per person-hour          5.0 / (60/3600) = 300 s
#   projected at 8 h/day     300 * 8 / 60 = 40 minutes  -> way over 3, NO_GO
#   stitched at N=5s         gap == window, so it joins -> 0 s, GO
#   track broke while present  track 1 only (track 2 ends at the exit)

def _write_scenario(tmp_path: Path):
    log = tmp_path / "tracks_cam0.ndjson"
    lines = []

    def emit(frame: int, pts: float, track_id: int, x: float) -> None:
        lines.append(
            json.dumps(
                {
                    "cam": "cam0",
                    "f": frame,
                    "pts": round(pts, 4),
                    "w": 1920,
                    "h": 1080,
                    "tr": [[track_id, x, 0.2, x + 0.05, 0.8, "TRACKED", 0.9]],
                },
                separators=(",", ":"),
            )
        )

    frame = 0
    pts = 0.0
    while pts <= 20.0 + 1e-9:
        frame += 1
        emit(frame, pts, 1, 0.30)
        pts = round(pts + 0.1, 4)

    pts = 25.0
    frame = 251
    while pts <= 60.0 + 1e-9:
        emit(frame, pts, 2, 0.60)
        frame += 1
        pts = round(pts + 0.1, 4)

    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    annotation_path = tmp_path / "annotation.yaml"
    annotation_path.write_text(
        """
recording:
  file: scenario.mp4
  sha256: null
  camera_id: cam0
  duration_seconds: 60.0
persons:
  - id: P1
    presence:
      - {enter: 0.0, exit: 60.0, exit_via_door: true}
track_map:
  cam0:
    1: P1
    2: P1
""".strip(),
        encoding="utf-8",
    )
    return log, load_annotation(annotation_path)


def test_false_gap_arithmetic_matches_the_hand_computed_scenario(tmp_path):
    log, annotation = _write_scenario(tmp_path)
    segments = segments_from_log(log)
    assert len(segments) == 2, [s.as_dict() for s in segments]

    result = M.false_gaps(segments, annotation, workday_hours=8.0)
    raw = result["raw"]
    assert raw["total_false_gap_seconds"] == pytest.approx(5.0, rel=0.02)
    assert raw["total_presence_seconds"] == pytest.approx(60.0)
    assert raw["false_gap_seconds_per_person_hour"] == pytest.approx(300.0, rel=0.02)
    assert raw["projected_minutes_per_person_per_day"] == pytest.approx(40.0, rel=0.02)


def test_stitching_closes_a_gap_no_larger_than_its_window(tmp_path):
    """
    §13.6 exists because judging the feature on the raw number condemns it on a
    basis the design never intended. A 5 s gap must survive a 2 s window and
    disappear under a 5 s one — otherwise the two numbers are the same number.
    """
    log, annotation = _write_scenario(tmp_path)
    segments = segments_from_log(log)
    result = M.false_gaps(segments, annotation, workday_hours=8.0)

    two = result["stitched"]["N=2s"]
    five = result["stitched"]["N=5s"]
    assert two["total_false_gap_seconds"] == pytest.approx(5.0, rel=0.02)
    assert five["total_false_gap_seconds"] == pytest.approx(0.0, abs=0.05)
    assert five["basis"] == "annotated_identity"


def test_track_that_ends_at_the_exit_is_not_counted_as_broken(tmp_path):
    """
    §4.7 asks how long a track lasts *while the person is still in the room*.
    A person walking out produces a short track that is entirely correct;
    counting it would make the tracker look bad for doing its job.
    """
    log, annotation = _write_scenario(tmp_path)
    segments = segments_from_log(log)
    lifetime = M.track_lifetime(segments, annotation)

    broken = lifetime["broken_while_person_present_seconds"]
    assert broken["count"] == 1, broken
    assert broken["p50"] == pytest.approx(20.0, rel=0.02)
    assert lifetime["raw_seconds"]["count"] == 2


def test_fragmentation_is_measured_and_id_switches_are_not(tmp_path):
    """
    The cheap annotation of §13.8 sees one person split across tracks. It cannot
    see one track carrying two people. Reporting the second as 0 would be a
    fabricated clean bill of health.
    """
    log, annotation = _write_scenario(tmp_path)
    segments = segments_from_log(log)
    continuity = M.identity_continuity(segments, annotation)

    assert continuity["fragmentation"]["tracks_per_person"] == {"P1": 2}
    assert continuity["fragmentation"]["total_extra_tracks"] == 1
    assert continuity["id_switches"]["value"] is None
    assert "track_segments" in continuity["id_switches"]["withheld_reason"]


def test_metrics_without_annotation_are_withheld_not_zero(tmp_path):
    log, _ = _write_scenario(tmp_path)
    segments = segments_from_log(log)

    gaps = M.false_gaps(segments, annotation=None)
    assert gaps["value"] is None
    assert "track_map" in gaps["withheld_reason"]

    lifetime = M.track_lifetime(segments, annotation=None)
    assert lifetime["broken_while_person_present_seconds"]["value"] is None
    # The raw distribution needs no ground truth, so it is still reported.
    assert lifetime["raw_seconds"]["count"] == 2


# --------------------------------------------------------------------------
# Interval algebra
# --------------------------------------------------------------------------

def test_complement_of_full_coverage_is_empty():
    assert M.complement([(0.0, 10.0)], (0.0, 10.0)) == []


def test_complement_finds_leading_and_trailing_gaps():
    gaps = M.complement([(2.0, 4.0)], (0.0, 10.0))
    assert gaps == [(0.0, 2.0), (4.0, 10.0)]


def test_merge_intervals_joins_overlaps():
    assert M.merge_intervals([(0, 5), (3, 8), (20, 21)]) == [(0, 8), (20, 21)]


def test_percentile_interpolates():
    assert M.percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert M.percentile([], 95) is None


# --------------------------------------------------------------------------
# The verdict cannot be talked into GO
# --------------------------------------------------------------------------

def _thresholds(tmp_path: Path, **overrides):
    body = {
        "declared_on": "2026-09-19",
        "max_false_gap_minutes_per_person_per_day": 3.0,
        "min_track_lifetime_seconds_while_present": 30.0,
        "min_recognizable_faces_per_person_hour": None,
        "workday_hours": 8.0,
        "stitch_window_for_verdict_seconds": 5.0,
    }
    body.update(overrides)
    path = tmp_path / "gonogo.yaml"
    path.write_text(
        "\n".join(f"{k}: {'null' if v is None else v}" for k, v in body.items()),
        encoding="utf-8",
    )
    return load_thresholds(path)


def test_unmeasured_metrics_can_never_produce_go(tmp_path):
    thresholds = _thresholds(tmp_path)
    outcome = verdict({"false_gaps": M.withheld("no annotation")}, thresholds)
    assert outcome["verdict"] == INCONCLUSIVE
    assert outcome["verdict"] != GO


def test_a_measured_failure_beats_an_unmeasured_one(tmp_path):
    """NO_GO outranks INCONCLUSIVE: one real failure is a decision, not a gap."""
    thresholds = _thresholds(tmp_path)
    outcome = verdict(
        {
            "false_gaps": {
                "stitched": {
                    "N=5s": {
                        "basis": "annotated_identity",
                        "projected_minutes_per_person_per_day": 40.0,
                    }
                }
            },
            "track_lifetime": {},
        },
        thresholds,
    )
    assert outcome["verdict"] == NO_GO


def test_all_checks_passing_produces_go(tmp_path):
    thresholds = _thresholds(tmp_path)
    outcome = verdict(
        {
            "false_gaps": {
                "stitched": {
                    "N=5s": {
                        "basis": "annotated_identity",
                        "projected_minutes_per_person_per_day": 1.2,
                    }
                }
            },
            "track_lifetime": {
                "broken_while_person_present_seconds": {"p50": 95.0, "count": 12}
            },
        },
        thresholds,
    )
    assert outcome["verdict"] == GO, outcome["reasons"]


def test_proximity_stitched_numbers_are_refused_for_a_verdict(tmp_path):
    """
    Proximity stitching joins two people who cross paths and misses somebody who
    reappears across the room. It is a first look, not evidence.
    """
    thresholds = _thresholds(tmp_path)
    outcome = verdict(
        {
            "false_gaps": {
                "stitched": {
                    "N=5s": {
                        "basis": "proximity_heuristic",
                        "projected_minutes_per_person_per_day": 0.4,
                    }
                }
            },
            "track_lifetime": {
                "broken_while_person_present_seconds": {"p50": 95.0}
            },
        },
        thresholds,
    )
    assert outcome["verdict"] == INCONCLUSIVE


def test_no_thresholds_means_no_verdict():
    outcome = verdict({}, None)
    assert outcome["verdict"] == INCONCLUSIVE
    assert outcome["thresholds"] is None


def test_thresholds_file_is_required_and_has_no_default_in_code(tmp_path):
    with pytest.raises(ThresholdError):
        load_thresholds(tmp_path / "nope.yaml")


def test_go_no_go_numbers_live_outside_the_engine():
    """
    §16: the engine may hold perceptual constants only. A thirty-minute
    allowance and an eight-hour day are company policy, and a benchmark is not
    a loophole. The thresholds file must exist, and it must not be under
    engine/.
    """
    shipped = REPO_ROOT / "bench" / "gonogo.yaml"
    assert shipped.exists(), "bench/gonogo.yaml is missing"
    assert "engine" not in shipped.relative_to(REPO_ROOT).parts

    thresholds_module = (ENGINE_ROOT / "bench" / "thresholds.py").read_text("utf-8")
    for assignment in (
        "max_false_gap_minutes_per_person_per_day =",
        "workday_hours =",
        "min_track_lifetime_seconds_while_present =",
    ):
        assert assignment not in thresholds_module, (
            f"{assignment} is hardcoded in engine/bench/thresholds.py — that is "
            f"a policy constant inside engine/ (§16)"
        )


# --------------------------------------------------------------------------
# The config loader works from an allowlist, not a denylist
# --------------------------------------------------------------------------
#
# B0 shipped a denylist of the key names the old config used for office rules.
# contracts/tools/policy_grep.py flagged config/loader.py for containing them,
# and it was right: a denylist lags whatever leaks in next, and writing the
# forbidden names into engine/ is itself what §16 says to grep for. The loader
# now accepts only what the schema declares.

def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def test_an_unknown_section_is_refused_by_name(tmp_path):
    from engine.config import ConfigBoundaryError, load_config

    path = _write_config(
        tmp_path,
        """
core:
  source_type: mock
office_rules:
  daily_budget_minutes: 30
""",
    )
    with pytest.raises(ConfigBoundaryError, match="office_rules"):
        load_config(path)


def test_an_unknown_key_inside_a_known_section_is_refused(tmp_path):
    """
    The denylist only looked at section names and a fixed list of keys. A rule
    smuggled into `core:` under a name nobody predicted would have passed.
    """
    from engine.config import ConfigBoundaryError, load_config

    path = _write_config(
        tmp_path,
        """
core:
  source_type: mock
  personal_time_budget_minutes: 30
""",
    )
    with pytest.raises(ConfigBoundaryError, match="personal_time_budget_minutes"):
        load_config(path)


def test_a_typo_is_an_error_not_a_silent_default(tmp_path):
    """
    §6.8's "ignore unknown fields" is a rule for the wire protocol, where the
    two sides cannot be deployed together. A config file has no such problem,
    and a benchmark run that silently used a default because of a typo is a
    baseline nobody can trust.
    """
    from engine.config import ConfigBoundaryError, load_config

    path = _write_config(
        tmp_path,
        """
core:
  source_type: mock
tracker:
  track_buffer_secconds: 1.0
""",
    )
    with pytest.raises(ConfigBoundaryError, match="track_buffer_secconds"):
        load_config(path)


def test_the_old_error_name_still_catches_it(tmp_path):
    """PolicyLeakError is kept as an alias so existing callers keep working."""
    from engine.config import PolicyLeakError, load_config

    path = _write_config(tmp_path, "core:\n  source_type: mock\nshift:\n  start: 8")
    with pytest.raises(PolicyLeakError):
        load_config(path)


def test_the_loader_carries_no_denylist():
    text = (ENGINE_ROOT / "config" / "loader.py").read_text("utf-8")
    for leftover in ("FORBIDDEN_SECTIONS", "FORBIDDEN_KEYS", "break_start_hour"):
        assert leftover not in text, (
            f"{leftover} is back in config/loader.py — the allowlist exists so "
            f"the engine never has to name a company rule (§16)"
        )


def test_every_key_in_the_shipped_config_is_declared_by_the_schema():
    """The allowlist is only safe if the config we ship actually satisfies it."""
    from engine.config import load_config

    config = load_config()
    assert config.source_type in ("opencv", "video_file", "mock")


# --------------------------------------------------------------------------
# Report schema
# --------------------------------------------------------------------------

def test_report_schema_only_ever_gains_fields():
    """
    §13.4. The rule is not "this list never changes" — it is that a field may
    be ADDED and an existing one may never be removed or renamed, because every
    baseline already committed was written against the older set. So the lists
    below are the keys as of the step that froze them, and the assertion is a
    subset check.

    When a later step adds a field, this test keeps passing. When someone
    deletes one, it fails, and the three months of baselines that quietly
    became incomparable get noticed on the pull request instead of in an
    argument about a regression.
    """
    frozen_at_b1_top_level = (
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
    frozen_at_b1_metrics = (
        "throughput",
        "latency",
        "track_lifetime",
        "identity_continuity",
        "false_gaps",
        "recognizable_faces",
        "end_to_end_accuracy",
        "detector_throughput_probe",
    )
    # Added by B4. Listed separately so the history of the schema is readable
    # from the test rather than from the git log.
    added_by_b4_metrics = ("timeline",)

    missing_top = [k for k in frozen_at_b1_top_level if k not in FROZEN_TOP_LEVEL_KEYS]
    missing_metrics = [
        k
        for k in frozen_at_b1_metrics + added_by_b4_metrics
        if k not in FROZEN_METRIC_KEYS
    ]
    assert not missing_top, f"removed from the report schema: {missing_top}"
    assert not missing_metrics, f"removed from the metrics schema: {missing_metrics}"


def test_report_records_the_config_contents_not_its_path(tmp_path):
    report = run_bench(
        BenchOptions(mock=True, frames=20, out_dir=tmp_path / "out", label="unit")
    )
    assert isinstance(report["config"]["effective"], dict)
    assert report["config"]["effective"]["tracker"]["track_buffer_seconds"] == 1.0
    assert len(report["config"]["sha256"]) == 64
    for key in FROZEN_TOP_LEVEL_KEYS:
        assert key in report
    for key in FROZEN_METRIC_KEYS:
        assert key in report["metrics"]


def test_report_names_the_classes_that_actually_ran(tmp_path):
    report = run_bench(BenchOptions(mock=True, frames=10, out_dir=tmp_path / "out"))
    stream = report["streams"][0]
    assert stream["detector_class"] == "MockDetector"
    assert stream["tracker_class"] == "MockTracker"
    assert stream["source_class"] == "MockFrameSource"


def test_gpu_utilisation_is_recorded_as_advisory_only(tmp_path):
    report = run_bench(BenchOptions(mock=True, frames=5, out_dir=tmp_path / "out"))
    assert report["environment"]["gpu"]["advisory_only"] is True


# --------------------------------------------------------------------------
# Mode discipline (§13.2)
# --------------------------------------------------------------------------

def test_throughput_mode_withholds_drop_rate(tmp_path):
    report = run_bench(BenchOptions(mock=True, frames=20, out_dir=tmp_path / "out"))
    assert report["metrics"]["throughput"]["drop_rate"]["value"] is None


def test_realtime_mode_withholds_track_quality(tmp_path):
    report = run_bench(
        BenchOptions(mock=True, frames=10, mode="realtime", out_dir=tmp_path / "out")
    )
    metrics = report["metrics"]
    assert metrics["track_lifetime"]["value"] is None
    assert metrics["false_gaps"]["value"] is None
    assert metrics["throughput"]["drop_rate"]["rate"] is not None


def test_realtime_mode_withholds_ingest_latency_because_it_contains_a_sleep(tmp_path):
    report = run_bench(
        BenchOptions(mock=True, frames=10, mode="realtime", out_dir=tmp_path / "out")
    )
    stages = report["metrics"]["latency"]["stages"]
    assert stages["source_ingest"]["value"] is None
    assert stages["total_pipeline"]["value"] is None
    assert stages["detector"]["p95_ms"] is not None


def test_multi_camera_withholds_identity_metrics(tmp_path):
    report = run_bench(
        BenchOptions(mock=True, frames=10, cameras=3, out_dir=tmp_path / "out")
    )
    assert report["metrics"]["track_lifetime"]["value"] is None
    assert any("N=3" in caveat for caveat in report["caveats"])


def test_an_invalid_mode_is_refused():
    with pytest.raises(ValueError):
        BenchOptions(mode="both")


# --------------------------------------------------------------------------
# The seam is still zero-effect
# --------------------------------------------------------------------------

def test_attaching_the_span_recorder_does_not_change_the_output():
    """
    B0 promised the instrumentation would not change behaviour. B1 changed the
    shape of the seam (durations became spans), so the promise is re-tested
    rather than assumed.
    """
    from engine.bench.spans import SpanRecorder
    from engine.config import EngineConfig
    from engine.ingest import MockFrameSource
    from engine.perception import MockDetector, MockTracker
    from engine.pipeline.engine import VisionEngine

    def run(recorder):
        engine = VisionEngine(
            source=MockFrameSource(max_frames=25),
            detector=MockDetector(),
            tracker=MockTracker(),
            config=EngineConfig(source_type="mock"),
            recorder=recorder,
        )
        engine.start()
        out = []
        while True:
            frame, tracks = engine.step()
            if frame is None:
                break
            out.append([(t.track_id, t.bbox.to_xyxy()) for t in tracks])
        engine.stop()
        return out

    assert run(None) == run(SpanRecorder("cam0"))


def test_span_recorder_keeps_exact_counts_even_when_the_ring_wraps():
    """
    A percentile over an unannounced suffix of the run is the sort of number
    that looks fine for months. Counts and means stay exact; the report flags
    the percentiles as tail_only.
    """
    from engine.bench.spans import SpanRecorder

    recorder = SpanRecorder("cam0", capacity=10)
    recorder.begin_frame("cam0", 1, 0.0)
    for i in range(100):
        recorder.record_span("detector", 0.0, 0.001 * (i + 1))

    assert recorder.totals()["detector"].count == 100
    assert recorder.evicted_spans == 90
    summary = M.latency_by_stage([recorder])
    assert summary["sampling"] == "tail_only"
    assert summary["stages"]["detector"]["count"] == 100
    assert summary["stages"]["detector"]["percentile_sample_size"] == 10


# --------------------------------------------------------------------------
# Structural rules
# --------------------------------------------------------------------------

def test_bench_never_names_pipeline_internals():
    """
    §13.9. A bench that reaches into `pipeline.engine` dies at step 6, when the
    engine moves behind a socket — exactly where comparability matters most.
    """
    import ast

    private = {"_engine", "_tracker", "_detector", "_source", "_metrics", "_listeners"}
    offenders = []

    for path in (ENGINE_ROOT / "bench").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "pipeline" in node.module.split("."):
                    offenders.append(f"{path.name}:{node.lineno}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "pipeline" in alias.name.split("."):
                        offenders.append(f"{path.name}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.Attribute) and node.attr in private:
                offenders.append(f"{path.name}:{node.lineno}: .{node.attr}")

    assert not offenders, offenders


def test_bench_runs_without_torch_or_libreyolo():
    """
    §13.9: the bench must run fully on mocks so it can live in CI. If importing
    it drags in torch, the CI job needs a GPU image and stops being run.

    This test was written on a machine where neither package was installed, so
    `'torch/libreyolo in sys.modules` was False no matter what the code did and the test
    passed while proving nothing. It only earned its keep on a developer
    machine that *has* them, where it immediately caught
    `report.package_versions()` importing both in order to read `__version__`.

    Hence the guard: where the packages are absent the test says it cannot
    prove anything rather than reporting a pass.
    """
    import importlib.util

    installed = [
        name
        for name in ("torch", "libreyolo")
        if importlib.util.find_spec(name) is not None
    ]
    if not installed:
        pytest.skip(
            "neither torch nor LibreYOLO is installed here, so this check "
            "cannot fail and must not be counted as a pass. Run it on a "
            "machine with the real detector stack (CI covers the other half: "
            "it installs neither and the mock path must still work)."
        )

    code = (
        "import sys;"
        "import engine.bench.runner as r;"
        "r.run_bench(r.BenchOptions(mock=True, frames=5, out_dir='/tmp/_b1ci'));"
        "print('torch' in sys.modules, 'libreyolo' in sys.modules)"
    )
    result = subprocess_run(code)
    assert result.strip().endswith("False False"), result


def subprocess_run(code: str) -> str:
    import subprocess

    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


# --------------------------------------------------------------------------
# Annotation loading refuses to guess
# --------------------------------------------------------------------------

def test_parse_time_accepts_clock_and_seconds():
    assert parse_time("00:01:30") == pytest.approx(90.0)
    assert parse_time("01:30") == pytest.approx(90.0)
    assert parse_time(90.5) == pytest.approx(90.5)


def test_annotation_rejects_overlapping_presence(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(
        """
recording: {duration_seconds: 100, camera_id: cam0}
persons:
  - id: P1
    presence:
      - {enter: 0, exit: 50}
      - {enter: 40, exit: 90}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AnnotationError, match="overlapping"):
        load_annotation(path)


def test_annotation_rejects_an_interval_past_the_end(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(
        """
recording: {duration_seconds: 100, camera_id: cam0}
persons:
  - id: P1
    presence:
      - {enter: 0, exit: 500}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AnnotationError, match="past the end"):
        load_annotation(path)


def test_annotation_rejects_a_track_mapped_to_an_unknown_person(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(
        """
recording: {duration_seconds: 100, camera_id: cam0}
persons:
  - id: P1
    presence:
      - {enter: 0, exit: 50}
track_map:
  cam0:
    7: P9
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AnnotationError, match="unknown person"):
        load_annotation(path)


def test_annotation_requires_a_duration(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(
        """
recording: {camera_id: cam0}
persons:
  - id: P1
    presence:
      - {enter: 0, exit: 50}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AnnotationError, match="duration_seconds"):
        load_annotation(path)


# --------------------------------------------------------------------------
# Track log
# --------------------------------------------------------------------------

def test_track_log_round_trips_normalized_boxes(tmp_path):
    from engine.bench.tracklog import TrackLogWriter, read_track_log
    from engine.ports.geometry import NormalizedBox
    from engine.ports.observation import FrameObservation, TrackObservation

    path = tmp_path / "t.ndjson"
    with TrackLogWriter(path, "cam0") as writer:
        writer.write(
            FrameObservation(
                camera_id="cam0",
                frame_id=1,
                pts=0.0,
                wallclock=0.0,
                width=1920,
                height=1080,
                tracks=(
                    TrackObservation(
                        track_id=7,
                        box=NormalizedBox(0.1, 0.2, 0.3, 0.4),
                        state="TRACKED",
                        confidence=0.9,
                    ),
                ),
            )
        )
    record = next(iter(read_track_log(path)))
    assert record["tr"][0][:5] == [7, 0.1, 0.2, 0.3, 0.4]


def test_realtime_source_drops_when_the_consumer_falls_behind():
    """
    The drop path is the only thing realtime mode measures that throughput
    cannot, so it needs a test that actually falls behind rather than a hope.
    """
    import time as _time

    from engine.bench.pacing import RealtimeSource
    from engine.bench.spans import SpanRecorder

    class Instant:
        is_running = True
        fps = 1000.0
        total_frames = 0
        source_id = "fake"
        resolution = (2, 2)

        def __init__(self):
            self.n = 0

        def start(self):
            return None

        def stop(self):
            self.is_running = False

        def read(self):
            self.n += 1
            return object() if self.n <= 400 else None

    recorder = SpanRecorder("cam0")
    source = RealtimeSource(Instant(), fps=1000.0, recorder=recorder)
    source.start()
    delivered = 0
    for _ in range(20):
        if source.read() is None:
            break
        delivered += 1
        _time.sleep(0.005)   # 5 ms per frame against a 1 ms deadline

    assert delivered > 0
    assert recorder.dropped_frames > 0, "a consumer 5x too slow must drop frames"
    assert recorder.drop_reasons.get("behind_schedule") == recorder.dropped_frames


def test_realtime_source_refuses_to_pace_against_an_unknown_fps():
    from engine.bench.pacing import RealtimeSource

    with pytest.raises(ValueError, match="fps"):
        RealtimeSource(object(), fps=0.0)


def test_annotation_template_lists_the_tracks_but_invents_no_people(tmp_path):
    """
    The skeleton fills in the mechanical parts. It must not guess a presence
    timeline: a guessed interval in ground truth is fiction with authority.
    """
    from engine.tools.overlay import render_template

    log, _ = _write_scenario(tmp_path)
    out = render_template(log, tmp_path / "skeleton.yaml", camera_id="cam0")
    text = out.read_text("utf-8")

    assert "# 1: P1" in text and "# 2: P1" in text, text
    assert "duration_seconds: 60.0" in text
    # every track_map entry is commented out — the human assigns them
    assert "\n    1: P1" not in text


def test_a_missing_track_log_explains_that_bench_produces_it(tmp_path):
    """
    A track log is an output of the benchmark. Everyone reaches for the overlay
    tool first and gets a bare FileNotFoundError on a path that was never going
    to exist; the error has to say which command creates the file.
    """
    from engine.bench.tracklog import TrackLogNotFound, read_track_log

    with pytest.raises(TrackLogNotFound, match="python -m engine.bench"):
        list(read_track_log(tmp_path / "tracks.ndjson"))


def test_a_missing_track_log_suggests_the_files_that_are_there(tmp_path):
    log, _ = _write_scenario(tmp_path)
    from engine.bench.tracklog import TrackLogNotFound, read_track_log

    with pytest.raises(TrackLogNotFound, match="tracks_cam0.ndjson"):
        list(read_track_log(tmp_path / "tracks.ndjson"))


def test_a_gap_inside_one_track_id_becomes_two_segments(tmp_path):
    """
    ByteTrack keeps a lost track alive for track_buffer frames and then emits it
    again under the same id. Treating that as one continuous appearance hides
    the interruption §4.7 asks us to count.
    """
    path = tmp_path / "t.ndjson"
    lines = []
    for pts in [0.0, 0.1, 0.2, 5.0, 5.1]:
        lines.append(
            json.dumps(
                {
                    "cam": "cam0",
                    "f": int(pts * 10) + 1,
                    "pts": pts,
                    "w": 640,
                    "h": 480,
                    "tr": [[3, 0.1, 0.1, 0.2, 0.5, "TRACKED", 0.9]],
                }
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    segments = segments_from_log(path, max_gap_seconds=0.5)
    assert len(segments) == 2


def test_a_mock_run_is_not_labelled_as_the_opencv_backend(tmp_path):
    """
    The mock source opens no container and decodes nothing, so a caveat telling
    the reader that cv2 discarded the PTS is simply false. It printed anyway,
    because `timeline_summary` defaulted the backend name to "opencv" whenever
    a source did not describe itself. A caveat that is wrong is worse than no
    caveat: it is the report lying about itself in the section whose whole job
    is honesty.
    """
    report = run_bench(BenchOptions(mock=True, frames=20, out_dir=tmp_path / "out"))

    assert report["metrics"]["timeline"]["per_camera"][0]["backend"] == "unknown"
    joined = " ".join(report["caveats"])
    assert "OpenCV backend" not in joined
    assert "Synthetic source" in joined
