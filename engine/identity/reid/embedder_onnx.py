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

eb-r12: satu InferenceSession per bucket batch (`reid.batch_buckets`, default
1/2/4/8). CUDA EP hanya menyimpan plan conv cuDNN untuk shape TERAKHIR per
session; tiap pergantian batch size = replan ±350 ms (10-18 dtk bila torch ada
di proses). Tiap session hanya pernah melihat satu shape: crop di-padding nol ke
bucket terkecil yang muat dan keluaran dipotong kembali (OSNet-AIN memproses
tiap sampel sendiri-sendiri, jadi padding tidak mengubah baris asli). Rujukan
pengukuran: `tools/reid_train/diag_reid_bucket.py`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

import numpy as np

from ..face_onnx import RecognizerUnavailable, _session, provider_list

logger = logging.getLogger("engine.identity.reid.embedder_onnx")

INPUT_HEIGHT = 256
INPUT_WIDTH = 128
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
DEFAULT_BUCKETS = (1, 2, 4, 8)
WARMUP_RUNS = 3
# Tanpa opsi ini cuDNN mencari algoritme conv secara menyeluruh pada shape pertama.
CUDA_OPTIONS = {"cudnn_conv_algo_search": "HEURISTIC"}
NVRTC_DLLS = ("nvrtc64_120_0.dll", "nvrtc64_120_0.alt.dll")


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


class ReidBucketRunner:
    """Satu session per ukuran batch; `run(blob)` setara satu session tanpa padding.

    `make_session()` dipanggil sekali per bucket. Tiap session di-warmup hanya
    dengan shape bucket-nya sendiri (input nol), lalu tidak pernah melihat shape lain.
    """

    def __init__(self, make_session: Callable[[], Any], buckets: Sequence[int] = DEFAULT_BUCKETS,
                 warmup_runs: int = WARMUP_RUNS, sample_shape: Sequence[int] = (3, INPUT_HEIGHT, INPUT_WIDTH),
                 label: str = "reid") -> None:
        ordered = tuple(sorted({int(b) for b in buckets}))
        if not ordered or ordered[0] < 1:
            raise ValueError("bucket batch ReID harus bilangan bulat >= 1 dan tidak kosong")
        self.buckets = ordered
        self.sample_shape = tuple(int(v) for v in sample_shape)
        self._sessions = {}
        self.dim: Optional[int] = None
        for bucket in ordered:
            session = make_session()
            name = session.get_inputs()[0].name
            zeros = np.zeros((bucket,) + self.sample_shape, dtype=np.float32)
            for _ in range(max(1, int(warmup_runs))):
                out = session.run(None, {name: zeros})[0]
            self.dim = int(np.asarray(out).reshape(bucket, -1).shape[1])
            self._sessions[bucket] = (session, name)
            active = list(session.get_providers())
            if not active or active[0] != "CUDAExecutionProvider":
                logger.warning(
                    "%s bucket %d: provider aktif %s, BUKAN CUDAExecutionProvider. Embedding ReID "
                    "jalan di CPU (lambat); cek reid.onnx_providers dan onnxruntime-gpu.",
                    label, bucket, active)
            else:
                logger.info("%s bucket %d: provider aktif %s", label, bucket, active)

    def bucket_for(self, n: int) -> int:
        return next(b for b in self.buckets if b >= n)

    def run(self, blob: np.ndarray) -> np.ndarray:
        """(N, C, H, W) float32 -> (N, D) mentah. N = 0 tidak memanggil session."""
        n_total = int(blob.shape[0])
        if n_total == 0:
            return np.zeros((0, self.dim or 0), dtype=np.float32)
        largest = self.buckets[-1]
        outputs: List[np.ndarray] = []
        for start in range(0, n_total, largest):
            part = blob[start:start + largest]
            n = part.shape[0]
            bucket = self.bucket_for(n)
            if bucket > n:
                pad = np.zeros((bucket - n,) + tuple(part.shape[1:]), dtype=part.dtype)
                part = np.concatenate([part, pad], axis=0)
            session, name = self._sessions[bucket]
            result = session.run(None, {name: np.ascontiguousarray(part, dtype=np.float32)})[0]
            outputs.append(np.asarray(result, dtype=np.float32).reshape(bucket, -1)[:n])
        return np.concatenate(outputs, axis=0)

    __call__ = run


