"""Ke mana 84 ms per gambar D-FINE M di RTX 4060 pergi?

Uji 3 Okt (batch_check di RTX 4060): 84 ms/gambar, FP16 dan cudnn.benchmark
tidak mengubah apa pun, batch 5 hanya 1,10x lebih cepat. Itu sama dengan GTX
1060 (78-104 ms), padahal 4060 berkali lipat lebih kuat. Waktu yang tidak ikut
turun saat GPU-nya diganti, tidak ikut turun saat FP16, dan tidak terbagi saat
di-batch, hampir pasti BUKAN waktu GPU. Alat ini memisahkannya:

1. `forward GPU murni`: modul torch di dalam LibreYOLO dipanggil langsung
   dengan tensor 1x3xNxN yang sudah di GPU (FP32 dan FP16), dengan
   `cuda.synchronize`. Ini batas bawah yang bisa dicapai GPU ini.
2. `panggilan LibreYOLO penuh`: sama seperti engine (pre_resize, pra-proses,
   forward, pasca-proses), juga dengan synchronize.
3. `waktu CPU proses` per gambar selama (2). Hanya informasi: cuda.synchronize
   bisa menunggu sambil berputar (spin), jadi angka ini tidak membuktikan apa pun
   sendirian. Pembanding yang menentukan adalah (1) lawan (2).
4. Clock dan P-state GPU (nvidia-smi) selama pengukuran: GPU yang tidak naik
   clock (power state, mode daya laptop) juga membuat forward lambat.

    python -m engine.tools.detector_profile --source C:\\video\\uji-siap.mp4
    python -m engine.tools.detector_profile --source uji.mp4 --torch-profile bench-out/profil.txt

Butuh GPU, torch dan LibreYOLO. Tidak membuka kamera, tidak menyentuh backend.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

MODULE_ATTRS = ("model", "net", "_model", "module", "detector", "backbone_model")
OVERHEAD_SHARE = 0.5      # > 50% waktu di luar forward = penghambatnya di CPU
LOW_CLOCK_SHARE = 0.6     # clock SM median < 60% clock maks = GPU tidak naik clock


@dataclass
class GpuSample:
    pstate: str
    sm_mhz: float
    sm_max_mhz: float
    power_w: float
    power_limit_w: float
    temp_c: float
    util_pct: float


@dataclass
class Profile:
    device: str = ""
    gpu_name: str = ""
    param_device: str = ""
    param_dtype: str = ""
    module_path: str = ""
    image_size: int = 0
    half_config: bool = False
    prepare_ms: float = 0.0
    call_ms: float = 0.0
    call_cpu_ms: float = 0.0
    forward_fp32_ms: Optional[float] = None
    forward_fp16_ms: Optional[float] = None
    forward_error: Optional[str] = None
    gpu: Dict[str, Any] = field(default_factory=dict)

    @property
    def forward_best_ms(self) -> Optional[float]:
        values = [v for v in (self.forward_fp32_ms, self.forward_fp16_ms) if v]
        return min(values) if values else None

    def verdicts(self) -> List[str]:
        out: List[str] = []
        if self.param_device and "cuda" not in self.param_device:
            out.append(f"MODEL DI {self.param_device.upper()}, BUKAN GPU. Itu sebabnya lambat; cek detector.device "
                       "dan torch.cuda.is_available().")
            return out
        forward = self.forward_best_ms
        total = self.call_ms + self.prepare_ms
        if forward is None:
            out.append("forward murni tidak terukur (" + (self.forward_error or "modul torch tidak ditemukan")
                       + "); hanya waktu total yang ada.")
        else:
            outside = max(0.0, total - forward)
            share = outside / total if total else 0.0
            if share > OVERHEAD_SHARE:
                out.append(f"PENGHAMBAT DI CPU: {outside:.0f} ms dari {total:.0f} ms ({100 * share:.0f}%) terjadi di "
                           f"luar forward GPU ({forward:.1f} ms). Itu pra/pasca-proses LibreYOLO di Python/CPU. "
                           "FP16, cudnn.benchmark dan batching tidak akan menolong; TensorRT juga tidak, selama "
                           "pra/pasca-proses itu tetap di CPU.")
            else:
                out.append(f"PENGHAMBAT DI GPU: forward {forward:.1f} ms dari {total:.0f} ms total.")
            if self.forward_fp32_ms and self.forward_fp16_ms:
                ratio = self.forward_fp32_ms / self.forward_fp16_ms
                out.append(f"FP16 vs FP32 di forward murni: {ratio:.2f}x "
                           + ("(FP16 layak)" if ratio > 1.15 else "(FP16 tidak berarti di sini)"))
        sm = self.gpu.get("sm_mhz_median")
        sm_max = self.gpu.get("sm_max_mhz")
        if sm and sm_max and sm < LOW_CLOCK_SHARE * sm_max:
            out.append(f"GPU TIDAK NAIK CLOCK: SM median {sm:.0f} MHz dari maks {sm_max:.0f} MHz "
                       f"(P-state {self.gpu.get('pstates')}). Cek mode daya Windows/Razer, charger, "
                       "NVIDIA Control Panel 'Prefer maximum performance'.")
        return out


# -- modul torch di dalam LibreYOLO ------------------------------------------

def find_torch_module(root: Any, module_type: type, depth: int = 3) -> Tuple[str, Any]:
    """Cari nn.Module pertama di dalam pembungkus LibreYOLO. ("", None) bila tidak ada."""
    import types

    if isinstance(root, module_type):
        return "", root
    skip = (types.FunctionType, types.MethodType, types.BuiltinFunctionType, types.ModuleType, type)
    frontier: List[Tuple[str, Any]] = [("", root)]
    seen = {id(root)}
    for _ in range(depth):
        nxt: List[Tuple[str, Any]] = []
        for path, obj in frontier:
            own = sorted(vars(obj)) if hasattr(obj, "__dict__") else []
            for name in list(MODULE_ATTRS) + [n for n in own if n not in MODULE_ATTRS]:
                try:
                    child = getattr(obj, name, None)
                except Exception:  # noqa: BLE001 -- properti yang melempar dilewati
                    continue
                if child is None or id(child) in seen or isinstance(child, skip):
                    continue
                seen.add(id(child))
                full = f"{path}.{name}" if path else name
                if isinstance(child, module_type):
                    return full, child
                if hasattr(child, "__dict__"):
                    nxt.append((full, child))
        frontier = nxt
    return "", None


# -- nvidia-smi ---------------------------------------------------------------

SMI_QUERY = "pstate,clocks.sm,clocks.max.sm,power.draw,power.limit,temperature.gpu,utilization.gpu"


def parse_smi_line(line: str) -> Optional[GpuSample]:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 7:
        return None

    def num(text: str) -> float:
        try:
            return float(text.split()[0])
        except (ValueError, IndexError):
            return 0.0

    return GpuSample(parts[0], num(parts[1]), num(parts[2]), num(parts[3]), num(parts[4]),
                     num(parts[5]), num(parts[6]))


def summarize_samples(samples: Sequence[GpuSample]) -> Dict[str, Any]:
    if not samples:
        return {}
    return {
        "samples": len(samples),
        "pstates": sorted({s.pstate for s in samples}),
        "sm_mhz_median": statistics.median(s.sm_mhz for s in samples),
        "sm_mhz_min": min(s.sm_mhz for s in samples),
        "sm_max_mhz": max(s.sm_max_mhz for s in samples),
        "power_w_median": statistics.median(s.power_w for s in samples),
        "power_limit_w": max(s.power_limit_w for s in samples),
        "temp_c_max": max(s.temp_c for s in samples),
        "util_pct_median": statistics.median(s.util_pct for s in samples),
    }


class GpuSampler:
    def __init__(self, interval: float = 0.5, runner: Optional[Callable[[], str]] = None) -> None:
        self._interval = interval
        self._runner = runner or self._smi
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.samples: List[GpuSample] = []

    @staticmethod
    def _smi() -> str:
        return subprocess.run(["nvidia-smi", f"--query-gpu={SMI_QUERY}", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=5).stdout

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                sample = parse_smi_line(self._runner().strip().splitlines()[0])
                if sample:
                    self.samples.append(sample)
            except Exception:  # noqa: BLE001 -- telemetri opsional
                return
            self._stop.wait(self._interval)

    def __enter__(self) -> "GpuSampler":
        if self._runner is self._smi and shutil.which("nvidia-smi") is None:
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=6)


# -- pengukuran ---------------------------------------------------------------

def _sync(torch: Any) -> None:
    if torch is not None and torch.cuda.is_available():
        torch.cuda.synchronize()


def time_calls(detector: Any, images: Sequence[Any], torch: Any, repeat: int = 2) -> Tuple[float, float, float]:
    """(prepare ms, panggilan penuh ms, waktu CPU proses ms) per gambar, ambil putaran tercepat."""
    best = None
    for _ in range(max(1, repeat)):
        prep = call = cpu = 0.0
        for image in images:
            t0 = time.perf_counter()
            model_input, colour, scale = detector._prepare(image)
            t1 = time.perf_counter()
            c0 = time.process_time()
            _sync(torch)
            t2 = time.perf_counter()
            with detector._inference():
                detector._model(model_input, **detector._kwargs(colour, None))
            _sync(torch)
            t3 = time.perf_counter()
            cpu += time.process_time() - c0
            prep += t1 - t0
            call += t3 - t2
        n = len(images)
        row = (1000 * prep / n, 1000 * call / n, 1000 * cpu / n)
        if best is None or row[1] < best[1]:
            best = row
    return best  # type: ignore[return-value]


def time_forward(module: Any, torch: Any, size: int, device: Any, half: bool, iters: int = 30) -> float:
    x = torch.zeros((1, 3, size, size), device=device)
    autocast = torch.autocast(device_type="cuda", dtype=torch.float16) if half else _Null()
    with torch.no_grad(), autocast:
        for _ in range(5):
            module(x)
        _sync(torch)
        start = time.perf_counter()
        for _ in range(iters):
            module(x)
        _sync(torch)
    return 1000 * (time.perf_counter() - start) / iters


class _Null:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> None:
        return None


def format_profile(p: Profile) -> str:
    def ms(v: Optional[float]) -> str:
        return "-" if v is None else f"{v:.1f} ms"

    lines = [
        f"GPU {p.gpu_name or '?'}; detector.device {p.device}; parameter model di {p.param_device or '?'} "
        f"({p.param_dtype or '?'}); modul '{p.module_path or '?'}'; imgsz {p.image_size}; half config {p.half_config}",
        f"  pre_resize (OpenCV)        {ms(p.prepare_ms)}",
        f"  panggilan LibreYOLO penuh  {ms(p.call_ms)}   (waktu CPU proses {ms(p.call_cpu_ms)}, info saja)",
        f"  forward GPU murni FP32     {ms(p.forward_fp32_ms)}",
        f"  forward GPU murni FP16     {ms(p.forward_fp16_ms)}",
    ]
    if p.gpu:
        lines.append(f"  nvidia-smi: P-state {p.gpu.get('pstates')}, SM median {p.gpu.get('sm_mhz_median'):.0f} / "
                     f"maks {p.gpu.get('sm_max_mhz'):.0f} MHz, daya {p.gpu.get('power_w_median'):.0f} / "
                     f"{p.gpu.get('power_limit_w'):.0f} W, suhu maks {p.gpu.get('temp_c_max'):.0f} C, "
                     f"util median {p.gpu.get('util_pct_median'):.0f}%")
    else:
        lines.append("  nvidia-smi tidak tersedia: clock GPU tidak terukur")
    for verdict in p.verdicts():
        lines.append("KESIMPULAN: " + verdict)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="engine/config/dfine-m.yaml")
    parser.add_argument("--source", required=True, help="berkas video berisi orang")
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--torch-profile", default=None,
                        help="tulis tabel torch.profiler (operasi terberat) ke berkas ini")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    import torch

    from .. import factory
    from ..config import load_config
    from .batch_check import _read_frames

    config = load_config(args.config)
    config = dataclasses.replace(config, source_type="video_file")
    images = _read_frames(args.source, args.frames, max(1, args.stride))
    detector = factory.build_detector(config)
    detector.warmup()

    profile = Profile(device=str(config.detector.device), image_size=int(config.detector.image_size),
                      half_config=bool(config.detector.half))
    if torch.cuda.is_available():
        profile.gpu_name = torch.cuda.get_device_name(0)
    path, module = find_torch_module(detector._model, torch.nn.Module)
    profile.module_path = path
    if module is not None:
        try:
            param = next(module.parameters())
            profile.param_device, profile.param_dtype = str(param.device), str(param.dtype)
        except StopIteration:
            pass

    with GpuSampler() as sampler:
        profile.prepare_ms, profile.call_ms, profile.call_cpu_ms = time_calls(detector, images, torch)
        if module is not None and profile.param_device.startswith("cuda"):
            was_training = getattr(module, "training", False)
            module.eval()
            try:
                profile.forward_fp32_ms = time_forward(module, torch, profile.image_size, param.device, half=False)
                profile.forward_fp16_ms = time_forward(module, torch, profile.image_size, param.device, half=True)
            except Exception as exc:  # noqa: BLE001 -- forward langsung bisa butuh argumen lain
                profile.forward_error = f"{type(exc).__name__}: {exc}"
            finally:
                module.train(was_training)
    profile.gpu = summarize_samples(sampler.samples)

    print(format_profile(profile))

    if args.torch_profile:
        from torch.profiler import ProfilerActivity, profile as torch_profile

        activities = [ProfilerActivity.CPU] + ([ProfilerActivity.CUDA] if torch.cuda.is_available() else [])
        with torch_profile(activities=activities) as prof:
            for image in images[:10]:
                model_input, colour, _ = detector._prepare(image)
                with detector._inference():
                    detector._model(model_input, **detector._kwargs(colour, None))
            _sync(torch)
        table = prof.key_averages().table(sort_by="self_cpu_time_total", row_limit=30)
        with open(args.torch_profile, "w", encoding="utf-8") as handle:
            handle.write(table)
        print(f"tabel torch.profiler (10 gambar, urut waktu CPU) ditulis ke {args.torch_profile}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({**asdict(profile), "verdicts": profile.verdicts()}, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
