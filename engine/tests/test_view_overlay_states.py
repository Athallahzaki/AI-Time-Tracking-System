"""Overlay hanya menggambar track yang terlihat di frame ini.

Gejala yang dikunci: di dashboard satu orang tampil dengan 2-3 kotak. Penyebab:
ByteTrack memberi ID baru (ID switch), sementara track lama tetap dikembalikan
selama masa tenggang `track_buffer_seconds` dengan state LOST dan kotak terakhir
yang membeku. `_maybe_view` dulu mengirim semuanya ke kanal view.

Yang TIDAK boleh berubah: masa tenggang itu tetap milik presensi. Tes ini hanya
memeriksa kanal view.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any, Dict, List

import numpy as np

from engine.config import load_config
from engine.ports.frame import Frame, FrameMetadata
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import Track, TrackState
from engine.runtime.camera import CameraSpec, CameraSupervisor


def _camera(views: List[Dict[str, Any]]) -> CameraSupervisor:
    config = dataclasses.replace(
        load_config(), source_type="mock", auto_warmup=False, strict_mode=True
    )
    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock"), config=config,
        emit_event=lambda m: m, emit_view=lambda m: views.append(m) or m,
        view_fps=1000.0,
    )
    clock = SimpleNamespace(
        offset=1_791_250_000.0, camera_id="r1", stream_epoch=1,
        at=lambda pts: "2026-10-08T11:00:00Z",
    )
    # Assembler baru dibuat saat stream terbuka; di sini cukup jam-nya saja.
    camera._assembler = SimpleNamespace(clock_for=lambda camera_id: clock)
    return camera


NOW = 1_000.0


def _frame() -> Frame:
    return Frame(
        image=np.zeros((100, 200, 3), dtype=np.uint8),
        metadata=FrameMetadata(
            frame_id=1, source_id="r1", fps=10.0,
            width=200, height=100, pts=5.0, pts_source="container",
            timestamp=NOW,
        ),
    )


def _track(track_id: int, state: TrackState, x: float, last_seen: float = NOW) -> Track:
    track = Track(track_id=track_id, bbox=BoundingBox(x, 10.0, x + 40.0, 90.0), state=state)
    track.last_seen_timestamp = last_seen
    track.attributes["track_uuid"] = f"uuid-{track_id}"
    return track


def test_track_lost_tidak_dikirim_ke_overlay():
    views: List[Dict[str, Any]] = []
    camera = _camera(views)
    tracks = [
        _track(1, TrackState.LOST, 10.0, last_seen=NOW - 0.8),  # kotak hantu
        _track(2, TrackState.TRACKED, 60.0),   # orang yang sama, ID baru
        _track(3, TrackState.NEW, 120.0),
        _track(4, TrackState.REMOVED, 150.0),
    ]
    camera._maybe_view(_frame(), tracks, 5.0)

    assert len(views) == 1
    sent = [box["track_uuid"] for box in views[0]["boxes"]]
    assert sent == ["uuid-2", "uuid-3"]


def test_frame_tanpa_track_aktif_tetap_dikirim_kosong():
    """Frame kosong itu bermakna: tanpanya browser terus menggambar kotak terakhir."""
    views: List[Dict[str, Any]] = []
    camera = _camera(views)
    camera._maybe_view(_frame(), [_track(1, TrackState.LOST, 10.0, last_seen=NOW - 1.0)], 5.0)

    assert len(views) == 1
    assert views[0]["boxes"] == []


def test_lost_sekejap_tetap_digambar_supaya_tidak_berkedip():
    """Satu frame tanpa deteksi (0,1 dtk di 10 fps) tidak boleh menghapus kotak."""
    views: List[Dict[str, Any]] = []
    camera = _camera(views)
    tracks = [
        _track(1, TrackState.LOST, 10.0, last_seen=NOW - 0.1),
        _track(2, TrackState.LOST, 60.0, last_seen=NOW - 0.5),
    ]
    camera._maybe_view(_frame(), tracks, 5.0)

    sent = [box["track_uuid"] for box in views[0]["boxes"]]
    assert sent == ["uuid-1"]
