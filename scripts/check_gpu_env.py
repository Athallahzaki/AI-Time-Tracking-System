"""Periksa env Python engine di mesin GPU sebelum menjalankan apa pun.

    python scripts/check_gpu_env.py
    python scripts/check_gpu_env.py --json bench-out/env.json

Setiap baris OK / PERINGATAN / GAGAL. Exit 1 bila ada GAGAL. Yang diperiksa
adalah jebakan yang sudah pernah terjadi di proyek ini: torch CPU-only dari
PyPI, onnxruntime-gpu CUDA 13 di env CUDA 12 (jatuh diam-diam ke CPU),
LibreYOLO tanpa cuda_graph, GPU Pascal dengan build torch yang tidak membawa
kernelnya, dan paket yang mematok versi torch lain (xformers).
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
TORCH_EXPECTED = "2.14.1+cu126"
LIBREYOLO_MIN = (1, 6)
ORT_CUDA13_FROM = (1, 27)
DRIVER_MIN = 560
FACE_MODEL = ROOT / "models" / "scrfd_10g_bnkps.onnx"
# Tempat lain yang dipakai di mesin tim (laptop 1060: engine/models/recognition/).
FACE_MODEL_CANDIDATES = (
    FACE_MODEL,
    ROOT / "engine" / "models" / "recognition" / "scrfd_10g_bnkps.onnx",
    ROOT / "engine" / "models" / "scrfd_10g_bnkps.onnx",
)


def find_face_model(candidates=FACE_MODEL_CANDIDATES) -> Optional[Path]:
    return next((path for path in candidates if Path(path).is_file()), None)


@dataclass
class Check:
    status: str      # OK / PERINGATAN / GAGAL
    name: str
    detail: str


def version_tuple(text: str) -> Tuple[int, ...]:
    import re

    parts = []
    for piece in str(text).split("+")[0].split(".")[:3]:
        match = re.match(r"\d+", piece)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts)


def _module(name: str) -> Optional[Any]:
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001 -- tidak terpasang atau rusak: dilaporkan pemanggil
        return None


def _dist_version(name: str) -> Optional[str]:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # noqa: BLE001
        return None


# -- pemeriksaan satu per satu (murni, bisa dites tanpa GPU) -----------------

def check_python(info: Tuple[int, int]) -> Check:
    text = f"{info[0]}.{info[1]}"
    if info in ((3, 11), (3, 12)):
        return Check("OK", "python", text)
    if info >= (3, 10):
        return Check("PERINGATAN", "python", f"{text}; yang diuji 3.11/3.12 (onnxruntime-gpu terbaru butuh >= 3.11)")
    return Check("GAGAL", "python", f"{text}; LibreYOLO butuh >= 3.10")


def check_torch_build(version: Optional[str], cuda_available: bool) -> Check:
    if version is None:
        return Check("GAGAL", "torch", "tidak terpasang: pip install -r engine/requirements-torch-cu126.txt")
    if "+cu" not in version:
        return Check("GAGAL", "torch", f"{version} = build CPU-only (dari PyPI). Pasang ulang dari "
                     "engine/requirements-torch-cu126.txt")
    if not cuda_available:
        return Check("GAGAL", "torch", f"{version} tetapi torch.cuda.is_available() False: driver NVIDIA?")
    if version != TORCH_EXPECTED:
        return Check("PERINGATAN", "torch", f"{version}; yang dipatok {TORCH_EXPECTED}")
    return Check("OK", "torch", version)


def check_arch(capability: Tuple[int, int], arch_list: List[str], name: str) -> Check:
    sm = f"sm_{capability[0]}{capability[1]}"
    if sm in arch_list:
        return Check("OK", "gpu", f"{name} ({sm}); build membawa {sm}")
    # PTX untuk arsitektur lebih lama tidak bisa dijalankan di GPU yang lebih tua.
    same_major = [a for a in arch_list if a.startswith(f"sm_{capability[0]}")]
    if same_major:
        return Check("PERINGATAN", "gpu", f"{name} ({sm}) tidak ada persis di {arch_list}; "
                     f"biner {same_major} sekeluarga biasanya jalan")
    return Check("GAGAL", "gpu", f"{name} ({sm}) TIDAK didukung build torch ini ({arch_list}). "
                 "Untuk Pascal (GTX 10xx) wajib cu126.")


def check_libreyolo(version: Optional[str]) -> Check:
    if version is None:
        return Check("GAGAL", "libreyolo", "tidak terpasang")
    if version_tuple(version)[:2] < LIBREYOLO_MIN:
        return Check("PERINGATAN", "libreyolo", f"{version}: detector.cuda_graph dan batch sungguhan butuh >= 1.6")
    return Check("OK", "libreyolo", version)


def check_onnxruntime(version: Optional[str], providers: List[str], gpu_package: bool) -> Check:
    if version is None:
        return Check("PERINGATAN", "onnxruntime", "tidak terpasang (hanya perlu bila rekognisi wajah dinyalakan)")
    if not gpu_package:
        return Check("PERINGATAN", "onnxruntime", f"{version} paket CPU; rekognisi akan di CPU. "
                     "Pasang onnxruntime-gpu dari engine/requirements-face.txt dan hapus 'onnxruntime'.")
    if version_tuple(version)[:2] >= ORT_CUDA13_FROM:
        return Check("GAGAL", "onnxruntime", f"onnxruntime-gpu {version} = CUDA 13; env ini CUDA 12 (torch cu126). "
                     "Akan jatuh ke CPU (cublasLt64_13.dll). pip install \"onnxruntime-gpu[cuda,cudnn]<1.27\"")
    if "CUDAExecutionProvider" not in providers:
        return Check("GAGAL", "onnxruntime", f"{version} tanpa CUDAExecutionProvider ({providers})")
    return Check("OK", "onnxruntime", f"onnxruntime-gpu {version}")


def check_driver(text: Optional[str]) -> Check:
    if not text:
        return Check("PERINGATAN", "driver", "nvidia-smi tidak ditemukan")
    major = version_tuple(text)[0]
    if major < DRIVER_MIN:
        return Check("GAGAL", "driver", f"{text}; CUDA 12.6 butuh >= {DRIVER_MIN}")
    return Check("OK", "driver", text)


def check_conflicts(installed: Callable[[str], Optional[str]]) -> List[Check]:
    out = []
    xformers = installed("xformers")
    if xformers:
        out.append(Check("PERINGATAN", "xformers", f"{xformers} terpasang: tidak dipakai engine, mematok versi torch "
                         "tertentu dan memicu peringatan triton. pip uninstall -y xformers"))
    if installed("opencv-python") and installed("opencv-python-headless"):
        out.append(Check("PERINGATAN", "opencv", "opencv-python dan opencv-python-headless sama-sama terpasang; "
                         "cv2 bisa rusak. Sisakan satu (opencv-python)."))
    if installed("onnxruntime") and installed("onnxruntime-gpu"):
        out.append(Check("GAGAL", "onnxruntime", "'onnxruntime' (CPU) dan 'onnxruntime-gpu' sama-sama terpasang; "
                         "yang CPU bisa menang. pip uninstall -y onnxruntime"))
    return out


# -- pengumpulan dari mesin sungguhan ----------------------------------------

def collect() -> List[Check]:
    checks = [check_python(sys.version_info[:2])]

    torch = _module("torch")
    cuda = bool(torch and torch.cuda.is_available())
    checks.append(check_torch_build(getattr(torch, "__version__", None), cuda))
    if torch is not None and cuda:
        capability = torch.cuda.get_device_capability(0)
        checks.append(check_arch(capability, list(torch.cuda.get_arch_list()), torch.cuda.get_device_name(0)))
        try:
            x = torch.randn(256, 256, device="cuda")
            float((x @ x).sum())
            cudnn = torch.backends.cudnn.version()
            checks.append(Check("OK", "cuda", f"matmul di GPU jalan; cuDNN {cudnn}"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("GAGAL", "cuda", f"kernel gagal jalan: {exc}"))

    torchvision = _module("torchvision")
    if torchvision is None:
        checks.append(Check("GAGAL", "torchvision", "tidak terpasang"))
    else:
        checks.append(Check("OK", "torchvision", torchvision.__version__))

    checks.append(check_libreyolo(_dist_version("libreyolo")))

    ort = _module("onnxruntime")
    providers: List[str] = []
    if ort is not None:
        if hasattr(ort, "preload_dlls"):
            try:
                ort.preload_dlls()
            except Exception:  # noqa: BLE001
                pass
        providers = list(ort.get_available_providers())
    checks.append(check_onnxruntime(getattr(ort, "__version__", None), providers,
                                    _dist_version("onnxruntime-gpu") is not None))
    face_model = find_face_model()
    if ort is not None and "CUDAExecutionProvider" in providers and face_model is None:
        checks.append(Check("PERINGATAN", "onnx-sesi", "scrfd_10g_bnkps.onnx tidak ditemukan di models/ atau "
                            "engine/models/recognition/: sesi CUDA rekognisi tidak diuji"))
    elif ort is not None and "CUDAExecutionProvider" in providers:
        try:
            session = ort.InferenceSession(str(face_model), providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
            active = session.get_providers()
            status = "OK" if "CUDAExecutionProvider" in active else "GAGAL"
            checks.append(Check(status, "onnx-sesi", f"{face_model}: provider aktif {active}"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("GAGAL", "onnx-sesi", f"{face_model.name}: {exc}"))

    av = _module("av")
    if av is None:
        checks.append(Check("GAGAL", "av", "PyAV tidak terpasang"))
    else:
        hw = _module("av.codec.hwaccel") is not None
        checks.append(Check("OK", "av", f"{av.__version__}; HWAccel {'ada' if hw else 'tidak ada'} "
                            "(wheel PyPI tanpa CUDA: ingest.hwaccel tetap 'none')"))

    cv2 = _module("cv2")
    checks.append(Check("OK", "opencv", cv2.__version__) if cv2 else Check("GAGAL", "opencv", "cv2 tidak terpasang"))

    driver = None
    if shutil.which("nvidia-smi"):
        try:
            driver = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                    capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        except Exception:  # noqa: BLE001
            driver = None
    checks.append(check_driver(driver))
    checks.extend(check_conflicts(_dist_version))
    return checks


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    checks = collect()
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"{c.status:<10} {c.name:<{width}}  {c.detail}")
    failed = [c for c in checks if c.status == "GAGAL"]
    print("\nKESIMPULAN: " + ("env SIAP" if not failed else f"{len(failed)} GAGAL, perbaiki dulu"))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps([asdict(c) for c in checks], indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
