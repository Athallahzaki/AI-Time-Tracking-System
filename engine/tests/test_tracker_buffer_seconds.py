"""04 §5: buffer track dalam detik PTS, bukan jumlah frame.

Uji 2 Okt 2026: mode live menganalisis ±4 fps sementara buffer dihitung dari
target 12 fps. 1,0 dtk = 12 frame = 3 dtk sungguhan: track orang yang sudah
pergi tetap hidup cukup lama untuk menempel ke orang berikutnya.
"""

from __future__ import annotations

import numpy as np

from engine.perception.iou_tracker import IoUTracker
from engine.ports.detection import Detection
from engine.ports.frame import Frame, FrameMetadata
from engine.ports.geometry import BoundingBox
from engine.ports.tracking import TrackState

IMAGE = np.zeros((10, 10, 3), dtype=np.uint8)


def frame(pts, i):
    return Frame(image=IMAGE, metadata=FrameMetadata(frame_id=i, pts=pts, timestamp=1000.0 + pts))


def person(x=100.0):
    return Detection(bbox=BoundingBox(x, 100.0, x + 60.0, 260.0), confidence=0.9, class_id=0, class_name="person")


def run(tracker, fps, seen_seconds, gone_seconds):
    """Orang terlihat `seen_seconds`, lalu hilang; kembalikan detik hilang saat track dihapus."""
    i, pts = 0, 0.0
    while pts < seen_seconds:
        tracker.update([person()], frame(pts, i))
        i, pts = i + 1, pts + 1.0 / fps
    gone_at = pts
    while pts < seen_seconds + gone_seconds:
        tracks = tracker.update([], frame(pts, i))
        if not tracks:
            return pts - gone_at
        i, pts = i + 1, pts + 1.0 / fps
    return None


def test_buffer_detik_tidak_ikut_melar_saat_fps_turun():
    # Buffer 12 frame (1 dtk pada target 12 fps), tapi sebenarnya hanya 4 fps.
    by_frames = run(IoUTracker(max_missing_frames=12), fps=4.0, seen_seconds=2.0, gone_seconds=6.0)
    by_seconds = run(IoUTracker(max_missing_frames=12, max_missing_seconds=1.0),
                     fps=4.0, seen_seconds=2.0, gone_seconds=6.0)
    assert by_frames >= 3.0, "perilaku lama: 12 frame pada 4 fps = 3 dtk"
    assert 1.0 <= by_seconds <= 1.3, f"buffer wajib ±1 dtk berapa pun fps-nya, dapat {by_seconds}"


def test_oklusi_singkat_tetap_track_yang_sama():
    tracker = IoUTracker(max_missing_frames=12, max_missing_seconds=1.0, min_hits_to_confirm=1)
    i, pts, first_id = 0, 0.0, None
    for _ in range(8):                              # 2 dtk terlihat, 4 fps
        tracks = tracker.update([person()], frame(pts, i))
        first_id = first_id or tracks[0].track_id
        i, pts = i + 1, pts + 0.25
    for _ in range(3):                              # 0,75 dtk terhalang
        tracker.update([], frame(pts, i))
        i, pts = i + 1, pts + 0.25
    tracks = tracker.update([person()], frame(pts, i))
    assert [t.track_id for t in tracks] == [first_id]


def test_timeline_mulai_ulang_menghapus_track_lama():
    tracker = IoUTracker(max_missing_frames=12, max_missing_seconds=1.0)
    for i in range(10):
        tracker.update([person()], frame(50.0 + i * 0.1, i))
    tracks = tracker.update([], frame(0.0, 11))       # reconnect: pts kembali ke 0
    assert tracks == []


def test_tanpa_pts_kembali_ke_aturan_frame():
    tracker = IoUTracker(max_missing_frames=2, max_missing_seconds=1.0)
    no_pts = lambda i: Frame(image=IMAGE, metadata=FrameMetadata(frame_id=i, pts=None))
    tracker.update([person()], no_pts(0))
    assert tracker.update([], no_pts(1)) and tracker.update([], no_pts(2))
    assert tracker.update([], no_pts(3)) == []
