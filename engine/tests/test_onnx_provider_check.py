"""Rekognisi tidak boleh diam-diam jalan di CPU.

Laporan 3 Okt (GTX 1060): onnxruntime-gpu 1.30 dibangun untuk CUDA 13, DLL
`cublasLt64_13.dll` tidak ada, onnxruntime menulis peringatan lalu memakai CPU
tanpa error. Engine sekarang berhenti dengan pesan yang menunjuk penyebabnya.
"""

from __future__ import annotations

import sys
import types

import pytest

from engine.identity import face_onnx


def _fake_ort(monkeypatch, active, available=("CUDAExecutionProvider", "CPUExecutionProvider")):
    calls = {"preload": 0}
    module = types.ModuleType("onnxruntime")
    module.__version__ = "1.30.0"
    module.get_available_providers = lambda: list(available)

    def preload_dlls():
        calls["preload"] += 1

    class Session:
        def __init__(self, path, providers):
            self.requested = providers

        def get_providers(self):
            return list(active)

    module.preload_dlls = preload_dlls
    module.InferenceSession = Session
    monkeypatch.setitem(sys.modules, "onnxruntime", module)
    monkeypatch.setattr(face_onnx, "_DLLS_PRELOADED", False)
    return calls


def _model(tmp_path):
    path = tmp_path / "glintr100.onnx"
    path.write_bytes(b"x")
    return str(path)


def test_cuda_diminta_tapi_jatuh_ke_cpu_berhenti_keras(monkeypatch, tmp_path):
    _fake_ort(monkeypatch, active=["CPUExecutionProvider"])
    with pytest.raises(face_onnx.RecognizerUnavailable, match="CUDAExecutionProvider diminta"):
        face_onnx._session(_model(tmp_path), ["CUDAExecutionProvider", "CPUExecutionProvider"])


def test_cuda_aktif_lolos_dan_dll_dimuat_sekali(monkeypatch, tmp_path):
    calls = _fake_ort(monkeypatch, active=["CUDAExecutionProvider", "CPUExecutionProvider"])
    model = _model(tmp_path)
    face_onnx._session(model, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    face_onnx._session(model, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert calls["preload"] == 1


def test_cpu_yang_diminta_sendiri_tidak_ditolak(monkeypatch, tmp_path):
    calls = _fake_ort(monkeypatch, active=["CPUExecutionProvider"])
    face_onnx._session(_model(tmp_path), ["CPUExecutionProvider"])
    assert calls["preload"] == 0


def test_batas_vram_dipasang_hanya_pada_cuda():
    providers = face_onnx.provider_list(["CUDAExecutionProvider", "CPUExecutionProvider"], 512)
    name, options = providers[0]
    assert name == "CUDAExecutionProvider"
    assert options == {"gpu_mem_limit": 512 * 1024 * 1024, "arena_extend_strategy": "kSameAsRequested"}
    assert providers[1] == "CPUExecutionProvider"
    assert face_onnx.provider_list(["CPUExecutionProvider"], None) == ["CPUExecutionProvider"]
    assert face_onnx.provider_list(None, None) is None


def test_sesi_menerima_provider_beropsi(monkeypatch, tmp_path):
    calls = _fake_ort(monkeypatch, active=["CUDAExecutionProvider", "CPUExecutionProvider"])
    providers = face_onnx.provider_list(["CUDAExecutionProvider", "CPUExecutionProvider"], 256)
    session = face_onnx._session(_model(tmp_path), providers)
    assert session.requested[0][0] == "CUDAExecutionProvider" and calls["preload"] == 1
