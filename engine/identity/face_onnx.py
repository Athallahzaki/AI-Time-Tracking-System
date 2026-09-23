"""Recognizer wajah berbasis ONNX: SCRFD (deteksi + 5 landmark) -> AuraFace/ArcFace.

Ini "tempat" recognizer yang dipasang lewat config (`recognition.recognizer:
onnx_face`). Default-nya mati. Selama mati, tidak ada `onnxruntime` yang diimpor
dan tidak ada berkas model yang dibaca — engine jalan persis seperti sebelumnya.

Model TIDAK dibundel. Yang dibutuhkan (letakkan di mesin engine):

- detektor: SCRFD ONNX (mis. `det_10g.onnx` / `scrfd_2.5g_bnkps.onnx`), keluaran
  score/bbox/kps per stride 8-16-32 (format insightface).
- embedder: AuraFace-v1 ONNX (fal/AuraFace-v1, Apache-2.0), input 112x112.

Kontrak ke sisa engine sama dengan yang sudah diuji di `presence/binding.py`:
`recognizer(track, frame) -> Optional[Evidence]`. Untuk enrollment,
`analyze_image(bgr)` mengembalikan pengukuran yang dibutuhkan `EnrollmentPolicy`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

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


def _session(path: str, providers: Optional[Sequence[str]]):
    try:
        import onnxruntime as ort  # noqa: WPS433 — optional dependency by design
    except ImportError as error:
        raise RecognizerUnavailable(
            "recognition.recognizer=onnx_face butuh onnxruntime "
            "(pip install onnxruntime-gpu atau onnxruntime)"
        ) from error
    if not Path(path).is_file():
        raise RecognizerUnavailable(f"berkas model tidak ditemukan: {path}")
    available = ort.get_available_providers()
    chosen = [p for p in (providers or available) if p in available] or available
    return ort.InferenceSession(path, providers=chosen)


class ScrfdDetector:
    """SCRFD with keypoints, insightface output layout (9 outputs, 3 strides)."""

    STRIDES = (8, 16, 32)
    NUM_ANCHORS = 2

    def __init__(self, model_path: str, providers: Optional[Sequence[str]] = None,
                 input_size: int = 640, threshold: float = 0.5, nms: float = 0.4) -> None:
        self._session = _session(model_path, providers)
        self._input_name = self._session.get_inputs()[0].name
        self._size = int(input_size)
        self._threshold = float(threshold)
        self._nms = float(nms)
        outputs = self._session.get_outputs()
        if len(outputs) != 9:
            raise RecognizerUnavailable(
                f"{model_path}: SCRFD dengan keypoint diharapkan 9 keluaran, dapat {len(outputs)}"
            )
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
                 head_fraction: float = 0.45) -> None:
        self._detector = detector
        self._embedder = embedder
        self.embedding_version = embedding_version
        self._min_face = float(min_face_px)
        self._head_fraction = float(head_fraction)
        # onnxruntime sessions are thread-safe for run(), but the detector's
        # anchor cache and cv2 temporary buffers are cheap to serialise and the
        # recognition path is already rate-limited by the scheduler.
        self._lock = threading.Lock()

    # -- runtime: one track in one frame --------------------------------
    def __call__(self, track: Any, frame: Any) -> Optional[Evidence]:
        image = frame.image
        height, width = image.shape[:2]
        box = track.bbox
        x1, y1 = max(0, int(box.x1)), max(0, int(box.y1))
        x2, y2 = min(width, int(box.x2)), min(height, int(box.y2))
        if x2 - x1 < self._min_face or y2 - y1 < self._min_face:
            return None
        # The face is in the upper part of a person box; searching only there
        # is cheaper and avoids picking up a second person's face.
        head_y2 = y1 + max(int((y2 - y1) * self._head_fraction), int(self._min_face))
        crop = np.ascontiguousarray(image[y1:head_y2, x1:x2])
        with self._lock:
            faces = self._detector.detect(crop)
            faces = [f for f in faces if min(f.width, f.height) >= self._min_face]
            if not faces:
                return None
            face = max(faces, key=lambda f: f.width * f.height)
            landmarks = face.landmarks + np.array([x1, y1], dtype=np.float32)
            aligned = align_face(image, landmarks, self._embedder.input_size)
            embedding = self._embedder.embed(aligned)
        quality = float(min(1.0, face.score * min(1.0, min(face.width, face.height) / 112.0)))
        return Evidence(
            embedding=embedding,
            pts=float(frame.metadata.pts or 0.0),
            quality=max(quality, 1e-3),
            embedding_version=self.embedding_version,
        )

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
    providers = recognition_config.onnx_providers
    detector = ScrfdDetector(
        detector_path, providers,
        threshold=recognition_config.face_detection_threshold,
    )
    embedder = OnnxFaceEmbedder(embedder_path, providers)
    logger.info("recognizer onnx_face dimuat (%s, %s)", detector_path, embedder_path)
    return OnnxFaceRecognizer(
        detector, embedder,
        embedding_version=recognition_config.embedding_version,
        min_face_px=recognition_config.min_face_px,
    )
