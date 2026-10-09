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

CSV beberapa kamera (kolom camera_id berisi cam01..camN, hasil lag_probe dengan
beberapa --camera) dihitung per kamera lalu digabung: tabel menampilkan satu baris
per kamera dan satu baris gabungan per file. Irama fps dan laju drop selalu dihitung
dalam deret satu kamera, tidak pernah dicampur antar kamera. CSV satu kamera (atau
tanpa camera_id) tampil persis seperti dulu: satu baris per file.

Vonis LULUS bila:
- waktu lambat (fps < 80% target) < 5%;
- umur kotak p99 < 1 dtk;
- tidak ada stall (umur > 2 dtk).
Ambang ini sama dengan yang dipakai saat membaca gladi 8 Okt.
Vonis tetap satu per file: pada CSV beberapa kamera, LULUS hanya bila SEMUA kamera
LULUS (kamera tanpa sampel box juga GAGAL). Baris gabungan: fps, lambat, umur box
dihitung dari semua sampel; ganti dan stall dijumlahkan; drop/s = jumlah median per kamera.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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
    # Terisi hanya untuk CSV beberapa kamera; kosong = satu kamera (perilaku lama).
    cameras: List["Summary"] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        if self.cameras:
            return all(c.passed for c in self.cameras)
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


def _count_stalls(age_values: Sequence[float]) -> int:
    # Stall = umur kotak melewati ambang; hitung kejadian, bukan sampel.
    stalls, inside = 0, False
    for age in age_values:
        if age > STALL_AGE_SECONDS and not inside:
            stalls += 1
        inside = age > STALL_AGE_SECONDS
    return stalls


def _switches_and_rates(health: Sequence[tuple], slow_limit: float) -> Tuple[int, List[float], List[bool]]:
    """Ganti fase dan laju drop dari SATU deret kamera (urut waktu)."""
    slow = [fps < slow_limit for _, fps, _ in health]
    switches = sum(1 for a, b in zip(slow, slow[1:]) if a != b)
    rates = []
    for (t0, _, d0), (t1, _, d1) in zip(health, health[1:]):
        if d0 is not None and d1 is not None and t1 > t0 and d1 >= d0:
            rates.append((d1 - d0) / (t1 - t0))
    return switches, rates, slow


def _span_minutes(health: Sequence[tuple], ages: Sequence[tuple]) -> float:
    times = [t for t, _, _ in health] + [t for t, _ in ages]
    return (max(times) - min(times)) / 60.0 if times else 0.0


def summarize(path: Path, target_fps: float) -> Summary:
    # Per kamera: camera_id -> deret (urut kemunculan = urut waktu).
    health: Dict[str, List[tuple]] = {}    # (elapsed, fps, dropped)
    ages: Dict[str, List[tuple]] = {}      # (elapsed, age)
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            elapsed = _num(row.get("elapsed_s", ""))
            if elapsed is None or elapsed < WARMUP_SECONDS:
                continue
            source = row.get("source", "")
            camera = (row.get("camera_id") or "").strip()
            if source == "health":
                fps = _num(row.get("fps", ""))
                if fps is not None:
                    health.setdefault(camera, []).append((elapsed, fps, _num(row.get("dropped", ""))))
            elif source == "view":
                age = _num(row.get("frame_age_s", ""))
                if age is not None:
                    ages.setdefault(camera, []).append((elapsed, age))

    slow_limit = SLOW_FRACTION * target_fps
    names = sorted(set(health) | set(ages))
    # Satu kamera (atau tanpa camera_id): jalur lama, satu baris per file.
    if len(names) <= 1:
        only = names[0] if names else ""
        return _build(path.name, health.get(only, []), ages.get(only, []), slow_limit)

    per_camera = [_build(name or "(tanpa id)", health.get(name, []), ages.get(name, []), slow_limit)
                  for name in names]
    all_health = [h for name in names for h in health.get(name, [])]
    all_ages = [a for name in names for a in ages.get(name, [])]
    combined = _build(path.name, all_health, all_ages, slow_limit, per_camera=per_camera)
    return combined


def _build(name: str, health: Sequence[tuple], ages: Sequence[tuple], slow_limit: float,
           per_camera: Optional[List[Summary]] = None) -> Summary:
    fps_values = [fps for _, fps, _ in health]
    age_values = [age for _, age in ages]
    if per_camera:
        # Gabungan: irama/laju/stall tidak boleh dihitung dari deret campuran.
        slow = [fps < slow_limit for fps in fps_values]
        switches = sum(c.phase_switches for c in per_camera)
        rate_parts = [c.drops_per_s for c in per_camera if c.drops_per_s is not None]
        drops = sum(rate_parts) if rate_parts else None
        stalls = sum(c.stalls for c in per_camera)
    else:
        switches, rates, slow = _switches_and_rates(health, slow_limit)
        drops = _quantile(rates, 0.5)
        stalls = _count_stalls(age_values)
    return Summary(
        name=name,
        minutes=_span_minutes(health, ages),
        fps_median=_quantile(fps_values, 0.5),
        slow_share=(sum(slow) / len(slow)) if slow else None,
        phase_switches=switches,
        drops_per_s=drops,
        age_median=_quantile(age_values, 0.5),
        age_p95=_quantile(age_values, 0.95),
        age_p99=_quantile(age_values, 0.99),
        age_max=max(age_values) if age_values else None,
        stalls=stalls,
        cameras=list(per_camera or []),
    )


def _fmt(value: Optional[float], spec: str) -> str:
    return "-" if value is None else format(value, spec)


def _row(label: str, s: Summary, passed: bool) -> str:
    return (
        f"{label[:28]:<28} {s.minutes:>5.1f} {_fmt(s.fps_median, '.2f'):>7} "
        f"{_fmt(None if s.slow_share is None else s.slow_share * 100, '.1f') + '%':>7} "
        f"{s.phase_switches:>5} {_fmt(s.drops_per_s, '.1f'):>6} "
        f"{_fmt(s.age_median, '.2f'):>8} {_fmt(s.age_p95, '.2f'):>5} "
        f"{_fmt(s.age_p99, '.2f'):>5} {_fmt(s.age_max, '.2f'):>5} {s.stalls:>5}  "
        f"{'LULUS' if passed else 'GAGAL'}"
    )


def render(summaries: Sequence[Summary], target_fps: float) -> str:
    header = (
        f"{'file':<28} {'menit':>5} {'fps med':>7} {'lambat':>7} {'ganti':>5} "
        f"{'drop/s':>6} {'umur med':>8} {'p95':>5} {'p99':>5} {'maks':>5} {'stall':>5}  vonis"
    )
    lines = [f"target {target_fps:g} fps; lambat = fps < {SLOW_FRACTION * target_fps:g}; "
             f"menit pertama dibuang", header, "-" * len(header)]
    for s in summaries:
        if s.cameras:
            for cam in s.cameras:
                lines.append(_row(f"  {cam.name}", cam, cam.passed))
            lines.append(_row(f"{s.name[:20]} [{len(s.cameras)} kam]", s, s.passed))
        else:
            lines.append(_row(s.name, s, s.passed))
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
