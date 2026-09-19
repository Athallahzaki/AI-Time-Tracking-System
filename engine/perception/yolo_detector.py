from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import numpy as np

from ..ports.geometry import BoundingBox
from ..ports.detection import Detection
from ..ports.frame import Frame
from ..config import resolve_engine_path

logger = logging.getLogger(__name__)


class YOLODetector:
    """
    Adapter for LibreYOLO models — primary model: D-FINE (Transformer-based, NMS-free).

    LibreYOLO is MIT-licensed — a commercially safe drop-in replacement
    for the Ultralytics YOLO ecosystem (which uses AGPL-3.0).

    Primary  : D-FINE nano/small/medium  ("LibreDFINEn.pt", "LibreDFINEs.pt", "LibreDFINEm.pt")
    Fallback : YOLOv9 small/tiny         ("LibreYOLO9s.pt", "LibreYOLO9t.pt")

    Docs: https://libreyolo.com/docs/models/d-fine
    GitHub: https://github.com/LibreYOLO/libreyolo
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "LibreDFINEs.pt",
        confidence_threshold: float = 0.50,
        iou_threshold: float = 0.45,
        target_classes: Optional[List[Union[int, str]]] = None,
        image_size: int = 640,
        device: Union[str, int] = "auto",
        half: bool = False,
        verbose: bool = False,
    ) -> None:
        # LibreYOLO auto-downloads named checkpoints (e.g. "LibreDFINEn.pt")
        # from HuggingFace on first use. Local .pt paths are also supported.
        model_str = str(model_path)
        if not Path(model_str).is_absolute() and Path(model_str).suffix in (".pt", ".onnx"):
            # Try to resolve as a local path first; fall back to auto-download name
            resolved = resolve_engine_path(model_path)
            self._model_path = str(resolved) if Path(resolved).exists() else model_str
        else:
            self._model_path = model_str

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
                logger.info(f"CUDA detected: {cuda_name}. Using GPU 0 for LibreYOLO.")
                return 0
            logger.info("CUDA not available. Using CPU for LibreYOLO.")
            return "cpu"
        return dev

    def _load_model(self) -> None:
        try:
            from libreyolo import LibreYOLO
        except ImportError as exc:
            raise ImportError(
                "LibreYOLO is required for YOLODetector. "
                "Install via `pip install libreyolo`. "
                "It is MIT-licensed and commercially safe (unlike Ultralytics AGPL-3.0)."
            ) from exc

        logger.info(f"Loading LibreYOLO model from '{self._model_path}' on device '{self._device}'...")
        self._model = LibreYOLO(self._model_path)

        # LibreYOLO exposes .names as a dict {int: str} on the model object
        self._class_names = getattr(self._model, "names", {}) or {}

        # Resolve target classes to IDs
        if self._raw_target_classes is not None:
            resolved_ids: Set[int] = set()
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
            logger.info(f"LibreYOLO detector filtering for class IDs: {self._target_class_ids}")
        else:
            # Default to person (class 0) for COCO-pretrained models
            self._target_class_ids = {0}

    def warmup(self) -> None:
        """Runs a dummy forward pass to prime PyTorch/CUDA engine."""
        if self._model is None:
            return
        dummy = np.zeros((self._imgsz, self._imgsz, 3), dtype=np.uint8)
        self._model(
            dummy,
            conf=self._conf,
            iou=self._iou,
            imgsz=self._imgsz,
            device=self._device,
            verbose=False,
        )
        logger.info("LibreYOLO detector warmup completed.")

    def detect(self, frame: Frame) -> List[Detection]:
        """
        Runs object detection on the provided frame.
        Maps LibreYOLO results into normalized domain Detection objects.
        """
        if self._model is None:
            raise RuntimeError("LibreYOLO model not initialized.")

        predict_kwargs: Dict[str, Any] = {
            "conf": self._conf,
            "iou": self._iou,
            "imgsz": self._imgsz,
            "device": self._device,
            "verbose": self._verbose,
        }
        if self._half:
            predict_kwargs["half"] = True

        # LibreYOLO accepts numpy arrays directly
        result = self._model(frame.image, **predict_kwargs)

        detections: List[Detection] = []
        if result is None or result.boxes is None or len(result.boxes) == 0:
            return detections

        boxes_xyxy = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        class_ids = result.boxes.cls.cpu().numpy().astype(int)

        # Filter candidate boxes by target class and confidence
        candidate_boxes = []
        candidate_confs = []
        candidate_cls_ids = []

        for i in range(len(boxes_xyxy)):
            cls_id = int(class_ids[i])
            if self._target_class_ids is not None and cls_id not in self._target_class_ids:
                continue
            conf = float(confs[i])
            if conf < self._conf:
                continue
            candidate_boxes.append(boxes_xyxy[i])
            candidate_confs.append(conf)
            candidate_cls_ids.append(cls_id)

        if not candidate_boxes:
            return detections

        candidate_boxes_np = np.array(candidate_boxes, dtype=np.float32)
        candidate_confs_np = np.array(candidate_confs, dtype=np.float32)

        # Apply containment & IoU suppression to eliminate duplicate/nested queries
        keep_indices = self._suppress_duplicate_boxes(
            candidate_boxes_np,
            candidate_confs_np,
            iou_thresh=self._iou,
            containment_thresh=0.65,
        )

        h, w = frame.shape[:2]

        for idx in keep_indices:
            cls_id = candidate_cls_ids[idx]
            conf = float(candidate_confs[idx])
            x1, y1, x2, y2 = candidate_boxes[idx]

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

    @staticmethod
    def _suppress_duplicate_boxes(
        boxes: np.ndarray,
        scores: np.ndarray,
        iou_thresh: float = 0.45,
        containment_thresh: float = 0.65,
    ) -> List[int]:
        """
        Suppresses both high-IoU duplicates and nested/contained duplicate queries
        (common in D-FINE / DETR when extra queries activate on torso or reflections).
        """
        if len(boxes) == 0:
            return []

        order = np.argsort(scores)[::-1]
        keep: List[int] = []

        while len(order) > 0:
            i = int(order[0])
            keep.append(i)
            if len(order) == 1:
                break

            other = order[1:]
            xx1 = np.maximum(boxes[i, 0], boxes[other, 0])
            yy1 = np.maximum(boxes[i, 1], boxes[other, 1])
            xx2 = np.minimum(boxes[i, 2], boxes[other, 2])
            yy2 = np.minimum(boxes[i, 3], boxes[other, 3])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h

            area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
            area_other = (boxes[other, 2] - boxes[other, 0]) * (boxes[other, 3] - boxes[other, 1])

            iou = inter / (area_i + area_other - inter + 1e-6)
            iom = inter / (np.minimum(area_i, area_other) + 1e-6)

            mask = (iou < iou_thresh) & (iom < containment_thresh)
            order = other[mask]

        return keep

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._class_names)

    @property
    def device(self) -> Union[str, int]:
        return self._device


# Alias for explicit D-FINE usage
DFINEDetector = YOLODetector