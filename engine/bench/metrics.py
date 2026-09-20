"""
Everything computed after the run, from files.

Nothing in this module touches the engine, and nothing in it runs while the
engine does. That is the point: the analysis can be re-run with different
stitching windows, a corrected annotation, or a bug fix in this file, without
re-running a long recording.

The rule that shapes the whole module: **a metric the run cannot justify is
`null`, never `0`.** Track lifetime from a realtime run is not a small number,
it is not a number; a drop rate from a throughput run is not zero, it is
undefined; a false-gap total with no annotation is not "no false gaps", it is
unmeasured. Each withheld field carries the reason it was withheld, and the
go/no-go verdict refuses to be GO on the strength of a field it never got.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..ingest.timeline import epochs_are_comparable
from .annotation import Annotation, PresenceInterval
from .tracklog import TrackSegment

# A track segment that ends this long before the person's annotated exit is
# treated as having broken while they were still in the room. Two seconds is
# slack for annotator reaction time, not a tuning knob: making it larger hides
# real breaks, making it smaller turns annotation jitter into false positives.
EXIT_TOLERANCE_SECONDS = 2.0

# Stitching windows evaluated offline (§13.6). These also answer the open
# question "how many seconds of gap still counts as the same presence?" in
# ARCHITECTURE.md §15.
STITCH_WINDOWS_SECONDS: Tuple[float, ...] = (2.0, 5.0, 15.0, 30.0)

# Proximity stitching, used only when no track_map is annotated. A chain may be
# continued by a segment that starts near where the previous one ended.
PROXIMITY_CENTRE_DISTANCE = 0.08   # normalized frame widths
PROXIMITY_SIZE_RATIO = 0.6         # min(area)/max(area)


# ---------------------------------------------------------------------------
# small numeric helpers
# ---------------------------------------------------------------------------

def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Linear-interpolated percentile. None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (q / 100.0)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[int(position)]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(values: Sequence[float]) -> Dict[str, Any]:
    """The shape of a sample, not just its mean. §13.3."""
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p90": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4),
        "p10": round(percentile(values, 10) or 0.0, 4),
        "p50": round(percentile(values, 50) or 0.0, 4),
        "p90": round(percentile(values, 90) or 0.0, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def withheld(reason: str) -> Dict[str, Any]:
    """A metric this run is not entitled to report."""
    return {"value": None, "withheld_reason": reason}


# ---------------------------------------------------------------------------
# interval algebra
# ---------------------------------------------------------------------------

Interval = Tuple[float, float]


def merge_intervals(intervals: Iterable[Interval]) -> List[Interval]:
    ordered = sorted((a, b) for a, b in intervals if b > a)
    merged: List[Interval] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def clip_intervals(intervals: Iterable[Interval], window: Interval) -> List[Interval]:
    low, high = window
    out: List[Interval] = []
    for start, end in intervals:
        a, b = max(start, low), min(end, high)
        if b > a:
            out.append((a, b))
    return out


def complement(covered: Sequence[Interval], window: Interval) -> List[Interval]:
    """The parts of `window` that `covered` does not cover."""
    low, high = window
    gaps: List[Interval] = []
    cursor = low
    for start, end in merge_intervals(covered):
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
        if cursor >= high:
            break
    if cursor < high:
        gaps.append((cursor, high))
    return gaps


# ---------------------------------------------------------------------------
# latency and throughput
# ---------------------------------------------------------------------------

def latency_by_stage(recorders: Sequence[Any], mode: str = "throughput") -> Dict[str, Any]:
    """
    Percentiles per stage, pooled across cameras.

    `count` and `mean_ms` come from the exact per-stage totals; percentiles come
    from whatever is still in the ring buffer. If anything was evicted the
    percentiles describe a suffix of the run, and `sampling` says so — see
    spans.py.

    In realtime mode `source_ingest` is withheld. The engine times the whole of
    `source.read()`, and in that mode read() deliberately sleeps until the
    frame's deadline — so the stage would report a 33 ms "decode cost" at 30 fps
    on a machine that decoded in two. The sleep is published separately as
    `pacing_wait`, and the honest decode number comes from a throughput run.
    """
    pooled: Dict[str, List[float]] = {}
    exact: Dict[str, Dict[str, float]] = {}
    evicted = 0

    for recorder in recorders:
        evicted += recorder.evicted_spans
        for stage, values in recorder.durations_ms().items():
            pooled.setdefault(stage, []).extend(values)
        for stage, totals in recorder.totals().items():
            slot = exact.setdefault(
                stage, {"count": 0, "total_ms": 0.0, "min_ms": float("inf"), "max_ms": 0.0}
            )
            slot["count"] += totals.count
            slot["total_ms"] += totals.total_ms
            slot["min_ms"] = min(slot["min_ms"], totals.min_ms)
            slot["max_ms"] = max(slot["max_ms"], totals.max_ms)

    out: Dict[str, Any] = {
        "sampling": "complete" if evicted == 0 else "tail_only",
        "spans_evicted": evicted,
        "stages": {},
    }
    for stage, slot in sorted(exact.items()):
        if mode == "realtime" and stage in ("source_ingest", "total_pipeline"):
            out["stages"][stage] = withheld(
                "in realtime mode source.read() sleeps until the frame's "
                "deadline, and this stage contains that sleep — it would "
                "report roughly one frame interval whatever the machine does. "
                "See the pacing_wait stage; measure this in throughput mode "
                "(§13.2)"
            )
            continue
        sample = pooled.get(stage, [])
        out["stages"][stage] = {
            "count": slot["count"],
            "mean_ms": round(slot["total_ms"] / slot["count"], 4) if slot["count"] else None,
            "min_ms": round(0.0 if slot["min_ms"] == float("inf") else slot["min_ms"], 4),
            "max_ms": round(slot["max_ms"], 4),
            "p50_ms": round_opt(percentile(sample, 50)),
            "p95_ms": round_opt(percentile(sample, 95)),
            "p99_ms": round_opt(percentile(sample, 99)),
            "percentile_sample_size": len(sample),
        }
    return out


def throughput(recorders: Sequence[Any], mode: str) -> Dict[str, Any]:
    """Aggregate and per-camera FPS. Drop rate only in realtime mode."""
    per_camera = []
    total_frames = 0
    wall = 0.0
    total_drops = 0
    drop_reasons: Dict[str, int] = {}

    for recorder in recorders:
        frames = recorder.total_frames
        seconds = recorder.wall_seconds
        total_frames += frames
        total_drops += recorder.dropped_frames
        wall = max(wall, seconds)
        for reason, count in recorder.drop_reasons.items():
            drop_reasons[reason] = drop_reasons.get(reason, 0) + count
        per_camera.append(
            {
                "camera_id": recorder.camera_id,
                "frames": frames,
                "wall_seconds": round(seconds, 4),
                "fps": round(frames / seconds, 3) if seconds > 0 else None,
                "dropped_frames": recorder.dropped_frames,
            }
        )

    result: Dict[str, Any] = {
        "frames_total": total_frames,
        "wall_seconds": round(wall, 4),
        "fps_aggregate": round(total_frames / wall, 3) if wall > 0 else None,
        "per_camera": per_camera,
    }

    if mode == "realtime":
        offered = total_frames + total_drops
        result["drop_rate"] = {
            "dropped_frames": total_drops,
            "offered_frames": offered,
            "rate": round(total_drops / offered, 5) if offered else None,
            "reasons": drop_reasons,
        }
        result["queue_depth"] = withheld(
            "no recognition worker pool exists yet (step 18); the slot is "
            "reserved so adding it later is a field gaining a value"
        )
    else:
        result["drop_rate"] = withheld(
            "throughput mode never drops a frame by construction (§13.2); a "
            "drop rate from this mode would be a tautological zero"
        )
        result["queue_depth"] = withheld("valid in realtime mode only (§13.2)")

    return result


def round_opt(value: Optional[float], digits: int = 4) -> Optional[float]:
    return None if value is None else round(value, digits)


# Kept as an alias: internal callers used the underscored name first.
_round_opt = round_opt


# ---------------------------------------------------------------------------
# track quality
# ---------------------------------------------------------------------------

@dataclass
class Chain:
    """One or more track segments judged to be the same continuous presence."""

    camera_id: str
    start_pts: float
    end_pts: float
    segments: List[TrackSegment]
    basis: str
    person_id: Optional[str] = None
    epoch: int = 0

    @property
    def duration(self) -> float:
        return max(0.0, self.end_pts - self.start_pts)


def stitch(
    segments: Sequence[TrackSegment],
    window_seconds: float,
    annotation: Optional[Annotation] = None,
) -> Tuple[List[Chain], str]:
    """
    Offline stitching (§13.6). Zero lines of engine code.

    Two bases, and the report says which was used:

    `annotated_identity` — when the annotation maps tracks to people, segments
    of the same person on the same camera within the window are one presence.
    This is what §4.3's identity-level stitching will actually do, so the number
    is a fair estimate of it.

    `proximity_heuristic` — with no map, a segment may continue a chain if it
    starts near where the previous one ended, at a similar size. This is *not*
    a bound on the identity version in either direction: it will join two people
    who cross paths, and it will fail to join someone who reappears across the
    room. Useful for a first look, not for a go/no-go.
    """
    if window_seconds < 0:
        raise ValueError("stitching window must not be negative")

    basis = (
        "annotated_identity"
        if annotation is not None and annotation.has_track_map
        else "proximity_heuristic"
    )
    ordered = sorted(segments, key=lambda s: (s.camera_id, s.start_pts))
    chains: List[Chain] = []
    open_chains: List[Chain] = []

    for segment in ordered:
        person_id = (
            annotation.person_of_track(segment.camera_id, segment.track_id)
            if basis == "annotated_identity" and annotation is not None
            else None
        )
        target: Optional[Chain] = None

        for chain in open_chains:
            if chain.camera_id != segment.camera_id:
                continue
            # B4: a reconnect resets the timebase, so a "gap" measured across
            # one is two unrelated numbers subtracted. Never stitch across it —
            # the result would look like a plausible short gap and be nothing
            # of the kind.
            if not epochs_are_comparable(
                getattr(chain, "epoch", 0), getattr(segment, "epoch", 0)
            ):
                continue
            gap = segment.start_pts - chain.end_pts
            if gap < 0 or gap > window_seconds:
                continue
            if basis == "annotated_identity":
                if person_id is not None and chain.person_id == person_id:
                    target = chain
                    break
            elif _is_plausible_continuation(chain.segments[-1], segment):
                target = chain
                break

        if target is None:
            target = Chain(
                camera_id=segment.camera_id,
                start_pts=segment.start_pts,
                end_pts=segment.end_pts,
                segments=[segment],
                basis=basis,
                person_id=person_id,
                epoch=getattr(segment, "epoch", 0),
            )
            chains.append(target)
            open_chains.append(target)
        else:
            target.segments.append(segment)
            target.end_pts = max(target.end_pts, segment.end_pts)

        open_chains = [
            chain
            for chain in open_chains
            if segment.start_pts - chain.end_pts <= window_seconds
        ]
        if target not in open_chains:
            open_chains.append(target)

    return chains, basis


def _is_plausible_continuation(previous: TrackSegment, nxt: TrackSegment) -> bool:
    ax1, ay1, ax2, ay2 = previous.last_box
    bx1, by1, bx2, by2 = nxt.first_box
    acx, acy = (ax1 + ax2) / 2.0, (ay1 + ay2) / 2.0
    bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
    if math.hypot(acx - bcx, acy - bcy) > PROXIMITY_CENTRE_DISTANCE:
        return False
    area_a = max(1e-9, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1e-9, (bx2 - bx1) * (by2 - by1))
    return min(area_a, area_b) / max(area_a, area_b) >= PROXIMITY_SIZE_RATIO


def track_lifetime(
    segments: Sequence[TrackSegment],
    annotation: Optional[Annotation],
) -> Dict[str, Any]:
    """
    Two numbers, per §13.6: raw, and effective after offline stitching.

    Plus the one §4.7 actually asks for — how long a track survives *while the
    person is still in the room* — which needs the annotation and is withheld
    without it.
    """
    raw = [segment.duration for segment in segments]
    result: Dict[str, Any] = {
        "raw_seconds": distribution(raw),
        "stitched_seconds": {},
    }

    for window in STITCH_WINDOWS_SECONDS:
        chains, basis = stitch(segments, window, annotation)
        result["stitched_seconds"][f"N={window:g}s"] = {
            "basis": basis,
            "chains": len(chains),
            "segments_per_chain_mean": (
                round(len(segments) / len(chains), 3) if chains else None
            ),
            **distribution([chain.duration for chain in chains]),
        }

    if annotation is None or not annotation.has_track_map:
        result["broken_while_person_present_seconds"] = withheld(
            "needs an annotation with track_map: a track that ends cannot be "
            "told from a person who left without ground truth (§13.8)"
        )
        return result

    inside: List[float] = []
    for segment in segments:
        person_id = annotation.person_of_track(segment.camera_id, segment.track_id)
        if person_id is None:
            continue
        person = annotation.person(person_id)
        if person is None:
            continue
        interval = _containing_interval(person.presence, segment.end_pts)
        if interval is None:
            continue
        if segment.end_pts < interval.exit - EXIT_TOLERANCE_SECONDS:
            inside.append(segment.duration)

    result["broken_while_person_present_seconds"] = distribution(inside)
    return result


def _containing_interval(
    intervals: Sequence[PresenceInterval], pts: float
) -> Optional[PresenceInterval]:
    for interval in intervals:
        if interval.enter <= pts <= interval.exit:
            return interval
    return None


def identity_continuity(
    segments: Sequence[TrackSegment],
    annotation: Optional[Annotation],
) -> Dict[str, Any]:
    """
    Fragmentation and ID switches — different failures, different label cost.

    **Fragmentation**: one person carried by several track ids. This is what the
    cheap `track_map` measures, and it is the one that manufactures false breaks
    (§4.1).

    **ID switch**: one track id carrying two different people. This is how one
    employee's minutes land on another's record, and it needs the expensive
    per-segment `track_segments` labelling. Without that, it is `null`.

    The workplan says "ID switch" in several places while §13.8 costs only the
    cheap annotation. Those are not the same measurement, so both are named.
    """
    result: Dict[str, Any] = {}

    if annotation is not None and annotation.has_track_map:
        per_person: Dict[str, set] = {}
        unmapped = 0
        for segment in segments:
            person_id = annotation.person_of_track(segment.camera_id, segment.track_id)
            if person_id is None:
                unmapped += 1
                continue
            per_person.setdefault(person_id, set()).add(
                (segment.camera_id, segment.track_id)
            )
        fragments = {p: len(ids) for p, ids in sorted(per_person.items())}
        result["fragmentation"] = {
            "tracks_per_person": fragments,
            "total_extra_tracks": sum(max(0, n - 1) for n in fragments.values()),
            "unmapped_segments": unmapped,
        }
    else:
        result["fragmentation"] = withheld(
            "needs annotation.track_map (§13.8 cheap form)"
        )

    if annotation is not None and annotation.has_track_segments:
        switches = 0
        by_track: Dict[tuple, List[Any]] = {}
        for label in annotation.track_segments:
            by_track.setdefault((label.camera_id, label.track_id), []).append(label)
        for labels in by_track.values():
            labels.sort(key=lambda label: label.start)
            for a, b in zip(labels, labels[1:]):
                if a.person_id != b.person_id:
                    switches += 1
        result["id_switches"] = {"count": switches, "basis": "annotated_track_segments"}
    else:
        result["id_switches"] = withheld(
            "an ID switch is one track carrying two people; the cheap "
            "annotation cannot see it. Needs annotation.track_segments"
        )

    return result


# ---------------------------------------------------------------------------
# the product metric: false gaps
# ---------------------------------------------------------------------------

def false_gaps(
    segments: Sequence[TrackSegment],
    annotation: Optional[Annotation],
    workday_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Time a person spent in the room with nothing tracking them.

    This is the number §4.7 and §13.7 turn into a go/no-go: every second here
    is a second the backend will see as a gap between presence intervals, and
    the backend will spend it out of a per-person budget the person never left
    their chair to use. How large that budget is, and how much of it may be
    lost to noise, are company numbers this module is not allowed to know —
    they arrive from bench/gonogo.yaml, outside engine/ (§16).

    Reported raw and after offline stitching at each window, because the whole
    argument of §13.6 is that judging the feature on the raw number alone
    condemns it on a basis the design never intended.
    """
    if annotation is None or not annotation.has_track_map:
        return withheld(
            "needs an annotation with track_map: time nothing was tracking "
            "someone cannot be told from time they were genuinely elsewhere, "
            "without ground truth (§13.8)"
        )

    def coverage_for(person_id: str, chains: Optional[Sequence[Chain]]) -> List[Interval]:
        if chains is None:
            return [
                (segment.start_pts, segment.end_pts)
                for segment in segments
                if annotation.person_of_track(segment.camera_id, segment.track_id)
                == person_id
            ]
        return [
            (chain.start_pts, chain.end_pts)
            for chain in chains
            if chain.person_id == person_id
        ]

    def evaluate(chains: Optional[Sequence[Chain]]) -> Dict[str, Any]:
        per_person: Dict[str, Any] = {}
        total_gap = 0.0
        total_presence = 0.0
        gap_lengths: List[float] = []

        for person in annotation.persons:
            covered = merge_intervals(coverage_for(person.person_id, chains))
            person_gap = 0.0
            person_gaps: List[float] = []
            for interval in person.presence:
                window = (interval.enter, interval.exit)
                for start, end in complement(
                    clip_intervals(covered, window), window
                ):
                    length = end - start
                    person_gap += length
                    person_gaps.append(length)
            total_gap += person_gap
            total_presence += person.total_presence_seconds
            gap_lengths.extend(person_gaps)
            per_person[person.person_id] = {
                "presence_seconds": round(person.total_presence_seconds, 3),
                "false_gap_seconds": round(person_gap, 3),
                "false_gap_count": len(person_gaps),
                "coverage": (
                    round(1.0 - person_gap / person.total_presence_seconds, 4)
                    if person.total_presence_seconds > 0
                    else None
                ),
            }

        presence_hours = total_presence / 3600.0
        per_hour = total_gap / presence_hours if presence_hours > 0 else None
        return {
            "per_person": per_person,
            "total_false_gap_seconds": round(total_gap, 3),
            "total_presence_seconds": round(total_presence, 3),
            "false_gap_seconds_per_person_hour": (
                round(per_hour, 3) if per_hour is not None else None
            ),
            # The projection needs a working-day length, and that is a company
            # number, not a perceptual one. §16 says the engine may not hold it,
            # so it arrives from the thresholds file (which lives outside
            # engine/) or the projection is simply not made. See thresholds.py.
            "projected_minutes_per_person_per_day": (
                round(per_hour * workday_hours / 60.0, 3)
                if per_hour is not None and workday_hours
                else None
            ),
            "projection_workday_hours": workday_hours,
            "gap_length_seconds": distribution(gap_lengths),
        }

    result: Dict[str, Any] = {"raw": evaluate(None), "stitched": {}}
    for window in STITCH_WINDOWS_SECONDS:
        chains, basis = stitch(segments, window, annotation)
        entry = evaluate(chains)
        entry["basis"] = basis
        result["stitched"][f"N={window:g}s"] = entry
    return result


