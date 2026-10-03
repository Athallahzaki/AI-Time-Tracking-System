"""scripts/preflight_demo.py: yang biasanya baru ketahuan di depan klien."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location("preflight_demo", Path("scripts/preflight_demo.py"))
pf = importlib.util.module_from_spec(_spec)
sys.modules["preflight_demo"] = pf
_spec.loader.exec_module(pf)


def _config(tmp_path, enabled=True, cuda_graph=True):
    recognition = SimpleNamespace(enabled=enabled, recognizer="onnx_face",
                                  face_detector_model="models/scrfd.onnx",
                                  face_embedder_model="models/glint.onnx",
                                  reference_db_path="engine/data/references.sqlite3")
    return SimpleNamespace(recognition=recognition, detector=SimpleNamespace(cuda_graph=cuda_graph))


def test_profil_demo_termuat():
    check, config = pf.check_config("engine/config/demo-1060.yaml")
    assert check.status == "OK" and config is not None
    assert "LibreDFINEs.pt" in check.detail


def test_config_rusak_gagal(tmp_path):
    broken = tmp_path / "x.yaml"
    broken.write_text("detector:\n<<<<<<< Updated upstream\n  half: true\n", encoding="utf-8")
    check, config = pf.check_config(str(broken))
    assert check.status == "GAGAL" and config is None


def test_model_wajah_hilang_kecil_dan_ada(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "engine" / "data").mkdir(parents=True)
    checks = {c.name: c.status for c in pf.check_face_models(_config(tmp_path), tmp_path)}
    assert checks["model-scrfd"] == "GAGAL" and checks["model-embedder"] == "GAGAL"
    assert checks["roster"] == "PERINGATAN"

    (tmp_path / "models" / "scrfd.onnx").write_bytes(b"version https://git-lfs")     # pointer LFS
    (tmp_path / "models" / "glint.onnx").write_bytes(b"\0" * 2_000_000)
    (tmp_path / "engine" / "data" / "references.sqlite3").write_bytes(b"x")
    checks = {c.name: c for c in pf.check_face_models(_config(tmp_path), tmp_path)}
    assert checks["model-scrfd"].status == "GAGAL" and "LFS" in checks["model-scrfd"].detail
    assert checks["model-embedder"].status == "OK" and checks["roster"].status == "OK"


def test_rekognisi_mati_diperingatkan(tmp_path):
    checks = pf.check_face_models(_config(tmp_path, enabled=False), tmp_path)
    assert [c.status for c in checks] == ["PERINGATAN"]


def test_libreyolo_untuk_cuda_graph(tmp_path):
    config = _config(tmp_path)
    assert pf.check_libreyolo_for_graph(config, "1.6.0").status == "OK"
    assert pf.check_libreyolo_for_graph(config, "1.5.0").status == "PERINGATAN"
    assert pf.check_libreyolo_for_graph(config, None).status == "GAGAL"
    assert pf.check_libreyolo_for_graph(_config(tmp_path, cuda_graph=False), "1.5.0").status == "OK"


def test_mediamtx():
    def down(url):
        raise OSError("connection refused")

    assert pf.check_mediamtx(down).status == "GAGAL"
    assert pf.check_mediamtx(lambda url: {"items": []}).status == "GAGAL"
    assert pf.check_mediamtx(lambda url: {"items": [{"name": "cam01", "ready": False}]}).status == "GAGAL"
    assert pf.check_mediamtx(lambda url: {"items": [{"name": "cam01", "ready": True}]}).status == "OK"


def test_port_dan_git():
    assert pf.check_ports(lambda port: False)[0].status == "OK"
    busy = pf.check_ports(lambda port: port == 8765)[0]
    assert busy.status == "PERINGATAN" and "8765" in busy.detail
    assert pf.check_git("", "demo-1060").status == "OK"
    assert pf.check_git(" M engine/config/demo-1060.yaml\n", "abc-dirty").status == "PERINGATAN"
    assert pf.check_git("UU engine/config/dfine-m.yaml\n", "abc").status == "GAGAL"
    assert pf.check_git(None, None).status == "PERINGATAN"


def test_penanda_konflik(tmp_path):
    config_dir = tmp_path / "engine" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "ok.yaml").write_text("a: 1\n", encoding="utf-8")
    assert pf.check_conflict_markers(tmp_path).status == "OK"
    (config_dir / "dfine-m.yaml").write_text("a: 1\n<<<<<<< Updated upstream\n", encoding="utf-8")
    check = pf.check_conflict_markers(tmp_path)
    assert check.status == "GAGAL" and "dfine-m.yaml" in check.detail
