"""
`python -m engine.bench.compare bench-out/k0 bench-out/k1 ...` — one row per run.

Reads only `baseline.json` files; computes nothing new. The column that matters
for calibration is `raw/2s`: raw tracks per chain stitched across gaps <= 2 s.
1.0 = no track broke and came back; higher = the tracker keeps losing the same
person (each break is a chance for ReID to mint a new ANON). It comes from the
proximity heuristic, not ground truth, so compare runs on the SAME recording
and seed only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def row(report: Dict[str, Any]) -> Dict[str, Any]:
    eff = report["config"]["effective"]
    metrics = report["metrics"]
    stages = _get(metrics, "latency", "stages") or {}
    infer = stages.get("detector_shared_infer") or stages.get("detector_infer") or {}
    lifetime = metrics.get("track_lifetime") or {}
    raw = _get(lifetime, "raw_seconds", "count")
    chains2 = _get(lifetime, "stitched_seconds", "N=2s", "count")
    per_cam = _get(metrics, "throughput", "per_camera") or []
    return {
        "label": report["run"].get("label") or "-",
        "cam": report["run"]["cameras"],
        "conf": _get(eff, "detector", "confidence_threshold"),
        "nms": _get(eff, "detector", "nms_iou_threshold"),
        "trk_thr": _get(eff, "tracker", "track_threshold"),
        "buf_s": _get(eff, "tracker", "track_buffer_seconds"),
        "graph": _get(eff, "detector", "cuda_graph"),
        "fps/cam": round(min(c["fps"] for c in per_cam), 2) if per_cam else None,
        "drop": _get(metrics, "throughput", "drop_rate", "rate"),
        "infer_p50": infer.get("p50_ms"),
        "tracks": raw,
        "life_p50": _get(lifetime, "raw_seconds", "p50"),
        "chains2s": chains2,
        "raw/2s": round(raw / chains2, 3) if raw and chains2 else None,
        "chains30s": _get(lifetime, "stitched_seconds", "N=30s", "count"),
        "batch": _get(metrics, "shared_detector", "mean_batch"),
    }


def table(rows: List[Dict[str, Any]]) -> str:
    cols = list(rows[0])
    cells = [[("-" if r[c] is None else str(r[c])) for c in cols] for r in rows]
    widths = [max(len(c), *(len(line[i]) for line in cells)) for i, c in enumerate(cols)]
    fmt = lambda values: "| " + " | ".join(v.ljust(w) for v, w in zip(values, widths)) + " |"
    lines = [fmt(cols), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    lines += [fmt(line) for line in cells]
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 1
    rows = []
    for arg in argv:
        path = Path(arg)
        path = path / "baseline.json" if path.is_dir() else path
        rows.append(row(json.loads(path.read_text(encoding="utf-8"))))
    print(table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
