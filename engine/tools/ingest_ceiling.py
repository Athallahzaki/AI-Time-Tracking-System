"""Cari plafon fps dari jalur ingest saja, tanpa GPU dan tanpa detector.

Uji 2 Okt 2026: mode `live_buffer: latest` mentok di 3,97 fps di keempat run
(FP32 dan FP16), sedangkan `none` 6,5-8 fps. FP16 tidak mengubah apa pun, jadi
GPU bukan pembatasnya. Hipotesis: decoder FFmpeg berthread (`AUTO` = frame
threading, satu thread per core) di thread pembaca berebut CPU/GIL dengan
pipeline, sehingga pipeline kebagian frame baru hanya ±4 kali per detik.

Alat ini membuktikan atau membantah hipotesis itu tanpa GPU: detector diganti
beban tiruan dengan durasi yang sama, lalu beberapa varian decoder dibandingkan
pada stream MediaMTX yang sama.

    python -m engine.tools.ingest_ceiling --uri rtsp://127.0.0.1:8554/cam01 --work-ms 110

Beban tiruan (`--work`):
- `sleep` : menunggu tanpa memegang GIL, seperti menunggu GPU selesai.
- `gil`   : loop Python yang memegang GIL, seperti pra/pasca-proses di Python.
- `torch` : resize OpenCV frame asli ke 640 + matmul torch di CPU. Memakai pool
            thread torch/OpenCV seperti detector sungguhan, jadi rebutan thread
            dengan decoder (dugaan plafon 4 fps) ikut terjadi. Butuh torch.

`--cpu-threads N` menerapkan batas thread yang sama dengan `core.cpu_threads`
di engine. Bandingkan `--work torch` tanpa dan dengan `--cpu-threads 2`.

Membaca hasil: `fps analisis` dibandingkan dengan `harapan` = min(target_fps,
1000 / (beban + konversi)). Jauh di bawah harapan = ingest yang menahan.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

VARIANTS: Dict[str, Dict[str, Any]] = {
    "latest-auto":    {"live_buffer": "latest", "decoder_thread_type": "AUTO", "decoder_threads": 0},
    "latest-slice":   {"live_buffer": "latest", "decoder_thread_type": "SLICE", "decoder_threads": 0},
    "latest-frame2":  {"live_buffer": "latest", "decoder_thread_type": "FRAME", "decoder_threads": 2},
    "latest-1thread": {"live_buffer": "latest", "decoder_thread_type": "SLICE", "decoder_threads": 1},
    "none-auto":      {"live_buffer": "none", "decoder_thread_type": "AUTO", "decoder_threads": 0},
    # Decode di GPU (NVDEC). Butuh PyAV >= 14 ber-CUDA; gagal = baris GAGAL, bukan crash.
    "latest-cuvid":   {"live_buffer": "latest", "decoder_thread_type": "AUTO", "decoder_threads": 0,
                       "hwaccel": "cuda"},
}
DEFAULT_VARIANTS = ["latest-auto", "latest-slice", "latest-frame2", "none-auto"]
WORK_KINDS = ("sleep", "gil", "torch")


@dataclass
class VariantResult:
    name: str
    seconds: float
    analysed: int = 0
    decoded: int = 0
    replaced: int = 0
    analysed_fps: float = 0.0
    decoded_fps: float = 0.0
    convert_ms: float = 0.0
    lag_median: Optional[float] = None
    lag_max: Optional[float] = None
    expected_fps: float = 0.0
    error: Optional[str] = None
    verdict: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)


class _TorchWork:
    """Beban CPU yang memakai pool thread torch dan OpenCV, seperti detector."""

    def __init__(self) -> None:
        import torch  # noqa: PLC0415 -- hanya untuk --work torch

        self._torch = torch
        self._a = torch.randn(384, 384)
        self._b = torch.randn(384, 384)
        try:
            import cv2  # noqa: PLC0415

            self._cv2 = cv2
        except ImportError:
            self._cv2 = None

    def __call__(self, frame: Any, ms: float) -> None:
        end = time.perf_counter() + ms / 1000.0
        if self._cv2 is not None and frame is not None:
            self._cv2.resize(frame.image, (640, 640), interpolation=self._cv2.INTER_AREA)
        while time.perf_counter() < end:
            self._torch.mm(self._a, self._b)


def _work(kind: str, ms: float, frame: Any = None, torch_work: Any = None) -> None:
    if ms <= 0:
        return
    if kind == "sleep":
        time.sleep(ms / 1000.0)
        return
    if kind == "torch":
        torch_work(frame, ms)
        return
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:      # memegang GIL, sengaja
        pass


def run_variant(
    name: str,
    make_source: Callable[[Dict[str, Any]], Any],
    seconds: float,
    work_ms: float,
    work_kind: str = "sleep",
    target_fps: float = 12.0,
) -> VariantResult:
    settings = dict(VARIANTS[name])
    result = VariantResult(name=name, seconds=seconds, settings=settings)
    torch_work = None
    if work_kind == "torch":
        try:
            torch_work = _TorchWork()
        except Exception as error:  # noqa: BLE001
            result.error = f"--work torch butuh torch: {error}"
            result.verdict = "GAGAL"
            return result
    try:
        source = make_source(settings)
        source.start()
    except Exception as error:  # noqa: BLE001
        result.error = f"gagal membuka: {error}"
        result.verdict = "GAGAL"
        return result

    period = 1.0 / target_fps if target_fps > 0 else 0.0
    next_due: Optional[float] = None
    convert: List[float] = []
    lags: List[float] = []
    decoded_start = getattr(source, "_frame_count", 0)
    t0 = time.perf_counter()
    try:
        while time.perf_counter() - t0 < seconds:
            frame = source.read()
            if frame is None:
                break
            pts = frame.metadata.pts
            # Aturan decimation yang sama dengan VisionEngine._read_due_frame.
            if period and pts is not None:
                if next_due is not None and pts < next_due - 0.25 * period:
                    continue
                base = next_due if next_due is not None else pts
                next_due = max(base + period, pts + 0.5 * period)
            latest = getattr(source, "latest_decoded", None)
            if latest is not None and pts is not None and latest[0] == frame.metadata.stream_epoch:
                lags.append(max(0.0, latest[1] - pts))
            c0 = time.perf_counter()
            _ = frame.image                       # konversi BGR, seperti detector
            convert.append(time.perf_counter() - c0)
            _work(work_kind, work_ms, frame, torch_work)
            result.analysed += 1
    finally:
        elapsed = max(1e-6, time.perf_counter() - t0)
        result.decoded = int(getattr(source, "_frame_count", 0) - decoded_start)
        result.replaced = int(getattr(source, "frames_replaced", 0) or 0)
        try:
            source.stop()
        except Exception:  # noqa: BLE001
            pass

    result.seconds = round(elapsed, 2)
    result.analysed_fps = round(result.analysed / elapsed, 2)
    result.decoded_fps = round(result.decoded / elapsed, 2)
    result.convert_ms = round(1000.0 * statistics.fmean(convert), 1) if convert else 0.0
    if lags:
        result.lag_median = round(statistics.median(lags), 3)
        result.lag_max = round(max(lags), 3)
    per_frame = (work_ms + result.convert_ms) / 1000.0
    result.expected_fps = round(min(target_fps or 1e9, 1.0 / per_frame if per_frame > 0 else 1e9), 2)
    result.verdict = verdict(result)
    return result


def verdict(result: VariantResult) -> str:
    if result.error:
        return "GAGAL"
    if result.analysed == 0:
        return "TIDAK ADA FRAME"
    ratio = result.analysed_fps / result.expected_fps if result.expected_fps else 0.0
    if ratio >= 0.8:
        return "OK: ingest tidak menahan"
    if ratio >= 0.5:
        return "TERTAHAN SEBAGIAN"
    return "INGEST MENAHAN PIPELINE"


def format_table(results: List[VariantResult]) -> str:
    head = f"{'varian':<15} {'fps analisis':>12} {'harapan':>8} {'decode fps':>10} {'dilewati':>8} " \
           f"{'konversi ms':>11} {'lag med/max':>12}  kesimpulan"
    lines = [head, "-" * len(head)]
    for r in results:
        lag = "-" if r.lag_median is None else f"{r.lag_median:.2f}/{r.lag_max:.2f}"
        lines.append(f"{r.name:<15} {r.analysed_fps:>12.2f} {r.expected_fps:>8.2f} {r.decoded_fps:>10.2f} "
                     f"{r.replaced:>8d} {r.convert_ms:>11.1f} {lag:>12}  {r.verdict}"
                     + (f" ({r.error})" if r.error else ""))
    return "\n".join(lines)


def _pyav_factory(uri: str, timeout: float) -> Callable[[Dict[str, Any]], Any]:
    def make(settings: Dict[str, Any]) -> Any:
        from ..ingest.pyav_source import PyAVSource

        return PyAVSource(uri=uri, source_id="ceiling", rtsp_transport="tcp", timeout_seconds=timeout,
                          reconnect_attempts=3, **settings)
    return make


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uri", default="rtsp://127.0.0.1:8554/cam01")
    parser.add_argument("--seconds", type=float, default=30.0, help="per varian (default 30)")
    parser.add_argument("--work-ms", type=float, default=110.0,
                        help="durasi detector tiruan per frame (bench lama: ±110 ms)")
    parser.add_argument("--work", choices=list(WORK_KINDS), default="sleep")
    parser.add_argument("--cpu-threads", type=int, default=0,
                        help="batas thread torch/OpenCV/BLAS, sama dengan core.cpu_threads (0 = tidak dibatasi)")
    parser.add_argument("--target-fps", type=float, default=12.0)
    parser.add_argument("--variants", default=",".join(DEFAULT_VARIANTS),
                        help=f"pilihan: {', '.join(VARIANTS)}")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    names = [n.strip() for n in args.variants.split(",") if n.strip()]
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        parser.error(f"varian tidak dikenal: {unknown}")

    if args.cpu_threads > 0:
        from ..runtime.threads import apply_cpu_threads

        print(f"batas thread: {apply_cpu_threads(args.cpu_threads)}")
    make = _pyav_factory(args.uri, timeout=8.0)
    results = []
    for name in names:
        print(f"... {name} ({args.seconds:.0f} dtk, beban {args.work} {args.work_ms:.0f} ms)", flush=True)
        results.append(run_variant(name, make, args.seconds, args.work_ms, args.work, args.target_fps))
    print()
    print(format_table(results))
    print()
    print("Bila latest-auto jauh di bawah harapan tapi latest-slice / latest-frame2 mendekati,\n"
          "penyebab plafon adalah threading decoder: pakai varian itu di config ingest.\n"
          "Bila semua varian latest rendah dan none-auto tinggi, penyebabnya di thread pembaca/GIL.\n"
          "Ulangi dengan --work gil untuk melihat pengaruh kerja Python yang memegang GIL.\n"
          "Bila --work torch jauh lebih rendah dari --work sleep di varian latest, dan\n"
          "--cpu-threads 2 memulihkannya, penyebabnya rebutan thread: set core.cpu_threads.\n"
          "Bila latest-cuvid paling tinggi, decode CPU adalah pembatasnya: set ingest.hwaccel: cuda.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump([asdict(r) for r in results], handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
