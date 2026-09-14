import pytest
import numpy as np

from engine.vision_core.contracts.geometry import BoundingBox, Point
from engine.vision_core.contracts.detection import Detection
from engine.vision_core.contracts.tracking import Track, TrackState
from engine.vision_core.contracts.frame import Frame, FrameMetadata


def test_point_distance():
    p1 = Point(x=0.0, y=0.0)
    p2 = Point(x=3.0, y=4.0)
    assert p1.distance_to(p2) == pytest.approx(5.0)


def test_bounding_box_geometry():
    box = BoundingBox(x1=10.0, y1=20.0, x2=50.0, y2=100.0)
    assert box.width == 40.0
    assert box.height == 80.0
    assert box.area == 3200.0
    assert box.center.x == 30.0
    assert box.center.y == 60.0
    assert box.to_xyxy() == (10.0, 20.0, 50.0, 100.0)
    assert box.to_xywh() == (10.0, 20.0, 40.0, 80.0)
    assert box.to_int_xyxy() == (10, 20, 50, 100)


def test_bounding_box_invalid():
    with pytest.raises(ValueError):
        BoundingBox(x1=50.0, y1=20.0, x2=10.0, y2=100.0)


def test_bounding_box_iou():
    box1 = BoundingBox(x1=0.0, y1=0.0, x2=10.0, y2=10.0)
    box2 = BoundingBox(x1=5.0, y1=0.0, x2=15.0, y2=10.0)
    # Intersection = 5 * 10 = 50. Union = 100 + 100 - 50 = 150. IoU = 50 / 150 = 1/3
    assert box1.iou(box2) == pytest.approx(1.0 / 3.0)

    # Disjoint boxes
    box3 = BoundingBox(x1=20.0, y1=20.0, x2=30.0, y2=30.0)
    assert box1.iou(box3) == 0.0


def test_bounding_box_clipping():
    box = BoundingBox(x1=-10.0, y1=-5.0, x2=120.0, y2=150.0)
    clipped = box.clip(max_width=100, max_height=100)
    assert clipped.x1 == 0.0
    assert clipped.y1 == 0.0
    assert clipped.x2 == 100.0
    assert clipped.y2 == 100.0


def test_detection_contract():
    box = BoundingBox(x1=10, y1=10, x2=30, y2=50)
    det = Detection(bbox=box, confidence=0.85, class_id=0, class_name="person")
    assert det.confidence == 0.85
    assert det.class_name == "person"

    with pytest.raises(ValueError):
        Detection(bbox=box, confidence=1.5, class_id=0)


def test_track_contract():
    box = BoundingBox(x1=10, y1=10, x2=30, y2=50)
    track = Track(track_id=1, bbox=box, state=TrackState.NEW)
    assert track.is_active is True
    assert track.is_confirmed is False

    track.state = TrackState.TRACKED
    assert track.is_confirmed is True
