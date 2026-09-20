# `engine/ingest` — B4: the timeline OpenCV threw away

`ARCHITECTURE.md` §5.5 and §6.6, `WORKPLAN.md` B4.

```bash
# run this FIRST. It is the only thing that proves the PyAV binding works.
python -m engine.tools.probe_ingest --video X:\video.mp4 --json bench/ingest-probe.json
```

## Read this before trusting anything here

**The PyAV binding was written without PyAV installed.** The environment it was
written in has no access to PyPI, so `pyav_source.py` could not be executed
once by its author. Everything around it — PTS conversion, the wallclock
anchor, the reconnect epoch, the frame-count fallback, the variable-rate
measurement — lives in `timeline.py` and is driven by a fake container in
`tests/test_b4_ingest.py`. What no unit test here can settle is whether real
libav behaves like that fake.

Two things close that gap, and neither is optional: `probe_ingest` on a real
file, and the `ingest-pyav` CI job, which installs `av`, opens a real clip and
asserts that both decoders agree on the frame count. If either fails, nothing
downstream of ingest means anything.

## What the first real recording actually said

`probe_ingest` on the 109 s test clip, and the reconstruction it allows:

| | |
|---|---|
| frames, both backends | 2711 — they agree exactly, so the binding is sound |
| `average_rate` / `guessed_rate` | 24.7988 / 25.0 |
| interval error, ≤1 s and ≤5 s | 0.6397 s |
| interval error, ≤30 s and ≤300 s | 0.8105 s |
| max deviation | 0.8027 s, at pts 98.92 |
| final drift | 0.0003 s |
| long frame intervals | 2 |
| decode | **not resolvable** — see below |

Those numbers are not vague evidence of "variable rate". They pin down exactly
what the phone did. The deviation of a true-25-fps file measured against an
average of 67775/2733 grows by 22/67775 = 0.324 ms per frame; 0.8027 s of it is
2473 frames, and 2473 × 0.04 = 98.92 s — the reported position of the maximum,
to four significant figures. The remaining 237 frames cover 10.36 s where 25 fps
would take 9.48, so 0.88 s — exactly 22 frames — is missing from the tail.

**The clip is a perfect 25 fps for 98.92 seconds and then stalls twice in the
last ten.** `cv2` reports the average, which smears those two stalls evenly
across the whole file.

The interval errors pin down the two stalls individually. A window of 1 s or
5 s can be wrong by 0.6397 s; adding the per-frame ramp back gives 0.64 s
exactly, which is **16 frames**. A 30 s window reaches 0.8105 s, so it contains
a second stall that a 5 s window does not — and the only size consistent with
both that figure and the 22 frames known to be missing is **6 frames**, with
the two stalls about 8.5 s apart. Had the second stall been 5 frames they would
sit 3.6 s apart and the 5-second figure would already have shown it.

So: **16 frames and 6 frames, roughly 8.5 seconds apart, both in the final ten
seconds.** For a threshold measured in minutes per day, 0.81 s is 0.45% of the
budget — negligible, and now known rather than assumed.

### Which means the argument for reordering was mostly wrong

The case for taking B4 first was that the timeline error would be correlated
with the detector failing, and flattering — gaps looking shorter than they were.
The data says otherwise, in two ways.

In the constant-rate stretch the derived timeline runs 0.81% **fast**, so every
duration measured on it is *overstated* by that fraction: a twelve-second gap by
0.097 s, a twelve-minute one by 5.8 s. Overstating a gap is the conservative
direction, not the flattering one.

The flattering error is real but small and local: 0.88 s of dead time hidden in
two stalls, both in the final ten seconds. And the stalls sit at the end of the
recording, which looks like the phone finishing a file rather than anything to
do with the light.

So: had the original order been followed, the baseline would have been fine.
B4 was still worth doing first — the timeline is now correct rather than
correct-on-average, and the measurement cost nothing — but the reasoning that
justified it did not survive contact with the file. Recorded here rather than
quietly dropped.

### And the metric had the wrong headline

`max_abs_deviation` answers "how far apart are the two clocks at the worst
moment". Nothing in this system needs that. Every product metric is a
*duration*, and a duration inherits the **difference** of two deviations, not
their level — which is why a recording with 0.80 s of deviation misstates a
twelve-second gap by 0.097 s.

