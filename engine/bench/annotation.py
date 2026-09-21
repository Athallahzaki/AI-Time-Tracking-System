"""
Ground truth: who was in the room, when, and which track was whom.

ARCHITECTURE.md §13.8 is blunt about this and it is worth repeating, because
the previous revision of the plan costed the camera and forgot to cost the
label: **the expensive part of B1 is not recording, it is annotating.** "How
long does a track survive while the person is still in the room" cannot be
measured unless something knows the person was still in the room. Without this
file the benchmark still runs and still reports latency and FPS — but both
go/no-go metrics come back `null`, and the verdict comes back INCONCLUSIVE. It
does not come back GO.

The format is deliberately the cheap one §13.8 describes: a presence timeline
per person, not a label per frame. Thirty minutes with five people is roughly
15–25 intervals, about an hour of work.

    recording:
      file: room_morning_2026-09-22.mp4
      sha256: 8f3c...            # the video is NOT committed; its hash is
      camera_id: cam0
      duration_seconds: 1812.4
      notes: phone on a shelf in the north-east corner, ~2.6 m

    persons:
      - id: P1
        presence:
          - {enter: "00:00:00", exit: "00:12:30", exit_via_door: true}
          - {enter: "00:18:05", exit: "00:30:12", exit_via_door: false}

    track_map:                   # optional, but both product metrics need it
      cam0:
        7: P1
        12: P1
        9: P2

    track_segments:              # optional, expensive, see below
      - {cam: cam0, track: 9, person: P2, from: "00:04:00", to: "00:06:30"}

**`track_map` measures fragmentation, not ID switches, and the difference
matters.** The cheap annotation says "track 7 and track 12 are the same
person": that is one person broken into several tracks — fragmentation, which
is exactly the failure mode that manufactures false breaks (§4.1). An ID
switch is the opposite: one track that contains two different people, which is
how one employee's time lands on another's record. It needs `track_segments`,
which is per-segment labelling and far more work. Whichever you do not supply
is reported as `null`. It is never reported as zero.

`exit_via_door` stands in for the `door_region` that arrives in step B5: a
track that ends while the person is still inside is a false break, a track that
ends because they walked out is not. Until zones exist, the annotator says so.

**The video is not committed. The annotation is.** It is biometric data about
colleagues, §7.4 already invokes UU 27/2022, and git means retention forever.
Keep the recording outside the repository, record its hash here, and get
written consent before recording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")


class AnnotationError(ValueError):
    """The annotation file is unusable. Never downgraded to a warning."""


def parse_time(value: Any, field_name: str = "time") -> float:
    """Accepts 12.5, "00:12:30", "12:30.5". Returns seconds from recording start."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        match = _CLOCK.match(value.strip())
        if not match:
            raise AnnotationError(
                f"{field_name}={value!r} is not a time. Use seconds (12.5) or "
                f"HH:MM:SS / MM:SS."
            )
        hours, minutes, secs = match.groups()
        seconds = (
            float(hours or 0) * 3600.0 + float(minutes) * 60.0 + float(secs)
        )
    else:
        raise AnnotationError(f"{field_name}={value!r} is not a time.")
    if seconds < 0.0:
        raise AnnotationError(f"{field_name}={value!r} is negative.")
    return seconds


@dataclass(frozen=True)
class PresenceInterval:
    """One continuous stretch during which a person was in the room."""

    enter: float
    exit: float
    exit_via_door: bool = True

    @property
    def duration(self) -> float:
        return max(0.0, self.exit - self.enter)


@dataclass(frozen=True)
class Person:
    person_id: str
    presence: Tuple[PresenceInterval, ...]

    @property
    def total_presence_seconds(self) -> float:
        return sum(interval.duration for interval in self.presence)


@dataclass(frozen=True)
class TrackSegmentLabel:
    """One track carried one person between two times. The expensive form."""

    camera_id: str
    track_id: int
    person_id: str
    start: float
    end: float


