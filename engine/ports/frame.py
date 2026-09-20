from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import numpy as np


@dataclass(frozen=True)
class FrameMetadata:
    """
    Metadata associated with an ingested frame.

    ## The timeline fields (B4)

    `pts`, `pts_source` and `stream_epoch` were added in B4 and are additive:
    every existing field keeps its meaning, and a source that does not know its
    timeline leaves them at their defaults. `ports/` is shared with Engine A, so
    this is a change A should know about even though nothing of A's breaks.

    **`pts`** — seconds on the source's own timeline. ARCHITECTURE.md §6.6: the
    engine and the backend pull the same stream, so for the same frame both read
    the same number, and nobody has to agree on a clock. It was living in
    `extra["pts"]` between B1 and B4, which is where things go to be forgotten:
    not greppable with confidence, invisible to a type checker, easy to
    misspell into silence.

    **`pts_source`** — where that number came from, and this is the field that
    stops a later reader from over-trusting it:

    - `"container"` — read off the stream. Real, and the only value that makes
      §6.6's arithmetic sound.
    - `"derived_from_fps"` — `(frame_index - 1) / declared_fps`. What
      `cv2.VideoCapture` forces, because it discards the real PTS (§5.5). Exact
      for a constant-rate file. **Not** exact for a variable-rate recording, and
      phone recordings are routinely variable-rate: the test clip reports
      r_frame_rate 25 against avg_frame_rate 24.8, which is 22 frames that do
      not exist being assumed into the timeline.
    - `"none"` — no timeline at all (the mock source).

    **`stream_epoch`** — increments every time a source reconnects. RTP restarts
    its timestamps from a fresh random offset after a reconnect, so PTS can jump
    or go backwards across that boundary. Anything computing a duration must
    refuse to subtract two PTS values from different epochs; the result would
    not be a wrong duration, it would be a meaningless one that still prints.

    **`wallclock`** — absolute time for this frame, derived once per epoch from
    the PTS-to-wallclock offset (§6.6). All interval arithmetic stays in PTS;
    this exists only for the edge, where an event is emitted and a human has to
    read "10:15".
    """

    frame_id: int
    timestamp: float = field(default_factory=time.time)
    source_id: str = "default"
    fps: float = 0.0
    width: int = 0
    height: int = 0

    pts: Optional[float] = None
    pts_source: str = "none"
    stream_epoch: int = 0
    wallclock: Optional[float] = None

    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_real_pts(self) -> bool:
        return self.pts is not None and self.pts_source == "container"


@dataclass
class Frame:
    """
    Encapsulates raw image buffer and associated metadata.
    Avoids unnecessary copies by passing the underlying ndarray.
    """
    image: np.ndarray
    metadata: FrameMetadata

    @property
    def frame_id(self) -> int:
        return self.metadata.frame_id

    @property
    def timestamp(self) -> float:
        return self.metadata.timestamp

    @property
    def pts(self) -> Optional[float]:
        return self.metadata.pts

    @property
    def stream_epoch(self) -> int:
        return self.metadata.stream_epoch

    @property
    def shape(self) -> tuple[int, ...]:
        return self.image.shape

    @property
    def height(self) -> int:
        return self.image.shape[0]

    @property
    def width(self) -> int:
        return self.image.shape[1]
