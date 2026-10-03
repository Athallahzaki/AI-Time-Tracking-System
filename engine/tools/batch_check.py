"""Apakah batching D-FINE benar dan lebih cepat di mesin ini?

`detector.batch_inference: true` menggabungkan frame beberapa kamera dalam satu
panggilan model. Alat ini memeriksa dua hal sebelum tombol itu dinyalakan:

1. **Benar.** Kotak hasil batch dibandingkan per gambar dengan hasil tanpa
   batch (jumlah kotak, IoU, skor). Batching yang mengubah jawaban tidak boleh
   dipakai, secepat apa pun.
2. **Lebih cepat.** ms per gambar untuk setiap ukuran batch.

    python -m engine.tools.batch_check --config engine/config/dfine-m.yaml --source C:\\video\\uji-siap.mp4
    python -m engine.tools.batch_check --config engine/config/dfine-m.yaml --source uji.mp4 --batch-sizes 1,2,5 --half

Butuh GPU dan LibreYOLO. Tidak membuka kamera dan tidak menyentuh backend.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

IOU_OK = 0.98
CONF_OK = 0.02


@dataclass
class SizeResult:
    batch_size: int
    ms_per_image: float
    speedup: float = 1.0
    batched: bool = False
    mismatched_images: int = 0
    worst_iou: float = 1.0
    worst_conf_delta: float = 0.0


@dataclass
class Report:
    images: int
    reference_ms_per_image: float
    batch_supported: Optional[bool]
    sizes: List[SizeResult] = field(default_factory=list)
    cuda_graph: Any = False
    fast_preprocess: bool = False

    @property
    def verdict(self) -> str:
        if self.batch_supported is False:
            return "LibreYOLO ini tidak menerima batch: biarkan batch_inference: false"
        wrong = [s for s in self.sizes if s.mismatched_images]
        if wrong:
            return "BATCH MENGUBAH HASIL: jangan nyalakan batch_inference"
        best = max(self.sizes, key=lambda s: s.speedup, default=None)
        active = [name for name, on in (("cuda_graph", self.cuda_graph), ("fast_preprocess", self.fast_preprocess)) if on]
        graph = f" ({' + '.join(active)} aktif; pembanding eager/PIL)" if active else ""
        if best is None or best.speedup < 1.1:
            return "Tidak lebih cepat (<10%) dari pembanding" + graph + ": tidak perlu dinyalakan"
        single = next((s for s in self.sizes if s.batch_size == 1), None)
        if best.batch_size == 1:
            # Ukuran 1 bukan batch: percepatannya datang dari cuda_graph.
            return (f"Tercepat pada ukuran 1 ({best.speedup:.2f}x){graph}: batch TIDAK membantu, "
                    "biarkan batch_inference: false" + (f"; {' + '.join(f'{n}: true' for n in active)} layak dipakai"
                                                         if active else ""))
        gain = (single.ms_per_image / best.ms_per_image) if single and best.ms_per_image else best.speedup
        if single and gain < 1.1:
            return (f"Batch {best.batch_size} hanya {gain:.2f}x dibanding ukuran 1{graph}: "
                    "biarkan batch_inference: false")
        return (f"Batch benar dan {gain:.2f}x lebih cepat per gambar dibanding ukuran 1, pada ukuran "
                f"{best.batch_size}{graph}: layak dinyalakan (batch_inference: true, max_batch: {best.batch_size})")


def _boxes(result: Any):
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return np.zeros((0, 4), np.float32), np.zeros((0,), np.float32)

    def arr(value):
        if hasattr(value, "detach"):
            value = value.detach().float().cpu().numpy()
        return np.asarray(value, dtype=np.float32)

    return arr(boxes.xyxy).reshape(-1, 4), arr(boxes.conf).reshape(-1)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union) if union > 0 else 1.0


def compare(reference: Any, candidate: Any):
    """(cocok?, IoU terburuk, selisih skor terburuk) untuk satu gambar."""
    ref_boxes, ref_conf = _boxes(reference)
    cand_boxes, cand_conf = _boxes(candidate)
    if len(ref_boxes) != len(cand_boxes):
        return False, 0.0, 1.0
    worst_iou, worst_conf = 1.0, 0.0
    used = set()
    for box, conf in zip(ref_boxes, ref_conf):
        best, best_j = -1.0, None
        for j, other in enumerate(cand_boxes):
            if j in used:
                continue
            value = _iou(box, other)
            if value > best:
                best, best_j = value, j
        if best_j is None:
            return False, 0.0, 1.0
        used.add(best_j)
        worst_iou = min(worst_iou, best)
        worst_conf = max(worst_conf, abs(float(conf) - float(cand_conf[best_j])))
    ok = worst_iou >= IOU_OK and worst_conf <= CONF_OK
    return ok, worst_iou, worst_conf


def _timed(fn: Callable[[], List[Any]]):
    started = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - started


def run(detector: Any, images: Sequence[np.ndarray], batch_sizes: Sequence[int], repeat: int = 2) -> Report:
    """`detector` = DFINEDetector (atau yang setara) dengan predict_images.

    Pembanding selalu eager tanpa batch. Bila detector memakai cuda_graph,
    baris-baris ukuran batch memakai graph, sehingga perbedaan hasil akibat
    graph juga tertangkap sebagai "salah".
    """
    graph_mode = getattr(detector, "_cuda_graph", False)
    fast_mode = getattr(detector, "_fast_preprocess", False)
    if hasattr(detector, "_cuda_graph"):
        detector._cuda_graph = False
    if hasattr(detector, "_fast_preprocess"):
        detector._fast_preprocess = False
    detector._batch_inference = False
    reference: List[Any] = []
    ref_times = []
    for _ in range(repeat):
        reference, elapsed = _timed(lambda: detector.predict_images(list(images)))
        ref_times.append(elapsed)
    ref_ms = 1000.0 * min(ref_times) / len(images)

    if hasattr(detector, "_cuda_graph"):
        detector._cuda_graph = graph_mode
    if hasattr(detector, "_fast_preprocess"):
        detector._fast_preprocess = fast_mode
    detector._batch_inference = True
    report = Report(images=len(images), reference_ms_per_image=round(ref_ms, 1), batch_supported=None)
    for size in batch_sizes:
        size = max(1, int(size))
        times = []
        results: List[Any] = []
        for _ in range(repeat):
            results = []
            started = time.perf_counter()
            for start in range(0, len(images), size):
                results.extend(detector.predict_images(list(images[start:start + size])))
            times.append(time.perf_counter() - started)
        entry = SizeResult(batch_size=size, ms_per_image=round(1000.0 * min(times) / len(images), 1),
                           batched=bool(size > 1 and getattr(detector, "_batch_supported", None)))
        entry.speedup = round(ref_ms / entry.ms_per_image, 2) if entry.ms_per_image else 1.0
        for ref, cand in zip(reference, results):
            ok, iou, conf = compare(ref, cand)
            entry.worst_iou = round(min(entry.worst_iou, iou), 4)
            entry.worst_conf_delta = round(max(entry.worst_conf_delta, conf), 4)
            entry.mismatched_images += 0 if ok else 1
        report.sizes.append(entry)
    report.batch_supported = getattr(detector, "_batch_supported", None)
    report.cuda_graph = graph_mode
    report.fast_preprocess = bool(fast_mode)
    detector._batch_inference = False
    return report


def format_report(report: Report) -> str:
    lines = [f"{report.images} gambar; tanpa batch {report.reference_ms_per_image:.1f} ms/gambar; "
             f"batch didukung: {report.batch_supported}",
             f"{'batch':>5} {'ms/gambar':>10} {'percepatan':>10} {'dibatch':>8} {'salah':>6} {'IoU min':>8} {'Δskor':>7}"]
    for s in report.sizes:
        lines.append(f"{s.batch_size:>5} {s.ms_per_image:>10.1f} {s.speedup:>9.2f}x {str(s.batched):>8} "
                     f"{s.mismatched_images:>6} {s.worst_iou:>8.3f} {s.worst_conf_delta:>7.3f}")
    lines.append("KESIMPULAN: " + report.verdict)
    return "\n".join(lines)


def _read_frames(path: str, count: int, stride: int) -> List[np.ndarray]:
    from ..ingest.pyav_source import PyAVSource

    source = PyAVSource(uri=path, source_id="batch-check")
    source.start()
    frames: List[np.ndarray] = []
    try:
        index = 0
        while len(frames) < count:
            frame = source.read()
            if frame is None:
                break
            if index % stride == 0:
                frames.append(np.ascontiguousarray(frame.image))
            index += 1
    finally:
        source.stop()
    if not frames:
        raise SystemExit(f"tidak ada frame terbaca dari {path}")
    return frames


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="engine/config/dfine-m.yaml")
    parser.add_argument("--source", required=True, help="berkas video berisi orang")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--stride", type=int, default=5, help="ambil 1 dari tiap N frame supaya bervariasi")
    parser.add_argument("--batch-sizes", default="1,2,5")
    parser.add_argument("--repeat", type=int, default=2)
    precision = parser.add_mutually_exclusive_group()
    precision.add_argument("--half", action="store_true", help="paksa detector.half: true")
    precision.add_argument("--no-half", action="store_true",
                           help="paksa detector.half: false (FP32), apa pun isi config")
    parser.add_argument("--cudnn-benchmark", action="store_true", help="paksa detector.cudnn_benchmark: true")
    parser.add_argument("--fast-preprocess", action="store_true",
                        help="paksa detector.fast_preprocess: true (pra-proses di GPU); pembanding tetap PIL")
    parser.add_argument("--cuda-graph", action="store_true",
                        help="paksa detector.cuda_graph: true (LibreYOLO >= 1.6); pembanding tetap eager")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    from .. import factory
    from ..config import load_config

    config = load_config(args.config)
    changes: Dict[str, Any] = {"batch_inference": True}
    if args.half:
        changes["half"] = True
    if args.no_half:
        changes["half"] = False
    if args.cudnn_benchmark:
        changes["cudnn_benchmark"] = True
    if args.cuda_graph:
        changes["cuda_graph"] = True
    if args.fast_preprocess:
        changes["fast_preprocess"] = True
        changes["pre_resize"] = True
    config = dataclasses.replace(config, source_type="video_file",
                                 detector=dataclasses.replace(config.detector, **changes))
    images = _read_frames(args.source, args.frames, max(1, args.stride))
    detector = factory.build_detector(config)
    detector.warmup()
    sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    report = run(detector, images, sizes, repeat=max(1, args.repeat))
    print(f"model {config.detector.model_path}, half {config.detector.half}, "
          f"cudnn_benchmark {config.detector.cudnn_benchmark}, cuda_graph {getattr(detector, '_cuda_graph', '?')} "
          f"fast_preprocess {getattr(detector, '_fast_preprocess', '?')} "
          f"(dipakai {getattr(detector, '_fast_preprocess_hits', 0)}x) (pembanding: eager, PIL, tanpa batch)")
    print(format_report(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({**asdict(report), "verdict": report.verdict}, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
