from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np

from ..ports.geometry import BoundingBox, Point
from ..ports.detection import Detection
from ..ports.tracking import Track, TrackState
from ..ports.frame import Frame
from .iou_tracker import IoUTracker

logger = logging.getLogger(__name__)


class TrackerArgs:
    """Dynamic arguments container for Ultralytics ByteTrack / BoTSORT."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def __getattr__(self, name: str) -> Any:
        defaults: Dict[str, Any] = {
            "tracker_type": "bytetrack",
            "track_high_thresh": 0.5,
            "track_low_thresh": 0.1,
            "new_track_thresh": 0.6,
            "match_thresh": 0.8,
            "track_buffer": 30,
            "fuse_score": True,
            "gmc_method": "sparseOptFlow",
            "proximity_thresh": 0.5,
            "appearance_thresh": 0.25,
            "with_reid": False,
            "mot20": False,
        }
        return defaults.get(name, 0.5)


class DetectionsWrapper:
    """
    Adapter mimicking Ultralytics Boxes / Results objects for BYTETracker.update().
    Provides .conf, .xywh, .xyxy, .cls, .data and slicing via __getitem__.
    """

    def __init__(self, detections_or_tensor: Union[List[Detection], Any]) -> None:
        import torch

        if isinstance(detections_or_tensor, torch.Tensor):
            self.data = detections_or_tensor
        elif isinstance(detections_or_tensor, list) and detections_or_tensor:
            rows = []
            for d in detections_or_tensor:
                x1, y1, x2, y2 = d.bbox.to_xyxy()
                rows.append([x1, y1, x2, y2, d.confidence, float(d.class_id)])
            self.data = torch.tensor(rows, dtype=torch.float32)
        else:
            self.data = torch.empty((0, 6), dtype=torch.float32)

    @property
    def xyxy(self) -> Any:
        import torch
        return self.data[:, :4] if len(self.data) > 0 else torch.empty((0, 4), dtype=torch.float32)

    @property
    def conf(self) -> Any:
        import torch
        return self.data[:, 4] if len(self.data) > 0 else torch.empty((0,), dtype=torch.float32)

    @property
    def cls(self) -> Any:
        import torch
        return self.data[:, 5] if len(self.data) > 0 else torch.empty((0,), dtype=torch.float32)

    @property
    def xywh(self) -> Any:
        import torch
        if len(self.data) == 0:
            return torch.empty((0, 4), dtype=torch.float32)
        xyxy = self.data[:, :4]
        cx = (xyxy[:, 0] + xyxy[:, 2]) / 2.0
        cy = (xyxy[:, 1] + xyxy[:, 3]) / 2.0
        w = xyxy[:, 2] - xyxy[:, 0]
        h = xyxy[:, 3] - xyxy[:, 1]
        return torch.stack([cx, cy, w, h], dim=-1)

    def __getitem__(self, idx: Any) -> DetectionsWrapper:
        return DetectionsWrapper(self.data[idx])

    def __len__(self) -> int:
        return len(self.data)


class ByteTrackTracker:
    """
    Adapter for ByteTrack / BoT-SORT trackers.
    Provides robust multi-object tracking with Kalman filtering and low-score detection association.
    Falls back gracefully to IoUTracker if native ByteTrack is not installed.
    """

    def __init__(
        self,
        track_thresh: float = 0.45,
        match_thresh: float = 0.8,
        track_buffer: int = 30,
        frame_rate: int = 30,
        strict: bool = True,
    ) -> None:
        self._track_thresh = track_thresh
        self._match_thresh = match_thresh
        self._track_buffer = track_buffer
        self._frame_rate = frame_rate
        self._strict = strict

        self._tracker = None
        self._fallback = IoUTracker(max_missing_frames=track_buffer)
        self._tracks_cache: Dict[int, Track] = {}

        self._init_tracker()

    def _init_tracker(self) -> None:
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker

            args = TrackerArgs(
                tracker_type="bytetrack",
                track_thresh=self._track_thresh,
                track_high_thresh=self._track_thresh,
                track_low_thresh=0.1,
                new_track_thresh=self._track_thresh + 0.1,
                track_buffer=self._track_buffer,
                match_thresh=self._match_thresh,
                fuse_score=True,
                frame_rate=self._frame_rate,
                mot20=False,
            )
            try:
                self._tracker = BYTETracker(args)
            except TypeError:
                self._tracker = BYTETracker(args, frame_rate=self._frame_rate)
            logger.info("Initialized native ByteTrack tracker.")
        except Exception as e:
            # ARCHITECTURE.md §9 item 9, in the tracker's territory. Falling back
            # to IoUTracker here means a benchmark run silently measures a
            # completely different tracker and still reports tidy numbers. Under
            # strict_mode that is a startup failure, not a log line at INFO.
            if self._strict:
                raise RuntimeError(
                    "Tracker backend 'bytetrack' was requested but could not be "
                    f"initialised ({e}). Refusing to fall back to IoUTracker: a "
                    "silent backend swap makes every measurement meaningless. "
                    "Install the backend, or set tracker.backend to 'iou' "
                    "explicitly in the config."
                ) from e
            logger.warning(
                "ByteTrack unavailable (%s); falling back to IoUTracker. "
                "strict_mode is OFF, so numbers from this run describe IoUTracker.",
                e,
            )
            self._tracker = None

    def reset(self) -> None:
        if self._tracker is not None:
            self._init_tracker()
        else:
            self._fallback.reset()
        self._tracks_cache.clear()

    def update(self, detections: List[Detection], frame: Frame) -> List[Track]:
        if self._tracker is None:
            return self._fallback.update(detections, frame)

        h, w = frame.shape[:2]
        now = frame.timestamp

        wrapper = DetectionsWrapper(detections)

        try:
            online_targets = self._tracker.update(wrapper, frame.image)
        except Exception as e:
            logger.warning(f"Error in ByteTrack update ({e}), falling back to IoU tracker.")
            return self._fallback.update(detections, frame)

        active_tracks: List[Track] = []
        seen_tids: set[int] = set()

        if online_targets is None:
            online_targets = []

        for t in online_targets:
            # Handle NumPy array row: [x1, y1, x2, y2, track_id, score, cls_id, ...]
            if isinstance(t, (np.ndarray, list, tuple)) or (hasattr(t, "__len__") and not hasattr(t, "track_id")):
                if len(t) < 5:
                    continue
                x1, y1, x2, y2 = float(t[0]), float(t[1]), float(t[2]), float(t[3])
                tid = int(t[4])
                score = float(t[5]) if len(t) > 5 else 1.0
                cls_id = int(t[6]) if len(t) > 6 else 0
                bbox = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2).clip(max_width=w, max_height=h)
            elif hasattr(t, "track_id"):
                tid = int(t.track_id)
                score = float(t.score) if hasattr(t, "score") else 1.0
                cls_id = int(t.cls) if hasattr(t, "cls") else 0
                if hasattr(t, "tlwh") and t.tlwh is not None:
                    tlwh = t.tlwh
                    bbox = BoundingBox(
                        x1=float(tlwh[0]),
                        y1=float(tlwh[1]),
                        x2=float(tlwh[0] + tlwh[2]),
                        y2=float(tlwh[1] + tlwh[3]),
                    ).clip(max_width=w, max_height=h)
                elif hasattr(t, "xyxy") and t.xyxy is not None:
                    xyxy = t.xyxy
                    bbox = BoundingBox(
                        x1=float(xyxy[0]),
                        y1=float(xyxy[1]),
                        x2=float(xyxy[2]),
                        y2=float(xyxy[3]),
                    ).clip(max_width=w, max_height=h)
                else:
                    continue
            else:
                continue

            seen_tids.add(tid)

            if tid in self._tracks_cache:
                track = self._tracks_cache[tid]
                dt = max(1e-4, now - track.last_seen_timestamp)
                prev_c = track.bbox.center
                curr_c = bbox.center

                inst_vx = (curr_c.x - prev_c.x) / dt
                inst_vy = (curr_c.y - prev_c.y) / dt
                smooth_vx = track.velocity[0] * 0.7 + inst_vx * 0.3
                smooth_vy = track.velocity[1] * 0.7 + inst_vy * 0.3

                track.bbox = bbox
                track.confidence = score
                track.last_seen_timestamp = now
                track.hits += 1
                track.age += 1
                track.lost_frames = 0
                track.state = TrackState.TRACKED
                track.velocity = (smooth_vx, smooth_vy)
                track.history.append(bbox.center)
                if len(track.history) > 30:
                    track.history.pop(0)
            else:
                track = Track(
                    track_id=tid,
                    bbox=bbox,
                    state=TrackState.TRACKED,
                    class_id=cls_id,
                    class_name="person",
                    confidence=score,
                    first_seen_timestamp=now,
                    last_seen_timestamp=now,
                    age=1,
                    hits=1,
                    lost_frames=0,
                    velocity=(0.0, 0.0),
                    history=[bbox.center],
                )
                self._tracks_cache[tid] = track

            active_tracks.append(track)

        # Any previously known track that the native tracker did NOT report
        # this frame is either temporarily occluded/lost, or truly gone.
        # We keep reporting it (in LOST state) for up to `track_buffer`
        # missing frames -- matching IoUTracker's contract -- so that
        # VisionEngine can emit a proper TrackLostEvent and downstream
        # listeners (e.g. face recognition cache) get a grace period
        # instead of an immediate, premature REMOVED/eviction.
        stale_tids = [
            tid for tid in self._tracks_cache
            if tid not in seen_tids
        ]

        for tid in stale_tids:
            track = self._tracks_cache[tid]
            track.lost_frames += 1
            track.age += 1

            if track.lost_frames > self._track_buffer:
                # Exceeded the buffer window: drop it from the cache and
                # do not include it in the output. VisionEngine will see
                # it disappear from current_track_ids and emit REMOVED.
                del self._tracks_cache[tid]
                continue

            track.state = TrackState.LOST
            active_tracks.append(track)

        return active_tracks