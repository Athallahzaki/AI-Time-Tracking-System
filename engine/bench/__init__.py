"""
The benchmark harness. ARCHITECTURE.md §13, WORKPLAN.md B1.

`bench.py` is the first step after porting because too many decisions are
waiting on numbers, and two of them decide whether an entire feature — personal
break monitoring — is worth building at all.

What is here, and what each file is for:

    pacing.py      the two modes, and the wall between them (§13.2)
    spans.py       intervals, not averages (§13.3)
    tracklog.py    per-frame NDJSON, the input to every offline metric
    annotation.py  ground truth, and why it is the expensive part (§13.8)
    metrics.py     everything computed after the run (§13.5, §13.6)
    faceprobe.py   the second go/no-go metric (§3.1, §13.5)
    thresholds.py  the verdict — and why it holds no numbers (§13.7, §16)
    report.py      the frozen, additive-only report schema (§13.4)
    runner.py      orchestration
    cli.py         python -m engine.bench

Two rules this package is built around, both from §13:

**It must run on mocks, with no GPU and no weights** (§13.9), so it can live in
CI and so a bug in the bench itself is found in three seconds rather than
half an hour into a run.

**It must not be able to lie in a flattering direction** (§13.1). A metric the
run cannot justify is `null` with a reason, never `0`; a missing measurement
can never produce a GO; a source that stopped early is an error, not a
completed run; and the report names the classes that actually executed rather
than the ones the config asked for.
"""

from __future__ import annotations

from typing import Any

_LAZY = {
    "BenchOptions": "runner",
    "run_bench": "runner",
    "main": "cli",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f".{module_name}", __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
