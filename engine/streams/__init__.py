"""
Adapters that satisfy `ports.observation.TrackStream`.

Today there is one: `local`, which runs the pipeline in this process. At step 6
there will be a second one reading the NDJSON `events` channel, and whatever
consumes a TrackStream — the benchmark, first — will not notice the difference.

Imports are lazy for the same reason as `ingest` and `perception`: pulling the
pipeline in eagerly would drag torch into anything that merely wants the port
definitions.
"""

from __future__ import annotations

from typing import Any

_LAZY = {
    "LocalTrackStream": "local",
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