@dataclass(frozen=True)
class Annotation:
    recording_file: str
    recording_sha256: Optional[str]
    camera_id: str
    duration_seconds: float
    persons: Tuple[Person, ...]
    track_map: Dict[str, Dict[int, str]] = field(default_factory=dict)
    track_segments: Tuple[TrackSegmentLabel, ...] = ()
    notes: str = ""
    source_path: Optional[str] = None

    @property
    def has_track_map(self) -> bool:
        return any(self.track_map.values())

    @property
    def has_track_segments(self) -> bool:
        return bool(self.track_segments)

    @property
    def total_presence_seconds(self) -> float:
        return sum(person.total_presence_seconds for person in self.persons)

    def person_of_track(self, camera_id: str, track_id: int) -> Optional[str]:
        return self.track_map.get(camera_id, {}).get(track_id)

    def person(self, person_id: str) -> Optional[Person]:
        for candidate in self.persons:
            if candidate.person_id == person_id:
                return candidate
        return None

    def summary(self) -> Dict[str, Any]:
        return {
            "source": self.source_path,
            "recording_file": self.recording_file,
            "recording_sha256": self.recording_sha256,
            "camera_id": self.camera_id,
            "duration_seconds": round(self.duration_seconds, 3),
            "persons": len(self.persons),
            "presence_intervals": sum(len(p.presence) for p in self.persons),
            "total_presence_seconds": round(self.total_presence_seconds, 3),
            "has_track_map": self.has_track_map,
            "has_track_segments": self.has_track_segments,
            "notes": self.notes,
        }


