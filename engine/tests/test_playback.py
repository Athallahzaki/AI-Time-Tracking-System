from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.ingest.playback import PlaybackSource


class _Frames:
    def __init__(self) -> None:
        self.index = 0
        self.is_running = False

    def start(self) -> None:
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False

    def read(self):
        pts = (0.0, 0.05)[self.index]
        self.index += 1
        return SimpleNamespace(
            metadata=SimpleNamespace(pts=pts, stream_epoch=1)
        )


def test_playback_source_does_not_let_media_pts_run_ahead(monkeypatch):
    clock = iter((100.0, 100.0, 100.0, 100.0, 100.01))
    sleeps: list[float] = []
    monkeypatch.setattr("engine.ingest.playback.time.perf_counter", lambda: next(clock))
    monkeypatch.setattr("engine.ingest.playback.time.sleep", sleeps.append)

    source = PlaybackSource(_Frames())
    source.start()
    source.read()
    source.read()

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.05)
