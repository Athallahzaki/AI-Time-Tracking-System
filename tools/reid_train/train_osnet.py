"""Latih OSNet untuk ReID dari manifest RandPerson (jalankan di laptop dengan GPU).

Loss: softmax + label smoothing + triplet batch-hard (bobot 1:1). Optimizer Adam
amsgrad, lr 0.0015, jadwal cosine. Checkpoint terbaik berdasarkan mAP val
(jarak kosinus, sama seperti pemakaian di engine) + checkpoint terakhir.

Contoh:
  python train_osnet.py --data D:\\data\\rp256 --out runs --init imagenet --amp
  python train_osnet.py --data D:\\data\\rp256 --out runs --init scratch  --amp
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import transforms as T

import torchreid
from torchreid.data.sampler import RandomIdentitySampler
from torchreid.metrics import evaluate_rank

import randperson_dataset  # noqa: F401  (mendaftarkan 'randperson')
from randperson_dataset import RandPerson
from reid_common import LEBAR, MEAN, STD, TINGGI, sha256_berkas

ARSITEKTUR = ("osnet_ain_x1_0", "osnet_x1_0", "osnet_ain_x0_25")
ID_DRIVE_IMAGENET = {  # sama dengan docs/MODEL_ZOO.md torchreid ("ImageNet pretrained models")
    "osnet_ain_x1_0": "1-CaioD9NaqbHK_kzSMW8VE4_3KcsRjEo",
    "osnet_ain_x0_25": "1SxQt2AvmEcgWNhaRb2xC4rP6ZwVDP0Wt",
    "osnet_x1_0": "1LaG1EJpHrxdAxKnSCJ_i0u-nbxSAeiFY",
}


# ---------------------------------------------------------------- bobot ImageNet
def folder_cache_torch() -> Path:
    """Sama dengan torchreid: $TORCH_HOME atau $XDG_CACHE_HOME/torch atau ~/.cache/torch."""
    home = os.getenv("TORCH_HOME") or os.path.join(
        os.getenv("XDG_CACHE_HOME", os.path.join("~", ".cache")), "torch")
    return Path(os.path.expanduser(home)) / "checkpoints"


def path_bobot_imagenet(arch: str) -> Path:
    return folder_cache_torch() / f"{arch}_imagenet.pth"


def pastikan_bobot_imagenet(arch: str) -> Path:
    """Pastikan berkas bobot ImageNet ada; coba gdown sekali, kalau gagal beri petunjuk manual."""
    path = path_bobot_imagenet(arch)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    gid = ID_DRIVE_IMAGENET[arch]
    print(f"Bobot ImageNet belum ada di {path}; mencoba gdown ...")
    try:
        import gdown
        gdown.download(f"https://drive.google.com/uc?id={gid}", str(path), quiet=False)
    except Exception as e:  # noqa: BLE001 - gdown melempar berbagai jenis galat
        print(f"gdown gagal: {e}")
    if not path.is_file() or path.stat().st_size < 1024:
        path.unlink(missing_ok=True)
        raise SystemExit(
            "\nBobot ImageNet tidak bisa diunduh otomatis. Unduh manual lewat browser:\n"
            f"  https://drive.google.com/file/d/{gid}/view\n"
            f"lalu simpan dengan nama PERSIS:\n  {path}\n"
            "(lihat README bagian 'Bobot ImageNet'). Jalankan ulang perintah yang sama.")
    return path


def muat_bobot_imagenet(model: nn.Module, arch: str) -> dict:
    """Muat bobot ImageNet ke model; lapisan yang nama/ukurannya beda (classifier) dilewati."""
    path = pastikan_bobot_imagenet(arch)
    sd = torch.load(path, map_location="cpu", weights_only=True)
    if isinstance(sd, dict) and "state_dict" in sd:
        sd = sd["state_dict"]
    model_sd = model.state_dict()
    baru, cocok, dibuang = {}, [], []
    for k, v in sd.items():
        k = k[7:] if k.startswith("module.") else k
        if k in model_sd and model_sd[k].size() == v.size():
            baru[k] = v
            cocok.append(k)
        else:
            dibuang.append(k)
    if not cocok:
        raise SystemExit(f"Tidak ada lapisan cocok antara {path} dan {arch}: berkas salah?")
    model_sd.update(baru)
    model.load_state_dict(model_sd)
    print(f"Bobot ImageNet dimuat: {len(cocok)} lapisan cocok, {len(dibuang)} dilewati")
    return {"berkas": str(path), "sha256": sha256_berkas(path), "id_drive": ID_DRIVE_IMAGENET[arch],
            "lapisan_cocok": len(cocok), "lapisan_dilewati": len(dibuang)}


# ---------------------------------------------------------------- data
def transform_train(erase_prob: float) -> T.Compose:
    """Augmentasi kuat sintetis→nyata."""
    return T.Compose([
        T.Resize((TINGGI, LEBAR)),
        T.RandomResizedCrop((TINGGI, LEBAR), scale=(0.85, 1.0), ratio=(0.45, 0.55)),
        T.RandomHorizontalFlip(),
        T.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.05),
        T.RandomApply([T.GaussianBlur(5, sigma=(0.1, 1.5))], p=0.3),
        T.ToTensor(),
        T.Normalize(mean=MEAN.tolist(), std=STD.tolist()),
        T.RandomErasing(p=erase_prob, scale=(0.02, 0.2), ratio=(0.3, 3.3), value="random"),
    ])


def transform_eval() -> T.Compose:
    return T.Compose([T.Resize((TINGGI, LEBAR)), T.ToTensor(),
                      T.Normalize(mean=MEAN.tolist(), std=STD.tolist())])


# ---------------------------------------------------------------- loss & evaluasi
def triplet_batch_hard(feat: torch.Tensor, pid: torch.Tensor, margin: float) -> torch.Tensor:
    """Triplet batch-hard (jarak Euklides pada fitur mentah, seperti torchreid)."""
    d = torch.cdist(feat.float(), feat.float())
    sama = pid[:, None] == pid[None, :]
    pos = d.masked_fill(~sama, float("-inf")).max(dim=1).values
    neg = d.masked_fill(sama, float("inf")).min(dim=1).values
    return F.relu(pos - neg + margin).mean()


@torch.no_grad()
def ekstrak(model, loader, device, amp: bool):
    model.eval()
    fs, ps, cs = [], [], []
    for b in loader:
        x = b["img"].to(device, non_blocking=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp):
            f = model(x)
        fs.append(F.normalize(f.float(), dim=1).cpu())
        ps.append(b["pid"])
        cs.append(b["camid"])
    return torch.cat(fs), torch.cat(ps).numpy(), torch.cat(cs).numpy()


def evaluasi(model, q_loader, g_loader, device, amp: bool) -> dict:
    qf, qp, qc = ekstrak(model, q_loader, device, amp)
    gf, gp, gc = ekstrak(model, g_loader, device, amp)
    distmat = (1.0 - qf @ gf.t()).numpy()
    try:
        cmc, mAP = evaluate_rank(distmat, qp, gp, qc, gc, max_rank=10)
    except AssertionError as e:  # tidak ada query yang punya pasangan lintas-kamera
        print(f"  PERINGATAN evaluasi: {e}")
        return {"mAP": 0.0, "rank1": 0.0, "rank5": 0.0}
    return {"mAP": float(mAP), "rank1": float(cmc[0]), "rank5": float(cmc[min(4, len(cmc) - 1)])}


# ---------------------------------------------------------------- utilitas
def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True, help="folder hasil prepare_randperson.py")
    ap.add_argument("--out", default="runs", help="folder induk keluaran (default runs)")
    ap.add_argument("--name", default=None, help="nama run (default <arch>_<init>_<waktu>)")
    ap.add_argument("--init", choices=("imagenet", "scratch"), required=True)
    ap.add_argument("--arch", choices=ARSITEKTUR, default="osnet_ain_x1_0")
    ap.add_argument("--epochs", type=int, default=None, help="default 60 (imagenet) / 120 (scratch)")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--num-instances", type=int, default=4, help="gambar per identitas per batch")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--amp", action="store_true", help="mixed precision (hanya CUDA)")
    ap.add_argument("--lr", type=float, default=0.0015)
    ap.add_argument("--weight-decay", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=2, help="epoch pemanasan lr linear (default 2)")
    ap.add_argument("--label-smooth", type=float, default=0.1)
    ap.add_argument("--margin", type=float, default=0.3, help="margin triplet")
    ap.add_argument("--erase-prob", type=float, default=0.5, help="peluang random erasing")
    ap.add_argument("--eval-every", type=int, default=1)
    ap.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", default=None, help="lanjutkan dari last.pth")
    a = ap.parse_args(argv)
    if a.epochs is None:
        a.epochs = 60 if a.init == "imagenet" else 120
    if a.batch % a.num_instances:
        ap.error("--batch harus kelipatan --num-instances")
    return a


def atur_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def buat_scheduler(opt, epochs: int, warmup: int):
    warmup = max(0, min(warmup, epochs - 1))
    cos = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs - warmup))
    if warmup == 0:
        return cos
    hangat = torch.optim.lr_scheduler.LinearLR(opt, start_factor=0.1, total_iters=warmup)
    return torch.optim.lr_scheduler.SequentialLR(opt, [hangat, cos], milestones=[warmup])


def commit_git() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).parent, timeout=10).stdout.strip() or "tidak diketahui"
    except (OSError, subprocess.SubprocessError):
        return "tidak diketahui"


def main(argv=None) -> int:
    a = parse_args(argv)
    atur_seed(a.seed)
    device = torch.device("cuda" if (a.device == "auto" and torch.cuda.is_available()) or a.device == "cuda"
                          else "cpu")
    amp = bool(a.amp)
    if amp and device.type != "cuda":
        print("PERINGATAN: --amp hanya untuk CUDA; dimatikan di CPU.")
        amp = False
    print(f"Perangkat: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device.type == "cuda" else ""))

    root = os.path.abspath(a.data)
    train_ds = RandPerson(root=root, transform=transform_train(a.erase_prob), mode="train", verbose=False)
    query_ds = RandPerson(root=root, transform=transform_eval(), mode="query", verbose=False)
    gallery_ds = RandPerson(root=root, transform=transform_eval(), mode="gallery", verbose=False)
    n_id = train_ds.num_train_pids
    print(f"Train: {n_id} id, {len(train_ds)} gambar | val query {len(query_ds)}, gallery {len(gallery_ds)}")
    if n_id < a.batch // a.num_instances:
        raise SystemExit(f"Identitas train ({n_id}) kurang dari batch/num-instances "
                         f"({a.batch // a.num_instances}); kecilkan --batch.")

    kw = dict(num_workers=a.workers, pin_memory=device.type == "cuda",
              persistent_workers=a.workers > 0)
    train_loader = DataLoader(
        train_ds, batch_size=a.batch, drop_last=True,
        sampler=RandomIdentitySampler(train_ds.train, a.batch, a.num_instances), **kw)
    q_loader = DataLoader(query_ds, batch_size=128, shuffle=False, **kw)
    g_loader = DataLoader(gallery_ds, batch_size=128, shuffle=False, **kw)

    pretrained_info = None
    model = torchreid.models.build_model(a.arch, num_classes=n_id, loss="triplet", pretrained=False)
    if a.init == "imagenet":
        pretrained_info = muat_bobot_imagenet(model, a.arch)
    model.to(device)

    opt = torch.optim.Adam(model.parameters(), lr=a.lr, weight_decay=a.weight_decay, amsgrad=True)
    sched = buat_scheduler(opt, a.epochs, a.warmup)
    ce = nn.CrossEntropyLoss(label_smoothing=a.label_smooth)
    scaler = torch.amp.GradScaler("cuda", enabled=amp)

    nama = a.name or f"{a.arch}_{a.init}_{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir = Path(a.out) / nama
    run_dir.mkdir(parents=True, exist_ok=True)
    mulai_epoch, terbaik = 0, -1.0
    if a.resume:
        ck = torch.load(a.resume, map_location="cpu", weights_only=True)
        if ck.get("epochs") != a.epochs:
            raise SystemExit(f"--epochs ({a.epochs}) harus sama dengan run asal ({ck.get('epochs')}): "
                             "jadwal cosine ikut tersimpan di checkpoint dan akan rusak bila diubah.")
        model.load_state_dict(ck["state_dict"])
        opt.load_state_dict(ck["optimizer"])
        sched.load_state_dict(ck["scheduler"])
        mulai_epoch, terbaik = ck["epoch"], ck.get("best_mAP", -1.0)
        print(f"Dilanjutkan dari epoch {mulai_epoch}, mAP terbaik {terbaik:.4f}")

    konfigurasi = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()}
    konfigurasi.update(commit=commit_git(), torch=torch.__version__, bobot_imagenet=pretrained_info,
                       jumlah_id_train=n_id, mulai=time.strftime("%Y-%m-%d %H:%M:%S"))
    (run_dir / "config.json").write_text(json.dumps(konfigurasi, indent=2), encoding="utf-8")

    try:
        from torch.utils.tensorboard import SummaryWriter
        tb = SummaryWriter(str(run_dir / "tb"))
    except Exception as e:  # noqa: BLE001
        print(f"PERINGATAN: tensorboard tidak aktif ({e})")
        tb = None

    kolom = ["epoch", "lr", "loss", "loss_xent", "loss_tri", "acc", "val_mAP", "val_rank1",
             "val_rank5", "detik"]
    log_path = run_dir / "log.csv"
    baru = not (a.resume and log_path.exists())
    log_f = open(log_path, "w" if baru else "a", newline="", encoding="utf-8")
    log = csv.writer(log_f)
    if baru:
        log.writerow(kolom)

    def simpan(nama_berkas: str, epoch: int, metrik: dict) -> None:
        torch.save({"state_dict": model.state_dict(), "optimizer": opt.state_dict(),
                    "scheduler": sched.state_dict(), "epoch": epoch, "arch": a.arch,
                    "num_classes": n_id, "epochs": a.epochs, "best_mAP": terbaik, **{k: float(v) for k, v in metrik.items()}},
                   run_dir / nama_berkas)

    for epoch in range(mulai_epoch, a.epochs):
        t0 = time.time()
        model.train()
        jml = {"loss": 0.0, "x": 0.0, "t": 0.0, "acc": 0.0}
        n_iter = 0
        for b in train_loader:
            x = b["img"].to(device, non_blocking=True)
            y = b["pid"].to(device, non_blocking=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp):
                logits, feat = model(x)
                lx = ce(logits.float(), y)
                lt = triplet_batch_hard(feat, y, a.margin)
                loss = lx + lt  # bobot 1:1
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            n_iter += 1
            jml["loss"] += loss.item()
            jml["x"] += lx.item()
            jml["t"] += lt.item()
            jml["acc"] += (logits.argmax(1) == y).float().mean().item()
            if n_iter % 50 == 0:
                print(f"  epoch {epoch + 1}/{a.epochs} iter {n_iter} loss {jml['loss'] / n_iter:.4f}")
        lr_dipakai = opt.param_groups[0]["lr"]
        sched.step()
        rata = {k: v / max(1, n_iter) for k, v in jml.items()}

        metrik = {"mAP": float("nan"), "rank1": float("nan"), "rank5": float("nan")}
        if (epoch + 1) % a.eval_every == 0 or epoch + 1 == a.epochs:
            metrik = evaluasi(model, q_loader, g_loader, device, amp)
            if metrik["mAP"] > terbaik:
                terbaik = metrik["mAP"]
                simpan("best.pth", epoch + 1, metrik)
        simpan("last.pth", epoch + 1, metrik)

        dt = time.time() - t0
        log.writerow([epoch + 1, f"{lr_dipakai:.6g}", f"{rata['loss']:.5f}", f"{rata['x']:.5f}",
                      f"{rata['t']:.5f}", f"{rata['acc']:.4f}", f"{metrik['mAP']:.5f}",
                      f"{metrik['rank1']:.5f}", f"{metrik['rank5']:.5f}", f"{dt:.1f}"])
        log_f.flush()
        if tb:
            tb.add_scalar("lr", lr_dipakai, epoch + 1)
            for k, v in (("loss", rata["loss"]), ("loss_xent", rata["x"]), ("loss_tri", rata["t"]),
                         ("acc", rata["acc"])):
                tb.add_scalar(f"train/{k}", v, epoch + 1)
            if metrik["mAP"] == metrik["mAP"]:  # bukan NaN
                tb.add_scalar("val/mAP", metrik["mAP"], epoch + 1)
                tb.add_scalar("val/rank1", metrik["rank1"], epoch + 1)
        print(f"epoch {epoch + 1}/{a.epochs} loss {rata['loss']:.4f} acc {rata['acc']:.3f} "
              f"val mAP {metrik['mAP']:.4f} rank1 {metrik['rank1']:.4f} ({dt:.0f} dtk)")

    log_f.close()
    if tb:
        tb.close()
    print(f"\nSelesai. Terbaik val mAP {terbaik:.4f}. Berkas di {run_dir} (best.pth, last.pth, log.csv).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