`interval_error_s` is the replacement: the largest amount by which any duration
of up to *w* seconds can be wrong, computed as the maximum spread of the
deviation inside a sliding window. On this clip it is under 50 ms for any
5-second window in the constant stretch and ~0.44 s for one spanning a stall.
The verdict is now taken from that, not from the deviation.

## Why B4 moved ahead of the baseline — the argument as it was made

Kept verbatim, and **read the section above first**: most of this did not
survive the measurement. It is here because a prediction that is quietly
deleted once it turns out wrong teaches nobody anything, and because the last
paragraph of it is the part that still holds.

`WORKPLAN.md` puts B1 first and B4 fourth. B4 went first anyway, deliberately.

`ffprobe` on the test recording reports `r_frame_rate 25/1` against
`avg_frame_rate 67775/2733`. Reduce the second and it is **2711 frames in
109.32 seconds**, where a constant 25 fps would have produced 2733. Twenty-two
frames that were never recorded — 0.8% — and `frame_index / fps` assumes every
one of them into the timeline.

Small. The reason it still mattered is the *direction*: a phone drops frames
when the exposure lengthens, which is when the light is bad, which is when the
detector loses people. The error is correlated with the thing being measured,
and correlated in the flattering direction — a gap measured on the derived
timeline near a dropped burst looks **shorter** than it was. Taking the
baseline on a timeline with a one-way bias, however small, and then fixing the
timeline afterwards would leave every later comparison differing by two causes
at once.

And the decisive part: on the old timeline there was no way to find out how big
the error was. On the new one it is free. `metrics.timeline` and
`probe_ingest` both report it, so the question is now settled by a number
rather than by this argument.

## What is here

| File | What it is |
|---|---|
| `timeline.py` | Everything about time that does not need a decoder. Fully tested. |
| `pyav_source.py` | The binding. Deliberately thin, for the reason above. |
| `video_file.py`, `cv_stream.py` | The OpenCV originals. Kept for one step. |
| `mock_source.py` | Synthetic frames for CI. |

Both backends fill `FrameMetadata.pts`. Only one of them earned it, and
`pts_source` says which:

- `container` — read off the stream. The only value that makes §6.6's
  arithmetic sound.
- `derived_from_fps` — `(frame_index - 1) / declared_fps`. Exact for a
  constant-rate file, quietly wrong for a variable-rate one.

## Both backends ship, for exactly one step

`ingest.backend: pyav | opencv`. Replacing the source *and* changing the
timeline in one commit would be two variables in one step (§16), and the delta
would be unattributable. So the same recording gets benched on both, the
difference is committed, and then the OpenCV pair leaves.

The expected headline, written down before measuring so it could be wrong in
public: **B4 is roughly performance-neutral.** `cv2.VideoCapture` is FFmpeg
underneath, so both decoders do the same work and only the API around them
changed.

The first attempt to check it reported 96.7 fps against 91.0 and called PyAV 6%
ahead. The second run of the same tool on the same machine and the same file
reported 100.5 against 129.2 and would have called OpenCV 28% ahead. **Both
numbers were meaningless**: a single timed pass each, in a fixed order, with no
warm-up — so whichever backend ran first paid for filling the OS page cache and
handed a warm one to the other, and any background load landed on whoever was
running. The tool was printing three significant figures of noise, in exactly
the style this codebase spends its time complaining about elsewhere.

`probe_ingest` now discards a warm-up pass per backend, runs the timed passes
**interleaved** so drift hurts both equally, reports the median with the full
spread, and refuses to name a winner when the difference is inside the spread.

With that in place the answer came back: PyAV 81.9 fps median (spread 21.5%)
against OpenCV 114.0 (spread 4.0%) — OpenCV 28% ahead, outside the noise. And
the measurement was right while the conclusion was still wrong, because the
28% was **this code's bug, not PyAV's cost**:

```python
try:
    self._stream.thread_type = "AUTO"
except Exception:       # pragma: no cover - older PyAV
    pass
```

