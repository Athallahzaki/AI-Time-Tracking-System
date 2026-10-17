"""Periksa env Python engine di mesin GPU sebelum menjalankan apa pun.

    python scripts/check_gpu_env.py
    python scripts/check_gpu_env.py --json bench-out/env.json
    python scripts/check_gpu_env.py --tensorrt      # env TensorRT (scripts/setup-env-trt.ps1)

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
# Versi TensorRT yang dipakai CI onnxruntime untuk membangun onnxruntime-gpu (CUDA 12).
# Sumber: dokumen TensorRT EP (1.20) dan tools/ci_build/github/azure-pipelines/templates/
# common-variables.yml di tiap tag rilis (1.21-1.26), dibaca 16 Okt 2026.
TRT_FOR_ORT = {
    (1, 20): "10.4", (1, 21): "10.8", (1, 22): "10.9", (1, 23): "10.9",
    (1, 24): "10.14", (1, 25): "10.14", (1, 26): "10.14",
}
TRT_PACKAGES = ("tensorrt-cu12-libs", "tensorrt-libs", "tensorrt-cu12", "tensorrt")
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


def expected_tensorrt(ort_version: Optional[str]) -> Optional[str]:
    return TRT_FOR_ORT.get(version_tuple(ort_version)[:2]) if ort_version else None


def check_tensorrt_version(ort_version: Optional[str], trt_version: Optional[str]) -> Check:
    """Pasangan onnxruntime-gpu + pustaka TensorRT (paket ea-r11)."""
    expected = expected_tensorrt(ort_version)
    hint = f"tensorrt-cu12-libs=={expected}.*" if expected else "tensorrt-cu12-libs>=10,<11"
    if not trt_version:
        return Check("GAGAL", "tensorrt", f"pustaka TensorRT tidak terpasang. scripts/setup-env-trt.ps1, "
                     f"atau pip install \"{hint}\"")
    if version_tuple(trt_version)[0] != 10:
        return Check("GAGAL", "tensorrt", f"TensorRT {trt_version}; onnxruntime-gpu {ort_version} butuh TensorRT 10")
    if expected is None:
        return Check("PERINGATAN", "tensorrt", f"TensorRT {trt_version}; pasangan untuk onnxruntime {ort_version} "
                     "tidak tercatat di TRT_FOR_ORT. Penentunya sesi uji di bawah")
    if version_tuple(trt_version)[:2] != version_tuple(expected)[:2]:
        return Check("PERINGATAN", "tensorrt", f"TensorRT {trt_version}, sedangkan onnxruntime {ort_version} "
                     f"dibangun dengan {expected}. Sesama 10.x sering jalan tapi tidak dijamin; lebih aman "
                     f"pip install \"{hint}\"")
    return Check("OK", "tensorrt", f"TensorRT {trt_version} cocok dengan onnxruntime-gpu {ort_version} ({expected})")


def collect_tensorrt(ort: Any, ort_version: Optional[str]) -> List[Check]:
    """Versi + sesi SCRFD sungguhan lewat jalur engine (face_onnx.ScrfdDetector).

    Sesi ini juga mengisi cache engine SCRFD 640 di engine/data/trt-cache."""
    trt_version = next((v for v in (_dist_version(n) for n in TRT_PACKAGES) if v), None)
    checks = [check_tensorrt_version(ort_version, trt_version)]
    if ort is None:
        return checks
    if "TensorrtExecutionProvider" not in ort.get_available_providers():
        checks.append(Check("GAGAL", "tensorrt-ep", "build onnxruntime ini tidak membawa TensorrtExecutionProvider"))
        return checks
    sys.path.insert(0, str(ROOT))
    from engine.identity import face_onnx  # noqa: WPS433 -- hanya untuk --tensorrt

    folder = face_onnx.find_tensorrt_libs()
    checks.append(Check("OK" if folder else "PERINGATAN", "tensorrt-dll",
                        str(folder) if folder else "tensorrt_libs tidak ditemukan; nvinfer_10.dll harus ada di PATH"))
    face_model = find_face_model()
    if face_model is None:
        checks.append(Check("PERINGATAN", "tensorrt-sesi", "scrfd_10g_bnkps.onnx tidak ditemukan: sesi TensorRT tidak diuji"))
        return checks
    import time

    providers = face_onnx.provider_list(None, None, face_onnx.tensorrt_options(str(ROOT / "engine" / "data" / "trt-cache")))
    started = time.perf_counter()
    try:
        detector = face_onnx.ScrfdDetector(str(face_model), providers, input_size=640)
        import numpy as np

        detector.detect(np.zeros((200, 160, 3), dtype=np.uint8))
        checks.append(Check("OK", "tensorrt-sesi", f"{face_model.name} jalan di TensorRT FP16 "
                            f"({time.perf_counter() - started:.0f} dtk termasuk build/baca cache)"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("GAGAL", "tensorrt-sesi", f"{face_model.name}: {exc}"))
    return checks


NVRTC_POLA_WINDOWS = "nvrtc64_12*.dll"
NVRTC_POLA_LINUX = "libnvrtc.so.12*"


def nvrtc_candidate_dirs(path_env: str, torch_dir: Optional[Path], site_dirs: List[Path],
                         cuda_path: Optional[str]) -> Tuple[List[Path], List[Path]]:
    """(folder di PATH, folder lain yang sering memuat NVRTC: torch/lib, nvidia/cuda_nvrtc, CUDA_PATH)."""
    import os
    on_path = [Path(p) for p in path_env.split(os.pathsep) if p]
    others: List[Path] = []
    if torch_dir is not None:
        others.append(torch_dir / "lib")
    for site in site_dirs:
        others += [site / "nvidia" / "cuda_nvrtc" / "bin", site / "nvidia" / "cuda_nvrtc" / "lib"]
    if cuda_path:
        others.append(Path(cuda_path) / "bin")
    return on_path, others


def find_nvrtc(dirs: List[Path], pattern: str) -> Optional[Path]:
    for folder in dirs:
        try:
            hits = sorted(folder.glob(pattern))
        except OSError:
            continue
        if hits:
            return hits[0]
    return None


def check_nvrtc(on_path: Optional[Path], elsewhere: Optional[Path]) -> Check:
    """NVRTC (kompiler runtime CUDA) dicari cuDNN 9 untuk sebagian algoritma konvolusi.

    Uji 17 Okt (4060): tanpa NVRTC di PATH, setiap panggilan OSNet di onnxruntime menulis
    puluhan "Could not locate nvrtc64_120_0.dll". Bukan GAGAL: dengan NVRTC pun OSNet di
    onnxruntime tetap lambat (lihat CHANGELOG ea-r14), dan model lain jalan tanpanya.
    """
    if on_path is not None:
        return Check("OK", "nvrtc", f"{on_path}")
    if elsewhere is not None:
        return Check("PERINGATAN", "nvrtc", f"ada di {elsewhere.parent} tetapi TIDAK di PATH; cuDNN tidak "
                     "menemukannya. Tambahkan folder itu ke PATH sebelum menjalankan engine.")
    return Check("PERINGATAN", "nvrtc", "nvrtc64_12*.dll tidak ditemukan. cuDNN akan menulis "
                 "'Could not locate nvrtc...' berulang. pip install nvidia-cuda-nvrtc-cu12, lalu "
                 "tambahkan folder bin-nya ke PATH.")


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

def collect(tensorrt: bool = False) -> List[Check]:
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

    if tensorrt:
        checks.extend(collect_tensorrt(ort, getattr(ort, "__version__", None)))

    import os
    import site
    pattern = NVRTC_POLA_WINDOWS if os.name == "nt" else NVRTC_POLA_LINUX
    torch_dir = Path(torch.__file__).parent if torch is not None and getattr(torch, "__file__", None) else None
    try:
        site_dirs = [Path(p) for p in site.getsitepackages()]
    except Exception:  # noqa: BLE001
        site_dirs = []
    on_path_dirs, other_dirs = nvrtc_candidate_dirs(os.environ.get("PATH", ""), torch_dir, site_dirs,
                                                    os.environ.get("CUDA_PATH"))
    checks.append(check_nvrtc(find_nvrtc(on_path_dirs, pattern), find_nvrtc(other_dirs, pattern)))

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
    parser.add_argument("--tensorrt", action="store_true",
                        help="periksa juga TensorRT EP (env vision-engine-trt, paket ea-r11); "
                             "pertama kali bisa +-1 menit karena engine SCRFD dibangun")
    args = parser.parse_args(argv)
    checks = collect(tensorrt=args.tensorrt)
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
