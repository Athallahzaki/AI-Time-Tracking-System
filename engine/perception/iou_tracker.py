from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple
from ..ports.geometry import BoundingBox, Point
from ..ports.detection import Detection
from ..ports.tracking import Track, TrackState
from ..ports.frame import Frame

logger = logging.getLogger(__name__)


class IoUTracker:
    """
    Lightweight, self-contained multi-object tracker based on spatial overlap (IoU),
    normalized center distance, size similarity, and motion velocity.
    Requires no heavy external dependencies (e.g., LAPJV, Cython, Kalmans) and runs at >1000 FPS.
    """

    def __init__(
        self,
        min_iou_threshold: float = 0.25,
        reconnect_score_threshold: float = 0.40,
        max_missing_frames: int = 30,      # Evict track after ~1 sec at 30 FPS
        min_hits_to_confirm: int = 3,       # NEW -> TRACKED after N hits
        weight_center: float = 0.45,
        weight_iou: float = 0.30,
        weight_size: float = 0.15,
        weight_direction: float = 0.10,
    ) -> None:
        self._min_iou = min_iou_threshold
        self._reconnect_score_thresh = reconnect_score_threshold
        self._max_missing_frames = max_missing_frames
        self._min_hits_to_confirm = min_hits_to_confirm

        self._w_center = weight_center
        self._w_iou = weight_iou
        self._w_size = weight_size
        self._w_direction = weight_direction

        self._next_track_id = 1
        self._tracks: Dict[int, Track] = {}

    def reset(self) -> None:
        """Clears all active tracks."""
        self._tracks.clear()
        self._next_track_id = 1

    def update(self, detections: List[Detection], frame: Frame) -> List[Track]:
        """
        Associates input detections with existing tracks.
        Updates velocities, hits, age, and handles lifecycle states.
        """
        now = frame.timestamp

        # Compute cost/score matrix between active tracks and detections
        active_track_ids = list(self._tracks.keys())
        unmatched_detections = set(range(len(detections)))
        unmatched_tracks = set(active_track_ids)
        matched_pairs: List[Tuple[int, int]] = []  # (track_id, det_idx)

        # Greedy matching based on affinity score
        candidates: List[Tuple[float, int, int]] = []
        for tid in active_track_ids:
            track = self._tracks[tid]
            for d_idx, det in enumerate(detections):
                score = self._compute_affinity_score(track, det.bbox)
                if score >= self._reconnect_score_thresh:
                    candidates.append((score, tid, d_idx))

        # Sort descending by score
        candidates.sort(key=lambda x: x[0], reverse=True)

        for score, tid, d_idx in candidates:
            if tid in unmatched_tracks and d_idx in unmatched_detections:
                unmatched_tracks.remove(tid)
                unmatched_detections.remove(d_idx)
                matched_pairs.append((tid, d_idx))

        # 1. Update matched tracks
        for tid, d_idx in matched_pairs:
            track = self._tracks[tid]
            det = detections[d_idx]

            # Calculate velocity
            dt = max(1e-4, now - track.last_seen_timestamp)
            prev_cx, prev_cy = track.bbox.center.x, track.bbox.center.y
            curr_cx, curr_cy = det.bbox.center.x, det.bbox.center.y

            inst_vx = (curr_cx - prev_cx) / dt
            inst_vy = (curr_cy - prev_cy) / dt

            # Smooth velocity (EMA)
            old_vx, old_vy = track.velocity
            smooth_vx = old_vx * 0.7 + inst_vx * 0.3
            smooth_vy = old_vy * 0.7 + inst_vy * 0.3

            track.bbox = det.bbox
            track.confidence = det.confidence
            track.class_id = det.class_id
            track.class_name = det.class_name
            track.last_seen_timestamp = now
            track.hits += 1
            track.age += 1
            track.lost_frames = 0
            track.velocity = (smooth_vx, smooth_vy)
            track.history.append(det.bbox.center)
            if len(track.history) > 30:
                track.history.pop(0)

            # State transition to TRACKED if confirmed
            if track.state == TrackState.NEW and track.hits >= self._min_hits_to_confirm:
                track.state = TrackState.TRACKED
            elif track.state == TrackState.LOST:
                track.state = TrackState.TRACKED

        # 2. Update unmatched existing tracks (mark as LOST or REMOVED)
        to_remove = []
        for tid in unmatched_tracks:
            track = self._tracks[tid]
            track.lost_frames += 1
            track.age += 1

            if track.lost_frames > self._max_missing_frames:
                track.state = TrackState.REMOVED
                to_remove.append(tid)
            else:
                track.state = TrackState.LOST

        # 3. Create new tracks for unmatched detections
        for d_idx in unmatched_detections:
            det = detections[d_idx]
            new_id = self._next_track_id
            self._next_track_id += 1

            new_track = Track(
                track_id=new_id,
                bbox=det.bbox,
                state=TrackState.NEW if self._min_hits_to_confirm > 1 else TrackState.TRACKED,
                class_id=det.class_id,
                class_name=det.class_name,
                confidence=det.confidence,
                first_seen_timestamp=now,
                last_seen_timestamp=now,
                age=1,
                hits=1,
                lost_frames=0,
                velocity=(0.0, 0.0),
                history=[det.bbox.center],
            )
            self._tracks[new_id] = new_track

        # Remove evicted tracks from internal tracking map
        for tid in to_remove:
            del self._tracks[tid]

        return list(self._tracks.values())

    def _compute_affinity_score(self, track: Track, new_box: BoundingBox) -> float:
        """
        Combines IoU, normalized center distance, size similarity,
        and directional velocity alignment.
        """
        old_box = track.bbox

        # IoU score
        iou = old_box.iou(new_box)

        # Center distance score (normalized)
        dist_ratio = old_box.normalized_center_distance(new_box)
        max_dist = 1.5
        center_score = max(0.0, 1.0 - (dist_ratio / max_dist)) if dist_ratio < max_dist else 0.0

        # Size similarity
        size_score = old_box.size_similarity(new_box)

        # Directional velocity score
        vx, vy = track.velocity
        vel_mag = (vx ** 2 + vy ** 2) ** 0.5
        dx = new_box.center.x - old_box.center.x
        dy = new_box.center.y - old_box.center.y
        disp_mag = (dx ** 2 + dy ** 2) ** 0.5

        if vel_mag > 1.0 and disp_mag > 1.0:
            dot = (dx * vx + dy * vy) / (vel_mag * disp_mag)
            dot = max(-1.0, min(1.0, dot))
            dir_score = (dot + 1.0) / 2.0  # Normalized to [0, 1]
        else:
            dir_score = 0.5  # Neutral

        score = (
            self._w_center * center_score
            + self._w_iou * iou
            + self._w_size * size_score
            + self._w_direction * dir_score
        )

        if iou >= 0.15:
            score += 0.08

        return min(1.0, score)
