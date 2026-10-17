"""stream_epoch saat kamera dibuka ulang oleh supervisor (paket ea-r14).

Gladi 17 Okt: cam03 putus (`open_failed`) lalu dibuka ulang; validator kontrak
menolak `camera.online` dengan `stream_epoch` 0 -> 0, dan puluhan event berikutnya
punya PTS "mundur" 723 -> 0 di epoch yang sama. Penyebab: `_build()` membuat sumber
PyAV baru (StreamTimeline mulai dari 0) dan PresenceAssembler baru (jam mulai 0).
Reconnect DI DALAM sumber (epoch naik di timeline) sudah benar sejak dulu; yang
rusak hanya pembukaan ulang oleh supervisor.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any, Dict, List

import numpy as np

from engine.config import load_config
from engine.ingest.timeline import StreamTimeline
from engine.ports.frame import Frame, FrameMetadata
from engine.presence.assembler import PresenceAssembler
from engine.runtime import camera as camera_module
from engine.runtime.camera import CameraSpec, CameraSupervisor


def _config():
    return dataclasses.replace(load_config(), source_type="mock", auto_warmup=False, strict_mode=True)


def _kumpul():
    pesan: List[Dict[str, Any]] = []
    kunci = threading.Lock()

    def emit(m: Dict[str, Any]) -> Dict[str, Any]:
        with kunci:
            m = dict(m)
            m.setdefault("seq", len(pesan) + 1)
            pesan.append(m)
            return m

    return pesan, emit


class _SumberDenganTimeline:
    """Sumber PyAV tiruan: epoch frame = epoch timeline, berakhir setelah n frame."""

    def __init__(self, epoch: int, frames: int = 15, offset: float = 1_700_000_000.0) -> None:
        self.timeline = StreamTimeline(source_id="r1", epoch=epoch)
        self.timeline.begin_epoch(wall_now=offset)
        self._sisa = frames
        self._n = 0
        self._offset = offset
        self.is_running = True
        self.fps = 10.0
        self.resolution = (320, 240)
        self.total_frames = frames

    def start(self) -> None:
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False

    def read(self):
        if self._n >= self._sisa:
            self.is_running = False
            return None
        pts = self._n / 10.0
        self._n += 1
        return Frame(
            image=np.zeros((240, 320, 3), dtype=np.uint8),
            metadata=FrameMetadata(
                frame_id=self._n, source_id="r1", fps=10.0, width=320, height=240,
                pts=pts, pts_source="container", stream_epoch=self.timeline.epoch,
                wallclock=self._offset + pts, pts_wallclock_offset=self._offset,
            ),
        )


def test_timeline_bisa_mulai_dari_epoch_lanjutan():
    t = StreamTimeline(source_id="x", epoch=3)
    assert t.begin_epoch() == 3, "pembukaan pertama tidak menaikkan epoch"
    assert t.begin_epoch() == 4, "reconnect di dalam sumber tetap menaikkan"


def test_assembler_baru_memakai_epoch_yang_diberikan():
    pesan, emit = _kumpul()
    a = PresenceAssembler(emit=emit)
    a.camera_online("r1", wallclock_now=100.0, fps=10.0, stream_epoch=2)
    a.camera_online("r1", wallclock_now=200.0, fps=10.0)  # tanpa epoch: perilaku lama, naik 1
    online = [m for m in pesan if m["type"] == "camera.online"]
    assert [m["stream_epoch"] for m in online] == [2, 3]


def test_buka_ulang_oleh_supervisor_menaikkan_stream_epoch(monkeypatch):
    from engine import factory

    monkeypatch.setattr(camera_module, "RETRY_INITIAL_SECONDS", 0.05)
    diminta: List[int] = []
    real_build = factory.build_engine

    def build(config, **kwargs):
        base = kwargs.get("stream_epoch_base", 0)
        diminta.append(base)
        engine, _, fps = real_build(config, **kwargs)
        sumber = _SumberDenganTimeline(epoch=base, offset=1_700_000_000.0 + 100.0 * len(diminta))
        engine._source = sumber
        return engine, sumber, fps

    monkeypatch.setattr("engine.factory.build_engine", build)

    pesan, emit = _kumpul()
    kamera = CameraSupervisor(spec=CameraSpec("r1", "rtsp://127.0.0.1:8554/r1", None),
                              config=_config(), emit_event=emit, emit_view=lambda m: m)
    kamera.start()
    batas = time.time() + 30
    while time.time() < batas:
        if sum(1 for m in list(pesan) if m["type"] == "camera.online") >= 3:
            break
        time.sleep(0.02)
    kamera.stop()

    online = [m for m in pesan if m["type"] == "camera.online"]
    assert len(online) >= 3, f"supervisor tidak membuka ulang: {[m['type'] for m in pesan]}"
    epochs = [m["stream_epoch"] for m in online[:3]]
    assert epochs == [0, 1, 2], f"epoch tidak naik saat dibuka ulang: {epochs}"
    assert diminta[:3] == [0, 1, 2], "sumber baru harus dibuat dengan epoch lanjutan"
    assert any(m["type"] == "camera.failed" for m in pesan)
