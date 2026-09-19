# `engine/bench` — B1: the gate, not a checklist

`ARCHITECTURE.md` §13, `WORKPLAN.md` B1. This is the first step after the port,
because too many decisions are waiting on numbers and two of them decide
whether the personal-break-monitoring feature is worth building at all.

```bash
# what CI runs: no GPU, no weights, no recording
python -m engine.bench --mock --frames 200 --out bench-out/smoke

# the baseline
python -m engine.bench \
    --source recordings/room_morning.mp4 \
    --mode throughput \
    --annotation bench/annotations/room_morning.yaml \
    --thresholds bench/gonogo.yaml \
    --face-probe --detector-probe-iters 50 \
    --out bench-out/baseline

# what production actually does
python -m engine.bench --source recordings/room_morning.mp4 \
    --mode realtime --cameras 5 --out bench-out/realtime-5cam
```

Every run writes `baseline.json`, plus `tracks_<cam>.ndjson` and
`spans_<cam>.ndjson`. **Commit `baseline.json`.** The other two are large and
rebuildable; the recording is neither commitable nor rebuildable (see below).

## The one property that matters

A slow system is visible. A benchmark that is wrong in a flattering direction
is not — and it is worse than no benchmark, because decisions get made on it.
Everything here is built around four mechanisms:

1. **A metric the run cannot justify is `null` with a reason, never `0`.** No
   annotation does not mean no false gaps; throughput mode does not mean a zero
   drop rate; a realtime run does not have a track lifetime.
2. **A missing measurement can never produce a GO.** It produces
   `INCONCLUSIVE`, which is not a soft `NO_GO` — it means go and measure.
3. **The report names the classes that actually ran**, not the ones the config
   asked for. A tracker that silently fell back and a report naming the
   requested one is precisely the failure `strict_mode` exists to stop.
4. **A source that stopped early is an error.** `cv2.VideoCapture.read()`
   returns `None` at end-of-stream *and* on a decode failure. A benchmark over
   6% of a file, reported as a full run, is the same lie wearing a percentage.

## The two modes, and why they never mix (§13.2)

| | throughput | realtime |
|---|---|---|
| Pacing | as fast as the machine allows | to the source timeline |
| Drops | never | when behind |
| Valid here | track lifetime, fragmentation, latency, decode cost | drop rate, queue depth |

In realtime mode `source.read()` sleeps until the frame's deadline, so
`source_ingest` and `total_pipeline` would report roughly one frame interval
whatever the hardware does. Both are withheld there and the sleep is published
separately as `pacing_wait`. Decode cost comes from a throughput run.

`--cameras N` plays the same file N times at random (seeded) offsets. Honest
for decode and detection cost. Dishonest for identity, because N copies of the
same person destroy the per-frame dedup of §5.3 and the cross-camera fusion of
§5.4 — so identity and track-quality metrics are reported for N=1 only, and the
restriction is printed with the numbers rather than filed in a document.

## Two track-lifetime numbers, not one (§13.6)

§4.7 asks how long a track survives before breaking, and uses the answer to
judge a feature that §4.3 stitching and the §5.3 `HELD` state are specifically
designed to rescue. Measuring the raw number and concluding "not viable" would
condemn the design on a basis it never assumed.

So the bench reports the raw track lifetime **and** the effective presence after
**offline** stitching at N ∈ {2, 5, 15, 30} s, computed post-hoc from the track
log. Zero lines of engine code, and it answers the open question "how many
seconds of gap still count as the same presence?" in §15 with data instead of a
preference.

Stitching has two bases and the report always says which:

- `annotated_identity` — the annotation maps tracks to people. This is what
  §4.3 will actually do, so the number estimates it fairly.
- `proximity_heuristic` — no map, so a segment continues a chain if it starts
  near where the last one ended. It joins two people who cross paths and misses
  someone who reappears across the room. It is a first look. **The verdict
  refuses to use it.**

## Fragmentation is not an ID switch

The cheap annotation §13.8 costs — "track 7 and track 12 are the same person" —
measures **fragmentation**: one person split across several tracks. That is the
failure that manufactures false breaks (§4.1).

An **ID switch** is the opposite: one track carrying two different people, which
is how one employee's minutes land on another's record. Seeing it needs
per-segment labelling (`track_segments`), which is much more work. The workplan
says "ID switch" in several places while costing only the cheap annotation;
those are not the same measurement. Both are named, and whichever was not
labelled comes back `null`.

