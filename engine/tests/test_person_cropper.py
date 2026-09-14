import numpy as np

from engine.plugins.face_recognizer.preprocessing.person_cropper import (
    BoundingBoxPersonCropper,
)
from engine.vision_core.contracts.geometry import BoundingBox
from engine.vision_core.contracts.tracking import Track


def make_track(
    track_id=1,
    x1=10,
    y1=20,
    x2=60,
    y2=100,
):
    return Track(
        track_id=track_id,
        bbox=BoundingBox(
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
        ),
    )


def test_person_cropper_extracts_track_region():
    image = np.zeros((120, 100, 3), dtype=np.uint8)
    image[20:100, 10:60] = 255

    cropper = BoundingBoxPersonCropper()

    crop = cropper.crop(
        image=image,
        track=make_track(),
    )

    assert crop is not None
    assert crop.shape == (80, 50, 3)
    assert np.all(crop == 255)


def test_person_cropper_clips_bbox_to_frame():
    image = np.zeros((100, 100, 3), dtype=np.uint8)

    track = make_track(
        x1=-20,
        y1=-10,
        x2=120,
        y2=110,
    )

    cropper = BoundingBoxPersonCropper()

    crop = cropper.crop(
        image=image,
        track=track,
    )

    assert crop is not None
    assert crop.shape == (100, 100, 3)


def test_person_cropper_returns_none_for_invalid_bbox():
    image = np.zeros((100, 100, 3), dtype=np.uint8)

    track = make_track(
        x1=80,
        y1=80,
        x2=20,
        y2=20,
    )

    cropper = BoundingBoxPersonCropper()

    crop = cropper.crop(
        image=image,
        track=track,
    )

    assert crop is None


def test_person_cropper_returns_none_for_empty_image():
    image = np.empty((0, 0, 3), dtype=np.uint8)

    cropper = BoundingBoxPersonCropper()

    crop = cropper.crop(
        image=image,
        track=make_track(),
    )

    assert crop is None