def with_cuda_options(providers: Optional[Sequence[Any]]) -> Optional[list]:
    """Tambahkan `CUDA_OPTIONS` ke entri CUDA EP; opsi yang sudah ada (VRAM) dipertahankan."""
    if providers is None:
        return None
    out: list = []
    for entry in providers:
        if isinstance(entry, (tuple, list)):
            name, options = entry[0], dict(entry[1]) if len(entry) > 1 else {}
        else:
            name, options = str(entry), {}
        if name == "CUDAExecutionProvider":
            out.append((name, {**CUDA_OPTIONS, **options}))
        else:
            out.append(entry)
    return out


def loaded_nvrtc() -> Optional[List[str]]:
    """DLL NVRTC yang termuat di proses ini; None di luar Windows."""
    if os.name != "nt":
        return None
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    return [n for n in NVRTC_DLLS if k32.GetModuleHandleW(n)]


def log_cudnn_environment() -> None:
    """torch di proses = ORT memakai cuDNN torch, NVRTC ikut termuat = stall ganti shape."""
    if "torch" in sys.modules:
        logger.warning("ReID: torch ADA di sys.modules proses engine. ORT bisa memakai cuDNN milik "
                       "torch (NVRTC lewat torch\\lib); ganti batch size bisa stall detik-an.")
    else:
        logger.info("ReID: torch tidak ada di sys.modules proses engine")
    nvrtc = loaded_nvrtc()
    if nvrtc is None:
        return
    if nvrtc:
        logger.warning("ReID: NVRTC TERMUAT (%s); cuDNN akan mengompilasi kernel saat shape berubah.",
                       ", ".join(nvrtc))
    else:
        logger.info("ReID: NVRTC tidak termuat (kondisi benar; spam 'Could not locate nvrtc' "
                    "di log stderr C memang diharapkan)")


class OnnxReidEmbedder:
    """`embed(crops) -> (N, D)` ternormalisasi L2; inferensi lewat `ReidBucketRunner`.

    `max_batch` dipertahankan untuk kompatibilitas (worker membatch per nilai itu);
    pemecahan sesungguhnya per bucket terbesar.
    """

    def __init__(self, model_path: str, providers: Optional[Sequence[Any]] = None,
                 expected_sha256: Optional[str] = None, max_batch: int = 8,
                 buckets: Sequence[int] = DEFAULT_BUCKETS, warmup_runs: int = WARMUP_RUNS) -> None:
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
        providers = with_cuda_options(providers)

        def make_session():
            try:
                return _session(str(path), providers, purpose="reid.enabled=true",
                                providers_key="reid.onnx_providers")
            except ReidModelUnavailable:
                raise
            except RecognizerUnavailable as error:
                raise ReidModelUnavailable(str(error)) from error
            except Exception as error:  # noqa: BLE001 -- ONNX rusak = start ditolak, dengan alasan
                raise ReidModelUnavailable(f"gagal memuat {path.name}: {error}") from error

        # Session pertama hanya untuk memeriksa bentuk masukan; dipakai ulang sebagai
        # session bucket pertama supaya model tidak dimuat sekali lebih banyak.
        first = make_session()
        self._input = first.get_inputs()[0]
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
        if fixed == 1:
            buckets = (1,)
        pending = [first]
        try:
            self._runner = ReidBucketRunner(
                lambda: pending.pop() if pending else make_session(), buckets,
                warmup_runs=warmup_runs, label=f"onnx {path.name}")
        except ReidModelUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 -- warmup gagal = start ditolak, dengan alasan
            raise ReidModelUnavailable(f"warmup {path.name} gagal: {error}") from error
        self.buckets = self._runner.buckets
        self.dim = self._runner.dim
        self.model_name = path.name
        logger.info("embedder ReID %s dimuat (sha256 %s..., bucket %s, dim %s, warmup %d/bucket)",
                    path.name, self.sha256[:12], list(self.buckets), self.dim, warmup_runs)
        log_cudnn_environment()

    def embed(self, crops: Sequence[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.zeros((0, self.dim or 0), dtype=np.float32)
        raw = self._runner.run(preprocess(crops))
        return l2_rows(raw)

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
        buckets=getattr(reid_config, "batch_buckets", DEFAULT_BUCKETS),
    )
