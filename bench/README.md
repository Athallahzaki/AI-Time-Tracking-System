# `bench/` — what is committed, and what must never be

Company-level artefacts for the benchmark. The harness itself is
`engine/bench/`; this directory holds the things that are deliberately **not**
inside `engine/`.

| Path | What | Committed? |
|---|---|---|
| `gonogo.yaml` | Pre-registered go/no-go thresholds (§13.7) | **yes** |
| `annotations/*.yaml` | Ground-truth presence timelines (§13.8) | **yes** |
| `baselines/*.json` | `baseline.json` from each measured step (§16) | **yes** |
| the recordings | phone/CCTV video of colleagues | **never** |

`gonogo.yaml` is here rather than under `engine/` because the numbers in it are
company policy — a thirty-minute allowance, an eight-hour day, a judgement about
acceptable noise — and §16 forbids the engine from holding any of that. A
benchmark is not a loophole in that rule.

The recordings are biometric data about colleagues. §7.4 already puts this
system under UU 27/2022, and committing one means retention forever in every
clone. Keep them outside the repository, record the `sha256` in the annotation,
and get written consent before recording.