def load_annotation(path: Path) -> Annotation:
    """Reads and validates an annotation file. Raises rather than degrading."""
    import yaml

    path = Path(path)
    if not path.exists():
        raise AnnotationError(f"Annotation file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise AnnotationError(f"{path}: root must be a mapping.")

    recording = raw.get("recording") or {}
    if not isinstance(recording, dict):
        raise AnnotationError(f"{path}: 'recording' must be a mapping.")

    duration = recording.get("duration_seconds")
    if duration is None:
        raise AnnotationError(
            f"{path}: recording.duration_seconds is required — every interval "
            f"is validated against it, and an interval past the end of the "
            f"recording silently inflates presence."
        )
    duration = parse_time(duration, "recording.duration_seconds")
    camera_id = str(recording.get("camera_id", "cam0"))

    persons: List[Person] = []
    raw_persons = raw.get("persons") or []
    if not isinstance(raw_persons, list) or not raw_persons:
        raise AnnotationError(f"{path}: 'persons' must be a non-empty list.")

    seen_ids = set()
    for index, raw_person in enumerate(raw_persons):
        if not isinstance(raw_person, dict) or "id" not in raw_person:
            raise AnnotationError(f"{path}: persons[{index}] needs an 'id'.")
        person_id = str(raw_person["id"])
        if person_id in seen_ids:
            raise AnnotationError(f"{path}: duplicate person id {person_id!r}.")
        seen_ids.add(person_id)

        intervals: List[PresenceInterval] = []
        for j, raw_interval in enumerate(raw_person.get("presence") or []):
            where = f"{path}: persons[{person_id}].presence[{j}]"
            if not isinstance(raw_interval, dict):
                raise AnnotationError(f"{where} must be a mapping.")
            enter = parse_time(raw_interval.get("enter", 0.0), f"{where}.enter")
            exit_at = parse_time(
                raw_interval.get("exit", duration), f"{where}.exit"
            )
            if exit_at <= enter:
                raise AnnotationError(f"{where}: exit must be after enter.")
            if exit_at > duration + 1e-6:
                raise AnnotationError(
                    f"{where}: exit {exit_at:.2f}s is past the end of the "
                    f"recording ({duration:.2f}s)."
                )
            intervals.append(
                PresenceInterval(
                    enter=enter,
                    exit=exit_at,
                    exit_via_door=bool(raw_interval.get("exit_via_door", True)),
                )
            )

        if not intervals:
            raise AnnotationError(
                f"{path}: person {person_id!r} has no presence intervals. A "
                f"person who was never in the room is not ground truth, it is "
                f"a typo."
            )

        intervals.sort(key=lambda i: i.enter)
        for a, b in zip(intervals, intervals[1:]):
            if b.enter < a.exit:
                raise AnnotationError(
                    f"{path}: person {person_id!r} has overlapping presence "
                    f"intervals ({a.enter:.1f}–{a.exit:.1f} and "
                    f"{b.enter:.1f}–{b.exit:.1f}). One person cannot be in the "
                    f"room twice."
                )
        persons.append(Person(person_id=person_id, presence=tuple(intervals)))

    track_map: Dict[str, Dict[int, str]] = {}
    for cam, mapping in (raw.get("track_map") or {}).items():
        if not isinstance(mapping, dict):
            raise AnnotationError(f"{path}: track_map[{cam}] must be a mapping.")
        per_camera: Dict[int, str] = {}
        for track_id, person_id in mapping.items():
            person_id = str(person_id)
            if person_id not in seen_ids:
                raise AnnotationError(
                    f"{path}: track_map[{cam}][{track_id}] points at unknown "
                    f"person {person_id!r}."
                )
            per_camera[int(track_id)] = person_id
        track_map[str(cam)] = per_camera

    segments: List[TrackSegmentLabel] = []
    for index, raw_segment in enumerate(raw.get("track_segments") or []):
        where = f"{path}: track_segments[{index}]"
        if not isinstance(raw_segment, dict):
            raise AnnotationError(f"{where} must be a mapping.")
        person_id = str(raw_segment.get("person", ""))
        if person_id not in seen_ids:
            raise AnnotationError(f"{where} points at unknown person {person_id!r}.")
        segments.append(
            TrackSegmentLabel(
                camera_id=str(raw_segment.get("cam", camera_id)),
                track_id=int(raw_segment["track"]),
                person_id=person_id,
                start=parse_time(raw_segment.get("from", 0.0), f"{where}.from"),
                end=parse_time(raw_segment.get("to", duration), f"{where}.to"),
            )
        )

    return Annotation(
        recording_file=str(recording.get("file", "")),
        recording_sha256=recording.get("sha256"),
        camera_id=camera_id,
        duration_seconds=duration,
        persons=tuple(persons),
        track_map=track_map,
        track_segments=tuple(segments),
        notes=str(recording.get("notes", "")),
        source_path=str(path),
    )


TEMPLATE = """\
# Ground truth for one representative recording (ARCHITECTURE.md §13.8).
#
# The video itself is NOT committed — it is biometric data about colleagues
# (§7.4, UU 27/2022) and git keeps things forever. Store it outside the repo,
# put its sha256 here, and get written consent before recording.
#
# Times are seconds from the start of the recording, or HH:MM:SS.

recording:
  file: room_morning.mp4
  sha256: null            # shasum -a 256 room_morning.mp4
  camera_id: cam0
  duration_seconds: 0.0   # required
  notes: >-
    Phone, not a CCTV camera: wider lens, adaptive exposure, much higher
    bitrate than a substream and no rolling-shutter artefacts. Every number
    derived from it is an UPPER BOUND on what the real camera will do.

persons:
  - id: P1
    presence:
      - {enter: "00:00:00", exit: "00:12:30", exit_via_door: true}
      # exit_via_door: false means they were still in the room / the recording
      # ended / they left the frame without using the door.

# Optional but required for BOTH product metrics. Cheap form: which tracks
# belonged to whom. Produce it from the overlay video:
#   python -m engine.tools.overlay --video room_morning.mp4 \\
#       --track-log out/tracks_cam0.ndjson --out out/overlay.mp4
# track_map:
#   cam0:
#     7: P1
#     12: P1

# Optional, expensive: needed only for real ID switches (one track carrying two
# people), as opposed to fragmentation (one person split across tracks).
# track_segments:
#   - {cam: cam0, track: 9, person: P2, from: "00:04:00", to: "00:06:30"}
"""
