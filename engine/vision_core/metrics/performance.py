from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class PerformanceMetrics:
    """Tracks real-time runtime metrics such as FPS, latencies, and dropped frames."""
    window_size: int = 60

    _frame_times: deque = field(default_factory=deque)
    _latencies: Dict[str, deque] = field(default_factory=dict)
    _total_frames: int = 0
    _dropped_frames: int = 0
    _start_time: float = field(default_factory=time.time)

    def record_frame(self) -> None:
        """Records the completion of one frame processing cycle."""
        now = time.perf_counter()
        self._frame_times.append(now)
        self._total_frames += 1
        if len(self._frame_times) > self.window_size:
            self._frame_times.popleft()

    def record_latency(self, stage_name: str, duration_ms: float) -> None:
        """Records latency for a specific pipeline stage (e.g. 'detector', 'tracker')."""
        if stage_name not in self._latencies:
            self._latencies[stage_name] = deque(maxlen=self.window_size)
        self._latencies[stage_name].append(duration_ms)

    def record_drop(self) -> None:
        """Records a dropped or skipped frame."""
        self._dropped_frames += 1

    @property
    def fps(self) -> float:
        """Calculates current rolling FPS over the window."""
        if len(self._frame_times) < 2:
            return 0.0
        delta = self._frame_times[-1] - self._frame_times[0]
        if delta <= 0:
            return 0.0
        return (len(self._frame_times) - 1) / delta

    @property
    def average_latencies(self) -> Dict[str, float]:
        """Returns average latency in milliseconds for each monitored stage."""
        result = {}
        for stage, dq in self._latencies.items():
            if dq:
                result[stage] = sum(dq) / len(dq)
            else:
                result[stage] = 0.0
        return result

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self._start_time)

    def to_dict(self) -> Dict[str, float]:
        """Export metrics as dictionary."""
        data = {
            "fps": round(self.fps, 2),
            "total_frames": self.total_frames,
            "dropped_frames": self.dropped_frames,
            "uptime_sec": round(self.uptime_seconds, 1),
        }
        for stage, lat in self.average_latencies.items():
            data[f"latency_{stage}_ms"] = round(lat, 2)
        return data

    def summary_str(self) -> str:
        lat_strs = [f"{k}: {v:.1f}ms" for k, v in self.average_latencies.items()]
        lat_part = (" | " + ", ".join(lat_strs)) if lat_strs else ""
        return f"FPS: {self.fps:.1f} | Frames: {self._total_frames} (Drops: {self._dropped_frames}){lat_part}"
