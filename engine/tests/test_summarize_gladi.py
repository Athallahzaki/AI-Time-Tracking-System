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


def _write_multi(path: Path, cams: dict, seconds: int = 600) -> Path:
    """CSV beberapa kamera ala lag_probe: baris health dan view bergantian per kamera.

    cams: camera_id -> (fps_at, age_at, drop_rate_at).
    """
    rows = []
    dropped = {cam: 0.0 for cam in cams}
    for t in range(0, seconds, 2):
        for cam, (fps_at, age_at, drop_rate_at) in cams.items():
            dropped[cam] += 2 * drop_rate_at(t)
            rows.append({"elapsed_s": t, "camera_id": cam, "source": "health",
                         "fps": fps_at(t), "dropped": dropped[cam]})
            rows.append({"elapsed_s": t + 1, "camera_id": cam, "source": "view",
                         "frame_age_s": age_at(t)})
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


_BERSIH = (lambda t: 10.0, lambda t: 0.04, lambda t: 5.0)
_MACET = (lambda t: 10.0, lambda t: 3.0 if t >= 300 else 0.04, lambda t: 5.0)


def test_satu_kamera_dengan_camera_id_sama_dengan_tanpa_id(tmp_path):
    # Perilaku 1 kamera tidak berubah: tidak ada baris per kamera, angka identik.
    lama = sg.summarize(_write(tmp_path / "a.csv", *_BERSIH), target_fps=10.0)
    baru = sg.summarize(_write_multi(tmp_path / "b.csv", {"cam01": _BERSIH}), target_fps=10.0)
    assert baru.cameras == [] and lama.cameras == []
    for nama in ("fps_median", "slow_share", "phase_switches", "age_p99", "stalls"):
        assert getattr(baru, nama) == getattr(lama, nama)
    assert abs(baru.drops_per_s - 5.0) < 1e-9
    assert len(sg.render([baru], 10.0).splitlines()) == 4   # judul, header, garis, 1 baris


def test_lima_kamera_bersih_lulus_dengan_baris_per_kamera(tmp_path):
    cams = {f"cam0{i}": _BERSIH for i in range(1, 6)}
    s = sg.summarize(_write_multi(tmp_path / "lima.csv", cams), target_fps=10.0)
    assert s.passed
    assert [c.name for c in s.cameras] == [f"cam0{i}" for i in range(1, 6)]
    assert s.stalls == 0 and s.phase_switches == 0
    # Laju drop gabungan = jumlah per kamera (5 x 5/dtk), bukan selisih deret campuran.
    assert abs(s.drops_per_s - 25.0) < 1e-9
    assert all(abs(c.drops_per_s - 5.0) < 1e-9 for c in s.cameras)
    # 5 baris kamera + 1 gabungan + 3 baris judul.
    assert len(sg.render([s], 10.0).splitlines()) == 9


def test_satu_kamera_macet_menggagalkan_file(tmp_path):
    cams = {f"cam0{i}": _BERSIH for i in range(1, 5)}
    cams["cam05"] = _MACET
    s = sg.summarize(_write_multi(tmp_path / "macet.csv", cams), target_fps=10.0)
    assert not s.passed
    by_name = {c.name: c for c in s.cameras}
    assert by_name["cam05"].stalls == 1 and not by_name["cam05"].passed
    assert all(by_name[f"cam0{i}"].passed for i in range(1, 5))
    assert s.stalls == 1
    out = sg.render([s], 10.0)
    assert out.count("GAGAL") == 2 and out.count("LULUS") == 4   # cam05 + gabungan


def test_irama_dihitung_per_kamera_bukan_deret_campuran(tmp_path):
    # Satu kamera 10 fps, satu 6 fps (lambat) sepanjang run. Bila deret dicampur,
    # "ganti fase" meledak (bolak-balik tiap sampel); per kamera harus 0.
    cams = {"cam01": _BERSIH, "cam02": (lambda t: 6.0, lambda t: 0.04, lambda t: 5.0)}
    s = sg.summarize(_write_multi(tmp_path / "campur.csv", cams), target_fps=10.0)
    assert s.phase_switches == 0
    by_name = {c.name: c for c in s.cameras}
    assert by_name["cam01"].slow_share == 0.0 and by_name["cam02"].slow_share == 1.0
    assert abs(s.slow_share - 0.5) < 1e-9
    assert not s.passed


def test_kamera_tanpa_sampel_box_gagal(tmp_path):
    path = _write_multi(tmp_path / "buta.csv", {"cam01": _BERSIH, "cam02": _BERSIH})
    with open(path, newline="", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle)
                if not (r["camera_id"] == "cam02" and r["source"] == "view")]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    s = sg.summarize(path, target_fps=10.0)
    assert not s.passed
    assert {c.name: c.passed for c in s.cameras} == {"cam01": True, "cam02": False}


def test_main_vonis_per_file_pada_csv_multi_kamera(tmp_path, capsys):
    ok = _write_multi(tmp_path / "ok5.csv", {f"cam0{i}": _BERSIH for i in range(1, 6)})
    bad = _write_multi(tmp_path / "bad5.csv", {"cam01": _BERSIH, "cam02": _MACET})
    assert sg.main([str(ok)]) == 0
    assert sg.main([str(ok), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "ok5.csv [5 kam]" in out and "bad5.csv [2 kam]" in out
