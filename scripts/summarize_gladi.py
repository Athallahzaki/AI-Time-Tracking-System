"""Ringkas satu atau beberapa CSV lag_probe jadi satu tabel perbandingan.

Dibuat untuk uji A/B laptop 4060 (docs/DEMO-REMOTE.md, "Uji A/B 4060"), tetapi
berlaku untuk CSV gladi mana pun. Hanya pustaka standar, supaya bisa dijalankan
di laptop mana saja tanpa pandas.

    python scripts/summarize_gladi.py bench-out/ab-R0.csv bench-out/ab-R1.csv
    python scripts/summarize_gladi.py --target-fps 8 bench-out/gladi-1060.csv

Kolom yang dibaca (lag_probe): elapsed_s, source, fps, dropped, frame_age_s.
- fps dan dropped dari baris `health` (dropped = kumulatif frames_dropped_stale).
- umur kotak dari baris `view`.
Satu menit pertama dibuang (warmup dan start probe).

Vonis LULUS bila:
- waktu lambat (fps < 80% target) < 5%;
- umur kotak p99 < 1 dtk;
- tidak ada stall (umur > 2 dtk).
Ambang ini sama dengan yang dipakai saat membaca gladi 8 Okt.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

WARMUP_SECONDS = 60.0
SLOW_FRACTION = 0.8
STALL_AGE_SECONDS = 2.0


@dataclass
class Summary:
    name: str
    minutes: float
    fps_median: Optional[float]
    slow_share: Optional[float]
    phase_switches: int
    drops_per_s: Optional[float]
    age_median: Optional[float]
    age_p95: Optional[float]
    age_p99: Optional[float]
    age_max: Optional[float]
    stalls: int

    @property
    def passed(self) -> bool:
        return (
            self.slow_share is not None and self.slow_share < 0.05
            and self.age_p99 is not None and self.age_p99 < 1.0
            and self.stalls == 0
        )


def _num(value: str) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(math.floor(pos))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def summarize(path: Path, target_fps: float) -> Summary:
    health: List[tuple] = []          # (elapsed, fps, dropped)
    ages: List[tuple] = []            # (elapsed, age)
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            elapsed = _num(row.get("elapsed_s", ""))
            if elapsed is None or elapsed < WARMUP_SECONDS:
                continue
            source = row.get("source", "")
            if source == "health":
                fps = _num(row.get("fps", ""))
                if fps is not None:
                    health.append((elapsed, fps, _num(row.get("dropped", ""))))
            elif source == "view":
                age = _num(row.get("frame_age_s", ""))
                if age is not None:
                    ages.append((elapsed, age))

    fps_values = [fps for _, fps, _ in health]
    slow_limit = SLOW_FRACTION * target_fps
    slow = [fps < slow_limit for fps in fps_values]
    switches = sum(1 for a, b in zip(slow, slow[1:]) if a != b)

    rates = []
    for (t0, _, d0), (t1, _, d1) in zip(health, health[1:]):
        if d0 is not None and d1 is not None and t1 > t0 and d1 >= d0:
            rates.append((d1 - d0) / (t1 - t0))

    age_values = [age for _, age in ages]
    # Stall = umur kotak melewati ambang; hitung kejadian, bukan sampel.
    stalls, inside = 0, False
    for age in age_values:
        if age > STALL_AGE_SECONDS and not inside:
            stalls += 1
        inside = age > STALL_AGE_SECONDS

    times = [t for t, _, _ in health] + [t for t, _ in ages]
    minutes = (max(times) - min(times)) / 60.0 if times else 0.0
    return Summary(
        name=path.name,
        minutes=minutes,
        fps_median=_quantile(fps_values, 0.5),
        slow_share=(sum(slow) / len(slow)) if slow else None,
        phase_switches=switches,
        drops_per_s=_quantile(rates, 0.5),
        age_median=_quantile(age_values, 0.5),
        age_p95=_quantile(age_values, 0.95),
        age_p99=_quantile(age_values, 0.99),
        age_max=max(age_values) if age_values else None,
        stalls=stalls,
    )


def _fmt(value: Optional[float], spec: str) -> str:
    return "-" if value is None else format(value, spec)


def render(summaries: Sequence[Summary], target_fps: float) -> str:
    header = (
        f"{'file':<28} {'menit':>5} {'fps med':>7} {'lambat':>7} {'ganti':>5} "
        f"{'drop/s':>6} {'umur med':>8} {'p95':>5} {'p99':>5} {'maks':>5} {'stall':>5}  vonis"
    )
    lines = [f"target {target_fps:g} fps; lambat = fps < {SLOW_FRACTION * target_fps:g}; "
             f"menit pertama dibuang", header, "-" * len(header)]
    for s in summaries:
        lines.append(
            f"{s.name[:28]:<28} {s.minutes:>5.1f} {_fmt(s.fps_median, '.2f'):>7} "
            f"{_fmt(None if s.slow_share is None else s.slow_share * 100, '.1f') + '%':>7} "
            f"{s.phase_switches:>5} {_fmt(s.drops_per_s, '.1f'):>6} "
            f"{_fmt(s.age_median, '.2f'):>8} {_fmt(s.age_p95, '.2f'):>5} "
            f"{_fmt(s.age_p99, '.2f'):>5} {_fmt(s.age_max, '.2f'):>5} {s.stalls:>5}  "
            f"{'LULUS' if s.passed else 'GAGAL'}"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="+", type=Path, help="CSV hasil scripts/lag_probe.py")
    parser.add_argument("--target-fps", type=float, default=10.0,
                        help="core.target_fps profil yang diuji (4060: 10, 1060: 8)")
    args = parser.parse_args(argv)

    summaries = [summarize(path, args.target_fps) for path in args.csv]
    print(render(summaries, args.target_fps))
    return 0 if all(s.passed for s in summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
