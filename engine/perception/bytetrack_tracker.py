from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..ports.detection import Detection
from ..ports.frame import Frame
from ..ports.geometry import BoundingBox
from ..ports.tracking import Track, TrackState
from .iou_tracker import IoUTracker

logger = logging.getLogger(__name__)


class ByteTrackTracker:
    """LibreYOLO ByteTrack adapter.

    LibreYOLO exposes ByteTrack as a public tracker that consumes its native
    ``Results`` object.  The detector adapter stores that object for the same
    frame, so the engine does not perform a second inference in the normal
    detection path.
    """

    def __init__(
        self,
        track_thresh: float = 0.45,
        match_thresh: float = 0.8,
        track_buffer: int = 30,
        frame_rate: int = 30,
        strict: bool = True,
        detector: Optional[Any] = None,
    ) -> None:
        self._track_thresh = track_thresh
        self._match_thresh = match_thresh
        self._track_buffer = track_buffer
        self._frame_rate = frame_rate
        self._strict = strict
        self._detector = detector

        self._tracker: Any = None
        self._fallback = IoUTracker(max_missing_frames=track_buffer)
        self._tracks_cache: Dict[int, Track] = {}

        self._init_tracker()

    def _init_tracker(self) -> None:
        try:
            from libreyolo import ByteTracker, TrackConfig

            config = TrackConfig(
                track_high_thresh=self._track_thresh,
                track_low_thresh=min(0.1, self._track_thresh),
                new_track_thresh=self._track_thresh,
                match_thresh=self._match_thresh,
                track_buffer=self._track_buffer,
                frame_rate=self._frame_rate,
                fuse_score=True,
                minimum_consecutive_frames=1,
            )
            self._tracker = ByteTracker(config=config)
            logger.info(
                "Initialized LibreYOLO ByteTrack (buffer=%d frames, fps=%d).",
                self._track_buffer,
                self._frame_rate,
            )
        except Exception as exc:
            if self._strict:
                raise RuntimeError(
                    "Tracker backend 'bytetrack' was requested but LibreYOLO "
                    f"ByteTrack could not be initialised ({exc}). "
                    "Install the real-engine dependencies or set "
                    "tracker.backend to 'iou' explicitly."
                ) from exc
            logger.warning(
                "LibreYOLO ByteTrack unavailable (%s); falling back to "
                "IoUTracker because strict_mode is OFF.",
                exc,
            )
            self._tracker = None

    def reset(self) -> None:
        if self._tracker is not None:
            self._tracker.reset()
        self._fallback.reset()
        self._tracks_cache.clear()

    def _result_for_frame(self, frame: Frame, detections: List[Detection]) -> Any:
        """Get the native LibreYOLO Results for this exact frame.

        On the normal path ``DFINEDetector.detect`` has already produced it.
        When detection is intentionally skipped, run the same LibreYOLO model
        at the track threshold so the tracker can still receive fresh boxes.
        """
        if (
            self._detector is not None
            and getattr(self._detector, "last_result_frame_id", None)
            == frame.frame_id
        ):
            return self._detector.last_result

        if self._detector is None or not hasattr(self._detector, "predict_raw"):
            raise RuntimeError(
                "LibreYOLO ByteTrack requires a detector that exposes "
                "predict_raw()/last_result. Build the tracker through "
                "engine.factory.build_engine()."
            )

        return self._detector.predict_raw(
            frame,
            confidence=min(self._track_thresh, 0.1),
        )

    @staticmethod
    def _tensor_to_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if hasattr(value, "detach"):
            return value.detach().cpu().tolist()
        if hasattr(value, "cpu"):
            return value.cpu().tolist()
        return list(value)

    def update(self, detections: List[Detection], frame: Frame) -> List[Track]:
        if self._tracker is None:
            return self._fallback.update(detections, frame)

        try:
            result = self._result_for_frame(frame, detections)
            tracked = self._tracker.update(result)
        except Exception as exc:
            if self._strict:
                raise RuntimeError(
                    f"LibreYOLO ByteTrack update failed: {exc}"
                ) from exc
            logger.warning(
                "LibreYOLO ByteTrack update failed (%s); using IoUTracker "
                "because strict_mode is OFF.",
                exc,
            )
            return self._fallback.update(detections, frame)

        boxes = getattr(tracked, "boxes", None)
        if boxes is None or len(boxes) == 0:
            online = []
        else:
            xyxy = self._tensor_to_list(getattr(boxes, "xyxy", None))
            confs = self._tensor_to_list(getattr(boxes, "conf", None))
            class_ids = self._tensor_to_list(getattr(boxes, "cls", None))
            ids = self._tensor_to_list(getattr(boxes, "id", None))
            online = [
                (box, int(tid), float(conf), int(cls_id))
                for box, tid, conf, cls_id in zip(
                    xyxy, ids, confs, class_ids
                )
                if tid is not None
            ]

        h, w = frame.shape[:2]
        now = frame.timestamp
        active_tracks: List[Track] = []
        seen_tids: set[int] = set()

        class_names = getattr(self._detector, "class_names", {}) if self._detector else {}

        for box, tid, score, cls_id in online:
            x1, y1, x2, y2 = (float(v) for v in box[:4])
            bbox = BoundingBox(
                x1=x1, y1=y1, x2=x2, y2=y2
            ).clip(max_width=w, max_height=h)
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
                    class_name=class_names.get(cls_id, "person"),
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

        # LibreYOLO only returns currently confirmed tracks. Preserve the
        # engine's existing LOST-state contract during the configured grace
        # period so downstream code still receives stable lifecycle semantics.
        stale_tids = [tid for tid in self._tracks_cache if tid not in seen_tids]
        for tid in stale_tids:
            track = self._tracks_cache[tid]
            track.lost_frames += 1
            track.age += 1

            if track.lost_frames > self._track_buffer:
                del self._tracks_cache[tid]
                continue

            track.state = TrackState.LOST
            active_tracks.append(track)

        return active_tracks
