"""
The track log: one NDJSON line per processed frame, per camera.

Everything §13.6 asks for is computed from this file *after* the run — raw
track lifetime, stitched effective presence at several window sizes, and (with
an annotation) false gaps. Zero lines of engine code, and the analysis can be
re-run with different parameters without re-running a long recording.

Schema, deliberately terse because a half-hour five-camera run writes
hundreds of thousands of lines:

    {"cam":"cam0","f":412,"pts":16.48,"w":1920,"h":1080,
     "tr":[[7,0.104,0.233,0.191,0.712,"TRACKED",0.91]]}

    cam  camera id
    f    frame id as the source numbered it
    pts  seconds on the source timeline (see StreamDescriptor.pts_source)
    w,h  frame size, so normalized boxes can be put back into pixels
    tr   [track_id, x1, y1, x2, y2, state, confidence], box NORMALIZED to [0,1]

Boxes are normalized because this file is a boundary (ENGINE_PROTOCOL.md §5)
and because the annotator's overlay video and the engine's mainstream may not
be the same resolution.

The same additive-only rule as the protocol (§6.8) applies: a later step may
append a field to the track array or the record, and must never change what an
existing position means.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ..ports.observation import FrameObservation

TRACKLOG_SCHEMA_VERSION = 1


class TrackLogWriter:
    """Buffered NDJSON writer. One file per camera."""

    def __init__(self, path: Path, camera_id: str) -> None:
        self.path = path
        self.camera_id = camera_id
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", encoding="utf-8", buffering=1 << 20)
        self._lines = 0

    def write(self, observation: FrameObservation) -> None:
        record = {
            "cam": observation.camera_id,
            "f": observation.frame_id,
            "pts": round(observation.pts, 4),
            "w": observation.width,
            "h": observation.height,
            "tr": [
                [
                    track.track_id,
                    round(track.box.x1, 5),
                    round(track.box.y1, 5),
                    round(track.box.x2, 5),
                    round(track.box.y2, 5),
                    track.state,
                    round(track.confidence, 4),
                ]
                for track in observation.tracks
            ],
        }
        self._handle.write(json.dumps(record, separators=(",", ":")))
        self._handle.write("\n")
        self._lines += 1

    @property
    def lines(self) -> int:
        return self._lines

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> "TrackLogWriter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class TrackLogNotFound(FileNotFoundError):
    """The track log does not exist — almost always because bench has not run."""


def _explain_missing(path: Path) -> TrackLogNotFound:
    """
    A track log is an *output* of the benchmark, not something you supply.

    Everyone hits this once: the overlay and annotation tools read a file the
    bench run produces, so running them first fails on a path that was never
    going to exist. A bare FileNotFoundError makes that look like a broken tool.
    """
    directory = path.parent
    siblings = (
        sorted(p.name for p in directory.glob("tracks_*.ndjson"))
        if directory.is_dir()
        else []
    )
    hint = (
        f"Did you mean one of: {', '.join(siblings)}?"
        if siblings
        else (
            "Nothing in that directory looks like a track log. Generate one:\n"
            "    python -m engine.bench --source <recording> --mode throughput "
            f"--out {directory}\n"
            "which writes tracks_cam0.ndjson (one file per simulated camera), "
            "spans_cam0.ndjson and baseline.json."
        )
    )
    return TrackLogNotFound(
        f"Track log not found: {path}\n"
        f"A track log is produced BY a benchmark run, not supplied to one. "
        f"{hint}"
    )


def read_track_log(path: Path) -> Iterator[Dict[str, Any]]:
    """Yields raw records. Kept as dicts: the metrics pass is the hot path."""
    path = Path(path)
    if not path.exists():
        raise _explain_missing(path)
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{line_number} is not valid NDJSON: {exc}. A "
                    f"truncated track log means every metric below it is "
                    f"computed over part of the run."
                ) from exc


class TrackSegment:
    """
    One continuous appearance of one track id on one camera.

    A track that the tracker stops emitting and later emits again under the
    same id becomes two segments here, split at any gap longer than
    `max_gap_seconds`. That matters: ByteTrack keeps a lost track alive for
    `track_buffer` frames without reporting it, and treating the whole span as
    continuous would hide exactly the interruption §4.7 asks us to count.
    """

    __slots__ = ("camera_id", "track_id", "start_pts", "end_pts", "frames", "first_box", "last_box")

    def __init__(
        self,
        camera_id: str,
        track_id: int,
        start_pts: float,
        first_box: List[float],
    ) -> None:
        self.camera_id = camera_id
        self.track_id = track_id
        self.start_pts = start_pts
        self.end_pts = start_pts
        self.frames = 1
        self.first_box = first_box
        self.last_box = first_box

    def extend(self, pts: float, box: List[float]) -> None:
        self.end_pts = pts
        self.last_box = box
        self.frames += 1

    @property
    def duration(self) -> float:
        return max(0.0, self.end_pts - self.start_pts)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cam": self.camera_id,
            "track_id": self.track_id,
            "start_pts": round(self.start_pts, 4),
            "end_pts": round(self.end_pts, 4),
            "duration_s": round(self.duration, 4),
            "frames": self.frames,
        }


def segments_from_log(
    path: Path,
    max_gap_seconds: float = 0.5,
) -> List[TrackSegment]:
    """
    Collapses the per-frame log into per-track segments.

    `max_gap_seconds` is the gap within one track id that is treated as the
    same continuous appearance. It defaults to half a second — long enough to
    ride out a single skipped frame at any sane rate, short enough that a
    genuine occlusion becomes two segments and is counted as an interruption.
    """
    open_segments: Dict[tuple, TrackSegment] = {}
    finished: List[TrackSegment] = []

    for record in read_track_log(path):
        cam = record["cam"]
        pts = float(record["pts"])
        seen = set()

        for entry in record["tr"]:
            track_id = int(entry[0])
            box = [float(v) for v in entry[1:5]]
            key = (cam, track_id)
            seen.add(key)

            segment = open_segments.get(key)
            if segment is None or (pts - segment.end_pts) > max_gap_seconds:
                if segment is not None:
                    finished.append(segment)
                open_segments[key] = TrackSegment(cam, track_id, pts, box)
            else:
                segment.extend(pts, box)

    finished.extend(open_segments.values())
    finished.sort(key=lambda s: (s.camera_id, s.start_pts, s.track_id))
    return finished


def log_span(path: Path) -> Optional[tuple]:
    """(first_pts, last_pts, frame_count) of a track log, or None if empty."""
    first = last = None
    count = 0
    for record in read_track_log(path):
        pts = float(record["pts"])
        if first is None:
            first = pts
        last = pts
        count += 1
    if first is None:
        return None
    return (first, last, count)
