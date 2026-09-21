"""
The annotator's tools. §13.8 — the expensive part of B1 is the labelling.

Two commands, both aimed at getting an annotation file written in about an hour
rather than a day.

    # burn track ids into the recording so a human can say "7 and 12 are Budi"
    python -m engine.tools.overlay video \\
        --video recordings/room_morning.mp4 \\
        --track-log bench-out/baseline/tracks_cam0.ndjson \\
        --out bench-out/baseline/overlay.mp4

    # a skeleton annotation, pre-filled with what the run actually saw
    python -m engine.tools.overlay template \\
        --track-log bench-out/baseline/tracks_cam0.ndjson \\
        --video recordings/room_morning.mp4 \\
        --out bench/annotations/room_morning.yaml

The overlay video contains faces. It is the same biometric data as the
recording (§7.4, UU 27/2022) and belongs outside the repository with it.
"""

from __future__ import annotations

import argparse
import colorsys
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..bench.tracklog import read_track_log, segments_from_log


def _colour(track_id: int) -> Tuple[int, int, int]:
    """Stable, well-separated colour per track id. Golden-ratio hue hopping."""
    hue = (track_id * 0.61803398875) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
    return (int(b * 255), int(g * 255), int(r * 255))  # BGR


def render_overlay(
    video: Path,
    track_log: Path,
    out: Path,
    max_frames: Optional[int] = None,
) -> Path:
    import cv2

    video = Path(video)
    if not video.exists():
        raise FileNotFoundError(
            f"Recording not found: {video}. This must be the same file the "
            f"benchmark ran against — the track log's frame ids index into it."
        )

    by_frame: Dict[int, List[list]] = {}
    for record in read_track_log(track_log):
        by_frame[int(record["f"])] = record["tr"]

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {video}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open {out} for writing")

    frame_id = 0
    try:
        while True:
            ok, image = capture.read()
            if not ok or image is None:
                break
            frame_id += 1
            if max_frames is not None and frame_id > max_frames:
                break

            for entry in by_frame.get(frame_id, []):
                track_id = int(entry[0])
                x1 = int(entry[1] * width)
                y1 = int(entry[2] * height)
                x2 = int(entry[3] * width)
                y2 = int(entry[4] * height)
                colour = _colour(track_id)
                cv2.rectangle(image, (x1, y1), (x2, y2), colour, 2)
                label = f"#{track_id} {entry[5]}"
                (tw, th), _ = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                )
                cv2.rectangle(
                    image, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), colour, -1
                )
                cv2.putText(
                    image,
                    label,
                    (x1 + 3, max(th, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 0),
                    2,
                )

            seconds = (frame_id - 1) / fps if fps else 0.0
            stamp = f"{int(seconds // 3600):02d}:{int(seconds // 60) % 60:02d}:{seconds % 60:05.2f}"
            cv2.putText(
                image,
                stamp,
                (12, height - 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )
            writer.write(image)
    finally:
        writer.release()
        capture.release()
    return out


def render_template(
    track_log: Path,
    out: Path,
    video: Optional[Path] = None,
    camera_id: str = "cam0",
) -> Path:
    """
    An annotation skeleton pre-filled with the track ids the run produced.

    It does not guess who anyone is and it does not invent presence intervals:
    those are the human's judgement and inventing them would put fiction into
    ground truth. It fills in the mechanical parts — duration, the recording
    hash, every track id long enough to be worth naming — so the annotator
    spends the hour on the part that needs eyes.
    """
    from ..bench.report import sha256_file
    from ..bench.tracklog import log_span

    span = log_span(track_log)
    duration = round(span[1] - span[0], 3) if span else 0.0
    segments = segments_from_log(track_log)

    by_track: Dict[int, float] = {}
    for segment in segments:
        by_track[segment.track_id] = by_track.get(segment.track_id, 0.0) + segment.duration

    listed = sorted(by_track.items(), key=lambda kv: -kv[1])
    lines: List[str] = []
    lines.append("# Generated skeleton — the presence timeline is yours to write.")
    lines.append("# See engine/bench/annotation.py for the full format.")
    lines.append("")
    lines.append("recording:")
    lines.append(f"  file: {video.name if video else 'UNKNOWN.mp4'}")
    hashed = sha256_file(video) if video else None
    lines.append(f"  sha256: {hashed or 'null'}")
    lines.append(f"  camera_id: {camera_id}")
    lines.append(f"  duration_seconds: {duration}")
    lines.append("  notes: >-")
    lines.append("    Phone recording: wider lens, adaptive exposure, bitrate far above")
    lines.append("    a CCTV substream. Every number from it is an UPPER BOUND.")
    lines.append("")
    lines.append("persons:")
    lines.append("  - id: P1")
    lines.append("    presence:")
    lines.append(
        f'      - {{enter: "00:00:00", exit: "{_clock(duration)}", exit_via_door: false}}'
    )
    lines.append("")
    lines.append("# Track ids this run produced, longest first. Assign each to a person.")
    lines.append("# Leaving one out is fine — it is reported as an unmapped segment.")
    lines.append("track_map:")
    lines.append(f"  {camera_id}:")
    if not listed:
        lines.append("    {}  # the run produced no tracks at all")
    for track_id, seconds in listed:
        lines.append(f"    # {track_id}: P1      # alive {seconds:.1f}s")
    lines.append("")
    lines.append("# Optional and expensive: only needed for real ID switches")
    lines.append("# (one track carrying two people), not fragmentation.")
    lines.append("# track_segments:")
    lines.append('#   - {cam: %s, track: 9, person: P2, from: "00:04:00", to: "00:06:30"}' % camera_id)
    lines.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _clock(seconds: float) -> str:
    return (
        f"{int(seconds // 3600):02d}:"
        f"{int(seconds // 60) % 60:02d}:"
        f"{int(seconds % 60):02d}"
    )


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="engine.tools.overlay")
    sub = parser.add_subparsers(dest="command", required=True)

    video_cmd = sub.add_parser("video", help="burn track ids into the recording")
    video_cmd.add_argument("--video", required=True)
    video_cmd.add_argument("--track-log", required=True)
    video_cmd.add_argument("--out", required=True)
    video_cmd.add_argument("--max-frames", type=int, default=None)

    template_cmd = sub.add_parser("template", help="emit an annotation skeleton")
    template_cmd.add_argument("--track-log", required=True)
    template_cmd.add_argument("--video", default=None)
    template_cmd.add_argument("--out", required=True)
    template_cmd.add_argument("--camera-id", default="cam0")

    args = parser.parse_args(argv)

    if args.command == "video":
        path = render_overlay(
            Path(args.video),
            Path(args.track_log),
            Path(args.out),
            max_frames=args.max_frames,
        )
        print(f"wrote {path}")
        print(
            "This file contains faces. Keep it outside the repository with the "
            "recording (§7.4)."
        )
    else:
        path = render_template(
            Path(args.track_log),
            Path(args.out),
            video=Path(args.video) if args.video else None,
            camera_id=args.camera_id,
        )
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
