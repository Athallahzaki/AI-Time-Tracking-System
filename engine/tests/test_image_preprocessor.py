import numpy as np
import pytest

from engine.plugins.face_recognizer.preprocessing.image_preprocessor import (
    DefaultImagePreprocessor,
)


def test_default_preprocessor_preserves_image():
    image = np.zeros((100, 50, 3), dtype=np.uint8)

    preprocessor = DefaultImagePreprocessor()

    result = preprocessor.preprocess(image)

    assert result is image
    assert result.shape == image.shape


def test_default_preprocessor_rejects_empty_image():
    image = np.empty((0, 0, 3), dtype=np.uint8)

    preprocessor = DefaultImagePreprocessor()

    with pytest.raises(ValueError):
        preprocessor.preprocess(image)