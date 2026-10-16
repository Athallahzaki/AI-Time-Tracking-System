"""Berapa ms per wajah, dan apakah hasilnya tetap sama? (paket ea-r11)

Uji 4060 15 Okt: rekognisi = 54 ms per wajah (SCRFD +-21 + glintr100 +-33) dan
worker jenuh di +-18 wajah/dtk. Alat ini mengukur satu wajah demi satu wajah, di
luar engine, untuk setiap varian provider/ukuran, lalu membandingkannya dengan
pembanding (CUDA EP pada ukuran config):

1. **Kecepatan.** ms SCRFD per potongan, ms glintr100 per wajah, waktu bangun sesi
   (TensorRT: build engine pertama, atau baca cache).
2. **Embedding.** glintr100 varian diberi wajah ter-align yang SAMA dengan pembanding,
   lalu dibandingkan kosinusnya ("cos embedder"). FP16 yang sehat >= 0,99.
3. **Deteksi wajah.** SCRFD varian pada potongan yang sama: wajah yang hilang/baru,
   IoU kotak. Penting untuk ukuran 320: wajah kecil bisa hilang.

Potongan yang diukur = potongan kepala dari kotak orang D-FINE, persis yang dikirim
runtime ke SCRFD (`face_onnx.head_crop`). Align dilakukan pada potongan (bukan frame
penuh), sama untuk semua varian.

    python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --source C:\\video\\uji-siap.mp4 --varian cuda,trt16
    python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --source uji.mp4 --simpan-potongan bench-out\\potongan
    python -m engine.tools.face_bench --config engine/config/demo-4060.yaml --potongan bench-out\\potongan --varian cuda,trt16 --ukuran 640,320 --model-detektor engine\\models\\recognition\\scrfd_10g_bnkps_dinamis.onnx

Varian: `cuda` (CUDA EP), `trt16` (TensorRT EP FP16), `trt32` (TensorRT EP FP32).
TensorRT memakai `recognition.onnx_tensorrt_cache_dir` yang sama dengan engine, jadi
menjalankan alat ini sekali juga MENGISI cache sebelum engine dijalankan watchdog.
Tidak membuka kamera dan tidak menyentuh backend.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

PROVIDERS = ("cuda", "trt16", "trt32")
COS_OK = 0.99           # kosinus embedding minimum vs pembanding
LOST_OK = 0.02          # porsi wajah pembanding yang boleh hilang pada ukuran sama
IOU_MATCH = 0.5


@dataclass(frozen=True)
class Variant:
    provider: str
    size: int
    detector_model: str

    @property
    def name(self) -> str:
        return f"{self.provider}@{self.size}"


@dataclass
class VariantResult:
    name: str
    provider: str
    size: int
    detector_model: str
    build_seconds: float = 0.0
    crops: int = 0
    faces: int = 0
    det_ms_median: float = 0.0
    det_ms_p90: float = 0.0
    emb_ms_median: float = 0.0
    emb_ms_p90: float = 0.0
    lost: int = 0                     # wajah pembanding yang tidak ditemukan varian
    extra: int = 0                    # wajah yang hanya ditemukan varian
    iou_median: float = 1.0
    cos_embedder_min: float = 1.0     # input align yang sama -> beda presisi/provider saja
    cos_embedder_p1: float = 1.0
    cos_embedder_mean: float = 1.0
    cos_e2e_median: float = 1.0       # deteksi + align + embed varian sendiri
    cos_e2e_min: float = 1.0
    error: Optional[str] = None

    @property
    def ms_per_face(self) -> float:
        return self.det_ms_median + self.emb_ms_median


@dataclass
class Report:
    crops: int
    reference: VariantResult
    variants: List[VariantResult] = field(default_factory=list)


@dataclass
class _Pass:
    faces: List[Optional[Any]]                # wajah terbesar per potongan (atau None)
    aligned: List[Optional[np.ndarray]]
    embeddings: List[Optional[np.ndarray]]
    det_ms: List[float]
    emb_ms: List[float]


def _largest(faces: Sequence[Any], min_face_px: float):
    faces = [f for f in faces if min(f.width, f.height) >= min_face_px]
    return max(faces, key=lambda f: f.width * f.height) if faces else None


def _process(detector: Any, embedder: Any, crops: Sequence[np.ndarray], min_face_px: float,
             repeat: int) -> _Pass:
    """Jalur yang sama dengan OnnxFaceRecognizer.__call__ (tanpa gerbang), diukur per langkah."""
    from ..identity.face_onnx import align_face

    det_ms: List[float] = []
    emb_ms: List[float] = []
    faces: List[Optional[Any]] = []
    aligned: List[Optional[np.ndarray]] = []
    embeddings: List[Optional[np.ndarray]] = []
    for round_index in range(max(1, repeat)):
        last = round_index == max(1, repeat) - 1
        for crop in crops:
            start = time.perf_counter()
            face = _largest(detector.detect(crop), min_face_px)
            det_ms.append((time.perf_counter() - start) * 1000.0)
            vector = None
            patch = None
            if face is not None:
                patch = align_face(crop, face.landmarks, embedder.input_size)
                start = time.perf_counter()
                vector = embedder.embed(patch)
                emb_ms.append((time.perf_counter() - start) * 1000.0)
            if last:
                faces.append(face)
                aligned.append(patch)
                embeddings.append(vector)
    return _Pass(faces, aligned, embeddings, det_ms, emb_ms)


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _pct(values: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if len(values) else 0.0


def _summarize(variant: Variant, run: _Pass, build_seconds: float, reference: Optional[_Pass],
               embedder: Any) -> VariantResult:
    result = VariantResult(name=variant.name, provider=variant.provider, size=variant.size,
                           detector_model=variant.detector_model, build_seconds=build_seconds,
                           crops=len(run.faces), faces=sum(f is not None for f in run.faces),
                           det_ms_median=_pct(run.det_ms, 50), det_ms_p90=_pct(run.det_ms, 90),
                           emb_ms_median=_pct(run.emb_ms, 50), emb_ms_p90=_pct(run.emb_ms, 90))
    if reference is None:
        return result
    ious: List[float] = []
    e2e: List[float] = []
    for ref_face, face, ref_vec, vec in zip(reference.faces, run.faces, reference.embeddings, run.embeddings):
        if ref_face is not None and face is None:
            result.lost += 1
        elif ref_face is None and face is not None:
            result.extra += 1
        elif ref_face is not None and face is not None:
            iou = _iou(ref_face.bbox, face.bbox)
            ious.append(iou)
            if iou < IOU_MATCH:
                result.lost += 1
                result.extra += 1
            elif ref_vec is not None and vec is not None:
                e2e.append(float(np.dot(ref_vec, vec)))
    # Input sama persis -> selisih hanya dari provider/presisi glintr100.
    same_input = [float(np.dot(ref_vec, embedder.embed(patch)))
                  for patch, ref_vec in zip(reference.aligned, reference.embeddings)
                  if patch is not None and ref_vec is not None]
    if ious:
        result.iou_median = _pct(ious, 50)
    if same_input:
        result.cos_embedder_min = float(min(same_input))
        result.cos_embedder_p1 = _pct(same_input, 1)
        result.cos_embedder_mean = float(np.mean(same_input))
    if e2e:
        result.cos_e2e_median = _pct(e2e, 50)
        result.cos_e2e_min = float(min(e2e))
    return result


Builder = Callable[[Variant], Tuple[Any, Any]]


def run(crops: Sequence[np.ndarray], reference: Variant, variants: Sequence[Variant], build: Builder,
        min_face_px: float = 40.0, repeat: int = 2, release: Optional[Callable[[], None]] = None) -> Report:
    """Pembanding dulu, lalu tiap varian; sesi dilepas di antaranya (VRAM 8 GB dipakai bergantian)."""
    def measure(variant: Variant, ref_pass: Optional[_Pass]):
        start = time.perf_counter()
        detector, embedder = build(variant)
        built = time.perf_counter() - start
        if crops:  # pemanasan: alokasi CUDA / profil TensorRT pertama tidak ikut terukur
            _process(detector, embedder, crops[: min(5, len(crops))], min_face_px, 1)
        result_pass = _process(detector, embedder, crops, min_face_px, repeat)
        summary = _summarize(variant, result_pass, built, ref_pass, embedder)
        del detector, embedder
        if release is not None:
            release()
        return result_pass, summary

    ref_pass, ref_result = measure(reference, None)
    report = Report(crops=len(crops), reference=ref_result)
    for variant in variants:
        if variant == reference:
            continue
        try:
            _, summary = measure(variant, ref_pass)
        except Exception as error:  # noqa: BLE001 -- satu varian gagal tidak menggugurkan yang lain
            summary = VariantResult(name=variant.name, provider=variant.provider, size=variant.size,
                                    detector_model=variant.detector_model, error=f"{type(error).__name__}: {error}")
        report.variants.append(summary)
    return report


def verdict(result: VariantResult, reference: VariantResult) -> List[str]:
    if result.error:
        return [f"GAGAL dimuat: {result.error}"]
    lines: List[str] = []
    if result.cos_embedder_min >= COS_OK:
        lines.append(f"embedding setara pembanding (cos min {result.cos_embedder_min:.4f})")
    else:
        lines.append(f"PERINGATAN embedding bergeser: cos min {result.cos_embedder_min:.4f} < {COS_OK} "
                     "-- cek kecocokan roster sebelum dipakai")
    base_faces = max(1, reference.faces)
    lost_ratio = result.lost / base_faces
    if result.size == reference.size and result.detector_model == reference.detector_model:
        status = "OK" if lost_ratio <= LOST_OK else "PERINGATAN"
        lines.append(f"{status} deteksi wajah: hilang {result.lost} ({lost_ratio:.1%}), baru {result.extra}")
    else:
        lines.append(f"deteksi wajah vs pembanding: hilang {result.lost} ({lost_ratio:.1%}), baru {result.extra} "
                     "-- wajah yang hilang = tidak pernah dikenali; nilai bersama median waktu identifikasi")
    if reference.ms_per_face > 0 and result.ms_per_face > 0:
        lines.append(f"{reference.ms_per_face / result.ms_per_face:.2f}x kecepatan pembanding per wajah")
    return lines


def format_report(report: Report) -> str:
    ref = report.reference
    header = (f"{'varian':<10} {'bangun s':>8} {'wajah':>6} {'scrfd ms':>9} {'p90':>6} {'embed ms':>9} {'p90':>6} "
              f"{'ms/wajah':>9} {'cos min':>8} {'cos p1':>7} {'iou':>5}")
    lines = [f"{report.crops} potongan kepala, pembanding {ref.name} ({Path(ref.detector_model).name})", header,
             "-" * len(header)]

    def row(r: VariantResult) -> str:
        if r.error:
            return f"{r.name:<10} GAGAL: {r.error}"
        return (f"{r.name:<10} {r.build_seconds:>8.1f} {r.faces:>6} {r.det_ms_median:>9.1f} {r.det_ms_p90:>6.1f} "
                f"{r.emb_ms_median:>9.1f} {r.emb_ms_p90:>6.1f} {r.ms_per_face:>9.1f} "
                f"{r.cos_embedder_min:>8.4f} {r.cos_embedder_p1:>7.4f} {r.iou_median:>5.2f}")

    lines.append(row(ref) + "  (pembanding)")
    for result in report.variants:
        lines.append(row(result))
    lines.append("")
    for result in report.variants:
        lines.append(f"{result.name}: " + "; ".join(verdict(result, ref)))
    if not report.variants:
        lines.append("hanya pembanding yang diukur; tambahkan --varian trt16")
    lines.append("Catatan: ms di sini tanpa D-FINE yang berebut GPU; di engine angkanya lebih besar. "
                 "Penentu akhirnya tetap log engine 'rata2 ms', porsi buang, dan 'identifikasi: ... median'.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# input: potongan kepala
# --------------------------------------------------------------------------

def collect_crops(config: Any, source: str, frames: int, stride: int, max_crops: int) -> List[np.ndarray]:
    """Kotak orang dari D-FINE (config engine) -> potongan kepala seperti runtime."""
    from .. import factory
    from ..identity.face_onnx import head_crop
    from ..ingest.pyav_source import PyAVSource

    rec = config.recognition
    config = dataclasses.replace(config, source_type="video_file")
    detector = factory.build_detector(config)
    detector.warmup()
    crops: List[np.ndarray] = []
    source = PyAVSource(uri=source, source_id="face-bench")
    source.start()
    try:
        index = read = 0
        while read < frames and len(crops) < max_crops:
            frame = source.read()
            if frame is None:
                break
            index += 1
            if (index - 1) % stride:
                continue
            read += 1
            for detection in detector.detect(frame):
                if getattr(detection, "class_name", "person") != "person":
                    continue
                cut = head_crop(frame.image, detection.bbox, rec.min_face_px)
                if cut is not None:
                    crops.append(cut[0].copy())
                if len(crops) >= max_crops:
                    break
    finally:
        source.stop()
        del detector
        _release_torch()
    return crops


def _release_torch() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 -- torch tidak wajib untuk mode --potongan
        pass


def save_crops(crops: Sequence[np.ndarray], folder: str) -> None:
    import cv2

    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    for index, crop in enumerate(crops):
        cv2.imwrite(str(path / f"potongan_{index:04d}.png"), crop)


def load_crops(folder: str, max_crops: int) -> List[np.ndarray]:
    import cv2

    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    crops = [img for img in (cv2.imread(str(p)) for p in files[:max_crops]) if img is not None]
    if not crops:
        raise SystemExit(f"tidak ada gambar di {folder}")
    return crops


def real_builder(rec: Any) -> Builder:
    from ..identity.face_onnx import OnnxFaceEmbedder, ScrfdDetector, provider_list, tensorrt_options

    def build(variant: Variant):
        tensorrt = None
        if variant.provider.startswith("trt"):
            tensorrt = tensorrt_options(rec.onnx_tensorrt_cache_dir, fp16=variant.provider == "trt16")
        providers = provider_list(rec.onnx_providers, rec.onnx_gpu_mem_limit_mb, tensorrt)
        detector = ScrfdDetector(variant.detector_model, providers, input_size=variant.size,
                                 threshold=rec.face_detection_threshold)
        embedder = OnnxFaceEmbedder(rec.face_embedder_model, providers)
        return detector, embedder

    return build


def _parse_list(text: str) -> List[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="engine/config/demo-4060.yaml")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", help="berkas video berisi orang (potongan dibuat dengan D-FINE)")
    source.add_argument("--potongan", help="folder potongan hasil --simpan-potongan (tanpa D-FINE)")
    parser.add_argument("--frames", type=int, default=150, help="frame yang diambil dari video")
    parser.add_argument("--stride", type=int, default=10, help="ambil 1 dari tiap N frame")
    parser.add_argument("--maks-potongan", type=int, default=300)
    parser.add_argument("--simpan-potongan", default=None, help="simpan potongan untuk dipakai ulang")
    parser.add_argument("--varian", default="cuda,trt16", help=f"dipisah koma: {', '.join(PROVIDERS)}")
    parser.add_argument("--ukuran", default=None, help="ukuran input SCRFD, dipisah koma (default: config)")
    parser.add_argument("--model-detektor", default=None,
                        help="SCRFD untuk varian (mis. hasil tools/scrfd_dynamic); pembanding tetap model config")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    from ..config import load_config

    config = load_config(args.config)
    rec = config.recognition
    if not (rec.face_detector_model and rec.face_embedder_model):
        raise SystemExit("config ini tidak punya recognition.face_detector_model / face_embedder_model")
    providers = _parse_list(args.varian)
    unknown = [p for p in providers if p not in PROVIDERS]
    if unknown:
        raise SystemExit(f"varian tidak dikenal: {unknown}; pilih dari {PROVIDERS}")
    sizes = [int(s) for s in _parse_list(args.ukuran)] if args.ukuran else [rec.face_detector_input_size]
    variant_model = args.model_detektor or rec.face_detector_model

    if args.potongan:
        crops = load_crops(args.potongan, args.maks_potongan)
    else:
        crops = collect_crops(config, args.source, args.frames, max(1, args.stride), args.maks_potongan)
        if args.simpan_potongan:
            save_crops(crops, args.simpan_potongan)
    if not crops:
        raise SystemExit("tidak ada potongan kepala: video tanpa orang, atau orang lebih kecil dari min_face_px")

    reference = Variant("cuda", rec.face_detector_input_size, rec.face_detector_model)
    variants = [Variant(p, s, variant_model) for p in providers for s in sizes]
    report = run(crops, reference, variants, real_builder(rec), min_face_px=rec.min_face_px,
                 repeat=max(1, args.repeat))
    # JSON dulu: kalau print gagal karena encoding konsol, angkanya tetap tersimpan.
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(report)
        payload["verdict"] = {r.name: verdict(r, report.reference) for r in report.variants}
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(format_report(report))
    return 1 if any(r.error for r in report.variants) else 0


if __name__ == "__main__":
    sys.exit(main())
