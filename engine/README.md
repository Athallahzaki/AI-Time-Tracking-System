# engine/ — B0: port, nothing more

This is step 0 of `ARCHITECTURE.md` §14 and B0 of `WORKPLAN.md` §3: the old
`vision_core/` and the parts of `plugins/face_recognizer/` that belong to
perception, moved into the structure `PROJECT STRUCTURE.md` §5 describes.

**It is not an improvement.** The baseline that B1's benchmark measures has to
be the behaviour of the old code, so the bugs came along on purpose. If you
find one and fix it here, you have quietly destroyed the ability to attribute
every later change to the step that caused it.

## Running it

```bash
# no GPU, no model weights, no torch — this is what CI runs
python -m engine.tools.run --mock --frames 30

# a real file, with real weights installed
python -m engine.tools.run --source samples/room.mp4

pytest engine/tests -q
```

The summary line reports the classes that actually ran, not the ones the config
asked for.

## What is deliberately still broken

| Symptom | Where | Fixed in |
|---|---|---|
| Skipped frames feed the tracker stale detections | `pipeline/engine.py` §2 | step 5 |
| `target_fps: 30` wastes ~3× the detection budget | `config/default_config.yaml` | step 10 |
| Tracker adapter still wraps Ultralytics (AGPL-3.0) and drags in torch | `perception/bytetrack_tracker.py` | step 11 |
| `cv2.VideoCapture` throws away PTS | `ingest/cv_stream.py` | step 2 |
| bbox on the wire is still pixel-space | everywhere | step 8 wires `NormalizedBox` in |

`tests/test_b0_port.py::test_stale_detection_bug_is_still_present` asserts the
first one **on purpose**. When step 5 arrives, invert it.

## What rode along, and why it was allowed

Four changes whose measurable effect is exactly zero. "Small" here means
*invisible to the benchmark*, not *short diff* — `target_fps: 30 → 10` is one
number in a YAML file and the largest behavioural lever in the whole plan,
which is why it is a step of its own.

1. **`crop()` copies instead of returning a view** (`perception/person_cropper.py`).
   Identical byte-for-byte while everything is synchronous; prevents silent
   corruption the moment crops are queued (§5.2, §9 item 10).
2. **Temporal constants are seconds** (`config/schema.py`). At 30 fps the
   conversion is the identity — `seconds_to_frames(1.0, 30) == 30`, which is
   exactly the `track_buffer=30` the old code hardcoded. There is a test for
   that equality, because it is the thing that makes this a port and not a
   change.
3. **`NormalizedBox` exists** (`ports/geometry.py`). A boundary type only:
   `api/`, `view.frame` and `door_region`. Internal geometry stays in pixels —
   face detection, cropping and the ByteTrack Kalman filter are all calibrated
   in pixel units, and normalising them would break the motion model while
   looking tidy.
4. **Strict mode** (`config/`, `perception/bytetrack_tracker.py`). Not a
   convenience: a prerequisite for the benchmark. See below.

## Strict mode, and why it is not optional

`ARCHITECTURE.md` §9 item 9 describes the worst failure mode this system has —
a component swallows an exception, degrades to something that looks harmless,
and the logs stay clean while the data goes wrong.

The port surfaced a second instance of it, in B's own territory:
`ByteTrackTracker._init_tracker` caught `Exception` and fell back to
`IoUTracker` with a log line at INFO. On a machine without Ultralytics, a
benchmark run would have measured a completely different tracker and still
produced a tidy report with plausible numbers. Under `strict_mode: true` that
is now a startup failure naming the backend. Falling back is still possible —
it just has to be asked for, with `tracker.backend: iou`.

A benchmark that can lie in a flattering direction is worse than no benchmark.

## Boundaries this code is held to

- **No company policy.** No break allowance, no working hours, no warning
  threshold. The old `attendance:` config block was not ported; it is dead, and
  its replacement is born in `backend/policy/`. `config/loader.py` rejects any
  config file carrying it, and CI runs `contracts/tools/policy_grep.py`.
- **No import of `backend/`.** Enforced by a ten-line test.
- **The mock path needs neither torch nor Ultralytics.** Enforced by a test
  that imports the pipeline in a subprocess and checks `sys.modules`. This is
  what lets B1's benchmark run in CI.

## Measurement

`vision_core/metrics/performance.py` was **not** ported. It kept a 60-sample
rolling mean per stage: no p95, no camera dimension, and it measured each stage
as a synchronous duration inside one loop — so the moment step 18 moves
recognition to a worker pool, `latency_recognize_ms` stops meaning anything
while still producing numbers.

What ships instead is `pipeline/instrument.py`: the seam, plus a recorder that
does nothing. B1 plugs the span recorder into it without touching the frame
loop again.

## Ownership

`ports/` and `pipeline/` are shared with Engine A — B0 initialises both,
including `__init__.py`, so A can pull and continue rather than resolve merge
conflicts. `identity/`, `store/` and `api/` are A's and are untouched here;
`store/` exists only as an empty package so the tree matches the document.
