"""
Test assets that are generated rather than committed.

`engine/samples/synthetic_24fps.mp4` is used by five tests, `*.mp4` is in
`.gitignore`, and nothing produced the file. On the machine B0 was written on it
existed; everywhere else — CI, a fresh clone, the next person's laptop — those
tests failed with `FileNotFoundError` on a path that was never going to exist.
A red suite is a suite people stop reading, and this one is red for a reason
that has nothing to do with the code under test.

Generating it is better than committing it on two counts. The `.gitignore` rule
exists because of §7.4: recordings in this project are biometric data about
colleagues, and git means retention for ever. A rule with an exception carved
into it invites the next exception to be a real recording. And the properties
these tests care about are *specific* — a rate that is not the 30.0 fps
placeholder `VideoFileSource` assumes before it opens anything — so a generated
file states them in code instead of leaving them as a property of a binary
nobody can inspect in a diff.

It is deliberately tiny: 160x120, two seconds, a moving rectangle. Nothing here
detects anything; the file exists so that opening it reports 24 fps.
"""

from __future__ import annotations

from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"
SYNTHETIC_24FPS = SAMPLES_DIR / "synthetic_24fps.mp4"

SYNTHETIC_FPS = 24.0
SYNTHETIC_FRAMES = 48
SYNTHETIC_SIZE = (160, 120)


def ensure_synthetic_clip(path: Path = SYNTHETIC_24FPS) -> Path:
    """
    Returns a 24 fps clip, writing it first if it is not there.

    Why 24 and not 30: `VideoFileSource.__init__` sets `self._fps = 30.0` as a
    placeholder and only learns the real rate in `start()`. A test clip at 30 fps
    could not tell the placeholder from the truth, and the regression this guards
    — every seconds-to-frames constant configured against the placeholder — would
    pass unnoticed.
    """
    path = Path(path)
    if path.exists():
        return path

    import cv2
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = SYNTHETIC_SIZE

    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        SYNTHETIC_FPS,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(
            f"OpenCV could not open a writer for {path}. The mp4v encoder is "
            f"missing from this OpenCV build, so the clip cannot be generated "
            f"here. Copy one in, or install a build with it."
        )
    try:
        for index in range(SYNTHETIC_FRAMES):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            x = (index * 3) % max(1, width - 30)
            frame[40:80, x:x + 30] = (0, 200, 255)
            writer.write(frame)
    finally:
        writer.release()

    if not path.exists():
        raise RuntimeError(f"writer reported success but {path} does not exist")
    return path
