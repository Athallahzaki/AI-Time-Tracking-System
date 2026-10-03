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

**No autograd (always) and `cudnn_benchmark`.** The forward pass runs
under `torch.no_grad()`: no autograd graph is recorded whatever the wrapper
does inside. `cudnn_benchmark` lets cuDNN time its convolution
algorithms once for our fixed 640x640 input; the first frames are slower,
the rest faster. Measure it before keeping it on.

**Batches (`batch_inference`, `predict_images`).** One call for several
cameras' frames. LibreYOLO only stacks a list into ONE forward when it is
called with `batch=len(list)`; a bare list runs one forward per image (that is
why batch_check measured only 1.1x on the RTX 4060). The adapter passes
`batch=`. Whether LibreYOLO accepts it and returns one Results per image is
checked on the first batch; if not, the adapter says so once and runs the
images one by one, so turning the flag on can never return wrong boxes.

**CUDA graph (`cuda_graph`).** D-FINE M at batch 1 is launch-bound: ±1000
kernels per forward, each launched from Python (RTX 4060, 3 Oct: GPU busy ±10
ms of a 57 ms forward, utilisation 26%). LibreYOLO >= 1.6 can replay the
forward from a captured CUDA graph (`predict(..., cuda_graph=True)`),
bit-identical to eager and verified per family; D-FINE opts in. One graph per
input shape (batch size). Measured 12.6 ms instead of 57 ms. A LibreYOLO that
does not know the option makes the adapter warn once and run eager.

**Fast preprocess (`fast_preprocess`).** With cuda_graph the forward is ±12.6
ms but a call is ±28.5 ms (RTX 4060, 3 Oct): the rest is LibreYOLO's CPU
pre/post-processing. For a numpy input its D-FINE preprocess goes numpy -> PIL
-> copy -> numpy -> PIL resize -> float32/255 -> CHW on the CPU, then copies a
4.9 MB float tensor to the GPU. With `pre_resize` the frame is ALREADY an RGB
`image_size` square, PIL's same-size resize is a plain copy, so the model input
is just `uint8 / 255` in CHW. The hook does exactly that on the GPU (1.2 MB
uint8 upload) and returns the same tensor bit for bit. Anything else (other
size, BGR, not uint8) goes through LibreYOLO's own preprocess unchanged.

