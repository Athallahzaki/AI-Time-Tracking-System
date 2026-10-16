"""scripts/summarize_gladi.py: vonis A/B 4060 harus sama dengan bacaan manual 8 Okt."""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("summarize_gladi", Path("scripts/summarize_gladi.py"))
sg = importlib.util.module_from_spec(_spec)
sys.modules["summarize_gladi"] = sg
_spec.loader.exec_module(sg)

FIELDS = ["wall_t", "elapsed_s", "camera_id", "source", "frame_age_s", "lag_s",
          "fps", "dropped", "drift_s", "note"]


def _write(path: Path, fps_at, age_at, drop_rate_at, seconds: int = 600) -> Path:
    rows = []
    dropped = 0.0
    for t in range(0, seconds, 2):
        dropped += 2 * drop_rate_at(t)
        rows.append({"elapsed_s": t, "source": "health", "fps": fps_at(t), "dropped": dropped})
        rows.append({"elapsed_s": t + 1, "source": "view", "frame_age_s": age_at(t)})
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_run_bersih_lulus(tmp_path):
    path = _write(tmp_path / "bersih.csv", lambda t: 10.0, lambda t: 0.04, lambda t: 0.0)
    s = sg.summarize(path, target_fps=10.0)
    assert s.passed
    assert s.slow_share == 0.0 and s.phase_switches == 0 and s.stalls == 0
    assert abs(s.drops_per_s) < 1e-9


def test_fase_6_fps_dan_stall_gagal(tmp_path):
    # 10 fps di menit 1-4, lalu 6 fps dengan umur kotak naik sampai 8 dtk.
    slow = lambda t: t >= 240
    path = _write(
        tmp_path / "fase.csv",
        lambda t: 6.0 if slow(t) else 10.0,
        lambda t: min(8.0, 0.5 + (t - 240) * 0.05) if slow(t) else 0.1,
        lambda t: 24.0 if slow(t) else 10.0,
    )
    s = sg.summarize(path, target_fps=10.0)
    assert not s.passed
    assert s.phase_switches == 1
    assert 0.55 < s.slow_share < 0.7
    assert s.stalls == 1
    assert s.age_max == 8.0


def test_menit_pertama_dibuang(tmp_path):
    # Warmup lambat tidak boleh menggagalkan run yang sesudahnya bersih.
    path = _write(tmp_path / "warmup.csv", lambda t: 3.0 if t < 60 else 10.0,
                  lambda t: 5.0 if t < 60 else 0.05, lambda t: 0.0)
    assert sg.summarize(path, target_fps=10.0).passed


def test_main_mengembalikan_1_bila_ada_yang_gagal(tmp_path, capsys):
    ok = _write(tmp_path / "ok.csv", lambda t: 10.0, lambda t: 0.04, lambda t: 0.0)
    bad = _write(tmp_path / "bad.csv", lambda t: 6.0, lambda t: 0.5, lambda t: 24.0)
    assert sg.main([str(ok)]) == 0
    assert sg.main([str(ok), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "LULUS" in out and "GAGAL" in out
