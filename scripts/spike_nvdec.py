"""Spike NVDEC (dokumen 04 §14.5): bisakah satu stream RTSP di-decode di GPU
dengan frame tetap di GPU, di mesin engine (Windows, RTX 4060)?

Membandingkan tiga jalur pada stream yang sama, masing-masing selama --seconds:

  pyav      PyAV decode di CPU (jalur sekarang)
  pyav-cuda PyAV dengan hwaccel cuda (decode di GPU, frame diunduh ke RAM)
            -- hanya jalan bila build FFmpeg di PyAV mendukung CUDA
  nvc       PyNvVideoCodec: CreateDemuxer + CreateDecoder(usedevicememory=True),
            frame tetap di GPU; bila torch ada, dicek torch.from_dlpack (nol-salin)

Yang dicatat per jalur: frame/detik, CPU proses (% satu core), latensi decode
per frame (median, p95), VRAM terpakai (bila torch tersedia), error.

Contoh (dari root repo, MediaMTX sudah jalan):

    python scripts/spike_nvdec.py --url rtsp://127.0.0.1:8554/cam01 --seconds 60
    python scripts/spike_nvdec.py --url rtsp://127.0.0.1:8554/cam01 --only nvc

Catatan jujur: API PyNvVideoCodec di skrip ini mengikuti panduan NVIDIA
("Using PyNvVideoCodec APIs"): CreateDemuxer(filename=...), CreateDecoder(gpuid,
codec, usedevicememory), Decode(packet), Flush(). Dukungan URL RTSP langsung
pada CreateDemuxer TIDAK tercantum di panduan itu -- justru itu salah satu yang
diuji spike ini. Bila gagal, catat errornya; alternatifnya demux lewat PyAV dan
umpan paket ke decoder (CreateDemuxer dengan callback), dikerjakan bila perlu.

Vonis yang ditulis ke docs/CHANGELOG.md / dokumen 14:
  LANJUT bila nvc stabil 60 dtk, CPU jauh di bawah pyav, dan from_dlpack jalan.
  TUNDA  bila nvc tidak bisa dipasang/dimuat di Windows atau tidak stabil.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Any, Callable, Dict, List, Optional


def _cpu_percent(cpu0: float, wall0: float) -> float:
    wall = max(1e-9, time.perf_counter() - wall0)
    return 100.0 * (time.process_time() - cpu0) / wall


def _summary(name: str, frames: int, lat: List[float], cpu0: float, wall0: float,
             error: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    wall = time.perf_counter() - wall0
    out: Dict[str, Any] = {
        "jalur": name,
        "frame": frames,
        "fps": round(frames / wall, 2) if wall > 0 else 0.0,
        # Tanpa frame, angka CPU hanya mengukur impor pustaka: tidak berarti.
        "cpu_persen_satu_core": round(_cpu_percent(cpu0, wall0), 1) if frames else None,
        "latensi_ms_median": round(statistics.median(lat) * 1000, 2) if lat else None,
        "latensi_ms_p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))] * 1000, 2) if lat else None,
        "error": error,
    }
    if extra:
        out.update(extra)
    return out


def _vram() -> Optional[float]:
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.memory_allocated() / 2**20, 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def run_pyav(url: str, seconds: float, hwaccel: bool) -> Dict[str, Any]:
    name = "pyav-cuda" if hwaccel else "pyav"
    cpu0, wall0 = time.process_time(), time.perf_counter()
    frames, lat = 0, []
    try:
        import av
        options = {"rtsp_transport": "tcp"}
        kwargs: Dict[str, Any] = {"options": options, "timeout": 8.0}
        if hwaccel:
            from av.codec.hwaccel import HWAccel  # PyAV >= 14
            kwargs["hwaccel"] = HWAccel(device_type="cuda", allow_software_fallback=False)
        container = av.open(url, **kwargs)
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        end = time.perf_counter() + seconds
        t = time.perf_counter()
        for frame in container.decode(stream):
            now = time.perf_counter()
            lat.append(now - t)
            frames += 1
            # Paksa piksel benar-benar tersedia di RAM, seperti yang dibutuhkan pipeline CPU.
            frame.to_ndarray(format="bgr24")
            if now >= end:
                break
            t = time.perf_counter()
        container.close()
    except Exception as error:  # noqa: BLE001
        return _summary(name, frames, lat, cpu0, wall0, error=repr(error))
    return _summary(name, frames, lat, cpu0, wall0)


def run_nvc(url: str, seconds: float, gpu: int) -> Dict[str, Any]:
    cpu0, wall0 = time.process_time(), time.perf_counter()
    frames, lat = 0, []
    extra: Dict[str, Any] = {"dlpack": "tidak dicoba"}
    try:
        import PyNvVideoCodec as nvc
    except Exception as error:  # noqa: BLE001
        return _summary("nvc", 0, [], cpu0, wall0, error=f"impor gagal: {error!r}")
    try:
        torch = None
        try:
            import torch as _torch
            torch = _torch if _torch.cuda.is_available() else None
        except Exception:  # noqa: BLE001
            torch = None
        demuxer = nvc.CreateDemuxer(filename=url)
        decoder = nvc.CreateDecoder(gpuid=gpu, codec=demuxer.GetNvCodecId(), usedevicememory=True)
        extra["resolusi"] = f"{demuxer.Width()}x{demuxer.Height()}"
        end = time.perf_counter() + seconds
        t = time.perf_counter()
        for packet in demuxer:
            for decoded in decoder.Decode(packet):
                now = time.perf_counter()
                lat.append(now - t)
                frames += 1
                if torch is not None and extra["dlpack"] == "tidak dicoba":
                    try:
                        tensor = torch.from_dlpack(decoded)
                        extra["dlpack"] = f"ok: {tuple(tensor.shape)} {tensor.dtype} di {tensor.device}"
                    except Exception as error:  # noqa: BLE001
                        extra["dlpack"] = f"gagal: {error!r}"
                t = time.perf_counter()
            if time.perf_counter() >= end:
                break
        extra["vram_mb_torch"] = _vram()
    except Exception as error:  # noqa: BLE001
        return _summary("nvc", frames, lat, cpu0, wall0, error=repr(error), extra=extra)
    return _summary("nvc", frames, lat, cpu0, wall0, extra=extra)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="rtsp://... atau path file")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--only", choices=("pyav", "pyav-cuda", "nvc"))
    parser.add_argument("--json", help="simpan hasil ke file JSON")
    args = parser.parse_args(argv)

    runners: Dict[str, Callable[[], Dict[str, Any]]] = {
        "pyav": lambda: run_pyav(args.url, args.seconds, hwaccel=False),
        "pyav-cuda": lambda: run_pyav(args.url, args.seconds, hwaccel=True),
        "nvc": lambda: run_nvc(args.url, args.seconds, args.gpu),
    }
    names = [args.only] if args.only else list(runners)
    results = []
    for name in names:
        print(f"... {name} ({args.seconds:.0f} dtk)", flush=True)
        results.append(runners[name]())

    cols = ["jalur", "frame", "fps", "cpu_persen_satu_core", "latensi_ms_median", "latensi_ms_p95", "error"]
    print()
    print("  ".join(f"{c:>22}" for c in cols))
    for row in results:
        print("  ".join(f"{str(row.get(c)):>22}" for c in cols))
    for row in results:
        rest = {k: v for k, v in row.items() if k not in cols}
        if rest:
            print(f"{row['jalur']}: {rest}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
