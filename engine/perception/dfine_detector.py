"""D-FINE detector adapter backed entirely by LibreYOLO.

The engine owns the detector port; LibreYOLO owns model loading, preprocessing,
inference and result representation.  Keeping this boundary here means the rest
of the engine never needs to know whether a checkpoint is D-FINE or another
LibreYOLO-supported detector.
"""

from __future__ import annotations

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
    ) -> None:
        self._model_path = self._resolve_model_path(model_path)
        self._conf = confidence_threshold
        self._iou = iou_threshold
        self._image_size = image_size
        self._device = self._resolve_device(device)
        self._half = bool(half and self._device != "cpu")
        self._verbose = verbose

        self._model: Any = None
        self._class_names: Dict[int, str] = {}
        self._target_class_ids: Optional[Set[int]] = None
        self._raw_target_classes = target_classes

        # The tracker consumes the exact LibreYOLO Results object produced by
        # this detector, avoiding a second model inference on normal frames.
        self._last_result: Any = None
        self._last_result_frame_id: Optional[int] = None

        self._load_model()

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
            "Loading LibreYOLO D-FINE model from %r on device %r",
            self._model_path,
            self._device,
        )
        self._model = LibreYOLO(self._model_path)

        raw_names = getattr(self._model, "names", {}) or {}
        self._class_names = {
            int(key): str(value) for key, value in raw_names.items()
        }
        self._target_class_ids = self._resolve_target_classes(
            self._raw_target_classes
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

    def _predict(self, image: np.ndarray, confidence: Optional[float] = None) -> Any:
        if self._model is None:
            raise RuntimeError("LibreYOLO model not initialized.")

        kwargs: Dict[str, Any] = {
            "conf": self._conf if confidence is None else confidence,
            "iou": self._iou,
            "imgsz": self._image_size,
            "device": self._device,
            "verbose": self._verbose,
            # Engine sources expose BGR arrays; avoid an implicit colour-space
            # guess inside a model wrapper.
            "color_format": "bgr",
        }
        # Filter kelas DI MODEL, bukan hanya di detect(). ByteTrack memakan
        # Results mentah (last_result); tanpa ini ia ikut melacak kursi, meja,
        # TV, dst. Set kosong tidak dikirim: `classes=[]` ambigu dan nama kelas
        # yang gagal di-resolve harus terlihat, bukan diam-diam membuang semua.
        if self._target_class_ids:
            kwargs["classes"] = sorted(self._target_class_ids)
        if self._half:
            kwargs["half"] = True
        return self._model(image, **kwargs)

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

        xyxy = boxes.xyxy
        confs = boxes.conf
        class_ids = boxes.cls

        if hasattr(xyxy, "detach"):
            xyxy = xyxy.detach().cpu().numpy()
            confs = confs.detach().cpu().numpy()
            class_ids = class_ids.detach().cpu().numpy().astype(int)
        else:
            xyxy = np.asarray(xyxy)
            confs = np.asarray(confs)
            class_ids = np.asarray(class_ids).astype(int)

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