**Low-score boxes for ByteTrack (`raw_confidence`).** The model is asked for
boxes down to `raw_confidence`, the native `Results` keeps all of them for
ByteTrack's second association stage, and `detect()` still filters at
`confidence_threshold`.
"""

from __future__ import annotations

import contextlib
import logging
import time
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
        cudnn_benchmark: bool = False,
        batch_inference: bool = False,
        cuda_graph: Union[bool, str] = False,
        fast_preprocess: bool = False,
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
        self._cudnn_benchmark = bool(cudnn_benchmark)
        # None = belum dicoba; True/False = hasil percobaan batch pertama.
        self._batch_inference = bool(batch_inference)
        self._batch_supported: Optional[bool] = None
        self._cuda_graph: Union[bool, str] = normalize_cuda_graph(cuda_graph) if self._device != "cpu" else False
        self._fast_preprocess = bool(fast_preprocess)
        self._fast_preprocess_hits = 0
        # (nama, t0, t1) perf_counter dari panggilan detect terakhir; dibaca pipeline.
        self.last_spans: List[Any] = []

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
        version = libreyolo_version()
        logger.info("LibreYOLO %s; cuda_graph %s, batch_inference %s",
                    version or "?", self._cuda_graph, self._batch_inference)
        if self._cuda_graph and version and version_tuple(version) < (1, 6):
            logger.warning("detector.cuda_graph needs LibreYOLO >= 1.6 (installed %s); it will be "
                           "turned off at the first call. pip install -U \"libreyolo>=1.6\"", version)
        if self._fast_preprocess:
            if not self._pre_resize:
                logger.warning("detector.fast_preprocess needs pre_resize: true (frames must already be "
                               "%dx%d RGB); every frame will take LibreYOLO's own path", self._image_size,
                               self._image_size)
            install_fast_preprocess(self)
        if self._cudnn_benchmark and self._device != "cpu":
            try:
                import torch

                torch.backends.cudnn.benchmark = True
                logger.info("cudnn.benchmark on: input size is fixed (%d)", self._image_size)
            except Exception as exc:  # noqa: BLE001 -- optimasi, bukan syarat
                logger.warning("cudnn.benchmark could not be enabled: %s", exc)

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

    def _inference(self):
        """no_grad + autocast. Without torch (unit tests) a no-op.

        no_grad, not inference_mode: inference tensors cannot be modified in
        place outside inference mode, and the Results tensors live on into
        rescale_result and LibreYOLO's ByteTrack.
        """
        stack = contextlib.ExitStack()
        try:
            import torch
        except ImportError:
            return stack
        stack.enter_context(torch.no_grad())
        stack.enter_context(self._autocast())
        return stack

    def _kwargs(self, colour_format: str, confidence: Optional[float]) -> Dict[str, Any]:
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
        if self._cuda_graph:
            kwargs["cuda_graph"] = self._cuda_graph
        # `half` and `verbose` are deliberately NOT passed: LibreYOLO accepts
        # both and does nothing with them (it says so in a warning).
        return kwargs

    def _call(self, model_input: Any, colour_format: str, confidence: Optional[float], **extra: Any) -> Any:
        """One LibreYOLO call. Turns cuda_graph off once if this LibreYOLO rejects it."""
        kwargs = {**self._kwargs(colour_format, confidence), **extra}
        try:
            with self._inference():
                return self._model(model_input, **kwargs)
        except (TypeError, NotImplementedError, ValueError) as exc:
            if not self._cuda_graph or "cuda_graph" not in str(exc):
                raise
            logger.warning("detector.cuda_graph rejected by LibreYOLO (%s); running eager. "
                           "Needs LibreYOLO >= 1.6.", exc)
            self._cuda_graph = False
            kwargs.pop("cuda_graph", None)
            with self._inference():
                return self._model(model_input, **kwargs)

    def _predict(self, image: np.ndarray, confidence: Optional[float] = None) -> Any:
        if self._model is None:
            raise RuntimeError("LibreYOLO model not initialized.")

        t0 = time.perf_counter()
        model_input, colour_format, scale = self._prepare(image)
        t1 = time.perf_counter()
        result = self._call(model_input, colour_format, confidence)
        if scale is not None:
            rescale_result(result, *scale)
        t2 = time.perf_counter()
        # Sub-span untuk bench (pipeline mencatatnya bila ada). LibreYOLO
        # memanggil .cpu() di pasca-prosesnya, jadi t2 sudah menunggu GPU.
        self.last_spans = [("detector_prepare", t0, t1), ("detector_infer", t1, t2)]
        return result

    def predict_images(self, images: List[np.ndarray], confidence: Optional[float] = None) -> List[Any]:
        """One Results per image, in order. Batched when allowed and possible."""
        if self._model is None:
            raise RuntimeError("LibreYOLO model not initialized.")
        if not images:
            return []
        prepared = [self._prepare(image) for image in images]
        formats = {colour for _, colour, _ in prepared}
        results: Optional[List[Any]] = None
        if (self._batch_inference and len(images) > 1 and len(formats) == 1
                and self._batch_supported is not False):
            results = self._try_batch([inp for inp, _, _ in prepared], formats.pop(), confidence)
        if results is None:
            results = []
            for model_input, colour_format, _ in prepared:
                results.append(self._call(model_input, colour_format, confidence))
        for result, (_, _, scale) in zip(results, prepared):
            if scale is not None:
                rescale_result(result, *scale)
        return results

    def _try_batch(self, inputs: List[np.ndarray], colour_format: str,
                   confidence: Optional[float]) -> Optional[List[Any]]:
        try:
            # batch= is what makes LibreYOLO run ONE stacked forward; without
            # it a list is processed image by image.
            out = self._call(list(inputs), colour_format, confidence, batch=len(inputs))
        except Exception as exc:  # noqa: BLE001 -- jatuh ke per gambar, dicatat sekali
            self._batch_unsupported(f"model(list, batch={len(inputs)}) raised {exc!r}")
            return None
        if isinstance(out, (list, tuple)) and len(out) == len(inputs):
            if self._batch_supported is None:
                self._batch_supported = True
                logger.info("batch inference works on this LibreYOLO: %d images per call", len(inputs))
            return list(out)
        self._batch_unsupported(f"model(list) returned {type(out).__name__}, not {len(inputs)} results")
        return None

    def _batch_unsupported(self, why: str) -> None:
        if self._batch_supported is not False:
            logger.warning("detector.batch_inference: %s; running images one by one", why)
        self._batch_supported = False

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
        t2 = time.perf_counter()
        self._remember_result(frame, result)
        self._refresh_class_names(result)
        detections = self.postprocess(frame, result)
        self.last_spans = list(self.last_spans) + [("detector_post", t2, time.perf_counter())]
        return detections

    def note_result(self, result: Any) -> None:
        """Class names may only arrive with the first result (shared detector path)."""
        self._refresh_class_names(result)

    def postprocess(self, frame: Frame, result: Any) -> List[Detection]:
        """Results -> Detections for one frame. Pure: safe from any camera thread."""
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


def install_fast_preprocess(detector: "DFINEDetector") -> bool:
    """Pasang hook `_preprocess_predict` di model LibreYOLO (lihat docstring modul).

    LibreYOLO (InferenceRunner._preprocess_model_input) memakai
    `model._preprocess_predict` bila ada, jadi atribut instance ini menggantikan
    pra-proses hanya untuk model ini. Hook membaca `detector._fast_preprocess`
    setiap panggilan, sehingga bisa dimatikan tanpa memasang ulang (batch_check
    mematikannya untuk pembanding).
    """
    model = detector._model
    original = getattr(model, "_preprocess_predict", None) or getattr(model, "_preprocess", None)
    if model is None or original is None:
        logger.warning("detector.fast_preprocess: this LibreYOLO has no preprocess hook; left off")
        detector._fast_preprocess = False
        return False

    def preprocess(image, color_format="auto", input_size=None, **kwargs):
        if detector._fast_preprocess and not kwargs:
            tensor = _fast_tensor(image, color_format, input_size, getattr(model, "device", None))
            if tensor is not None:
                detector._fast_preprocess_hits += 1
                height, width = image.shape[:2]
                # orig_img: Results menerima array BGR; view tanpa salinan.
                return tensor, image[..., ::-1], (int(width), int(height)), 1.0
        return original(image, color_format, input_size=input_size, **kwargs)

    model._preprocess_predict = preprocess
    logger.info("detector.fast_preprocess on: RGB %dx%d uint8 frames are normalised on the GPU",
                detector._image_size, detector._image_size)
    return True


def _fast_tensor(image: Any, color_format: str, input_size: Any, device: Any) -> Any:
    """`uint8/255` CHW di GPU, atau None bila input bukan kasus yang identik."""
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        return None
    if image.dtype != np.uint8 or color_format != "rgb":
        return None
    size = input_size if isinstance(input_size, (tuple, list)) else (input_size, input_size)
    if input_size is None or tuple(int(v) for v in size) != tuple(image.shape[:2]):
        return None      # LibreYOLO akan me-resize; itu bukan salinan polos lagi
    import torch

    tensor = torch.from_numpy(np.ascontiguousarray(image))
    if device is not None:
        tensor = tensor.to(device, non_blocking=False)
    # Sama PERSIS dengan preprocess_numpy LibreYOLO: float32(uint8) / 255.0.
    # Bukan `div_(255.0)`: di CUDA pembagian dengan skalar dikerjakan sebagai
    # kali kebalikan dan meleset 1 ulp untuk sebagian nilai (uji 4060 3 Okt:
    # IoU min 0,989 lawan jalur PIL). Tabel 256 nilai dihitung numpy, lalu diindeks.
    lut = _normalise_lut(tensor.device, torch)
    return lut[tensor.long()].permute(2, 0, 1).unsqueeze(0).contiguous()


_LUTS: Dict[str, Any] = {}


def _normalise_lut(device: Any, torch: Any) -> Any:
    """float32(i) / 255.0 untuk i = 0..255, dihitung numpy (identik dengan LibreYOLO)."""
    key = str(device)
    lut = _LUTS.get(key)
    if lut is None:
        values = np.arange(256, dtype=np.float32) / np.float32(255.0)
        lut = torch.from_numpy(values).to(device)
        _LUTS[key] = lut
    return lut


def normalize_cuda_graph(value: Any) -> Union[bool, str]:
    """False / True / "auto" (LibreYOLO's accepted values)."""
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "auto":
            return "auto"
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off", ""):
            return False
        raise ValueError(f"detector.cuda_graph must be true, false or \"auto\", got {value!r}")
    return bool(value)


def libreyolo_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("libreyolo")
    except Exception:  # noqa: BLE001 -- informasi saja
        return None


def version_tuple(text: str) -> tuple:
    import re

    parts = []
    for piece in text.split(".")[:3]:
        match = re.match(r"\d+", piece)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts)


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
