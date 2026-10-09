"""Tes mini ujung-ke-ujung di CPU: prepare → latih 1 epoch → export ONNX → eval_reid.

Dilewati otomatis bila torch/torchreid/onnx/onnxruntime belum terpasang.
Jalankan:  python -m pytest tools/reid_train/tests -q
"""
import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")
pytest.importorskip("torchreid")
pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
pytest.importorskip("cv2")

import numpy as np  # noqa: E402

import eval_reid  # noqa: E402
import export_onnx  # noqa: E402
import prepare_randperson  # noqa: E402
import train_osnet  # noqa: E402
from bantu import buat_crop_berlabel_palsu, buat_randperson_palsu  # noqa: E402


def test_ujung_ke_ujung_cpu(tmp_path, capsys):
    src, data, runs = tmp_path / "rp", tmp_path / "rp256", tmp_path / "runs"
    assert buat_randperson_palsu(src, n_id=4, n_kamera=2, per_kamera=5) == 40

    assert prepare_randperson.main(["--src", str(src), "--out", str(data), "--workers", "1",
                                    "--val-fraction", "0.25"]) == 0

    assert train_osnet.main(["--data", str(data), "--out", str(runs), "--name", "mini",
                             "--init", "scratch", "--arch", "osnet_ain_x0_25", "--epochs", "1",
                             "--batch", "8", "--workers", "0", "--device", "cpu"]) == 0
    run = runs / "mini"
    assert (run / "best.pth").is_file() and (run / "last.pth").is_file()
    baris = (run / "log.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(baris) == 2 and baris[0].startswith("epoch,")
    assert json.loads((run / "config.json").read_text(encoding="utf-8"))["init"] == "scratch"

    onnx_path = tmp_path / "mini.onnx"
    assert export_onnx.main(["--checkpoint", str(run / "best.pth"), "--out", str(onnx_path),
                             "--verify-dir", str(data / "images")]) == 0
    assert onnx_path.stat().st_size > 0

    crop = tmp_path / "crop_tim"
    buat_crop_berlabel_palsu(crop)
    capsys.readouterr()
    csv_out = tmp_path / "kurva.csv"
    assert eval_reid.main(["--data", str(crop), "--onnx", str(onnx_path), "--cpu",
                           "--csv-out", str(csv_out)]) == 0
    keluar = capsys.readouterr().out
    assert "mAP" in keluar and "Rekomendasi" in keluar and csv_out.is_file()


def test_eval_membandingkan_dua_onnx_dan_angka_valid(tmp_path):
    """Dua model berbeda → ringkasan perbandingan; mAP/rank-1 berupa angka di [0, 1]."""
    ck = {}
    for nama, seed in (("a", 1), ("b", 2)):
        torch.manual_seed(seed)
        m = train_osnet.torchreid.models.build_model("osnet_ain_x0_25", num_classes=3, loss="softmax",
                                                     pretrained=False)
        p = tmp_path / f"{nama}.pth"
        torch.save({"state_dict": m.state_dict(), "arch": "osnet_ain_x0_25"}, p)
        o = tmp_path / f"{nama}.onnx"
        assert export_onnx.main(["--checkpoint", str(p), "--out", str(o)]) == 0
        ck[nama] = o
    crop = tmp_path / "crop"
    buat_crop_berlabel_palsu(crop)
    imgs, orang, kamera, _ = eval_reid.muat_folder(crop)
    emb = eval_reid.embed_onnx(str(ck["a"]), imgs, 8, True)
    assert emb.shape[0] == len(imgs) and np.allclose(np.linalg.norm(emb, axis=1), 1.0, atol=1e-4)
    m = eval_reid.metrik_peringkat(emb @ emb.T, orang, kamera)
    assert 0.0 <= m["mAP"] <= 1.0 and 0.0 <= m["rank1"] <= 1.0
    assert eval_reid.main(["--data", str(crop), "--onnx", str(ck["a"]), str(ck["b"]), "--cpu"]) == 0


def test_kurva_ambang_dan_rekomendasi_pada_data_sintetis():
    """Dua orang, dua kamera, embedding buatan: hasil bisa dihitung tangan."""
    orang = np.array(["A", "A", "B", "B"])
    kamera = np.array(["c1", "c2", "c1", "c2"])
    e = np.array([[1, 0], [0.9, 0.436], [0, 1], [0.436, 0.9]], dtype=np.float32)
    e /= np.linalg.norm(e, axis=1, keepdims=True)
    amb = np.array([0.0, 0.5, 0.95])
    k = eval_reid.kurva_ambang(e @ e.T, orang, kamera, amb)
    # pos: (A1,A2) sim 0.9 ; (B1,B2) sim 0.9 → lolos di 0.0 dan 0.5, tidak di 0.95
    assert list(k["tpr"]) == [100.0, 100.0, 0.0]
    # neg lintas kamera: (A1,B2) 0.436 ; (A2,B1) 0.436 → lolos hanya di ambang 0.0
    assert list(k["fpr_lintas"]) == [100.0, 0.0, 0.0]
    assert eval_reid.rekomendasi(amb, k["fpr_lintas"], 1.0) == 0.5


def test_muat_bobot_imagenet_dari_cache_palsu(tmp_path, monkeypatch):
    """Jalur --init imagenet tanpa unduhan: berkas bobot palsu di cache torch."""
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "th"))
    sumber = train_osnet.torchreid.models.build_model("osnet_ain_x0_25", num_classes=1000,
                                                      loss="softmax", pretrained=False)
    sd = {k: v for k, v in sumber.state_dict().items() if not k.startswith("classifier")}
    cache = train_osnet.path_bobot_imagenet("osnet_ain_x0_25")
    cache.parent.mkdir(parents=True)
    torch.save(sd, cache)

    target = train_osnet.torchreid.models.build_model("osnet_ain_x0_25", num_classes=7,
                                                      loss="triplet", pretrained=False)
    info = train_osnet.muat_bobot_imagenet(target, "osnet_ain_x0_25")
    assert info["lapisan_cocok"] == len(sd) and len(info["sha256"]) == 64
    k = next(iter(sd))
    assert torch.equal(target.state_dict()[k], sd[k])


def test_bobot_imagenet_hilang_memberi_petunjuk_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "kosong"))
    import gdown
    monkeypatch.setattr(gdown, "download", lambda *a, **k: None)  # tanpa jaringan
    with pytest.raises(SystemExit) as e:
        train_osnet.pastikan_bobot_imagenet("osnet_ain_x1_0")
    assert "osnet_ain_x1_0_imagenet.pth" in str(e.value) and "1-CaioD9NaqbHK_kzSMW8VE4_3KcsRjEo" in str(e.value)
