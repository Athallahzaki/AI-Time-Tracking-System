"""Embedder tubuh ReID: OSNet ONNX hasil `tools/reid_train/export_onnx.py`.

Mengikuti pola `identity/face_onnx.py`: model TIDAK dibundel, dimuat hanya bila
config memintanya (`reid.enabled: true`), dan bila diminta tapi tidak bisa
dimuat engine GAGAL START (`ReidModelUnavailable`), bukan diam-diam berjalan
tanpa ReID. Selama `reid.enabled: false`, modul ini bahkan tidak diimpor.

Pra-proses HARUS identik dengan latihan (`tools/reid_train/reid_common.py`,
yang tercatat juga di metadata ONNX): BGR→RGB, resize langsung ke 256x128
tanpa padding (INTER_AREA bila mengecil, INTER_LINEAR bila membesar), /255,
mean/std ImageNet, CHW. Engine tidak mengimpor `tools/` (bukan dependensi
runtime), jadi definisinya disalin di sini dan disamakan oleh tes
`test_reid_embedder.py`. Ubah keduanya bersamaan atau tidak sama sekali:
pra-proses yang bergeser sedikit tidak memunculkan galat, hanya embedding
yang diam-diam lebih buruk.

Keluaran selalu dinormalisasi L2 di sini, baik model mengekspor embedding
mentah maupun sudah ternormalisasi (`--l2-normalize`); menormalisasi dua kali
tidak mengubah apa pun.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence

import numpy as np

from ..face_onnx import RecognizerUnavailable, _session, provider_list

logger = logging.getLogger("engine.identity.reid.embedder_onnx")

INPUT_HEIGHT = 256
INPUT_WIDTH = 128
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class ReidModelUnavailable(RecognizerUnavailable):
    """`reid.enabled: true` tetapi model tidak bisa dimuat atau tidak sah."""


def sha256_of(path: str, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(block)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def resize_crop(bgr: np.ndarray) -> np.ndarray:
    """Resize langsung ke 256x128, aturan interpolasi sama dengan latihan."""
    import cv2

    height, width = bgr.shape[:2]
    if (height, width) == (INPUT_HEIGHT, INPUT_WIDTH):
        return bgr
    interp = cv2.INTER_AREA if (height * width) > (INPUT_HEIGHT * INPUT_WIDTH) else cv2.INTER_LINEAR
    return cv2.resize(bgr, (INPUT_WIDTH, INPUT_HEIGHT), interpolation=interp)


def preprocess(crops: Sequence[np.ndarray]) -> np.ndarray:
    """Daftar crop BGR uint8 (ukuran bebas) → batch float32 Nx3x256x128."""
    import cv2

    if not crops:
        return np.zeros((0, 3, INPUT_HEIGHT, INPUT_WIDTH), dtype=np.float32)
    out = []
    for crop in crops:
        if crop is None or crop.ndim != 3 or crop.shape[2] != 3 or crop.size == 0:
            raise ValueError("crop harus BGR HxWx3 yang tidak kosong")
        rgb = cv2.cvtColor(resize_crop(crop), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        rgb = (rgb - MEAN) / STD
        out.append(np.ascontiguousarray(rgb.transpose(2, 0, 1)))
    return np.stack(out).astype(np.float32)


def l2_rows(matrix: np.ndarray) -> np.ndarray:
    """Normalisasi L2 per baris. Baris bernorma nol/non-finit = galat, bukan nol."""
    arr = np.asarray(matrix, dtype=np.float32)
    if arr.ndim != 2:
        arr = arr.reshape(arr.shape[0], -1)
    if not np.all(np.isfinite(arr)):
        raise ValueError("embedding ReID berisi NaN/inf")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError("embedding ReID bernorma nol")
    return arr / norms


class OnnxReidEmbedder:
    """`embed(crops) -> (N, D)` ternormalisasi L2, dibatch per `max_batch`."""

    def __init__(self, model_path: str, providers: Optional[Sequence[Any]] = None,
                 expected_sha256: Optional[str] = None, max_batch: int = 8) -> None:
        if max_batch < 1:
            raise ValueError("max_batch minimal 1")
        path = Path(model_path)
        if not path.is_file():
            raise ReidModelUnavailable(
                f"reid.model_path tidak ditemukan: {model_path}. Salin ONNX hasil "
                "tools/reid_train/export_onnx.py ke sana, atau set reid.enabled: false."
            )
        self.sha256 = sha256_of(str(path))
        if expected_sha256:
            if self.sha256.lower() != expected_sha256.strip().lower():
                raise ReidModelUnavailable(
                    f"SHA-256 {path.name} = {self.sha256}, tidak sama dengan reid.model_sha256 "
                    f"({expected_sha256}). Berkas yang salah atau rusak; engine tidak start."
                )
        else:
            logger.warning(
                "reid.model_sha256 kosong: %s (sha256 %s) dimuat tanpa verifikasi. "
                "Isi dari MODEL-CARD sebelum uji sungguhan.", path.name, self.sha256,
            )
        try:
            self._session = _session(str(path), providers, purpose="reid.enabled=true",
                                     providers_key="reid.onnx_providers")
        except ReidModelUnavailable:
            raise
        except RecognizerUnavailable as error:
            raise ReidModelUnavailable(str(error)) from error
        except Exception as error:  # noqa: BLE001 -- ONNX rusak = start ditolak, dengan alasan
            raise ReidModelUnavailable(f"gagal memuat {path.name}: {error}") from error
        self._input = self._session.get_inputs()[0]
        shape = list(self._input.shape)
        if len(shape) != 4 or shape[1] not in (3, "3") or (
                isinstance(shape[2], int) and shape[2] != INPUT_HEIGHT) or (
                isinstance(shape[3], int) and shape[3] != INPUT_WIDTH):
            raise ReidModelUnavailable(
                f"{path.name}: masukan diharapkan Nx3x{INPUT_HEIGHT}x{INPUT_WIDTH}, dapat {shape}"
            )
        # export_onnx.py mengekspor batch dinamis. Graf berbatch tetap 1 masih
        # bisa dipakai (satu per satu); batch tetap lain tidak.
        fixed = shape[0] if isinstance(shape[0], int) else None
        if fixed is not None and fixed != 1:
            raise ReidModelUnavailable(
                f"{path.name}: batch tetap {fixed} tidak didukung; ekspor ulang dengan batch dinamis."
            )
        self.max_batch = 1 if fixed == 1 else int(max_batch)
        self.model_name = path.name
        logger.info("embedder ReID %s dimuat (sha256 %s..., batch maks %d)",
                    path.name, self.sha256[:12], self.max_batch)

    def embed(self, crops: Sequence[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.zeros((0, 0), dtype=np.float32)
        outputs: List[np.ndarray] = []
        for start in range(0, len(crops), self.max_batch):
            blob = preprocess(crops[start:start + self.max_batch])
            result = self._session.run(None, {self._input.name: blob})[0]
            outputs.append(np.asarray(result, dtype=np.float32).reshape(blob.shape[0], -1))
        return l2_rows(np.concatenate(outputs, axis=0))

    __call__ = embed


def build_reid_embedder(reid_config: Any) -> Optional[OnnxReidEmbedder]:
    """None bila `reid.enabled` false; ReidModelUnavailable bila tidak bisa dimuat."""
    if not getattr(reid_config, "enabled", False):
        return None
    from ...config.schema import resolve_engine_path

    providers = provider_list(reid_config.onnx_providers, reid_config.onnx_gpu_mem_limit_mb)
    return OnnxReidEmbedder(
        resolve_engine_path(reid_config.model_path), providers,
        expected_sha256=reid_config.model_sha256, max_batch=reid_config.max_batch,
    )
