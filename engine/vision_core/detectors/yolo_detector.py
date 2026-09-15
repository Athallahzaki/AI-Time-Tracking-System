from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import numpy as np

from ..contracts.geometry import BoundingBox
from ..contracts.detection import Detection
from ..contracts.frame import Frame
from ..pipeline.config import resolve_engine_path

logger = logging.getLogger(__name__)


class YOLODetector:
    """
    Adapter for Ultralytics YOLO models (YOLOv8, YOLOv10, YOLO11, etc.).
    Isolates YOLO-specific dependencies and returns pure domain Detection objects.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "models/yolo/yolo11s.pt",
        confidence_threshold: float = 0.4,
        iou_threshold: float = 0.45,
        target_classes: Optional[List[Union[int, str]]] = None,
        image_size: int = 640,
        device: Union[str, int] = "auto",
        half: bool = False,
        verbose: bool = False,
    ) -> None:
        resolved_path = resolve_engine_path(model_path)
        self._model_path = str(resolved_path)
        self._conf = confidence_threshold
        self._iou = iou_threshold
        self._imgsz = image_size
        self._raw_device = device
        self._device = self._resolve_device(device)
        self._half = half and (self._device != "cpu")
        self._verbose = verbose

        self._model = None
        self._class_names: Dict[int, str] = {}
        self._target_class_ids: Optional[Set[int]] = None
        self._raw_target_classes = target_classes

        self._load_model()

    @staticmethod
    def _resolve_device(dev: Union[str, int]) -> Union[str, int]:
        """Resolves 'auto' or checks CUDA availability."""
        if str(dev).lower() in ("auto", "none"):
            import torch

            if torch.cuda.is_available():
                cuda_name = torch.cuda.get_device_name(0)
                logger.info(f"CUDA detected: {cuda_name}. Using GPU 0 for YOLO.")
                return 0
            logger.info("CUDA not available. Using CPU for YOLO.")
            return "cpu"
        return dev

    def _load_model(self) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "Ultralytics is required for YOLODetector. Install via `pip install ultralytics`."
            ) from exc

        logger.info(f"Loading YOLO model from {self._model_path} on device '{self._device}'...")
        self._model = YOLO(self._model_path)
        self._class_names = self._model.names if hasattr(self._model, "names") else {}

        # Resolve target classes to IDs
        if self._raw_target_classes is not None:
            resolved_ids = set()
            for item in self._raw_target_classes:
                if isinstance(item, int):
                    resolved_ids.add(item)
                elif isinstance(item, str):
                    matched = [
                        cid for cid, name in self._class_names.items()
                        if name.lower() == item.lower()
                    ]
                    resolved_ids.update(matched)
            self._target_class_ids = resolved_ids
            logger.info(f"YOLO detector filtering for class IDs: {self._target_class_ids}")
        else:
            # Default to person (class 0) if COCO model
            self._target_class_ids = {0}

    def warmup(self) -> None:
        """Runs a dummy forward pass to prime PyTorch/CUDA engine."""
        if self._model is None:
            return
        dummy = np.zeros((self._imgsz, self._imgsz, 3), dtype=np.uint8)
        predict_kwargs = {
            "source": dummy,
            "imgsz": self._imgsz,
            "device": self._device,
            "verbose": False,
        }
        if self._half:
            predict_kwargs["half"] = True

        self._model.predict(**predict_kwargs)
        logger.info("YOLO detector warmup completed.")

    def detect(self, frame: Frame) -> List[Detection]:
        """
        Runs object detection on the provided frame.
        Maps YOLO results into normalized domain Detections.
        """
        if self._model is None:
            raise RuntimeError("YOLO model not initialized.")

        predict_kwargs = {
            "source": frame.image,
            "conf": self._conf,
            "iou": self._iou,
            "imgsz": self._imgsz,
            "device": self._device,
            "verbose": self._verbose,
        }
        if self._half:
            predict_kwargs["half"] = True

        # Run inference
        results = self._model.predict(**predict_kwargs)

        detections: List[Detection] = []
        if not results:
            return detections

        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return detections

        boxes_xyxy = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        class_ids = r.boxes.cls.cpu().numpy().astype(int)

        h, w = frame.shape[:2]

        for i in range(len(boxes_xyxy)):
            cls_id = int(class_ids[i])
            if self._target_class_ids is not None and cls_id not in self._target_class_ids:
                continue

            conf = float(confs[i])
            x1, y1, x2, y2 = boxes_xyxy[i]

            bbox = BoundingBox(
                x1=float(x1),
                y1=float(y1),
                x2=float(x2),
                y2=float(y2),
            ).clip(max_width=w, max_height=h)

            cls_name = self._class_names.get(cls_id, f"class_{cls_id}")

            detections.append(
                Detection(
                    bbox=bbox,
                    confidence=conf,
                    class_id=cls_id,
                    class_name=cls_name,
                )
            )

        return detections

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._class_names)

    @property
    def device(self) -> Union[str, int]:
        return self._device