"""
The second go/no-go metric: how often a usable face actually appears.

§3.1 changed the identity strategy from "verify periodically" to "catch the
rare good moment and hold it through tracking", on the assumption that people
in a corner-mounted room spend most of their time facing away. §13.5 turns that
assumption into a number: **how often a recognizable face shows up, per person
per hour.** If the answer is "twice an hour", the whole `HELD`-state design is
load-bearing and B6c's quality gate is urgent. If it is "forty times an hour",
several later steps are solving a problem that is not there.

Scope, stated plainly because it is a hole in the plan and not a detail:
**B0 did not port a face detector.** SCRFD lives in the old
`plugins/face_recognizer/`, and that whole area belongs to the identity layer
(Engine A). So this module ships the harness — an offline second pass over the
recording that crops head regions from the track log and asks a probe "is there
a usable face here?" — plus a probe that uses the frontal-face cascade bundled
with OpenCV.

That cascade is a *lower bound* and is labelled as one everywhere it appears.
It is a 2001 detector: it finds frontal, reasonably lit, reasonably large faces
and misses plenty that SCRFD would catch. A number from it answers "does a
usable face ever appear, and roughly how rarely" — which is the shape of the
question §3.1 asks — and it will understate the real rate. Nobody should quote
it as the production figure. When SCRFD lands in `identity/`, it satisfies the
same `FaceProbe` protocol, `probe` in the report changes, and the field
keeps its meaning.

The pass is entirely offline: it re-opens the recording afterwards and reads
the track log. Zero lines of engine code, and no effect whatsoever on the
latency numbers the run produced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from .annotation import Annotation
from .tracklog import read_track_log

logger = logging.getLogger("engine.bench.faceprobe")

# Fraction of a person box, measured from the top, treated as the head region.
# §12 ("head-crop") uses 30–40%; the midpoint is fine for a counting pass.
HEAD_FRACTION = 0.35

# A face smaller than this, aligned to 112×112, is being upscaled — which is
# exactly the enrollment gate of §10 applied to runtime. Counting such a face as
# "recognizable" would inflate the metric with faces the embedder cannot use.
MIN_FACE_PIXELS = 32


class FaceProbe(Protocol):
    """Answers one question about one head crop."""

    name: str
    is_lower_bound: bool

    def usable_faces(self, crop: Any) -> int:
        """How many usable faces this crop contains."""
        ...


class HaarFrontalFaceProbe:
    """
    OpenCV's bundled frontal-face cascade. A lower bound, and labelled as one.

    Chosen because it ships with opencv-python — no weights to download, no
    licence question, and it runs in CI. It is deliberately not tuned: tuning a
    proxy detector to produce a nicer number is how a benchmark starts lying.
    """

    name = "opencv_haar_frontalface_default"
    is_lower_bound = True

    def __init__(self, min_face_pixels: int = MIN_FACE_PIXELS) -> None:
        import cv2

        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        if not path.exists():
            raise RuntimeError(
                f"OpenCV cascade not found at {path}. Install opencv-python, or "
                f"pass a different probe."
            )
        self._cascade = cv2.CascadeClassifier(str(path))
        if self._cascade.empty():
            raise RuntimeError(f"Failed to load cascade from {path}.")
        self._min = min_face_pixels
        self._cv2 = cv2

    def usable_faces(self, crop: Any) -> int:
        if crop is None or crop.size == 0:
            return 0
        gray = self._cv2.cvtColor(crop, self._cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(self._min, self._min),
        )
        return int(len(faces))


@dataclass
class FaceProbeResult:
    probe: str
    is_lower_bound: bool
    sample_interval_seconds: float
    frames_sampled: int
    crops_examined: int
    crops_with_face: int
    per_track: Dict[int, int]
    duration_seconds: float

    def as_dict(self, annotation: Optional[Annotation]) -> Dict[str, Any]:
        hours = self.duration_seconds / 3600.0
        out: Dict[str, Any] = {
            "probe": self.probe,
            "is_lower_bound": self.is_lower_bound,
            "caveat": (
                "lower bound: this probe finds frontal, well-lit, reasonably "
                "large faces only. The real rate with SCRFD will be higher."
            )
            if self.is_lower_bound
            else None,
            "sample_interval_seconds": self.sample_interval_seconds,
            "frames_sampled": self.frames_sampled,
            "crops_examined": self.crops_examined,
            "crops_with_face": self.crops_with_face,
            "hit_rate": (
                round(self.crops_with_face / self.crops_examined, 5)
                if self.crops_examined
                else None
            ),
            "per_track_hits": dict(sorted(self.per_track.items())),
        }

        if annotation is not None and annotation.has_track_map and hours > 0:
            per_person: Dict[str, int] = {}
            for track_id, hits in self.per_track.items():
                person_id = annotation.person_of_track(annotation.camera_id, track_id)
                if person_id is None:
                    continue
                per_person[person_id] = per_person.get(person_id, 0) + hits
            if per_person:
                rates = {
                    person_id: round(hits / hours, 3)
                    for person_id, hits in sorted(per_person.items())
                }
                out["per_person_hour_by_person"] = rates
                out["per_person_hour"] = round(
                    sum(rates.values()) / len(rates), 3
                )
                return out

        out["per_person_hour"] = None
        out["per_person_hour_withheld_reason"] = (
            "needs annotation.track_map to attribute face sightings to people"
        )
        return out


def run_face_probe(
    video_path: Path,
    track_log: Path,
    probe: FaceProbe,
    sample_interval_seconds: float = 1.0,
    annotation: Optional[Annotation] = None,
) -> FaceProbeResult:
    """
    Second pass over the recording, sampling the track log.

    Sampling rather than every frame: consecutive frames are near-identical, so
    counting each one would report "a face was visible for 40 frames" as forty
    sightings. One sample per second answers the question §3.1 actually asks —
    how many *opportunities* per hour — without that inflation.
    """
    import cv2

    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Recording not found for the face probe: {video_path}")

    wanted: List[Tuple[int, float, List[Any]]] = []
    next_pts = -1.0
    first_pts = last_pts = None
    for record in read_track_log(track_log):
        pts = float(record["pts"])
        if first_pts is None:
            first_pts = pts
        last_pts = pts
        if pts + 1e-9 < next_pts:
            continue
        next_pts = pts + sample_interval_seconds
        if record["tr"]:
            wanted.append((int(record["f"]), pts, record["tr"]))

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {video_path} for the face probe.")

    per_track: Dict[int, int] = {}
    crops = 0
    hits = 0
    sampled = 0
    try:
        for frame_id, _pts, entries in wanted:
            # Frame ids in the log are 1-based as the source numbered them.
            capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_id - 1))
            ok, image = capture.read()
            if not ok or image is None:
                logger.warning("face probe could not seek to frame %d", frame_id)
                continue
            sampled += 1
            height, width = image.shape[:2]

            for entry in entries:
                track_id = int(entry[0])
                x1 = int(entry[1] * width)
                y1 = int(entry[2] * height)
                x2 = int(entry[3] * width)
                y2 = int(entry[4] * height)
                head_bottom = int(y1 + (y2 - y1) * HEAD_FRACTION)
                x1, y1 = max(0, x1), max(0, y1)
                x2 = min(width, x2)
                head_bottom = min(height, head_bottom)
                if x2 - x1 < MIN_FACE_PIXELS or head_bottom - y1 < MIN_FACE_PIXELS:
                    continue
                crop = image[y1:head_bottom, x1:x2].copy()
                crops += 1
                if probe.usable_faces(crop) > 0:
                    hits += 1
                    per_track[track_id] = per_track.get(track_id, 0) + 1
    finally:
        capture.release()

    duration = 0.0
    if first_pts is not None and last_pts is not None:
        duration = max(0.0, last_pts - first_pts)

    return FaceProbeResult(
        probe=probe.name,
        is_lower_bound=bool(probe.is_lower_bound),
        sample_interval_seconds=sample_interval_seconds,
        frames_sampled=sampled,
        crops_examined=crops,
        crops_with_face=hits,
        per_track=per_track,
        duration_seconds=duration,
    )
