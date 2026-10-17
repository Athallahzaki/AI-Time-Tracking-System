"""scripts/check_gpu_env.py: jebakan instalasi yang sudah pernah terjadi."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("check_gpu_env", Path("scripts/check_gpu_env.py"))
env = importlib.util.module_from_spec(_spec)
sys.modules["check_gpu_env"] = env      # dataclass butuh modulnya terdaftar
_spec.loader.exec_module(env)


def test_torch_cpu_dari_pypi_gagal():
    assert env.check_torch_build("2.14.1", cuda_available=False).status == "GAGAL"
    assert env.check_torch_build("2.14.1+cu126", cuda_available=True).status == "OK"
    assert env.check_torch_build("2.13.0+cu126", cuda_available=True).status == "PERINGATAN"
    assert env.check_torch_build("2.14.1+cu126", cuda_available=False).status == "GAGAL"


@pytest.mark.parametrize("capability,arch,status", [
    ((6, 1), ["sm_50", "sm_60", "sm_61", "sm_70", "sm_86", "sm_89"], "OK"),     # 1060 di cu126
    ((6, 1), ["sm_75", "sm_80", "sm_86", "sm_89", "sm_90"], "GAGAL"),           # 1060 di cu128/cu130
    ((8, 9), ["sm_75", "sm_80", "sm_86", "sm_89"], "OK"),                       # 4060
    ((8, 6), ["sm_75", "sm_80", "sm_89"], "PERINGATAN"),                        # 3050, sekeluarga sm_8x
])
def test_arsitektur(capability, arch, status):
    assert env.check_arch(capability, arch, "GPU").status == status


def test_onnxruntime_cuda13_di_env_cuda12_gagal():
    """Kasus 2 Okt: onnxruntime-gpu 1.30 mencari cublasLt64_13.dll lalu diam-diam ke CPU."""
    gpu = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert env.check_onnxruntime("1.30.0", gpu, gpu_package=True).status == "GAGAL"
    assert env.check_onnxruntime("1.26.0", gpu, gpu_package=True).status == "OK"
    assert env.check_onnxruntime("1.26.0", ["CPUExecutionProvider"], gpu_package=True).status == "GAGAL"
    assert env.check_onnxruntime("1.26.0", ["CPUExecutionProvider"], gpu_package=False).status == "PERINGATAN"
    assert env.check_onnxruntime(None, [], gpu_package=False).status == "PERINGATAN"


def test_libreyolo_dan_driver_dan_python():
    assert env.check_libreyolo("1.5.2").status == "PERINGATAN"
    assert env.check_libreyolo("1.6.0").status == "OK"
    assert env.check_libreyolo(None).status == "GAGAL"
    assert env.check_driver("581.42").status == "OK"
    assert env.check_driver("552.12").status == "GAGAL"
    assert env.check_python((3, 12)).status == "OK"
    assert env.check_python((3, 10)).status == "PERINGATAN"


def test_konflik_paket():
    installed = {"xformers": "0.0.33", "onnxruntime": "1.26.0", "onnxruntime-gpu": "1.26.0"}.get
    names = {(c.name, c.status) for c in env.check_conflicts(installed)}
    assert ("xformers", "PERINGATAN") in names and ("onnxruntime", "GAGAL") in names


def test_berkas_requirements_konsisten():
    """Torch cu126 dipatok persis, onnxruntime-gpu < 1.27, libreyolo >= 1.6, per GPU mengarah ke satu berkas."""
    torch_txt = Path("engine/requirements-torch-cu126.txt").read_text(encoding="utf-8")
    assert "download.pytorch.org/whl/cu126" in torch_txt
    assert f"torch=={env.TORCH_EXPECTED}" in torch_txt and "torchvision==0.29.1+cu126" in torch_txt
    gpu_txt = Path("engine/requirements-gpu.txt").read_text(encoding="utf-8")
    assert "-r requirements-torch-cu126.txt" in gpu_txt and "libreyolo>=1.6,<2" in gpu_txt
    assert "<1.27" in Path("engine/requirements-face.txt").read_text(encoding="utf-8")
    for gpu in ("rtx4060", "rtx3050", "gtx1060"):
        assert "-r requirements-gpu.txt" in Path(f"engine/requirements-gpu-{gpu}.txt").read_text(encoding="utf-8")


def test_model_wajah_dicari_di_beberapa_tempat(tmp_path):
    """Laptop 1060 menyimpan model di engine/models/recognition/: dulu baris onnx-sesi hilang diam-diam."""
    first, second = tmp_path / "a.onnx", tmp_path / "b.onnx"
    assert env.find_face_model((first, second)) is None
    second.write_bytes(b"x")
    assert env.find_face_model((first, second)) == second
    first.write_bytes(b"x")
    assert env.find_face_model((first, second)) == first


@pytest.mark.parametrize("ort, trt, status", [
    ("1.23.2", None, "GAGAL"),
    ("1.23.2", "10.9.0.34", "OK"),
    ("1.24.4", "10.14.1.48", "OK"),
    ("1.24.4", "10.9.0.34", "PERINGATAN"),
    ("1.23.2", "8.6.1", "GAGAL"),
    ("1.30.0", "10.15.0", "PERINGATAN"),
])
def test_pasangan_onnxruntime_tensorrt(ort, trt, status):
    check = env.check_tensorrt_version(ort, trt)
    assert check.status == status
    if trt is None:
        assert "tensorrt-cu12-libs==10.9.*" in check.detail and "setup-env-trt.ps1" in check.detail


def test_nvrtc_di_path_ok_di_tempat_lain_peringatan(tmp_path):
    """ea-r14: cuDNN 9 mencari NVRTC lewat PATH; di torch/lib saja tidak cukup (uji 17 Okt)."""
    di_path, lain = tmp_path / "a", tmp_path / "b"
    di_path.mkdir(); lain.mkdir()
    (lain / "nvrtc64_120_0.dll").write_bytes(b"x")
    assert env.find_nvrtc([di_path], "nvrtc64_12*.dll") is None
    temuan = env.find_nvrtc([di_path, lain], "nvrtc64_12*.dll")
    assert temuan is not None and temuan.name == "nvrtc64_120_0.dll"
    assert env.check_nvrtc(temuan, None).status == "OK"
    hasil = env.check_nvrtc(None, temuan)
    assert hasil.status == "PERINGATAN" and "PATH" in hasil.detail
    assert env.check_nvrtc(None, None).status == "PERINGATAN"


def test_folder_kandidat_nvrtc(tmp_path):
    import os
    x, y, cuda = tmp_path / "x", tmp_path / "y", tmp_path / "cuda"
    di_path, lain = env.nvrtc_candidate_dirs(os.pathsep.join([str(x), "", str(y)]), tmp_path / "torch",
                                             [tmp_path / "site"], str(cuda))
    assert di_path == [x, y]
    assert tmp_path / "torch" / "lib" in lain
    assert tmp_path / "site" / "nvidia" / "cuda_nvrtc" / "bin" in lain
    assert cuda / "bin" in lain
