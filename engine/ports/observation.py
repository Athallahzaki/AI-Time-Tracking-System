"""
What an observer of the engine is allowed to see.

ARCHITECTURE.md §13.9: the benchmark talks to `ports/`, never to
`pipeline.engine`, and never reads a private attribute. The reason is not
tidiness. At step 6 the engine moves behind a process boundary and starts
speaking NDJSON; a benchmark that reached into `engine._tracker` dies exactly
there — at the single largest change in the plan, which is the moment
comparability matters most. §16 ("every step is measured with the same
bench.py") would quietly become decoration.

So the engine exposes one observation contract, and everything that wants to
watch it — `engine/bench`, later the protocol layer, later anything else —
consumes that. Today it is satisfied by an in-process adapter
(`engine/streams/local.py`). At step 6 it will also be satisfied by a reader
over the `events` channel, and no line of bench code changes.

Two deliberate choices:

**Boxes on this boundary are normalized.** `NormalizedBox`, not `BoundingBox`.
This is a boundary, so ENGINE_PROTOCOL.md §5 applies: the engine sees the
mainstream, the dashboard sees the substream, and a pixel box means different
things to each. Internal perception keeps pixels (see ports/geometry.py).

**There is no identity here.** A `TrackObservation` has a track id and a box.
Whether that track is a person with a name is the identity layer's business
(Engine A), arrives later, and is added as a new optional field — never by
changing what an existing field means. Same evolution rule as the protocol
(§6.8), same reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional, Protocol, Tuple

from .geometry import NormalizedBox


@dataclass(frozen=True)
class TrackObservation:
    """One tracked object as seen from outside the engine."""

    track_id: int
    box: NormalizedBox
    state: str
    confidence: float = 1.0

    # Reserved for the identity layer. Present so that adding it later is a
    # field gaining a value, not a schema change.
    person_id: Optional[str] = None
    identity_source: Optional[str] = None


@dataclass(frozen=True)
class FrameObservation:
    """Everything one frame produced, from outside the engine."""

    camera_id: str
    frame_id: int
    pts: float
    wallclock: float
    width: int
    height: int
    tracks: Tuple[TrackObservation, ...] = ()

    # Added in B4. `pts_source` says how far the timeline can be trusted
    # ("container" or "derived_from_fps"); `stream_epoch` increments on every
    # reconnect, and two PTS values from different epochs must never be
    # subtracted — RTP restarts from a fresh random base, so the difference is
    # not a wrong duration, it is a meaningless one that still prints.
    pts_source: str = "none"
    stream_epoch: int = 0


@dataclass(frozen=True)
class StreamDescriptor:
    """
    What actually ran — not what the config asked for.

    The distinction is the whole point. A tracker that fell back to a different
    backend and a report that names the requested one is the flattering lie
    `strict_mode` exists to prevent; recording the real class names here means
    the benchmark report carries the evidence either way.
    """

    camera_id: str
    source_class: str
    detector_class: str
    tracker_class: str
    source_fps: float
    effective_fps: float
    width: int = 0
    height: int = 0
    total_frames: Optional[int] = None
    pts_source: str = "derived_from_fps"
    extra: Dict[str, Any] = field(default_factory=dict)


class TrackStream(Protocol):
    """
    A source of `FrameObservation`s, however it is produced.

    Implementations: `engine.streams.local.LocalTrackStream` (in-process, today)
    and, at step 6, a reader over the NDJSON `events` channel.
    """

    def open(self) -> StreamDescriptor:
        """Starts the stream and reports what actually got wired up."""
        ...

    def observations(self) -> Iterator[FrameObservation]:
        """Yields one observation per processed frame until the source ends."""
        ...

    def close(self) -> None:
        """Releases the stream. Must be safe to call twice."""
        ...
