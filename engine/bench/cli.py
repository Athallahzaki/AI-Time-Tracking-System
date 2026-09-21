"""
`python -m engine.bench` — the command every later step is measured with.

    # CI: no GPU, no weights, no recording
    python -m engine.bench --mock --frames 300 --out bench-out/smoke

    # the real baseline
    python -m engine.bench \\
        --source recordings/room_morning.mp4 \\
        --mode throughput \\
        --annotation bench/annotations/room_morning.yaml \\
        --thresholds bench/gonogo.yaml \\
        --face-probe \\
        --out bench-out/baseline

    # what production actually does
    python -m engine.bench --source recordings/room_morning.mp4 \\
        --mode realtime --cameras 5 --out bench-out/realtime-5cam

Two runs, because §13.2 refuses to mix them: throughput answers what a frame
costs, realtime answers what survives. Fields the mode cannot justify come back
null with the reason attached.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .runner import MODES, BenchOptions, run_bench


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine.bench",
        description="Benchmark harness (ARCHITECTURE.md §13).",
    )
    parser.add_argument("--config", default=None, help="path to a YAML engine config")
    parser.add_argument("--source", default=None, help="recording to play")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="synthetic source, detector and tracker — no GPU, no weights",
    )
    parser.add_argument("--mode", choices=MODES, default="throughput")
    parser.add_argument(
        "--cameras",
        type=int,
        default=1,
        help="simulate N cameras from the same file at random offsets. "
        "Identity and track-quality metrics are reported for N=1 only (§13.2)",
    )
    parser.add_argument("--frames", type=int, default=None, help="stop after N frames")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--out", default="bench-out", help="output directory")
    parser.add_argument("--label", default="", help="free-text name for this run")
    parser.add_argument(
        "--annotation",
        default=None,
        help="ground-truth YAML (§13.8). Without it BOTH product metrics are "
        "unmeasured and the verdict cannot be GO",
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help="pre-registered go/no-go thresholds (§13.7). Deliberately has no "
        "default in code: see bench/thresholds.py",
    )
    parser.add_argument(
        "--face-probe",
        action="store_true",
        help="second offline pass counting recognizable faces (§3.1, §13.5)",
    )
    parser.add_argument("--face-sample-interval", type=float, default=1.0)
    parser.add_argument(
        "--detector-probe-iters",
        type=int,
        default=0,
        help="measure raw detector inferences/second; divide by 150 for the "
        "five-camera question in §8",
    )
    parser.add_argument("--span-capacity", type=int, default=500_000)
    parser.add_argument("--track-gap-seconds", type=float, default=0.5)
    parser.add_argument(
        "--recording-is-cctv",
        action="store_true",
        help="the recording came from the real camera, not a phone; drops the "
        "'these numbers are an upper bound' caveat",
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--print-report",
        action="store_true",
        help="dump the full JSON to stdout as well as writing it",
    )
    return parser


def summarize(report: Dict[str, Any]) -> str:
    run = report["run"]
    metrics = report["metrics"]
    throughput = metrics["throughput"]
    lines = [
        "",
        f"  mode            {run['mode']}   cameras {run['cameras']}   "
        f"frames {run['frames_processed']}",
        f"  fps aggregate   {throughput.get('fps_aggregate')}",
    ]

    stages = metrics["latency"].get("stages", {})
    reported = {
        stage: data
        for stage, data in stages.items()
        if isinstance(data, dict) and data.get("p95_ms") is not None
    }
    if reported:
        lines.append(
            "  latency p95     "
            + "  ".join(
                f"{stage}={data['p95_ms']}ms"
                for stage, data in reported.items()
                if stage != "total_pipeline"
            )
        )
        total = reported.get("total_pipeline")
        if total:
            lines.append(
                f"  total_pipeline  p50={total['p50_ms']}ms "
                f"p95={total['p95_ms']}ms p99={total['p99_ms']}ms "
                f"({metrics['latency']['sampling']})"
            )

    drop = throughput.get("drop_rate")
    if isinstance(drop, dict) and "rate" in drop:
        lines.append(
            f"  drop rate       {drop['rate']} "
            f"({drop['dropped_frames']}/{drop['offered_frames']})"
        )

    lifetime = metrics.get("track_lifetime")
    if isinstance(lifetime, dict) and "raw_seconds" in lifetime:
        raw = lifetime["raw_seconds"]
        lines.append(
            f"  track lifetime  raw p50={raw['p50']}s  mean={raw['mean']}s  "
            f"n={raw['count']}"
        )
        for window, data in lifetime.get("stitched_seconds", {}).items():
            lines.append(
                f"    stitched {window:<8} p50={data['p50']}s  "
                f"chains={data['chains']}  basis={data['basis']}"
            )
        broken = lifetime.get("broken_while_person_present_seconds")
        if isinstance(broken, dict) and broken.get("count"):
            lines.append(
                f"  broke while present  p50={broken['p50']}s  n={broken['count']}"
            )

    gaps = metrics.get("false_gaps")
    if isinstance(gaps, dict) and "raw" in gaps:
        raw = gaps["raw"]
        lines.append(
            f"  false gaps      {raw['total_false_gap_seconds']}s over "
            f"{raw['total_presence_seconds']}s of presence "
            f"({raw['false_gap_seconds_per_person_hour']}s per person-hour)"
        )
        for window, data in gaps.get("stitched", {}).items():
            lines.append(
                f"    stitched {window:<8} "
                f"{data['false_gap_seconds_per_person_hour']}s/person-hour  "
                f"-> {data['projected_minutes_per_person_per_day']} min/day"
            )

    exits = metrics.get("zone_exits")
    if isinstance(exits, dict) and "endings_by_zone" in exits:
        by_zone = exits["endings_by_zone"]
        breakdown = "  ".join(f"{zone}={count}" for zone, count in by_zone.items())
        lines.append(
            f"  where tracks end {breakdown}  "
            f"(interior {exits['interior_ending_fraction']:.0%} of "
            f"{exits['total_endings']})"
        )
        if exits.get("caveat"):
            # Printed, not buried in the JSON: an interior fraction of 100% on a
            # camera with no door region looks alarming and means nothing.
            lines.append(f"    !! {exits['caveat']}")
        present = exits.get("while_person_present")
        if isinstance(present, dict) and present.get("endings"):
            lines.append(
                f"    while someone was present: {present['endings_in_interior']}"
                f"/{present['endings']} ended mid-room — count, not minutes"
            )

    queue = metrics.get("recognition_queue")
    if isinstance(queue, dict) and "submitted_total" in queue:
        lines.append(
            f"  recognition q   submitted={queue['submitted_total']:.0f}  "
            f"handed_out={queue['handed_out_total']:.0f}  "
            f"aged_out={queue['dropped_stale_total']:.0f}  "
            f"depth_at_end={queue['depth_at_end']:.0f}"
        )
        if not queue.get("had_consumer", False):
            # Staleness is swept when a request is popped, and with nothing
            # consuming the queue nothing is ever popped — so `aged_out` being
            # zero does NOT mean requests were fresh. Depth and age below
            # describe an unconsumed queue, which is what B5 built on purpose:
            # the worker pool is the last step in the B track (§5.2).
            lines.append(
                "    nothing consumes the queue yet (§5.2): depth only grows and "
                "aged_out stays 0 because staleness is swept at pop, not in the "
                "queue. Order is what B5 measures here, not throughput"
            )

    faces = metrics.get("recognizable_faces")
    if isinstance(faces, dict) and faces.get("per_person_hour") is not None:
        lines.append(
            f"  usable faces    {faces['per_person_hour']} per person-hour "
            f"({faces['probe']}, lower bound={faces['is_lower_bound']})"
        )

    probe = metrics.get("detector_throughput_probe")
    if isinstance(probe, dict) and probe.get("inferences_per_second"):
        ips = probe["inferences_per_second"]
        lines.append(
            f"  detector        {ips} inferences/s -> "
            f"{ips / 150.0:.2f}x the 5-camera 30 fps budget (§8)"
        )

    gonogo = report["go_no_go"]
    lines.append("")
    lines.append(f"  VERDICT: {gonogo['verdict']}")
    for reason in gonogo["reasons"]:
        lines.append(f"    - {reason}")

    lines.append("")
    lines.append("  Caveats printed with the numbers, on purpose:")
    for caveat in report["caveats"]:
        lines.append(f"    * {caveat}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    options = BenchOptions(
        config_path=args.config,
        source=args.source,
        mock=args.mock,
        mode=args.mode,
        cameras=args.cameras,
        frames=args.frames,
        seed=args.seed,
        out_dir=Path(args.out),
        annotation_path=args.annotation,
        thresholds_path=args.thresholds,
        face_probe=args.face_probe,
        face_sample_interval=args.face_sample_interval,
        detector_probe_iters=args.detector_probe_iters,
        span_capacity=args.span_capacity,
        track_gap_seconds=args.track_gap_seconds,
        recording_is_phone=not args.recording_is_cctv,
        label=args.label,
    )

    from .report import write_report

    report = run_bench(options)
    path = write_report(report, options.out_dir / "baseline.json")

    if args.print_report:
        print(json.dumps(report, indent=2))
    print(summarize(report))
    print(f"  report: {path}")

    return 0 if report["go_no_go"]["verdict"] != "NO_GO" else 2


if __name__ == "__main__":
    sys.exit(main())
