"""D-FINE object detector adapter with no dependency on Ultralytics/YOLO."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

import numpy as np

from ..config import resolve_engine_path
from ..ports.detection import Detection
from ..ports.frame import Frame
from ..ports.geometry import BoundingBox

logger = logging.getLogger(__name__)


class DFINEDetector:
    """Maps Hugging Face D-FINE output into the engine's detector port.

    ``model_path`` may be a local Transformers model directory or a Hugging
    Face model id. Remote weights are downloaded once and then read from the
    local Hugging Face cache.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = "ustc-community/dfine-nano-coco",
        confidence_threshold: float = 0.50,
        iou_threshold: float = 0.45,
        target_classes: Optional[List[Union[int, str]]] = None,
        image_size: int = 640,
        device: Union[str, int] = "auto",
        half: bool = False,
        verbose: bool = False,
    ) -> None:
        # D-FINE is end-to-end and does not require NMS.
        del iou_threshold, verbose

        candidate = Path(resolve_engine_path(model_path))
        self._model_path = str(candidate) if candidate.exists() else str(model_path)
        self._conf = confidence_threshold
        self._image_size = image_size

        try:
            import torch
            from transformers import AutoImageProcessor, DFineForObjectDetection
        except ImportError as exc:
            raise ImportError(
                "D-FINE requires torch and transformers. Install with "
                "`pip install -r engine/requirements.txt`."
            ) from exc

        self._torch = torch
        self._device = self._resolve_device(device)
        self._dtype = (
            torch.float16 if half and self._device.type == "cuda" else torch.float32
        )

        logger.info("Loading D-FINE model %r on %s", self._model_path, self._device)
        self._processor = AutoImageProcessor.from_pretrained(self._model_path)
        self._model = DFineForObjectDetection.from_pretrained(
            self._model_path, torch_dtype=self._dtype
        ).to(self._device)
        self._model.eval()

        raw_names = getattr(self._model.config, "id2label", {}) or {}
        self._class_names: Dict[int, str] = {
            int(key): str(value) for key, value in raw_names.items()
        }
        self._target_class_ids = self._resolve_target_classes(target_classes)

    def _resolve_device(self, device: Union[str, int]):
        value = str(device).lower()
        if value in ("auto", "none"):
            return self._torch.device(
                "cuda:0" if self._torch.cuda.is_available() else "cpu"
            )
        if isinstance(device, int) or value.isdigit():
            return self._torch.device(f"cuda:{int(device)}")
        return self._torch.device(value)

    def _resolve_target_classes(
        self, target_classes: Optional[List[Union[int, str]]]
    ) -> Set[int]:
        if target_classes is None:
            matches = {
                class_id
                for class_id, name in self._class_names.items()
                if name.lower() == "person"
            }
            return matches or {0}

        resolved: Set[int] = set()
        for item in target_classes:
            if isinstance(item, int):
                resolved.add(item)
            else:
                resolved.update(
                    class_id
                    for class_id, name in self._class_names.items()
                    if name.lower() == item.lower()
                )
        return resolved

    def _inputs(self, image: np.ndarray):
        # Sources expose BGR; Transformers image processors expect RGB.
        rgb = np.ascontiguousarray(image[..., ::-1])
        inputs = self._processor(images=rgb, return_tensors="pt")
        return {
            key: (
                value.to(device=self._device, dtype=self._dtype)
                if value.is_floating_point()
                else value.to(self._device)
            )
            for key, value in inputs.items()
        }

    def warmup(self) -> None:
        dummy = np.zeros((self._image_size, self._image_size, 3), dtype=np.uint8)
        with self._torch.inference_mode():
            self._model(**self._inputs(dummy))
        logger.info("D-FINE detector warmup completed")

    def detect(self, frame: Frame) -> List[Detection]:
        height, width = frame.shape[:2]
        with self._torch.inference_mode():
            outputs = self._model(**self._inputs(frame.image))

        result = self._processor.post_process_object_detection(
            outputs,
            target_sizes=[(height, width)],
            threshold=self._conf,
        )[0]

        detections: List[Detection] = []
        for score, label, box in zip(
            result["scores"], result["labels"], result["boxes"]
        ):
            class_id = int(label.item())
            if class_id not in self._target_class_ids:
                continue
            x1, y1, x2, y2 = (float(value) for value in box.tolist())
            detections.append(
                Detection(
                    bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2).clip(
                        max_width=width, max_height=height
                    ),
                    confidence=float(score.item()),
                    class_id=class_id,
                    class_name=self._class_names.get(class_id, f"class_{class_id}"),
                )
            )
        return detections

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._class_names)
