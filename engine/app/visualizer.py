from __future__ import annotations

import logging
import time
from collections import deque
from typing import List, Optional, Tuple
import cv2
import numpy as np

from ..vision_core.contracts.frame import Frame
from ..vision_core.contracts.tracking import Track, TrackState
from .config import VisualizerConfig

logger = logging.getLogger(__name__)


class OpenCVVisualizer:
    """
    Real-time visualization HUD (Head-Up Display) and frame sink.
    Renders status-colored bounding boxes, identity tags, timers, trajectory trails,
    and telemetry performance overlays.
    """

    # Status color scheme (BGR)
    COLOR_MAP = {
        "PASSING": (255, 255, 0),     # Cyan / Light Blue
        "CONFIRMED": (0, 255, 0),     # Green
        "WARNING": (0, 165, 255),     # Orange
        "LIMIT": (0, 0, 255),         # Red
        "UNKNOWN": (180, 180, 180),   # Gray
    }

    def __init__(
        self,
        config: Optional[VisualizerConfig] = None,
        is_headless: bool = False,
    ) -> None:
        self._config = config or VisualizerConfig()
        self._is_headless = is_headless
        self._window_created = False
        self._should_quit = False
        self._last_fps = 0.0
        self._frame_times: deque = deque(maxlen=30)

    def write(self, frame: Frame, tracks: List[Track]) -> None:
        """Renders annotations onto frame and displays window if not headless."""
        if not self._config.enabled:
            return

        annotated = frame.image.copy()

        # 1. Draw track trajectories
        if self._config.draw_history:
            for track in tracks:
                if len(track.history) > 1:
                    pts = np.array([[int(p.x), int(p.y)] for p in track.history], np.int32)
                    pts = pts.reshape((-1, 1, 2))
                    cv2.polylines(annotated, [pts], False, (100, 200, 255), 1, cv2.LINE_AA)

        # 2. Draw track bounding boxes & badges
        for track in tracks:
            if not track.is_active:
                continue

            x1, y1, x2, y2 = track.bbox.to_int_xyxy()
            presence_status = track.attributes.get("presence_status", "PASSING")
            identity = track.attributes.get("identity")
            similarity = track.attributes.get("similarity", 0.0)
            elapsed = track.attributes.get("session_elapsed", track.dwell_time)

            color = self.COLOR_MAP.get(presence_status, (255, 255, 255))
            if not identity:
                # If unknown person
                id_text = f"Track #{track.track_id} (Unknown)"
            else:
                id_text = f"Employee {identity}"

            # Box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Badge Label
            dur_str = self._format_duration(elapsed)
            label = f"{id_text} | {presence_status} | {dur_str}"
            if similarity > 0:
                label += f" | {similarity:.2f}"

            # Label background banner
            (tw, th), bl = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 1)
            label_y1 = max(0, y1 - th - bl - 4)
            label_y2 = y1

            cv2.rectangle(annotated, (x1, label_y1), (x1 + tw + 6, label_y2), color, -1)
            cv2.putText(
                annotated,
                label,
                (x1 + 3, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

        # 3. Top Telemetry Banner
        if self._config.show_metrics_overlay:
            # Compute local FPS from our own frame-time ring buffer.
            # This matches what the user sees in the window (sink FPS),
            # which may differ slightly from the engine's pipeline FPS.
            now = time.perf_counter()
            self._frame_times.append(now)
            if len(self._frame_times) > 1:
                local_fps = (len(self._frame_times) - 1) / max(
                    1e-4,
                    self._frame_times[-1] - self._frame_times[0],
                )
            else:
                local_fps = 0.0
            self._draw_telemetry_banner(annotated, frame, tracks, local_fps)

        # 4. Display frame
        if not self._is_headless:
            if not self._window_created:
                cv2.namedWindow(self._config.window_name, cv2.WINDOW_NORMAL)
                self._window_created = True

            cv2.imshow(self._config.window_name, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                self._should_quit = True
            elif key == ord("s"):
                snap_path = f"snapshot_{int(time.time())}.jpg"
                cv2.imwrite(snap_path, annotated)
                logger.info(f"Saved snapshot to {snap_path}")

    def _draw_telemetry_banner(
        self,
        img: np.ndarray,
        frame: Frame,
        tracks: List[Track],
        fps: float = 0.0,
    ) -> None:
        """Draws top HUD banner with FPS and active counts."""
        h, w = img.shape[:2]
        banner_h = 32

        # Draw semi-transparent header
        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (w, banner_h), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.75, img, 0.25, 0, img)

        active_people = len([t for t in tracks if t.is_active])
        recognized_count = len([t for t in tracks if t.is_active and t.attributes.get("identity")])

        banner_text = (
            f"FPS: {fps:.1f} | People: {active_people} (Recognized: {recognized_count}) | "
            f"Frame: #{frame.frame_id} | Res: {w}x{h}"
        )
        cv2.putText(
            img,
            banner_text,
            (10, 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 200),
            1,
            cv2.LINE_AA,
        )

    @staticmethod
    def _format_duration(seconds: float) -> str:
        s = max(0, int(seconds))
        m = s // 60
        sec = s % 60
        return f"{m:02d}:{sec:02d}"

    def close(self) -> None:
        if self._window_created:
            try:
                cv2.destroyWindow(self._config.window_name)
            except Exception:
                pass
            self._window_created = False

    @property
    def should_quit(self) -> bool:
        return self._should_quit
