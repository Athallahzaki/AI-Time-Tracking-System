"""Recognizer wajah berbasis ONNX: SCRFD (deteksi + 5 landmark) -> AuraFace/ArcFace.

Ini "tempat" recognizer yang dipasang lewat config (`recognition.recognizer:
onnx_face`). Default-nya mati. Selama mati, tidak ada `onnxruntime` yang diimpor
dan tidak ada berkas model yang dibaca — engine jalan persis seperti sebelumnya.

Model TIDAK dibundel. Yang dibutuhkan (letakkan di mesin engine):

- detektor: SCRFD ONNX (mis. `det_10g.onnx` / `scrfd_2.5g_bnkps.onnx`), keluaran
  score/bbox/kps per stride 8-16-32 (format insightface).
- embedder: AuraFace-v1 ONNX `glintr100.onnx` (fal/AuraFace-v1, Apache-2.0), input 112x112.

Kontrak ke sisa engine sama dengan yang sudah diuji di `presence/binding.py`:
`recognizer(track, frame) -> Optional[Evidence]`. Untuk enrollment,
`analyze_image(bgr)` mengembalikan pengukuran yang dibutuhkan `EnrollmentPolicy`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .ports import Evidence

logger = logging.getLogger("engine.identity.face_onnx")

# ArcFace 112x112 canonical landmark template (insightface).
_ARCFACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


class RecognizerUnavailable(RuntimeError):
    """Recognizer diminta config tapi tidak bisa dimuat. Engine gagal start
    dengan pesan ini, bukan diam-diam berjalan tanpa identitas."""


class ModelConfigMismatch(RecognizerUnavailable):
    """Model ada dan bisa dimuat, tetapi config tidak cocok dengannya (ea-r9).

    Menyalakan ulang tidak memperbaikinya, jadi __main__ keluar dengan kode 2
    (config salah), bukan 1."""


class ProviderUnavailable(ModelConfigMismatch):
    """Config meminta TensorRT EP tetapi env ini tidak bisa mengaktifkannya (ea-r11).

    Biasanya pustaka TensorRT (nvinfer) tidak terpasang atau versinya tidak cocok
    dengan build onnxruntime-gpu. Menyalakan ulang tidak menolong; perbaiki env
    (scripts/setup-env-trt.ps1) atau matikan `recognition.onnx_tensorrt` -> kode 2."""


TENSORRT = "TensorrtExecutionProvider"
CUDA = "CUDAExecutionProvider"


@dataclass
class FaceDetection:
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (pixels, frame coords)
    score: float
    landmarks: np.ndarray                    # (5, 2) pixels, frame coords

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class FaceAnalysis:
    """Everything `EnrollmentPolicy` needs about one image."""

    face_count: int
    embedding: Optional[np.ndarray]
    face_width: float = 0.0
    face_height: float = 0.0
    sharpness: float = 0.0
    brightness: float = 128.0
    contrast: float = 64.0
    detector_confidence: float = 0.0
    landmarks: Optional[List[List[float]]] = None


def _session(path: str, providers: Optional[Sequence[str]], *,
             purpose: str = "recognition.recognizer=onnx_face",
             providers_key: str = "recognition.onnx_providers",
             cache_prefix: Optional[str] = None):
    """Sesi onnxruntime; `purpose`/`providers_key` hanya untuk pesan galat
    (dipakai ulang oleh embedder ReID, `identity/reid/embedder_onnx.py`)."""
    try:
        import onnxruntime as ort  # noqa: WPS433 — optional dependency by design
    except ImportError as error:
        raise RecognizerUnavailable(
            f"{purpose} butuh onnxruntime "
            "(pip install onnxruntime-gpu atau onnxruntime)"
        ) from error
    if not Path(path).is_file():
        raise RecognizerUnavailable(f"berkas model tidak ditemukan: {path}")
    available = ort.get_available_providers()
    # Entri boleh berupa nama atau (nama, opsi) -- opsi dipakai untuk batas VRAM.
    wants_trt = any(_provider_name(p) == TENSORRT for p in (providers or ()))
    if wants_trt and TENSORRT not in available:
        raise ProviderUnavailable(
            f"{TENSORRT} diminta untuk {Path(path).name} tetapi build onnxruntime ini tidak membawanya "
            f"(tersedia: {available}, onnxruntime {getattr(ort, '__version__', '?')}). "
            "Pakai onnxruntime-gpu, atau matikan recognition.onnx_tensorrt."
        )
    requested = [_provider_name(p) for p in (providers or ())]
    if "CUDAExecutionProvider" in requested and "CUDAExecutionProvider" not in available:
        # ea-r14: dulu CUDA yang TIDAK TERSEDIA dibuang diam-diam dari daftar, jadi
        # pemeriksaan "diminta tapi tidak aktif" di bawah tidak pernah terpicu dan sesi
        # jalan di CPU (kejadian 17 Okt: engine dijalankan dari env latihan yang
        # memasang onnxruntime CPU).
        raise RecognizerUnavailable(
            f"CUDAExecutionProvider diminta untuk {Path(path).name} tetapi onnxruntime ini tidak "
            f"membawanya (tersedia: {available}, onnxruntime {getattr(ort, '__version__', '?')}). "
            "Biasanya env yang salah (onnxruntime CPU, mis. env latihan ReID) atau onnxruntime-gpu "
            f"tertimpa onnxruntime. Kalau memang ingin CPU, set {providers_key}: [\"CPUExecutionProvider\"]."
        )
    chosen = [p for p in (providers or available) if _provider_name(p) in available] or available
    names = [_provider_name(p) for p in chosen]
    if "CUDAExecutionProvider" in names:
        _preload_cuda_dlls(ort)
    started = time.perf_counter()
    if wants_trt:
        chosen = _with_cache_prefix(chosen, cache_prefix or Path(path).stem)
        _preload_tensorrt_dlls()
        _announce_tensorrt_build(path, chosen)
    session = ort.InferenceSession(path, providers=chosen)
    active = list(session.get_providers())
    if wants_trt:
        logger.info("onnx %s: sesi TensorRT siap dalam %.1f dtk", Path(path).name, time.perf_counter() - started)
    if "CUDAExecutionProvider" in names and "CUDAExecutionProvider" not in active:
        # onnxruntime TIDAK error saat DLL CUDA/cuDNN tidak cocok: ia menulis
        # peringatan lalu jalan di CPU. Rekognisi di CPU berarti setiap wajah
        # ratusan ms dan uji async/sync tidak bermakna -- jadi berhenti di sini.
        raise RecognizerUnavailable(
            f"CUDAExecutionProvider diminta untuk {Path(path).name} tetapi tidak aktif "
            f"(aktif: {active}, onnxruntime {getattr(ort, '__version__', '?')}). Biasanya DLL CUDA/cuDNN "
            "tidak cocok dengan build onnxruntime-gpu; lihat pesan [E:onnxruntime] di atas. "
            f"Kalau memang ingin CPU, set {providers_key}: [\"CPUExecutionProvider\"]."
        )
    if wants_trt and TENSORRT not in active:
        # Sama seperti CUDA: onnxruntime hanya menulis "EP Error ... falling back" lalu
        # jalan di CUDA EP. Angka uji TensorRT yang ternyata CUDA tidak ada artinya.
        raise ProviderUnavailable(
            f"{TENSORRT} diminta untuk {Path(path).name} tetapi tidak aktif (aktif: {active}, "
            f"onnxruntime {getattr(ort, '__version__', '?')}, pustaka TensorRT: {_TRT_DLL_DIR or 'tidak ditemukan'}). "
            "Biasanya nvinfer tidak terpasang atau versinya tidak cocok; jalankan "
            "`python scripts/check_gpu_env.py --tensorrt`, atau matikan recognition.onnx_tensorrt."
        )
    logger.info("onnx %s: provider aktif %s", Path(path).name, active)
    return session


_DLLS_PRELOADED = False


def _provider_name(entry) -> str:
    return entry[0] if isinstance(entry, (tuple, list)) else str(entry)


def provider_list(names: Optional[Sequence[str]], gpu_mem_limit_mb: Optional[int],
                  tensorrt: Optional[Dict[str, Any]] = None) -> Optional[list]:
    """Nama provider dari config -> daftar untuk onnxruntime, dengan batas VRAM CUDA.

    `kSameAsRequested`: arena tumbuh sebesar yang diminta, bukan berlipat dua;
    bersama `gpu_mem_limit`, ORT tidak lagi memakan VRAM yang dibutuhkan D-FINE.

    `tensorrt` (opsi dari `tensorrt_options`, ea-r11): TensorRT EP ditaruh paling
    depan. CUDA EP tetap di belakangnya untuk node yang tidak didukung TensorRT.
    """
    if not gpu_mem_limit_mb and tensorrt is None:
        return list(names) if names else None
    base = [n for n in (names or ["CUDAExecutionProvider", "CPUExecutionProvider"]) if n != TENSORRT]
    if tensorrt is not None and CUDA not in base:
        base.insert(0, CUDA)
    entries: list = list(base)
    if gpu_mem_limit_mb:
        options = {"gpu_mem_limit": int(gpu_mem_limit_mb) * 1024 * 1024,
                   "arena_extend_strategy": "kSameAsRequested"}
        entries = [(name, options) if name == CUDA else name for name in base]
    if tensorrt is not None:
        entries.insert(0, (TENSORRT, dict(tensorrt)))
    return entries


def tensorrt_options(cache_dir: str, fp16: bool = True, workspace_mb: Optional[int] = None) -> Dict[str, Any]:
    """Opsi TensorRT EP. Cache engine WAJIB: membangun engine glintr100 bisa memakan
    menit; tanpa cache itu terjadi setiap start dan watchdog bisa menganggap engine macet.

    Subfolder per versi onnxruntime + TensorRT + presisi: ORT tidak memasukkan
    ketiganya ke nama berkas cache dan memakai ulang engine lama begitu saja
    (dokumentasinya menyuruh menghapus cache manual bila salah satunya berubah)."""
    path = Path(cache_dir) / tensorrt_cache_tag(fp16)
    path.mkdir(parents=True, exist_ok=True)
    options: Dict[str, Any] = {
        "trt_fp16_enable": bool(fp16),
        "trt_engine_cache_enable": True,
        "trt_engine_cache_path": str(path),
        "trt_timing_cache_enable": True,
        "trt_timing_cache_path": str(path),
    }
    if workspace_mb:
        options["trt_max_workspace_size"] = int(workspace_mb) * 1024 * 1024
    return options


def _dist_version(*names: str) -> str:
    from importlib import metadata

    for name in names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return "lokal"


def tensorrt_cache_tag(fp16: bool) -> str:
    """Nama subfolder cache, mis. `ort1.23.2-trt10.9.0.34-fp16`."""
    ort = _dist_version("onnxruntime-gpu", "onnxruntime")
    trt = _dist_version("tensorrt-cu12-libs", "tensorrt-cu13-libs", "tensorrt-libs", "tensorrt")
    return f"ort{ort}-trt{trt}-{'fp16' if fp16 else 'fp32'}"


_TRT_DLL_DIR: Optional[str] = None
# Nama pustaka TensorRT 10 yang dimuat TensorRT EP onnxruntime.
_TRT_LIBS_WINDOWS = ("nvinfer_10.dll", "nvinfer_plugin_10.dll", "nvonnxparser_10.dll")
_TRT_LIBS_LINUX = ("libnvinfer.so.10", "libnvinfer_plugin.so.10", "libnvonnxparser.so.10")


def find_tensorrt_libs() -> Optional[Path]:
    """Folder pustaka TensorRT dari paket pip `tensorrt-cu12-libs` (modul `tensorrt_libs`)."""
    import importlib.util

    spec = importlib.util.find_spec("tensorrt_libs")
    if spec is None or not spec.submodule_search_locations:
        return None
    folder = Path(list(spec.submodule_search_locations)[0])
    names = _TRT_LIBS_WINDOWS if os.name == "nt" else _TRT_LIBS_LINUX
    return folder if (folder / names[0]).is_file() else None


def _preload_tensorrt_dlls() -> Optional[str]:
    """Muat nvinfer dari paket pip sebelum sesi dibuat.

    `onnxruntime.preload_dlls()` hanya mengurus CUDA/cuDNN. TensorRT EP mencari
    nvinfer_10.dll lewat PATH; DLL dari pip ada di site-packages/tensorrt_libs, yang
    tidak di PATH. Dimuat dengan path lengkap, pemanggilan berikutnya memakai modul
    yang sudah dimuat. TensorRT yang dipasang manual (di PATH) tetap jalan tanpa ini.
    """
    global _TRT_DLL_DIR
    if _TRT_DLL_DIR is not None:
        return _TRT_DLL_DIR
    folder = find_tensorrt_libs()
    if folder is None:
        logger.info("paket tensorrt_libs tidak ditemukan; TensorRT dicari di PATH")
        return None
    import ctypes

    if os.name == "nt":
        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(folder))
    names = _TRT_LIBS_WINDOWS if os.name == "nt" else _TRT_LIBS_LINUX
    for name in names:
        candidate = folder / name
        if candidate.is_file():
            try:
                ctypes.CDLL(str(candidate), mode=getattr(ctypes, "RTLD_GLOBAL", 0))
            except OSError as error:  # yang menentukan tetap provider aktif sesudahnya
                logger.warning("gagal memuat %s: %s", candidate, error)
    _TRT_DLL_DIR = str(folder)
    logger.info("pustaka TensorRT dimuat dari %s", folder)
    return _TRT_DLL_DIR


def _with_cache_prefix(chosen: Sequence[Any], name: str) -> list:
    """Prefix berkas cache per model (dan ukuran input SCRFD), supaya cache SCRFD dan
    glintr100 bisa dibedakan (nama bawaan ORT hanya hash graf)."""
    prefix = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    out = []
    for entry in chosen:
        if isinstance(entry, (tuple, list)) and entry[0] == TENSORRT:
            options = dict(entry[1])
            if options.get("trt_engine_cache_enable"):
                options.setdefault("trt_engine_cache_prefix", prefix)
            entry = (TENSORRT, options)
        out.append(entry)
    return out


def _announce_tensorrt_build(path: str, chosen: Sequence[Any]) -> None:
    """Peringatan sebelum build engine TensorRT yang lama (cache masih kosong)."""
    options = next((p[1] for p in chosen if isinstance(p, (tuple, list)) and p[0] == TENSORRT), {})
    cache = options.get("trt_engine_cache_path")
    prefix = options.get("trt_engine_cache_prefix", "")
    if not cache or not any(Path(cache).glob(f"{prefix}*.engine")):
        logger.warning(
            "onnx %s: TensorRT membangun engine (cache %s kosong). Pertama kali bisa beberapa menit; "
            "jalankan `python -m engine.tools.face_bench` dulu supaya cache terisi sebelum watchdog.",
            Path(path).name, cache or "tidak dipakai")


def _preload_cuda_dlls(ort) -> None:
    """onnxruntime >= 1.21: muat DLL CUDA/cuDNN dari paket pip nvidia-* atau torch.

    Di Windows DLL dari `pip install onnxruntime-gpu[cuda,cudnn]` tidak ada di PATH;
    tanpa ini onnxruntime mencari di PATH saja dan jatuh ke CPU.
    """
    global _DLLS_PRELOADED
    if _DLLS_PRELOADED or not hasattr(ort, "preload_dlls"):
        return
    _DLLS_PRELOADED = True
    try:
        ort.preload_dlls()
    except Exception as error:  # noqa: BLE001 -- yang menentukan adalah provider aktif sesudahnya
        logger.warning("onnxruntime.preload_dlls gagal: %s", error)


class ScrfdDetector:
    """SCRFD with keypoints, insightface output layout (9 outputs, 3 strides)."""

    STRIDES = (8, 16, 32)
    NUM_ANCHORS = 2

    def __init__(self, model_path: str, providers: Optional[Sequence[str]] = None,
                 input_size: int = 640, threshold: float = 0.5, nms: float = 0.4) -> None:
        # Model berdimensi dinamis: engine TensorRT dibangun untuk ukuran yang dipakai,
        # jadi cache per ukuran (ganti 640 <-> 320 tidak menimpa engine yang lain).
        self._session = _session(model_path, providers, cache_prefix=f"{Path(model_path).stem}_{int(input_size)}")
        self._input_name = self._session.get_inputs()[0].name
        self._size = int(input_size)
        self._threshold = float(threshold)
        self._nms = float(nms)
        outputs = self._session.get_outputs()
        if len(outputs) != 9:
            raise RecognizerUnavailable(
                f"{model_path}: SCRFD dengan keypoint diharapkan 9 keluaran, dapat {len(outputs)}"
            )
        _check_static_size(model_path, outputs, self._size, self.STRIDES, self.NUM_ANCHORS)
        self._anchor_cache: dict = {}

    def detect(self, bgr: np.ndarray) -> List[FaceDetection]:
        import cv2

        height, width = bgr.shape[:2]
        scale = self._size / max(height, width)
        resized = cv2.resize(bgr, (max(1, int(width * scale)), max(1, int(height * scale))))
        canvas = np.zeros((self._size, self._size, 3), dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        blob = cv2.dnn.blobFromImage(
            canvas, 1.0 / 128.0, (self._size, self._size), (127.5, 127.5, 127.5), swapRB=True
        )
        outputs = self._session.run(None, {self._input_name: blob})

        scores_all, boxes_all, kps_all = [], [], []
        count = len(self.STRIDES)
        for index, stride in enumerate(self.STRIDES):
            scores = outputs[index].reshape(-1)
            deltas = outputs[index + count].reshape(-1, 4) * stride
            kps = outputs[index + 2 * count].reshape(-1, 10) * stride
            centers = self._anchors(stride)
            keep = np.where(scores >= self._threshold)[0]
            if keep.size == 0:
                continue
            c = centers[keep]
            d = deltas[keep]
            boxes = np.stack([c[:, 0] - d[:, 0], c[:, 1] - d[:, 1],
                              c[:, 0] + d[:, 2], c[:, 1] + d[:, 3]], axis=1)
            k = kps[keep].reshape(-1, 5, 2) + c[:, None, :]
            scores_all.append(scores[keep])
            boxes_all.append(boxes)
            kps_all.append(k)

        if not scores_all:
            return []
        scores = np.concatenate(scores_all)
        boxes = np.concatenate(boxes_all) / scale
        kps = np.concatenate(kps_all) / scale
        order = _nms(boxes, scores, self._nms)
        return [
            FaceDetection(tuple(float(v) for v in boxes[i]), float(scores[i]), kps[i].astype(np.float32))
            for i in order
        ]

    def _anchors(self, stride: int) -> np.ndarray:
        cached = self._anchor_cache.get(stride)
        if cached is not None:
            return cached
        size = self._size // stride
        ys, xs = np.mgrid[:size, :size]
        centers = np.stack([xs, ys], axis=-1).reshape(-1, 2).astype(np.float32) * stride
        centers = np.repeat(centers, self.NUM_ANCHORS, axis=0)
        self._anchor_cache[stride] = centers
        return centers


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> List[int]:
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_o = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        iou = inter / np.maximum(area_i + area_o - inter, 1e-9)
        order = order[1:][iou <= threshold]
    return keep


def align_face(bgr: np.ndarray, landmarks: np.ndarray, size: int = 112) -> np.ndarray:
    import cv2

    template = _ARCFACE_TEMPLATE * (size / 112.0)
    matrix, _ = cv2.estimateAffinePartial2D(landmarks.astype(np.float32), template, method=cv2.LMEDS)
    if matrix is None:
        raise ValueError("alignment failed")
    return cv2.warpAffine(bgr, matrix, (size, size), borderValue=0.0)


def _check_static_size(model_path: str, outputs: Sequence[Any], size: int,
                       strides: Sequence[int], num_anchors: int) -> None:
    """Tolak `face_detector_input_size` yang tidak cocok dengan ONNX berbentuk tetap.

    Uji 4060 (15 Okt, paket ea-r9): `scrfd_10g_bnkps.onnx` mendeklarasikan keluaran
    untuk kanvas 640. Dengan 480, onnxruntime tetap jalan (peringatan
    `VerifyOutputSizes`) tetapi rata-rata rekognisi naik dari 54 ke 547 ms per wajah
    dan 86% permintaan dibuang. Ukuran lain butuh ekspor ulang dengan dimensi
    dinamis atau berbentuk tetap ukuran itu. Model berdimensi simbolik tidak diperiksa.
    """
    for index, stride in enumerate(strides):
        shape = list(getattr(outputs[index], "shape", None) or [])
        if not shape or not all(isinstance(dim, int) and dim > 0 for dim in shape):
            return
        declared = 1
        for dim in shape:
            declared *= dim
        expected = (size // stride) ** 2 * num_anchors
        if declared != expected:
            raise ModelConfigMismatch(
                f"{model_path}: model ini berbentuk tetap ({declared} skor untuk stride {stride}), "
                f"tidak cocok dengan recognition.face_detector_input_size={size} (butuh {expected}). "
                "Pakai ukuran asli model (biasanya 640) atau ekspor ulang model dengan dimensi "
                "dinamis. Menjalankannya tetap membuat rekognisi ±10x lebih lambat (uji 15 Okt)."
            )


def yaw_ratio(landmarks: np.ndarray) -> float:
    """Perkiraan kasar hadap samping dari 5 titik SCRFD (mata kiri, mata kanan, hidung, ...).

    |x hidung - x tengah dua mata| / jarak dua mata. Wajah frontal ±0; makin menyamping
    makin besar (±0,5 ke atas = sudah jauh dari frontal). Tidak dipakai sebagai sudut,
    hanya sebagai gerbang murah sebelum embedding.
    """
    points = np.asarray(landmarks, dtype=np.float32).reshape(-1, 2)
    left, right, nose = points[0], points[1], points[2]
    eye_distance = float(np.hypot(*(right - left)))
    if eye_distance <= 1e-6:
        return float("inf")
    return abs(float(nose[0]) - float(left[0] + right[0]) / 2.0) / eye_distance


class OnnxFaceEmbedder:
    def __init__(self, model_path: str, providers: Optional[Sequence[str]] = None,
                 mean: float = 127.5, std: float = 127.5) -> None:
        self._session = _session(model_path, providers)
        self._input = self._session.get_inputs()[0]
        self._mean, self._std = float(mean), float(std)
        shape = self._input.shape
        self._size = int(shape[2]) if isinstance(shape[2], int) else 112

    @property
    def input_size(self) -> int:
        return self._size

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        rgb = aligned_bgr[:, :, ::-1].astype(np.float32)
        blob = ((rgb - self._mean) / self._std).transpose(2, 0, 1)[None]
        vector = self._session.run(None, {self._input.name: blob})[0].reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError("zero embedding")
        return vector / norm


class OnnxFaceRecognizer:
    """`Recognizer` for the binding + `analyze_image` for enrollment."""

    def __init__(self, detector: ScrfdDetector, embedder: OnnxFaceEmbedder,
                 embedding_version: str, min_face_px: float = 40.0,
                 head_fraction: float = 0.45,
                 embed_min_face_px: Optional[float] = None,
                 embed_min_score: Optional[float] = None,
                 embed_max_yaw: Optional[float] = None) -> None:
        self._detector = detector
        self._embedder = embedder
        self.embedding_version = embedding_version
        self._min_face = float(min_face_px)
        self._head_fraction = float(head_fraction)
        # Gerbang kualitas sebelum embedding (paket ea-r9). Embedder (glintr100,
        # IResNet-100) adalah bagian termahal per wajah; wajah yang hampir pasti
        # gagal cocok tidak perlu dibayar. None = mati (perilaku lama).
        self._embed_min_face = None if embed_min_face_px is None else float(embed_min_face_px)
        self._embed_min_score = None if embed_min_score is None else float(embed_min_score)
        self._embed_max_yaw = None if embed_max_yaw is None else float(embed_max_yaw)
        self._gate = {"embedded": 0, "lewati_kecil": 0, "lewati_skor": 0, "lewati_samping": 0}
        # onnxruntime sessions are thread-safe for run(), but the detector's
        # anchor cache and cv2 temporary buffers are cheap to serialise and the
        # recognition path is already rate-limited by the scheduler.
        self._lock = threading.Lock()

    # -- runtime: one track in one frame --------------------------------
    def __call__(self, track: Any, frame: Any) -> Optional[Evidence]:
        image = frame.image
        cut = head_crop(image, track.bbox, self._min_face, self._head_fraction)
        if cut is None:
            return None
        crop, (x1, y1) = cut
        with self._lock:
            faces = self._detector.detect(crop)
            faces = [f for f in faces if min(f.width, f.height) >= self._min_face]
            if not faces:
                return None
            face = max(faces, key=lambda f: f.width * f.height)
            skip = self._gate_reason(face)
            if skip is not None:
                self._gate[skip] += 1
                return None
            landmarks = face.landmarks + np.array([x1, y1], dtype=np.float32)
            aligned = align_face(image, landmarks, self._embedder.input_size)
            embedding = self._embedder.embed(aligned)
            self._gate["embedded"] += 1
        quality = float(min(1.0, face.score * min(1.0, min(face.width, face.height) / 112.0)))
        return Evidence(
            embedding=embedding,
            pts=float(frame.metadata.pts or 0.0),
            quality=max(quality, 1e-3),
            embedding_version=self.embedding_version,
        )

    def _gate_reason(self, face: FaceDetection) -> Optional[str]:
        """Nama penghitung bila wajah ini dilewati, None bila di-embed."""
        if self._embed_min_face is not None and min(face.width, face.height) < self._embed_min_face:
            return "lewati_kecil"
        if self._embed_min_score is not None and face.score < self._embed_min_score:
            return "lewati_skor"
        if self._embed_max_yaw is not None and yaw_ratio(face.landmarks) > self._embed_max_yaw:
            return "lewati_samping"
        return None

    def gate_metrics(self) -> Dict[str, int]:
        """Kumulatif sejak start: wajah di-embed dan yang dilewati gerbang."""
        with self._lock:
            return dict(self._gate)

    # -- enrollment: one still image ------------------------------------
    def analyze_image(self, bgr: np.ndarray) -> FaceAnalysis:
        import cv2

        with self._lock:
            faces = self._detector.detect(bgr)
            if len(faces) != 1:
                return FaceAnalysis(face_count=len(faces), embedding=None)
            face = faces[0]
            aligned = align_face(bgr, face.landmarks, self._embedder.input_size)
            embedding = self._embedder.embed(aligned)
        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
        return FaceAnalysis(
            face_count=1,
            embedding=embedding,
            face_width=face.width,
            face_height=face.height,
            sharpness=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
            brightness=float(gray.mean()),
            contrast=float(gray.std()),
            detector_confidence=face.score,
            landmarks=face.landmarks.tolist(),
        )


def recognition_providers(recognition_config: Any) -> Optional[list]:
    """Daftar provider recognizer wajah dari `RecognitionConfig` (dipakai juga face_bench)."""
    tensorrt = None
    if getattr(recognition_config, "onnx_tensorrt", False):
        tensorrt = tensorrt_options(
            getattr(recognition_config, "onnx_tensorrt_cache_dir", "engine/data/trt-cache"),
            fp16=getattr(recognition_config, "onnx_tensorrt_fp16", True),
        )
    return provider_list(recognition_config.onnx_providers,
                         getattr(recognition_config, "onnx_gpu_mem_limit_mb", None), tensorrt)


def head_crop(image: np.ndarray, box: Any, min_face_px: float, head_fraction: float = 0.45):
    """Potongan kepala dari kotak orang, persis yang dikirim runtime ke SCRFD.

    -> (crop, (x1, y1)) atau None bila kotaknya terlalu kecil. Dipakai juga oleh
    tools/face_bench supaya yang diukur sama dengan input runtime."""
    height, width = image.shape[:2]
    x1, y1 = max(0, int(box.x1)), max(0, int(box.y1))
    x2, y2 = min(width, int(box.x2)), min(height, int(box.y2))
    if x2 - x1 < min_face_px or y2 - y1 < min_face_px:
        return None
    # The face is in the upper part of a person box; searching only there
    # is cheaper and avoids picking up a second person's face.
    head_y2 = y1 + max(int((y2 - y1) * head_fraction), int(min_face_px))
    return np.ascontiguousarray(image[y1:head_y2, x1:x2]), (x1, y1)


def build_recognizer(recognition_config: Any) -> Optional[OnnxFaceRecognizer]:
    """None when the config says so; RecognizerUnavailable when it cannot load."""
    kind = getattr(recognition_config, "recognizer", "none") or "none"
    if kind == "none":
        return None
    if kind != "onnx_face":
        raise RecognizerUnavailable(f"recognizer tidak dikenal: {kind!r}")
    detector_path = recognition_config.face_detector_model
    embedder_path = recognition_config.face_embedder_model
    if not detector_path or not embedder_path:
        raise RecognizerUnavailable(
            "recognition.face_detector_model dan recognition.face_embedder_model wajib diisi"
        )
    providers = recognition_providers(recognition_config)
    detector = ScrfdDetector(
        detector_path, providers,
        input_size=getattr(recognition_config, "face_detector_input_size", 640),
        threshold=recognition_config.face_detection_threshold,
    )
    embedder = OnnxFaceEmbedder(embedder_path, providers)
    logger.info("recognizer onnx_face dimuat (%s, %s)", detector_path, embedder_path)
    return OnnxFaceRecognizer(
        detector, embedder,
        embedding_version=recognition_config.embedding_version,
        min_face_px=recognition_config.min_face_px,
        embed_min_face_px=getattr(recognition_config, "embed_min_face_px", None),
        embed_min_score=getattr(recognition_config, "embed_min_score", None),
        embed_max_yaw=getattr(recognition_config, "embed_max_yaw", None),
    )
