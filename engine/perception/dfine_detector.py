"""D-FINE detector adapter backed entirely by LibreYOLO.

The engine owns the detector port; LibreYOLO owns model loading, inference and
result representation.  Keeping this boundary here means the rest of the
engine never needs to know whether a checkpoint is D-FINE or another
LibreYOLO-supported detector.

## What this adapter does around the model call, and why

**Pre-resize (`pre_resize`).** For a numpy input LibreYOLO's D-FINE path goes
through PIL on the CPU at full resolution: BGR->RGB copy, PIL image, a second
copy of that image, back to numpy, PIL again, and only then the resize to
`imgsz`. At 1080p that is four to five 6 MB copies per inference, and it was
most of the "detector" stage on the RTX 4060 bench. D-FINE resizes to a square
without letterbox, so resizing to exactly `image_size x image_size` here gives
the model the same geometry; boxes are scaled back on the native `Results`
object so ByteTrack and `detect()` both see frame coordinates. OpenCV's
INTER_AREA is not bit-identical to PIL's antialiased bilinear, which is why the
switch is a config flag and its accuracy is measured, not assumed.

**FP16 (`half`).** LibreYOLO accepts `half=` as a predict option and ignores
it, and its `quantize(recipe="fp16")` does not cover D-FINE. So `half` now runs
the forward pass under `torch.autocast(float16)`: weights stay FP32, matmuls
and convolutions use tensor cores. On Pascal (GTX 1060) FP16 is crippled and
this is slower; the adapter says so at load time.

**Low-score boxes for ByteTrack (`raw_confidence`).** The model is asked for
boxes down to `raw_confidence`, the native `Results` keeps all of them for
ByteTrack's second association stage, and `detect()` still filters at
`confidence_threshold`.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import numpy as np

from ..config import resolve_engine_path
from ..ports.detection import Detection
from ..ports.frame import Frame
from ..ports.geometry import BoundingBox

logger = logging.getLogger(__name__)


class DFINEDetector:
    """Maps a LibreYOLO D-FINE checkpoint into the engine detector port.

    The published LibreYOLO D-FINE checkpoints are named
    ``LibreDFINEn.pt``, ``LibreDFINEs.pt``, ``LibreDFINEm.pt``, etc.  The
    checkpoint is downloaded and cached by LibreYOLO on first use when it is
    not a local path.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "LibreDFINEn.pt",
        confidence_threshold: float = 0.50,
        iou_threshold: float = 0.45,
        target_classes: Optional[List[Union[int, str]]] = None,
        image_size: int = 640,
        device: Union[str, int] = "auto",
        half: bool = False,
        verbose: bool = False,
        pre_resize: bool = False,
        raw_confidence: Optional[float] = None,
        load_model: bool = True,
    ) -> None:
        self._model_path = self._resolve_model_path(model_path)
        self._conf = confidence_threshold
        # What the model is asked for. Never above the detection threshold:
        # asking for less than we keep is the point, asking for more would
        # silently drop boxes detect() promises to return.
        self._raw_conf = (
            confidence_threshold
            if raw_confidence is None
            else min(float(raw_confidence), confidence_threshold)
        )
        self._iou = iou_threshold
        self._image_size = int(image_size)
        self._device = self._resolve_device(device)
        self._half = bool(half and self._device != "cpu")
        self._verbose = verbose
        self._pre_resize = bool(pre_resize)

        self._model: Any = None
        self._class_names: Dict[int, str] = {}
        self._target_class_ids: Optional[Set[int]] = None
        self._raw_target_classes = target_classes

        # The tracker consumes the exact LibreYOLO Results object produced by
        # this detector, avoiding a second model inference on normal frames.
        self._last_result: Any = None
        self._last_result_frame_id: Optional[int] = None

        if load_model:
            self._load_model()
        else:  # unit tests drive the pre/post-processing without a model
            self._target_class_ids = self._resolve_target_classes(target_classes)

    @staticmethod
    def _resolve_model_path(model_path: Union[str, Path]) -> str:
        path = Path(model_path)
        if path.is_absolute() or path.exists():
            return str(path)
        resolved = Path(resolve_engine_path(path))
        return str(resolved) if resolved.exists() else str(path)

    @staticmethod
    def _resolve_device(device: Union[str, int]) -> Union[str, int]:
        value = str(device).lower()
        if value in ("auto", "none"):
            # Let LibreYOLO/PyTorch select CUDA when available. Keeping this
            # resolution here preserves the engine's explicit device contract.
            try:
                import torch

                if torch.cuda.is_available():
                    logger.info(
                        "CUDA detected: %s. Using GPU 0 for LibreYOLO.",
                        torch.cuda.get_device_name(0),
                    )
                    return 0
            except ImportError:
                pass
            logger.info("CUDA not available. Using CPU for LibreYOLO.")
            return "cpu"
        return device

    def _load_model(self) -> None:
        try:
            from libreyolo import LibreYOLO
        except ImportError as exc:
            raise ImportError(
                "LibreYOLO is required for the D-FINE detector. "
                "Install the real-engine dependencies with "
                "`pip install -r engine/requirements-dfine.txt`."
            ) from exc

        logger.info(
            "Loading LibreYOLO D-FINE model from %r on device %r "
            "(fp16 autocast: %s, pre_resize: %s, model conf floor: %.2f)",
            self._model_path,
            self._device,
            "on" if self._half else "off",
            "on" if self._pre_resize else "off",
            self._raw_conf,
        )
        self._model = LibreYOLO(self._model_path)

        if self._half:
            self._warn_if_fp16_is_slow()

        raw_names = getattr(self._model, "names", {}) or {}
        self._class_names = {
            int(key): str(value) for key, value in raw_names.items()
        }
        self._target_class_ids = self._resolve_target_classes(
            self._raw_target_classes
        )

    def _warn_if_fp16_is_slow(self) -> None:
        try:
            import torch

            index = self._device if isinstance(self._device, int) else 0
            major, minor = torch.cuda.get_device_capability(index)
        except Exception:  # noqa: BLE001 - informational only
            return
        if major < 7:
            logger.warning(
                "detector.half is on, but this GPU is compute capability %d.%d "
                "(Pascal or older). FP16 runs at a fraction of FP32 speed there "
                "(ARCHITECTURE.md §8): expect the detector to get SLOWER. Set "
                "half: false on this machine.",
                major,
                minor,
            )

    def _resolve_target_classes(
        self, target_classes: Optional[List[Union[int, str]]]
    ) -> Optional[Set[int]]:
        if target_classes is None:
            # COCO person is class 0. Do not require the model to expose names
            # during construction; some LibreYOLO backends populate names only
            # after the first result is produced.
            return {0}

        resolved: Set[int] = set()
        for item in target_classes:
            if isinstance(item, int):
                resolved.add(item)
                continue
            resolved.update(
                class_id
                for class_id, name in self._class_names.items()
                if name.lower() == item.lower()
            )
        return resolved

    # -- around the model call --------------------------------------------

    def _prepare(self, image: np.ndarray):
        """The array handed to LibreYOLO, and how to map its boxes back.

        Returns (model_input, colour_format, scale) where scale is
        (sx, sy, frame_height, frame_width) or None when the frame went in
        untouched.
        """
        if not self._pre_resize or image is None or image.ndim != 3:
            return image, "bgr", None
        height, width = image.shape[:2]
        size = self._image_size
        if height < size or width < size:
            # Upscaling at least one axis: INTER_AREA is the wrong filter for
            # that, and there is nothing to save. Let LibreYOLO do it.
            return image, "bgr", None

        import cv2

        small = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
        small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        return small, "rgb", (width / size, height / size, height, width)

    def _autocast(self):
        if not self._half:
            return contextlib.nullcontext()
        import torch

        return torch.autocast(device_type="cuda", dtype=torch.float16)

    def _predict(self, image: np.ndarray, confidence: Optional[float] = None) -> Any:
        if self._model is None:
            raise RuntimeError("LibreYOLO model not initialized.")

        model_input, colour_format, scale = self._prepare(image)
        kwargs: Dict[str, Any] = {
            "conf": self._raw_conf if confidence is None else confidence,
            "iou": self._iou,
            "imgsz": self._image_size,
            "device": self._device,
            # Engine sources expose BGR arrays; the pre-resize path converts
            # to RGB itself. Never let the wrapper guess.
            "color_format": colour_format,
        }
        # Filter kelas DI MODEL, bukan hanya di detect(). ByteTrack memakan
        # Results mentah (last_result); tanpa ini ia ikut melacak kursi, meja,
        # TV, dst. Set kosong tidak dikirim: `classes=[]` ambigu dan nama kelas
        # yang gagal di-resolve harus terlihat, bukan diam-diam membuang semua.
        if self._target_class_ids:
            kwargs["classes"] = sorted(self._target_class_ids)
        # `half` and `verbose` are deliberately NOT passed: LibreYOLO accepts
        # both and does nothing with them (it says so in a warning).
        with self._autocast():
            result = self._model(model_input, **kwargs)
        if scale is not None:
            rescale_result(result, *scale)
        return result

    def predict_raw(self, frame: Frame, confidence: Optional[float] = None) -> Any:
        """Return the native LibreYOLO Results object for a frame.

        This is intentionally a small integration seam for LibreYOLO's public
        ByteTracker API.  Normal engine callers should use ``detect``.
        """
        result = self._predict(frame.image, confidence=confidence)
        self._remember_result(frame, result)
        self._refresh_class_names(result)
        return result

    def _remember_result(self, frame: Frame, result: Any) -> None:
        self._last_result = result
        self._last_result_frame_id = frame.frame_id

    def _refresh_class_names(self, result: Any) -> None:
        raw_names = getattr(result, "names", None) or getattr(self._model, "names", {})
        if raw_names:
            self._class_names = {
                int(key): str(value) for key, value in raw_names.items()
            }
            if self._raw_target_classes is not None:
                self._target_class_ids = self._resolve_target_classes(
                    self._raw_target_classes
                )

    @property
    def last_result(self) -> Any:
        return self._last_result

    @property
    def last_result_frame_id(self) -> Optional[int]:
        return self._last_result_frame_id

    def warmup(self) -> None:
        dummy = np.zeros(
            (self._image_size, self._image_size, 3), dtype=np.uint8
        )
        self._predict(dummy)
        logger.info("LibreYOLO D-FINE detector warmup completed.")

    def detect(self, frame: Frame) -> List[Detection]:
        result = self._predict(frame.image)
        self._remember_result(frame, result)
        self._refresh_class_names(result)

        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = _to_numpy(boxes.xyxy, np.float32)
        confs = _to_numpy(boxes.conf, np.float32)
        class_ids = _to_numpy(boxes.cls, np.float32).astype(int)

        height, width = frame.shape[:2]
        detections: List[Detection] = []

        for box, conf, cls_id_raw in zip(xyxy, confs, class_ids):
            cls_id = int(cls_id_raw)
            if (
                self._target_class_ids is not None
                and cls_id not in self._target_class_ids
            ):
                continue

            score = float(conf)
            if score < self._conf:
                continue

            x1, y1, x2, y2 = (float(value) for value in box)
            detections.append(
                Detection(
                    bbox=BoundingBox(
                        x1=x1, y1=y1, x2=x2, y2=y2
                    ).clip(max_width=width, max_height=height),
                    confidence=score,
                    class_id=cls_id,
                    class_name=self._class_names.get(cls_id, f"class_{cls_id}"),
                )
            )

        return detections

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._class_names)

    @property
    def device(self) -> Union[str, int]:
        return self._device


