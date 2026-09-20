"""
B5: which zone each track is in, and who gets recognised next because of it.

Two jobs that look separate and are the same `door_region` read twice, which is
the whole reason ARCHITECTURE.md §3.2 and §4.2 are cheap:

**Forwards (§3.2).** Somebody walking in through the door faces into the room,
which is where the corner camera is. That is the only moment a frontal face is
close to guaranteed, so a track born in the door region goes to the front of the
recognition queue. Miss the moment and the next one may be twenty minutes away,
after the person turns round again.

**Backwards (§4.2).** A track that *ends* in the door region probably means the
person left. A track that ends in the middle of the room is almost certainly a
tracking failure, and the difference between those two is the difference between
a break and a warning letter for sitting still (§4.1).

## What this file is, and what it deliberately is not

It is wiring. The zone rule lives in `presence/zones.py` and the queue policy in
`identity/admission.py` — both Engine A's, both already written and tested — and
until B5 neither was reachable from a frame loop, which is B's half of the job.
Re-implementing either here to avoid the import would have produced two door
definitions that agree right up until one is changed.

**It changes nothing the benchmark measures.** Zone labelling reads a box that
detection and tracking already produced; it never feeds anything back. The
scheduler is off unless `recognition.enabled` is set, and even on, it only
decides an order — there is no recognition consumer until §5.2's worker pool, so
nothing pops unless something is attached. That is what keeps B1's baseline
comparable across B5 (§16), and it is also the honest reason the queue metrics
below are reported with a caveat rather than as a performance result.

## The conversion that has to happen exactly once

`Track.bbox` is in pixels — `geometry.py` says so, and says why: the Kalman
filter and the face crops are calibrated there. `door_region` is normalized,
because whoever drew it was looking at the dashboard's substream while the
engine sees the mainstream (§6.7.2). So the boundary crossing happens here,
through `NormalizedBox.from_pixels`, using the frame's own dimensions rather than
a remembered resolution — a camera that changes profile mid-run changes the
frame, and a cached width would put every box in the wrong place while still
producing plausible zones.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..ports.frame import Frame
from ..ports.geometry import NormalizedBox
from ..ports.tracking import Track, TrackState
from ..presence.zones import ZONE_INTERIOR, ZoneLabeller

logger = logging.getLogger(__name__)

# The attribute keys a track carries once it has been through here. Strings
# rather than a type because `Track.attributes` is a shared free-for-all and
# B5 is not the step that tightens it.
ZONE_ATTRIBUTE = "zone"
ENTRY_ZONE_ATTRIBUTE = "entry_zone"

# A recognition consumer: called with a Request when one is handed out. There is
# none until §5.2, and that is why `pop` does nothing without it.
RequestConsumer = Callable[[Any], None]


class TrackZoner:
    """
    Labels tracks with their zone and remembers where each one was last seen.

    The memory is the point. `track.ended` must carry `exit_zone`
    (ENGINE_PROTOCOL.md §7), and by the time a track ends the tracker has
    stopped reporting it — there is no box left to label. So the last zone is
    kept while the track is alive and read after it is gone.
    """

    def __init__(
        self,
        labeller: Optional[ZoneLabeller] = None,
        door_regions: Optional[Dict[str, Sequence[float]]] = None,
        edge_margin: float = 0.03,
    ) -> None:
        self._labeller = labeller or ZoneLabeller(
            door_regions=door_regions, edge_margin=edge_margin
        )
        self._last_zone: Dict[int, str] = {}
        self._entry_zone: Dict[int, str] = {}

    @property
    def labeller(self) -> ZoneLabeller:
        """The labeller itself, so `set_cameras` can update a region at runtime."""
        return self._labeller

    def label(self, frame: Frame, tracks: Sequence[Track]) -> None:
        """Annotates every track in place. Cheap: four comparisons per track."""
        camera_id = frame.metadata.source_id
        width, height = frame.metadata.width, frame.metadata.height
        if width <= 0 or height <= 0:
            height, width = frame.image.shape[:2]

        for track in tracks:
            try:
                box = NormalizedBox.from_pixels(track.bbox, width, height)
            except ValueError as exc:
                # A box outside the frame is a detector or tracker problem, not
                # a zone problem, and guessing `interior` here would hide it
                # while producing a zone that looks like evidence.
                logger.warning(
                    "[%s] track %s has an unnormalizable box %s: %s. Zone left "
                    "unset for this frame.",
                    camera_id, track.track_id, track.bbox.to_xyxy(), exc,
                )
                continue

            zone = self._labeller.label(camera_id, box.to_xyxy())
            track.attributes[ZONE_ATTRIBUTE] = zone
            self._last_zone[track.track_id] = zone

            if track.track_id not in self._entry_zone:
                self._entry_zone[track.track_id] = zone
            track.attributes[ENTRY_ZONE_ATTRIBUTE] = self._entry_zone[track.track_id]

    def zone_of(self, track_id: int) -> str:
        """
        Where this track was last seen, or `interior` if it was never labelled.

        The default is the suspicious side on purpose (`presence/zones.py` makes
        the same choice for an unconfigured camera): calling an unknown ending
        `door` would quietly mark every gap as a real departure, and the layer
        that reads this field is the one that decides what a gap costs somebody.
        """
        return self._last_zone.get(track_id, ZONE_INTERIOR)

    def entry_zone_of(self, track_id: int) -> str:
        return self._entry_zone.get(track_id, ZONE_INTERIOR)

    def forget(self, track_id: int) -> None:
        """Called when a track is removed, after its exit zone has been read."""
        self._last_zone.pop(track_id, None)
        self._entry_zone.pop(track_id, None)

    @property
    def tracked_ids(self) -> int:
        return len(self._last_zone)


class ZonePriorityQueue:
    """
    Drives `identity.RecognitionScheduler` from the frame loop (§3.2, §5.2).

    One submit per live track per frame, priority taken from its zone, and then
    at most `max_requests_per_frame` handed to whatever consumes them. Without a
    consumer nothing is popped — requests age out of the queue by themselves,
    which is exactly what the scheduler's drop-by-age rule is for and is
    reported rather than hidden.

    `now_pts` is the frame's PTS, not the wall clock. Every interval in this
    system is measured in PTS (§6.6), and a queue timed against the wall would
    behave differently in a throughput benchmark than in production — the two
    modes of §13.2 would stop being comparable in the one place where the number
    being compared is a queue depth.
    """

    def __init__(
        self,
        scheduler: Any,
        zoner: TrackZoner,
        max_requests_per_frame: int = 2,
        consumer: Optional[RequestConsumer] = None,
    ) -> None:
        self._scheduler = scheduler
        self._zoner = zoner
        self._max_per_frame = max(0, int(max_requests_per_frame))
        self._consumer = consumer
        self._submitted = 0
        self._handed_out = 0

    def set_consumer(self, consumer: Optional[RequestConsumer]) -> None:
        self._consumer = consumer

    def step(self, frame: Frame, tracks: Sequence[Track]) -> List[Any]:
        """Submits what deserves a look, hands out what the budget allows."""
        now_pts = frame.metadata.pts
        if now_pts is None:
            # No timeline, no ages, no stale-drop rule. A mock source has this,
            # and running the queue against a fabricated clock would produce
            # queue numbers that describe the fabrication.
            return []

        camera_id = frame.metadata.source_id

        for track in tracks:
            if track.state not in (TrackState.NEW, TrackState.TRACKED):
                continue
            # None until the identity layer writes it (A3–A5), which is why
            # every live track looks PENDING today and gets a zone-based
            # priority. Harmless: `submit` keeps one queue slot per track and
            # refuses a track that is already in flight, so a `priority_for`
            # that cannot see the in-flight set cannot make the queue grow.
            identity = track.attributes.get("identity_state")
            priority = self._scheduler.priority_for(
                identity,
                now_pts=now_pts,
                zone=track.attributes.get(ZONE_ATTRIBUTE, ZONE_INTERIOR),
                track_age_seconds=track.dwell_time,
            )
            if priority is None:
                continue
            # `track_uuid` is the identity layer's key and does not exist yet
            # (§5.2: it must outlive a recycled track_id). Until it does, the
            # per-camera id is the closest thing that is stable within a run,
            # and it is built here in one place so that swapping it for the real
            # uuid later is one line rather than a hunt.
            # A6: lapisan identitas menulis `track_uuid` ke atribut track, dan
            # uuid itu membawa nomor generasi supaya `track_id` yang didaur
            # ulang tracker tidak memakai kunci yang sama untuk orang yang
            # berbeda. Penahan sementara di bawah tetap dipakai selama belum
            # ada yang menuliskannya -- ini "satu baris" yang dijanjikan
            # komentar di atas.
            track_uuid = track.attributes.get("track_uuid") or f"{camera_id}-t{track.track_id}"
            if self._scheduler.submit(
                track_uuid=track_uuid,
                camera_id=camera_id,
                priority=priority,
                now_pts=now_pts,
            ):
                self._submitted += 1

        handed: List[Any] = []
        if self._consumer is None:
            return handed

        for _ in range(self._max_per_frame):
            request = self._scheduler.pop(now_pts)
            if request is None:
                break
            handed.append(request)
            self._handed_out += 1
            self._consumer(request)
        return handed

    def forget(self, track_id: int, camera_id: str) -> None:
        self._scheduler.forget(f"{camera_id}-t{track_id}")

    def metrics(self, now_pts: float) -> Dict[str, Any]:
        out = dict(self._scheduler.metrics(now_pts))
        out.update(
            {
                "submitted_total": float(self._submitted),
                "handed_out_total": float(self._handed_out),
                "has_consumer": self._consumer is not None,
            }
        )
        return out
