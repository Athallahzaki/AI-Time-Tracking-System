"""Tes prepare_randperson.py (tanpa torch)."""
import csv
import json

import pytest

pytest.importorskip("cv2")

import prepare_randperson as pr  # noqa: E402
from bantu import buat_randperson_palsu  # noqa: E402


def _baca(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_prepare_split_per_identitas_dan_query_per_kamera(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    assert buat_randperson_palsu(src) == 40
    (src / "bukan_format.jpg").write_bytes(b"x")  # nama tak cocok → dilewati

    assert pr.main(["--src", str(src), "--out", str(out), "--workers", "1",
                    "--val-fraction", "0.25"]) == 0

    baris = _baca(out / "manifest.csv")
    assert len(baris) == 40
    per_split = {s: {int(r["pid"]) for r in baris if r["split"] == s} for s in ("train", "query", "gallery")}
    assert len(per_split["train"]) == 3 and len(per_split["query"]) == 1
    assert per_split["train"].isdisjoint(per_split["query"])  # split per IDENTITAS
    assert per_split["query"] == per_split["gallery"]
    # satu query per (pid, kamera): 1 id val x 2 kamera
    q = [r for r in baris if r["split"] == "query"]
    assert len(q) == 2 and len({r["camid"] for r in q}) == 2
    # semua gambar keluaran 256x128
    import cv2
    img = cv2.imread(str(out / baris[0]["path"]))
    assert img.shape[:2] == (256, 128)
    ringkas = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert ringkas["nama_tak_cocok"] == 1 and ringkas["kamera_total"] == 2


def test_camid_unik_per_scene_dan_kamera(tmp_path):
    import cv2
    import numpy as np
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    for pid in (0, 1):
        for scene, cam in ((1, 0), (1, 1), (2, 0)):  # (2,0) ≠ (1,0) walau nomor kamera sama
            for f in range(2):
                cv2.imwrite(str(src / f"{pid}_s{scene}_c{cam}_f{f}.jpg"), np.zeros((20, 10, 3), np.uint8))
    assert pr.main(["--src", str(src), "--out", str(out), "--workers", "1"]) == 0
    assert len({r["camid"] for r in _baca(out / "manifest.csv")}) == 3
