"""Fungsi bersama kit latih ReID: pra-proses gambar, SHA-256, L2.

Sengaja TANPA torch: dipakai juga oleh prepare_randperson.py dan eval_reid.py.
Pra-proses di sini adalah definisi "resmi" masukan model; worker embedding di
engine nanti harus identik (BGR→RGB, resize 256x128, /255, mean/std ImageNet).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

TINGGI = 256
LEBAR = 128
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
EKSTENSI_GAMBAR = (".jpg", ".jpeg", ".png")


def baca_bgr(path) -> np.ndarray | None:
    """Baca gambar; aman untuk path Unicode di Windows. None bila gagal."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except OSError:
        return None


def ubah_ukuran(bgr: np.ndarray, tinggi: int = TINGGI, lebar: int = LEBAR) -> np.ndarray:
    """Resize langsung ke tinggi x lebar (tanpa padding), seperti torchreid."""
    h, w = bgr.shape[:2]
    if (h, w) == (tinggi, lebar):
        return bgr
    interp = cv2.INTER_AREA if (h * w) > (tinggi * lebar) else cv2.INTER_LINEAR
    return cv2.resize(bgr, (lebar, tinggi), interpolation=interp)


def simpan_jpg(path, bgr: np.ndarray, kualitas: int = 95) -> None:
    """Tulis JPG lewat berkas sementara lalu rename (aman bila proses mati)."""
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(kualitas)])
    if not ok:
        raise OSError(f"gagal meng-encode JPG: {path}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sementara = path.with_name(path.name + ".tmp")
    buf.tofile(str(sementara))
    sementara.replace(path)


def ke_tensor_np(bgr_256x128: np.ndarray) -> np.ndarray:
    """BGR uint8 256x128 → float32 CHW ternormalisasi (RGB, mean/std ImageNet)."""
    rgb = cv2.cvtColor(bgr_256x128, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - MEAN) / STD
    return np.ascontiguousarray(rgb.transpose(2, 0, 1))


def muat_batch(bgr_list: list[np.ndarray]) -> np.ndarray:
    """Daftar BGR (ukuran bebas) → batch float32 Nx3x256x128."""
    return np.stack([ke_tensor_np(ubah_ukuran(b)) for b in bgr_list]).astype(np.float32)


def l2_normalisasi(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), eps)


def sha256_berkas(path, blok: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(blok)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
