"""core.target_fps benar-benar membuang frame sebelum detector."""
from __future__ import annotations

from types import SimpleNamespace

from engine.config import EngineConfig
from engine.pipeline.engine import VisionEngine


class _Source:
    def __init__(self, pts_list):
        self._frames = [SimpleNamespace(metadata=SimpleNamespace(pts=p)) for p in pts_list]

    def read(self):
        return self._frames.pop(0) if self._frames else None


def _kept(pts_list, target):
    engine = VisionEngine(source=_Source(pts_list), detector=None, tracker=None,
                          config=EngineConfig(source_type="mock", target_fps=target))
    kept = []
    while True:
        frame = engine._read_due_frame()
        if frame is None:
            return kept, engine.decimated_frames
        kept.append(frame.metadata.pts)


def test_25fps_source_to_10fps():
    pts = [i / 25 for i in range(250)]           # 10 s
    kept, dropped = _kept(pts, 10.0)
    assert 95 <= len(kept) <= 105
    assert dropped == 250 - len(kept)
    gaps = [b - a for a, b in zip(kept, kept[1:])]
    assert max(gaps) <= 0.12 + 1e-9


def test_target_above_source_keeps_everything():
    pts = [i / 25 for i in range(100)]
    kept, dropped = _kept(pts, 30.0)
    assert len(kept) == 100 and dropped == 0


def test_no_target_or_no_pts_keeps_everything():
    assert len(_kept([i / 25 for i in range(50)], None)[0]) == 50
    assert len(_kept([None] * 50, 10.0)[0]) == 50


def test_timeline_restart_resets_cadence():
    pts = [i / 25 for i in range(50)] + [i / 25 for i in range(50)]
    kept, _ = _kept(pts, 10.0)
    assert kept.count(0.0) == 2
