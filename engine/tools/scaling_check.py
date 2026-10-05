"""Apakah `detector.swscale_resize` aman dan seberapa hemat?

Bench 4060 (3 Okt 21:41): per frame `frame_convert` ±16 ms (YUV -> BGR 1080p)
dan `detector_prepare` ±5 ms (cv2.resize INTER_AREA + BGR->RGB) hanya untuk
menghasilkan RGB 640x640. swscale bisa langsung YUV -> RGB 640x640 dalam satu
langkah. Pikselnya TIDAK identik dengan jalur OpenCV (filter AREA berbeda
implementasi), jadi alat ini membandingkan deteksi kedua jalur pada frame yang
sama, di ambang deteksi, plus waktu kedua jalur.

    python -m engine.tools.scaling_check --config engine/config/dfine-m.yaml --source C:\\video\\uji-siap.mp4

Butuh GPU dan LibreYOLO. Tidak membuka kamera, tidak menyentuh backend.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional

import numpy as np

from .batch_check import compare_detail


@dataclass
class ScalingReport:
    frames: int
    opencv_ms: float          # konversi BGR 1080p + cv2.resize + cvtColor, per frame
    swscale_ms: float         # swscale langsung ke RGB 640, per frame
    mismatched: int = 0       # frame yang deteksinya beda di ambang deteksi
    mismatched_all: int = 0   # termasuk kotak skor rendah (kandidat ByteTrack)
    worst_iou: float = 1.0
    worst_conf_delta: float = 0.0
    unmatched_max_score: float = 0.0
    pixel_mean_abs_diff: float = 0.0
    threshold: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        saved = self.opencv_ms - self.swscale_ms
        if self.mismatched:
            return (f"DETEKSI BERUBAH di {self.mismatched}/{self.frames} frame pada ambang {self.threshold} "
                    f"(skor kotak tanpa pasangan maks {self.unmatched_max_score:.3f}): periksa sebelum memakai "
                    f"swscale_resize (hemat {saved:.1f} ms/frame)")
        if saved <= 1.0:
            return f"Deteksi sama, tetapi hemat hanya {saved:.1f} ms/frame: tidak perlu"
        return (f"Deteksi sama pada ambang {self.threshold} dan hemat {saved:.1f} ms/frame CPU: "
                "layak dipakai (detector.swscale_resize: true)")


def run(detector: Any, frames: List[Any]) -> ScalingReport:
    """`frames`: LazyFrame PyAV yang belum dikonversi."""
    size = detector._image_size
    opencv_times, swscale_times, diffs = [], [], []
    swscale_inputs, opencv_inputs = [], []
    for frame in frames:
        t0 = time.perf_counter()
        small = frame.scaled_rgb(size, size)
        swscale_times.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        prepared = detector._prepare(frame.image)
        opencv_times.append(time.perf_counter() - t0)
        swscale_inputs.append(small)
        opencv_inputs.append(prepared)
        if prepared[1] == "rgb" and small is not None and small.shape == prepared[0].shape:
            diffs.append(float(np.mean(np.abs(small.astype(np.int16) - prepared[0].astype(np.int16)))))

    report = ScalingReport(frames=len(frames),
                           opencv_ms=round(1000 * statistics.fmean(opencv_times), 2),
                           swscale_ms=round(1000 * statistics.fmean(swscale_times), 2),
                           pixel_mean_abs_diff=round(statistics.fmean(diffs), 3) if diffs else 0.0,
                           threshold=getattr(detector, "_conf", None))
    from ..perception.dfine_detector import Prepared

    for frame, small, prepared in zip(frames, swscale_inputs, opencv_inputs):
        if small is None or prepared[2] is None:
            report.notes.append(f"frame {frame.metadata.frame_id}: tidak bisa dibandingkan (ukuran < image_size?)")
            continue
        height, width = frame.metadata.height, frame.metadata.width
        scale = (width / size, height / size, height, width)
        reference = detector._predict(Prepared(*prepared))
        candidate = detector._predict(Prepared(small, "rgb", scale))
        ok, iou, conf, unmatched = compare_detail(reference, candidate, report.threshold)
        report.worst_iou = round(min(report.worst_iou, iou), 4)
        report.worst_conf_delta = round(max(report.worst_conf_delta, conf), 4)
        report.mismatched += 0 if ok else 1
        ok_all, _, _, unmatched_all = compare_detail(reference, candidate, None)
        report.mismatched_all += 0 if ok_all else 1
        if unmatched:
            report.unmatched_max_score = round(max(report.unmatched_max_score, max(unmatched)), 3)
    return report


def format_report(report: ScalingReport) -> str:
    lines = [
        f"{report.frames} frame; ambang deteksi {report.threshold}",
        f"  OpenCV  (BGR 1080p + resize + cvtColor): {report.opencv_ms:.2f} ms/frame",
        f"  swscale (YUV -> RGB 640 langsung)      : {report.swscale_ms:.2f} ms/frame",
        f"  beda piksel rata-rata (0-255)          : {report.pixel_mean_abs_diff:.3f}",
        f"  frame beda di ambang / semua kotak     : {report.mismatched} / {report.mismatched_all}",
        f"  IoU min {report.worst_iou:.3f}, Δskor maks {report.worst_conf_delta:.3f}, "
        f"skor kotak tanpa pasangan maks {report.unmatched_max_score:.3f}",
    ]
    lines.extend("  catatan: " + note for note in report.notes[:5])
    lines.append("KESIMPULAN: " + report.verdict)
    return "\n".join(lines)


def _read_lazy(path: str, count: int, stride: int) -> List[Any]:
    from ..ingest.pyav_source import PyAVSource

    source = PyAVSource(uri=path, source_id="scaling-check")
    source.start()
    frames: List[Any] = []
    try:
        index = 0
        while len(frames) < count:
            frame = source.read()
            if frame is None:
                break
            if index % stride == 0:
                frames.append(frame)
            index += 1
    finally:
        source.stop()
    if not frames:
        raise SystemExit(f"tidak ada frame terbaca dari {path}")
    if not hasattr(frames[0], "scaled_rgb"):
        raise SystemExit("sumber ini tidak menghasilkan frame lazy PyAV; swscale_resize tidak berlaku")
    return frames


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="engine/config/dfine-m.yaml")
    parser.add_argument("--source", required=True)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    from .. import factory
    from ..config import load_config

    config = load_config(args.config)
    config = dataclasses.replace(config, source_type="video_file",
                                 detector=dataclasses.replace(config.detector, pre_resize=True,
                                                              swscale_resize=False))
    frames = _read_lazy(args.source, args.frames, max(1, args.stride))
    detector = factory.build_detector(config)
    detector.warmup()
    report = run(detector, frames)
    print(f"model {config.detector.model_path}, half {config.detector.half}, "
          f"cuda_graph {config.detector.cuda_graph}, fast_preprocess {config.detector.fast_preprocess}")
    print(format_report(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({**asdict(report), "verdict": report.verdict}, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
