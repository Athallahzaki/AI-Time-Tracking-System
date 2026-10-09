"""Pembuat data palsu untuk tes kit latih ReID."""
from pathlib import Path

import cv2
import numpy as np


def _gambar(pid: int, cam: int, k: int, tinggi: int = 80, lebar: int = 40) -> np.ndarray:
    rng = np.random.default_rng(pid * 1000 + cam * 100 + k)
    dasar = np.array([40 + 50 * pid, 200 - 40 * pid, 60 * (pid % 2) + 40], dtype=np.float32)
    img = np.tile(dasar, (tinggi, lebar, 1)) + rng.normal(0, 20, (tinggi, lebar, 3))
    img[: tinggi // 2, :, cam % 3] += 30 * cam  # beda "kamera" = beda warna latar atas
    return np.clip(img, 0, 255).astype(np.uint8)


def buat_randperson_palsu(folder: Path, n_id: int = 4, n_kamera: int = 2, per_kamera: int = 5) -> int:
    """n_id x n_kamera x per_kamera gambar bernama <pid>_s<scene>_c<cam>_f<frame>.jpg."""
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for pid in range(n_id):
        for cam in range(n_kamera):
            for k in range(per_kamera):
                cv2.imwrite(str(folder / f"{pid}_s1_c{cam}_f{k}.jpg"), _gambar(pid, cam, k))
                n += 1
    return n


def buat_crop_berlabel_palsu(folder: Path, n_id: int = 4, kamera=("lobby", "biliar"), per_kamera: int = 4) -> int:
    n = 0
    for pid in range(n_id):
        sub = folder / f"orang{pid}"
        sub.mkdir(parents=True, exist_ok=True)
        for ci, cam in enumerate(kamera):
            for k in range(per_kamera):
                cv2.imwrite(str(sub / f"{cam}_{k:03d}.jpg"), _gambar(pid, ci, k))
                n += 1
    return n
