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


def _satu_gambar_per_kamera(src, n_id, kamera_per_id):
    """Struktur subset RandPerson asli: <= 1 gambar per (orang, kamera)."""
    import cv2
    import numpy as np
    src.mkdir(parents=True, exist_ok=True)
    for pid in range(n_id):
        for cam in range(kamera_per_id(pid)):
            cv2.imwrite(str(src / f"{pid}_s1_c{cam}_f0.jpg"), np.full((20, 10, 3), pid * 10, np.uint8))


def test_satu_gambar_per_kamera_tetap_menghasilkan_query(tmp_path):
    """Regresi ea-r13: subset RandPerson asli menghasilkan 'query 0' dan latihan crash
    di akhir epoch 1. Setiap id val yang terlihat di >= 2 kamera wajib punya satu query,
    dan pasangannya ada di kamera lain di gallery."""
    src, out = tmp_path / "src", tmp_path / "out"
    _satu_gambar_per_kamera(src, n_id=20, kamera_per_id=lambda pid: 4)
    assert pr.main(["--src", str(src), "--out", str(out), "--workers", "1",
                    "--val-fraction", "0.25"]) == 0
    baris = _baca(out / "manifest.csv")
    q = [r for r in baris if r["split"] == "query"]
    g = [r for r in baris if r["split"] == "gallery"]
    val_ids = {r["pid"] for r in q} | {r["pid"] for r in g}
    assert len(val_ids) == 5
    assert len(q) == 5 and {r["pid"] for r in q} == val_ids, "tepat satu query per id val"
    for r in q:
        lain = [x for x in g if x["pid"] == r["pid"] and x["camid"] != r["camid"]]
        assert len(lain) == 3, "pasangan query ada di kamera lain"


def test_id_satu_kamera_tidak_diberi_query(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    _satu_gambar_per_kamera(src, n_id=8, kamera_per_id=lambda pid: 1 if pid % 2 else 3)
    assert pr.main(["--src", str(src), "--out", str(out), "--workers", "1",
                    "--val-fraction", "0.5"]) == 0
    baris = _baca(out / "manifest.csv")
    for r in baris:
        if r["split"] == "query":
            assert int(r["pid"]) % 2 == 0, "id yang hanya di satu kamera tidak punya pasangan"


def test_tanpa_query_sama_sekali_ditolak(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    _satu_gambar_per_kamera(src, n_id=6, kamera_per_id=lambda pid: 1)
    assert pr.main(["--src", str(src), "--out", str(out), "--workers", "1"]) == 3
