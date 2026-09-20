"""
Run this first. It is the only thing that proves the PyAV binding works.

    python -m engine.tools.probe_ingest --video X:\\video.mp4

B4 was written in an environment where PyAV could not be installed, so
everything above the binding is unit-tested against a fake container and the
binding itself is not. This tool is the missing half: it opens one real file
with both backends and reports what each one saw. If it prints sensible numbers,
the binding works; if it does not, nothing else in B4 can be trusted and the
failure shows up in fifteen seconds rather than in a benchmark report.

It also answers, with data rather than inference, the question that moved B4
ahead of the baseline: **how far is `frame_index / fps` from the recording's own
timeline?** For a constant-rate file the answer is zero and the pre-B4 numbers
were fine. For a phone recording the answer is usually not zero, and the
deviation is largest exactly where the recorder was struggling — which is also
where the detector loses people.

Three other things it settles cheaply:

- whether this FFmpeg build has any hardware decoder at all (§5.5 says to check
  rather than believe the documentation);
- whether the two backends agree on the frame count and the rate;
- what the decode actually costs on each, which is the delta B4 is supposed to
  be measured by.

`--json` writes the whole thing to a file so it can go in a commit next to the
baseline it justifies.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def probe_pyav(video: Path, max_frames: Optional[int] = None) -> Dict[str, Any]:
    from ..ingest.pyav_source import PyAVSource, probe_codecs

    result: Dict[str, Any] = {"backend": "pyav", "codecs": probe_codecs()}
    source = PyAVSource(uri=str(video), source_id="probe")

    t0 = time.perf_counter()
    source.start()
    open_seconds = time.perf_counter() - t0

    frames = 0
    first_pts = None
    last_pts = None
    pts_source = "none"
    epochs = set()
    t0 = time.perf_counter()
    while True:
        if max_frames is not None and frames >= max_frames:
            break
        frame = source.read()
        if frame is None:
            break
        frames += 1
        pts_source = frame.metadata.pts_source
        epochs.add(frame.metadata.stream_epoch)
        if frame.metadata.pts is not None:
            if first_pts is None:
                first_pts = frame.metadata.pts
            last_pts = frame.metadata.pts
    decode_seconds = time.perf_counter() - t0

    described = source.describe()
    source.stop()

    result.update(described)
    result.update(
        {
            "open_seconds": round(open_seconds, 4),
            "frames_read": frames,
            "decode_seconds": round(decode_seconds, 4),
            "decode_fps": round(frames / decode_seconds, 2) if decode_seconds else None,
            "pts_source": pts_source,
            "epochs_seen": sorted(epochs),
            "first_pts": first_pts,
            "last_pts": last_pts,
            "pts_span_seconds": (
                None if first_pts is None or last_pts is None else round(last_pts - first_pts, 4)
            ),
        }
    )
    return result


def probe_opencv(video: Path, max_frames: Optional[int] = None) -> Dict[str, Any]:
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        return {"backend": "opencv", "error": f"could not open {video}"}

    reported_fps = capture.get(cv2.CAP_PROP_FPS)
    declared_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    frames = 0
    t0 = time.perf_counter()
    while True:
        if max_frames is not None and frames >= max_frames:
            break
        ok, image = capture.read()
        if not ok or image is None:
            break
        frames += 1
    decode_seconds = time.perf_counter() - t0
    capture.release()

    return {
        "backend": "opencv",
        "reported_fps": round(float(reported_fps or 0.0), 6),
        "declared_frames": declared_frames,
        "frames_read": frames,
        "decode_seconds": round(decode_seconds, 4),
        "decode_fps": round(frames / decode_seconds, 2) if decode_seconds else None,
        "pts_source": "derived_from_fps",
        "note": (
            "cv2.VideoCapture discards the container PTS, so the only timeline "
            "available from this backend is frame_index / reported_fps (§5.5)."
        ),
    }


def _decode_once_pyav(video: Path) -> tuple:
    from ..ingest.pyav_source import PyAVSource

    source = PyAVSource(uri=str(video), source_id="timing",
                        measure_timeline_fidelity=False)
    source.start()
    frames = 0
    t0 = time.perf_counter()
    while source.read() is not None:
        frames += 1
    seconds = time.perf_counter() - t0
    source.stop()
    return frames, seconds


def _decode_once_opencv(video: Path) -> tuple:
    import cv2

    capture = cv2.VideoCapture(str(video))
    frames = 0
    t0 = time.perf_counter()
    while True:
        ok, image = capture.read()
        if not ok or image is None:
            break
        frames += 1
    seconds = time.perf_counter() - t0
    capture.release()
    return frames, seconds


def time_backends(video: Path, repeats: int = 3) -> Dict[str, Any]:
    """
    Decode throughput, measured in a way that can survive being disagreed with.

    The first version of this tool timed each backend exactly once, in a fixed
    order, with no warm-up. Two runs on the same machine and the same file then
    disagreed by more than the effect they were supposed to measure — one said
    PyAV was 6% ahead, the next said OpenCV was 28% ahead. Both were reported
    with three significant figures. Neither meant anything.

    So: a discarded warm-up pass (the first read of a file pays for the OS page
    cache, and whichever backend goes first pays it for the other), then
    `repeats` passes **interleaved**, so that a machine getting slower or busier
    during the measurement hurts both equally. The result is the median, the
    full spread, and an explicit refusal to call a winner when the spread is
    larger than the difference.
    """
    per_backend: Dict[str, List[float]] = {"pyav": [], "opencv": []}

    _decode_once_pyav(video)        # warm the page cache; result discarded
    _decode_once_opencv(video)

    for _ in range(max(1, repeats)):
        for name, fn in (("pyav", _decode_once_pyav), ("opencv", _decode_once_opencv)):
            frames, seconds = fn(video)
            if seconds > 0:
                per_backend[name].append(frames / seconds)

    def summarise(values: List[float]) -> Dict[str, Any]:
        if not values:
            return {"median_fps": None, "min_fps": None, "max_fps": None, "runs": 0}
        ordered = sorted(values)
        median = ordered[len(ordered) // 2]
        return {
            "median_fps": round(median, 2),
            "min_fps": round(ordered[0], 2),
            "max_fps": round(ordered[-1], 2),
            "spread_percent": round((ordered[-1] - ordered[0]) / median * 100, 1),
            "runs": len(values),
        }

    result = {
        "repeats": max(1, repeats),
        "method": (
            "one discarded warm-up pass per backend, then interleaved timed "
            "passes; median reported"
        ),
        "pyav": summarise(per_backend["pyav"]),
        "opencv": summarise(per_backend["opencv"]),
    }

    a, b = result["pyav"]["median_fps"], result["opencv"]["median_fps"]
    if a and b:
        difference = abs(a - b) / max(a, b) * 100
        noise = max(
            result["pyav"].get("spread_percent") or 0.0,
            result["opencv"].get("spread_percent") or 0.0,
        )
        result["difference_percent"] = round(difference, 1)
        result["noise_percent"] = round(noise, 1)
        result["conclusion"] = (
            f"not resolvable: the {difference:.1f}% difference is inside the "
            f"{noise:.1f}% run-to-run spread. Treat decode cost as unchanged by "
            f"B4, which is what both backends going through FFmpeg predicts."
            if difference <= noise
            else (
                f"{'PyAV' if a > b else 'OpenCV'} is {difference:.1f}% faster, "
                f"which is outside the {noise:.1f}% run-to-run spread. If that "
                f"is PyAV losing, it is per-frame Python overhead and should be "
                f"fixed rather than accepted."
            )
        )
    return result


def compare(pyav: Dict[str, Any], opencv: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    a, b = pyav.get("frames_read"), opencv.get("frames_read")
    if a is not None and b is not None:
        out["frame_count_agreement"] = {
            "pyav": a,
            "opencv": b,
            "difference": a - b,
            "note": (
                "a difference here means the two decoders disagree about what "
                "is in the file, which matters more than either number"
                if a != b
                else "both decoders saw the same number of frames"
            ),
        }

    average = pyav.get("average_rate")
    guessed = pyav.get("guessed_rate")
    if average and guessed:
        out["rate_declaration"] = {
            "average_rate": round(average, 6),
            "guessed_rate": round(guessed, 6),
            "variable_rate_signature": abs(average - guessed) > 1e-6,
            "note": (
                "average_rate != guessed_rate is the variable-rate signature: "
                "the container nominally runs at guessed_rate and actually "
                "delivered fewer frames. cv2 reports the average, so the "
                "derived timeline is right on average and wrong locally."
            ),
        }
    return out


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="engine.tools.probe_ingest",
        description="Compare the PyAV and OpenCV ingest backends on one file.",
    )
    parser.add_argument("--video", required=True)
    parser.add_argument(
        "--frames",
        type=int,
        default=None,
        help="stop after N frames (default: the whole file, which is the only "
        "way to see the end-of-file drift)",
    )
    parser.add_argument("--json", default=None, help="write the full result here")
    parser.add_argument("--skip-opencv", action="store_true")
    parser.add_argument(
        "--timing-repeats",
        type=int,
        default=3,
        help="timed decode passes per backend, interleaved, after a discarded "
        "warm-up. 0 skips the timing entirely",
    )
    args = parser.parse_args(argv)

    video = Path(args.video)
    if not video.exists():
        print(f"not found: {video}", file=sys.stderr)
        return 2

    result: Dict[str, Any] = {"video": str(video)}
    result["pyav"] = probe_pyav(video, args.frames)
    if not args.skip_opencv:
        result["opencv"] = probe_opencv(video, args.frames)
        result["comparison"] = compare(result["pyav"], result["opencv"])
        if args.timing_repeats > 0 and args.frames is None:
            result["decode_timing"] = time_backends(video, args.timing_repeats)

    pyav = result["pyav"]
    fidelity = pyav.get("timeline_fidelity") or {}

    print()
    print(f"  file            {video.name}")
    print(f"  frames          pyav {pyav.get('frames_read')}"
          + (f"   opencv {result['opencv'].get('frames_read')}"
             if "opencv" in result else ""))
    print(f"  average_rate    {pyav.get('average_rate')}")
    print(f"  guessed_rate    {pyav.get('guessed_rate')}")
    print(f"  declared frames {pyav.get('declared_frames')}   "
          f"duration {pyav.get('duration_seconds')}s")
    print()
    print("  How wrong a DURATION can be on the derived timeline")
    print("  (this is the number to read — a deviation that is a slow ramp")
    print("   barely affects any interval, one that steps does):")
    for window, error in (fidelity.get("interval_error_s") or {}).items():
        print(f"    a gap of {window:<8} can be off by  {error} s")
    print()
    print("  Shape of the deviation itself (context, not the verdict):")
    print(f"    max deviation   {fidelity.get('max_abs_deviation_s')} s"
          f"   (at pts {fidelity.get('max_deviation_at_pts_s')})")
    print(f"    rms deviation   {fidelity.get('rms_deviation_s')} s")
    print(f"    final drift     {fidelity.get('final_drift_s')} s")
    print(f"    long intervals  {fidelity.get('long_frame_intervals')}")
    print()
    print(f"    -> {fidelity.get('verdict')}")
    print()

    threading = pyav.get("decoder_threading") or {}
    print(f"  decoder threads request={threading.get('requested')} "
          f"applied_to={threading.get('applied_to')}"
          + (f"  refused={threading.get('refused_by')}"
             if threading.get("refused_by") else ""))
    if threading.get("warning"):
        print(f"    !! {threading['warning']}")
    print()

    timing = result.get("decode_timing")
    if timing:
        print("  Decode throughput (interleaved, warm cache, median of "
              f"{timing['repeats']}):")
        for name in ("pyav", "opencv"):
            entry = timing[name]
            print(f"    {name:<8} {entry['median_fps']} fps  "
                  f"(range {entry['min_fps']}–{entry['max_fps']}, "
                  f"spread {entry.get('spread_percent')}%)")
        print(f"    -> {timing.get('conclusion')}")
        print()

    codecs = pyav.get("codecs") or {}
    print(f"  hardware decoders in this build: "
          f"{codecs.get('hardware_decoders') or 'none'}")
    print(f"  ({codecs.get('note')})")
    print()

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"  written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
