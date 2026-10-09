"""Checkpoint OSNet → ONNX (embedding saja, tanpa classifier) + verifikasi + SHA-256.

Masukan 1x3x256x128 (sumbu batch dinamis), opset 17. Keluaran 'embedding'
(512-d, mentah; tambahkan --l2-normalize bila ingin dinormalisasi di dalam graf).

Menerima checkpoint hasil train_osnet.py maupun checkpoint torchreid eksternal
(mis. osnet_ain_x1_0 MSMT17 dari huggingface.co/kaiyangzhou/osnet) lewat
--checkpoint + --arch. Yang eksternal HANYA pembanding evaluasi: beri nama
keluaran jelas, mis. PEMBANDING-msmt17.onnx, dan jangan dipakai di engine.

Contoh:
  python export_onnx.py --checkpoint runs\\x\\best.pth --out osnet_rp_imagenet.onnx --verify-dir D:\\data\\rp256\\images
  python export_onnx.py --checkpoint osnet_ain_x1_0_msmt17.pth --arch osnet_ain_x1_0 --out PEMBANDING-msmt17.onnx
"""
from __future__ import annotations

import argparse
import pickle
import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

import torchreid

from reid_common import EKSTENSI_GAMBAR, LEBAR, TINGGI, baca_bgr, muat_batch, sha256_berkas

ARSITEKTUR = ("osnet_ain_x1_0", "osnet_x1_0", "osnet_ain_x0_25")
TOLERANSI = 1e-3
OPSET = 17


class PembungkusEmbedding(nn.Module):
    """Mode eval torchreid sudah mengembalikan embedding; bungkus agar L2 bisa opsional."""

    def __init__(self, model: nn.Module, l2: bool):
        super().__init__()
        self.model = model
        self.l2 = l2

    def forward(self, x):
        v = self.model(x)
        if self.l2:
            v = torch.nn.functional.normalize(v, dim=1)
        return v


def muat_checkpoint(path: str, arch: str | None, izinkan_pickle: bool):
    """Kembalikan (model eval, arch, info). arch dibaca dari checkpoint bila tidak diberikan."""
    try:
        ck = torch.load(path, map_location="cpu", weights_only=not izinkan_pickle)
    except pickle.UnpicklingError as e:
        raise SystemExit(
            f"Checkpoint memuat objek non-tensor ({e}).\n"
            "Bila berkasnya BERASAL DARI SUMBER YANG ANDA PERCAYAI, ulangi dengan --allow-pickle.")
    sd = ck["state_dict"] if isinstance(ck, dict) and "state_dict" in ck else ck
    sd = {(k[7:] if k.startswith("module.") else k): v for k, v in sd.items()}
    arch = arch or (ck.get("arch") if isinstance(ck, dict) else None)
    if arch not in ARSITEKTUR:
        raise SystemExit(f"--arch wajib salah satu dari {ARSITEKTUR} (checkpoint tidak menyebut arsitektur).")
    kls = sd.get("classifier.weight")
    n_kelas = int(kls.shape[0]) if kls is not None else 1000
    model = torchreid.models.build_model(arch, num_classes=n_kelas, loss="softmax", pretrained=False)
    kunci_hilang, kunci_lebih = model.load_state_dict(sd, strict=False)
    wajar = {"classifier.weight", "classifier.bias"}
    if set(kunci_hilang) - wajar or kunci_lebih:
        raise SystemExit(f"State dict tidak cocok dengan {arch}: hilang={list(kunci_hilang)[:5]} "
                         f"lebih={list(kunci_lebih)[:5]}")
    model.eval()
    info = {k: ck[k] for k in ("epoch", "mAP", "rank1") if isinstance(ck, dict) and k in ck}
    info.update(arch=arch, num_classes=n_kelas)
    return model, arch, info


def gambar_verifikasi(folder: str | None, n: int) -> tuple[np.ndarray, str]:
    if folder:
        berkas = sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in EKSTENSI_GAMBAR)
        random.Random(0).shuffle(berkas)
        imgs = [b for b in (baca_bgr(p) for p in berkas[: n * 3]) if b is not None][:n]
        if len(imgs) == n:
            return muat_batch(imgs), f"{n} gambar dari {folder}"
        print(f"PERINGATAN: gambar di {folder} kurang dari {n}; pakai masukan acak.")
    rng = np.random.default_rng(0)
    return rng.normal(size=(n, 3, TINGGI, LEBAR)).astype(np.float32), f"{n} masukan acak (tanpa --verify-dir)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", choices=ARSITEKTUR, default=None,
                    help="wajib untuk checkpoint eksternal; dibaca dari checkpoint train_osnet.py")
    ap.add_argument("--out", required=True, help="berkas .onnx keluaran")
    ap.add_argument("--verify-dir", default=None, help="folder gambar untuk uji kesamaan (default: acak)")
    ap.add_argument("--n-verify", type=int, default=8)
    ap.add_argument("--l2-normalize", action="store_true", help="normalisasi L2 di dalam graf")
    ap.add_argument("--allow-pickle", action="store_true",
                    help="izinkan unpickle penuh (HANYA untuk checkpoint tepercaya)")
    a = ap.parse_args(argv)

    model, arch, info = muat_checkpoint(a.checkpoint, a.arch, a.allow_pickle)
    print(f"Checkpoint dimuat: {arch}, {info}")
    wrap = PembungkusEmbedding(model, a.l2_normalize).eval()

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1, 3, TINGGI, LEBAR)
    with torch.no_grad():
        torch.onnx.export(
            wrap, dummy, str(out), opset_version=OPSET, dynamo=False,
            input_names=["input"], output_names=["embedding"],
            dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}})

    import onnx
    m = onnx.load(str(out))
    onnx.checker.check_model(m)
    for k, v in (("arsitektur", arch), ("embedding_dinormalisasi_l2", str(a.l2_normalize).lower()),
                 ("preproc", f"RGB, resize {TINGGI}x{LEBAR}, /255, mean/std ImageNet")):
        p = m.metadata_props.add()
        p.key, p.value = k, v
    onnx.save(m, str(out))

    import onnxruntime as ort
    x, asal = gambar_verifikasi(a.verify_dir, a.n_verify)
    sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    with torch.no_grad():
        ref = wrap(torch.from_numpy(x)).numpy()
    got = sess.run(None, {"input": x})[0]
    selisih = float(np.abs(ref - got).max())
    satu = sess.run(None, {"input": x[:1]})[0]  # batch=1 juga harus jalan (sumbu dinamis)
    selisih1 = float(np.abs(ref[:1] - satu).max())
    print(f"Verifikasi ({asal}): bentuk keluaran {got.shape}, selisih maks PyTorch vs ORT "
          f"{selisih:.2e} (batch {len(x)}), {selisih1:.2e} (batch 1)")
    if max(selisih, selisih1) >= TOLERANSI:
        print(f"GAGAL: selisih >= {TOLERANSI}. Berkas ONNX jangan dipakai.", file=sys.stderr)
        return 1
    print(f"OK (< {TOLERANSI})")
    print(f"ONNX : {out}")
    print(f"SHA-256: {sha256_berkas(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