def _to_numpy(value: Any, dtype) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().float().cpu().numpy()
    return np.asarray(value, dtype=dtype)


def rescale_result(result: Any, sx: float, sy: float, height: int, width: int) -> None:
    """Map a Results object predicted on a resized image back to the frame.

    Mutates `result` in place: new `boxes` in frame pixels and `orig_shape` set
    to the frame. Boxes are rebuilt with the same class LibreYOLO used, so the
    tracker's `results.boxes.xyxy / conf / cls` reads and its `_select()` keep
    working. Any surprise in that structure is an error, not a fallback: boxes
    in the wrong coordinate space would look plausible and be wrong everywhere.
    """
    try:
        boxes = getattr(result, "boxes", None)
        result.orig_shape = (int(height), int(width))
        if boxes is None:
            return
        xyxy = boxes.xyxy
        if hasattr(xyxy, "detach"):
            xyxy = xyxy.float()
            factor = xyxy.new_tensor([sx, sy, sx, sy])
        else:
            xyxy = np.asarray(xyxy, dtype=np.float32)
            factor = np.asarray([sx, sy, sx, sy], dtype=np.float32)
        scaled = xyxy * factor if len(xyxy) else xyxy
        result.boxes = type(boxes)(
            scaled,
            boxes.conf,
            boxes.cls,
            getattr(boxes, "id", None),
            (int(height), int(width)),
        )
    except (AttributeError, TypeError) as exc:
        raise RuntimeError(
            "detector.pre_resize could not map boxes back to the frame on this "
            f"LibreYOLO version ({exc!r}). Set detector.pre_resize: false."
        ) from exc
