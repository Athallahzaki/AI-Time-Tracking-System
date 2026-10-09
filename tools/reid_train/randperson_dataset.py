"""Dataset torchreid dari manifest hasil prepare_randperson.py.

Terdaftar sebagai 'randperson' lewat torchreid.data.register_image_dataset.
`root` = folder keluaran prepare (berisi manifest.csv dan images/).
Kelas dibuat di tingkat modul agar bisa di-pickle oleh DataLoader (spawn di Windows).
"""
from __future__ import annotations

import csv
import os.path as osp

from torchreid.data.datasets import ImageDataset, register_image_dataset

NAMA_DATASET = "randperson"


def baca_manifest(path_manifest: str):
    """Baca manifest → (train, query, gallery) berisi (path_abs, pid, camid).

    pid train dipetakan ulang ke 0..N-1 (syarat classifier); pid query/gallery
    dibiarkan asli karena hanya dibandingkan sesamanya.
    """
    akar = osp.dirname(osp.abspath(path_manifest))
    baris = {"train": [], "query": [], "gallery": []}
    with open(path_manifest, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["split"] not in baris:
                raise ValueError(f"split tak dikenal di manifest: {r['split']!r}")
            baris[r["split"]].append((osp.join(akar, r["path"]), int(r["pid"]), int(r["camid"])))
    for nama, isi in baris.items():
        if not isi:
            raise ValueError(f"manifest tidak punya baris '{nama}': {path_manifest}")
    peta = {pid: i for i, pid in enumerate(sorted({p for _, p, _ in baris["train"]}))}
    train = [(p, peta[pid], c) for p, pid, c in baris["train"]]
    return train, baris["query"], baris["gallery"]


class RandPerson(ImageDataset):
    """RandPerson (sintetis, Apache-2.0) yang sudah di-resize oleh prepare_randperson.py."""

    def __init__(self, root: str = "", manifest: str | None = None, **kwargs):
        path = manifest or osp.join(osp.abspath(osp.expanduser(root)), "manifest.csv")
        if not osp.isfile(path):
            raise FileNotFoundError(
                f"manifest tidak ditemukan: {path} (jalankan prepare_randperson.py dulu)")
        train, query, gallery = baca_manifest(path)
        super().__init__(train, query, gallery, **kwargs)


def daftarkan() -> None:
    """Daftarkan ke torchreid (aman dipanggil berulang)."""
    try:
        register_image_dataset(NAMA_DATASET, RandPerson)
    except ValueError:  # sudah terdaftar
        pass


daftarkan()