# ---------------------------------------------------------------------------
# where tracks end (B5)
# ---------------------------------------------------------------------------

def zone_exits(
    segments: Sequence[TrackSegment],
    annotation: Optional[Annotation] = None,
    door_configured: bool = False,
) -> Dict[str, Any]:
    """
    Where appearances ended, which is §13.8's cheap half of the product metric.

    §4.2 in one table. A track ending **at the door** is somebody leaving. A
    track ending **mid-room** is the tracker losing somebody who never moved,
    and every one of those becomes a gap the layer above has to interpret. The
    ratio between them is the earliest warning this benchmark can give, and it
    costs no annotation at all: if most appearances on a recording end in
    `interior`, the answer to §4.7 is already visible before anybody has
    labelled a single presence interval.

    **What this is not.** It counts *events*, not minutes, and the go/no-go in
    `bench/gonogo.yaml` is in minutes. Turning a broken ending into a duration
    requires knowing which person the track belonged to — otherwise there is no
    way to say how long they went untracked, only that something ended where it
    should not have. That is the expensive `track_map` annotation and
    `false_gaps()` above is where it is used. The two are reported side by side
    on purpose; conflating "how often" with "how long" is how a promising ratio
    turns into a number nobody can defend.

    With presence intervals alone — the cheapest annotation there is, no track
    map — the count is narrowed to endings that happened **while somebody was
    demonstrably in the room**, which removes the ordinary case of a person
    walking out and takes nothing more to produce.
    """
    if not segments:
        return withheld("no track segments in this run")

    by_zone: Dict[str, int] = {}
    for segment in segments:
        zone = getattr(segment, "last_zone", "interior")
        by_zone[zone] = by_zone.get(zone, 0) + 1

    total = len(segments)
    interior = by_zone.get("interior", 0)
    result: Dict[str, Any] = {
        "endings_by_zone": dict(sorted(by_zone.items())),
        "total_endings": total,
        "interior_ending_fraction": round(interior / total, 4),
        "door_region_configured": door_configured,
    }

    if not door_configured:
        # Without a region nothing can be labelled `door`, so the fraction above
        # is arithmetic rather than evidence. Saying so here is the difference
        # between a caveat and a number somebody quotes in two months.
        result["caveat"] = (
            "no door_region was configured for any camera in this run, so no "
            "ending could be labelled `door` and `interior_ending_fraction` "
            "carries no information about departures. Set zones.door_regions "
            "(or send set_cameras) before reading this line as anything."
        )

    if annotation is None:
        result["while_person_present"] = withheld(
            "needs presence intervals to tell an ending mid-room from somebody "
            "who had already left the room (§13.8). This is the CHEAP "
            "annotation — presence timelines only, no track map"
        )
        return result

    inside = 0
    inside_interior = 0
    for segment in segments:
        present = any(
            _containing_interval(person.presence, segment.end_pts) is not None
            for person in annotation.persons
        )
        if not present:
            continue
        inside += 1
        if getattr(segment, "last_zone", "interior") == "interior":
            inside_interior += 1

    result["while_person_present"] = {
        "endings": inside,
        "endings_in_interior": inside_interior,
        "interior_fraction": (round(inside_interior / inside, 4) if inside else None),
        "basis": "annotated_presence_only",
        "note": (
            "count of suspicious endings, NOT the go/no-go number. Minutes lost "
            "need track_map (see false_gaps)."
        ),
    }
    return result