## The thresholds are not in this directory

§13.7 requires the pass marks to be fixed before anyone sees the data. They are
also company numbers, and §16 forbids the engine from holding any of those — a
constant in `engine/bench/` would be a leak arriving through the back door of a
benchmark, and `policy_grep.py` would be right to go red. So would a docstring
that merely restates the figure: prose in `engine/` is still the figure in
`engine/`, and it becomes a confident second opinion the day the rule changes.

So they live in **`bench/gonogo.yaml`, outside `engine/`**, and
`thresholds.py` only loads and applies them. Its hash goes into the report.
Without `--thresholds` the bench reports every measurement and declines to
pronounce, because a verdict with no pre-registered pass mark is an opinion with
a JSON schema.

## The expensive part is the annotation

```bash
# 1. run the bench, get a track log
python -m engine.bench --source room_morning.mp4 --out bench-out/baseline

# 2. burn track ids into the video so a human can read them
python -m engine.tools.overlay video --video room_morning.mp4 \
    --track-log bench-out/baseline/tracks_cam0.ndjson \
    --out bench-out/baseline/overlay.mp4

# 3. generate a skeleton, pre-filled with the track ids the run produced
python -m engine.tools.overlay template \
    --track-log bench-out/baseline/tracks_cam0.ndjson \
    --video room_morning.mp4 --out bench/annotations/room_morning.yaml

# 4. write the presence timeline by hand. ~1 hour for 30 min × 5 people.
# 5. re-run with --annotation. The engine does not run again; only metrics.py.
```

Record **two sessions, morning and afternoon** (§13.8). One recording is n=1 and
the whole system ends up tuned to one lighting condition.

**The annotation is committed. The video is not.** It is biometric data about
colleagues, §7.4 already invokes UU 27/2022, and git means retention forever.
Keep it outside the repository, record its `sha256` in the annotation, and get
written consent before recording.

**Phone footage is optimistic.** Wider lens, adaptive exposure, bitrate far
above a CCTV substream, no rolling-shutter artefacts. Every number from it is an
**upper bound**, and the report says so in its own caveat list — because in two
months somebody will quote it as a production figure.

## Where the report is honest about itself

- **`latency.sampling`** — the span ring buffer is bounded. Counts and means are
  exact over every span; percentiles come from what is still in the ring. One
  eviction flips this to `tail_only`, because a percentile over an unannounced
  suffix of a run looks fine for months.
- **`environment.gpu.advisory_only: true`** — `nvidia-smi` utilisation is the
  fraction of time some kernel was resident, not headroom (§13.3). Recorded
  because it helps when debugging, flagged because it predicts nothing. The
  number you can divide by 150 (§8) is `detector_throughput_probe`.
- **`streams[].pts_source: derived_from_fps`** — `cv2.VideoCapture` discards the
  real PTS (§5.5). For a file off disk, index ÷ fps is the same thing. For a
  live RTSP camera it is not. Step B4 fixes it.
- **`engine.git.dirty_warning`** — a dirty tree means the SHA does not describe
  the code that ran.

## What is still `null`, and what it waits for

| Field | Waits for |
|---|---|
| `end_to_end_accuracy` | enrollment + identity layer (§10, A8) |
| `throughput.queue_depth` | the recognition worker pool (step 18) |
| `recognizable_faces` (real figure) | a ported face detector — see below |

**The face metric is a known hole.** §13.5 makes "how often a recognizable face
appears, per person per hour" a go/no-go metric, and B0 did not port a face
detector: SCRFD lives in the old `plugins/face_recognizer/` and belongs to the
identity layer. `faceprobe.py` ships the harness — an offline second pass that
crops head regions from the track log and asks a probe — plus a probe built on
the frontal-face cascade bundled with OpenCV. That cascade is a **lower bound**,
labelled as one everywhere it appears, and it is deliberately not tuned. It
answers "does a usable face ever appear, and roughly how rarely". It is not the
production figure. Re-run the pass with SCRFD when `identity/` lands; the field
keeps its meaning.

## Schema stability

The report schema is **frozen and additive-only** (§13.4), same rule and same
reason as the protocol (§6.8): a field may be added, the meaning of an existing
field never changes. `tests/test_b1_bench.py` asserts the frozen key set, so a
rename fails CI rather than quietly invalidating every committed baseline.