PyAV moved that property onto the codec context. On a current build the
assignment raised, the `pass` swallowed it, HEVC decoded on a single thread,
and OpenCV's FFmpeg used every core it had. `except Exception: pass` around a
performance setting is the same failure as §9 item 9 in different clothes:
nothing errored, the log stayed clean, and the number was confidently wrong.
Written, for the avoidance of doubt, by the same author who put a strict-mode
check in the tracker for exactly this.

`_configure_decoder_threads` now tries both targets, records which one took,
puts the outcome in `describe()` and the report, and logs a warning when a
decoder ends up single-threaded. `ingest.decoder_thread_type` also accepts
`NONE`, so the cost of single-threaded decode can be measured deliberately
instead of suffered accidentally.

**The comparison is therefore still open.** Re-run the probe on the fixed code
before quoting any decode figure.

## The epoch, and the bug it prevents

§6.6 says the PTS→wallclock offset must be re-established on every reconnect,
and calls it one line that, if missed, makes every camera that ever dropped
report intervals in the wrong year — and only that camera.

There is a second consequence the document does not spell out. After a
reconnect, RTP restarts from a fresh random base, so **PTS can jump or go
backwards**. Any code subtracting two PTS values must know whether they came
from the same connection, or it produces a duration that is not wrong so much
as meaningless — and, being a float, it prints perfectly well.

So every frame carries `stream_epoch`, the track log records it, and the things
downstream refuse to reason across a boundary:

- `segments_from_log` always ends a segment at an epoch change, whatever the
  PTS gap looks like;
- `metrics.stitch` never joins two segments from different epochs, even when
  the apparent gap is well inside the stitching window;
- `RealtimeSource` re-anchors its schedule instead of computing a deadline
  decades away.

`metrics.timeline.reconnects_total` puts the count in the report, so a run with
reconnects is visibly not the same kind of run as one without.

## PTS going backwards inside one epoch is counted, not fatal

It should not happen: `container.decode()` yields in presentation order. If it
does, an assumption here is wrong — and the module says so by counting and
reporting rather than raising. A 24/7 RTSP stream that dies on one malformed
timestamp is a worse failure than a run whose report says "three anomalies".
The rule this codebase holds is *never degrade silently*; counted and printed
is not silent.

## RTSP: two flags §5.5 calls practically mandatory

`rtsp_transport=tcp`, because UDP loses packets and produces corrupted frames
that will ruin an embedding without ever looking like an error. And an explicit
timeout, so a dead camera does not hang a thread for ever — set under both
`stimeout` and `timeout`, because FFmpeg renamed it and which one is honoured
depends on the build. An unrecognised option is ignored, so setting both is
free and setting neither is a hang.

Reconnect can be tested without a camera: MediaMTX serves a file as an RTSP
server (§6.7.1), so killing it mid-run exercises the whole path.

## What this step is not

**Not NVDEC — and §5.5's assumption about it is now known to be wrong.** The
document says a PyPI PyAV wheel ships an FFmpeg built without CUDA. PyAV 18.1.0
on Windows carries `hevc_cuvid`, `h264_cuvid` and the whole QSV family. B9 is
therefore cheaper than planned.

It is still not free and this step still does not take it. Asking for a cuvid
decoder moves the decode onto the GPU, but `to_ndarray` copies the frame
straight back to host memory, so the PCIe round trip §5.5 actually cares about
survives until the ONNX IO-binding refactor. Taking the cheap half now would
also be two variables in one step, with the less interesting one first.

One number to keep in view meanwhile: 96.7 fps for a single 1080p **HEVC**
stream on this machine. Five cameras at 25 fps is 125 fps of decode, so decode
alone does not fit in one stream's budget — which is what §8's "3–5 cores"
estimate already implied. An H.264 substream is considerably cheaper than HEVC
at 1080p, so the production figure will be better than this one.

**Not dual-stream.** One variable per step.

## The frame count the truncation check depends on

`streams/local.py` refuses to treat a short read as a finished run, and that
check needs to know how many frames to expect. `cv2` supplies it;
`stream.frames` is **0 for many containers and for every live stream**. Letting
that be zero would silently disable a check whose entire job is to stop a 6%
run being reported as a complete one.

So `PyAVSource.total_frames` falls back to `duration × average_rate`. That is
an estimate, and the truncation check now tolerates a shortfall of two frames
or half a percent, whichever is larger — which does not weaken a check aimed at
catching a run that covered a fraction of the file.