# ---------------------------------------------------------------------------
# the timeline itself (B4)
# ---------------------------------------------------------------------------

def timeline_summary(
    descriptors: Sequence[Dict[str, Any]],
    segments: Sequence[TrackSegment] = (),
) -> Dict[str, Any]:
    """
    How much the timeline every other metric is computed on can be trusted.

    Three things, and the first is the one that retroactively settles whether
    older baselines are comparable:

    **`fidelity`** — how far `frame_index / fps` is from the container's own
    PTS on this recording. A near-zero final drift with a non-zero maximum is
    the signature everybody misreads as "the fps was right": the *average* rate
    was right and the instantaneous one was not, and a gap measured near the
    worst moment is wrong by that much.

    **`epochs`** — how many times a source reconnected. Every boundary is a
    place where PTS restarts, so it is also a place where no duration may be
    computed. The segmenter already refuses to cross one; this is the count, so
    a run with reconnects is visibly not the same kind of run as one without.

    **`pts_backwards_within_epoch`** — an assumption failing. Non-zero means
    frames arrived out of presentation order inside a single connection, which
    should not happen; it is counted rather than raised, because a live stream
    that dies on one malformed timestamp is a worse outcome than a run whose
    report says "three anomalies".
    """
    if not descriptors:
        return withheld("no stream ran")

    sources = {d.get("pts_source", "unknown") for d in descriptors}
    per_camera = []
    total_epoch_changes = 0
    total_backwards = 0
    fidelities = []

    for descriptor in descriptors:
        extra = descriptor.get("extra") or {}
        timeline = extra.get("timeline") or {}
        fidelity = extra.get("timeline_fidelity")
        epochs_opened = int(timeline.get("epochs_opened", 1) or 1)
        backwards = int(timeline.get("pts_backwards_within_epoch", 0) or 0)
        total_epoch_changes += max(0, epochs_opened - 1)
        total_backwards += backwards
        if fidelity:
            fidelities.append(fidelity)
        per_camera.append(
            {
                "camera_id": descriptor.get("camera_id"),
                "pts_source": descriptor.get("pts_source"),
                # Not "opencv" by default. A source that does not describe
                # itself — the mock one — is not the OpenCV backend, and
                # saying so printed a caveat about container PTS for a run
                # that never opened a container.
                "backend": extra.get("backend", "unknown"),
                "average_rate": extra.get("average_rate"),
                "guessed_rate": extra.get("guessed_rate"),
                "reconnects": max(0, epochs_opened - 1),
                "pts_backwards_within_epoch": backwards,
                "timeline_fidelity": fidelity,
            }
        )

    segment_epochs = sorted({getattr(s, "epoch", 0) for s in segments})

    summary: Dict[str, Any] = {
        "pts_source": sorted(sources)[0] if len(sources) == 1 else sorted(sources),
        "per_camera": per_camera,
        "reconnects_total": total_epoch_changes,
        "pts_backwards_total": total_backwards,
        "epochs_seen_in_track_log": segment_epochs,
    }

    if not fidelities:
        summary["fidelity"] = withheld(
            "only the PyAV backend can compare a real PTS against "
            "frame_index / fps; the OpenCV backend has no container PTS to "
            "compare with (§5.5)"
        )
        return summary

    # Pooled across cameras by taking the worst, because the question this
    # answers is "could any measured duration be wrong", not "is it usually
    # fine".
    worst = max(
        (f for f in fidelities if f.get("max_abs_deviation_s") is not None),
        key=lambda f: f["max_abs_deviation_s"],
        default=None,
    )
    summary["fidelity"] = worst or withheld("no frames carried a PTS")
    return summary
