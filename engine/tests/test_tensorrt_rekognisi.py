"""Persiapan percepatan rekognisi (paket ea-r11).

Uji 4060 15 Okt: 54 ms per wajah (SCRFD +-21 + glintr100 +-33). Dua jalur yang
disiapkan untuk diukur di 4060: TensorRT EP FP16 untuk kedua model, dan SCRFD
berdimensi dinamis supaya ukuran 320 bisa dicoba. Di sini diuji logikanya: daftar
provider, cache, penolakan bila TensorRT diminta tapi tidak aktif (kode 2), config,
alat ukur face_bench, dan konversi SCRFD pada model tiruan lewat onnxruntime.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List

import numpy as np
import pytest

from engine.config import load_config
from engine.identity import face_onnx
from engine.identity.face_onnx import (
    CUDA,
    TENSORRT,
    FaceDetection,
    ModelConfigMismatch,
    ProviderUnavailable,
    provider_list,
    recognition_providers,
    tensorrt_options,
)
from engine.tools import face_bench

# --------------------------------------------------------------------------
# daftar provider dan cache
# --------------------------------------------------------------------------


def test_tanpa_tensorrt_daftar_provider_seperti_dulu():
    assert provider_list(None, None) is None
    assert provider_list([CUDA, "CPUExecutionProvider"], None) == [CUDA, "CPUExecutionProvider"]
    with_limit = provider_list(None, 1024)
    assert with_limit[0][0] == CUDA and with_limit[0][1]["gpu_mem_limit"] == 1024 * 1024 * 1024


def test_tensorrt_paling_depan_cuda_tetap_di_belakangnya():
    entries = provider_list([CUDA, "CPUExecutionProvider"], 1024, {"trt_fp16_enable": True})
    assert entries[0] == (TENSORRT, {"trt_fp16_enable": True})
    assert entries[1][0] == CUDA and "gpu_mem_limit" in entries[1][1]
    assert entries[2] == "CPUExecutionProvider"
    # TensorRT yang ditulis manual di onnx_providers tidak dobel, CUDA disisipkan bila tidak ada.
    entries = provider_list([TENSORRT, "CPUExecutionProvider"], None, {})
    assert [face_onnx._provider_name(e) for e in entries] == [TENSORRT, CUDA, "CPUExecutionProvider"]


def test_cache_dipisah_per_versi_dan_presisi(tmp_path):
    fp16 = tensorrt_options(str(tmp_path / "cache"), fp16=True)
    fp32 = tensorrt_options(str(tmp_path / "cache"), fp16=False)
    assert fp16["trt_engine_cache_enable"] and fp16["trt_timing_cache_enable"]
    assert fp16["trt_fp16_enable"] is True and fp32["trt_fp16_enable"] is False
    assert fp16["trt_engine_cache_path"] != fp32["trt_engine_cache_path"], "engine FP32 dipakai ulang sebagai FP16"
    assert Path(fp16["trt_engine_cache_path"]).is_dir()
    assert Path(fp16["trt_engine_cache_path"]).name.startswith("ort") and "-fp16" in fp16["trt_engine_cache_path"]


def test_prefix_cache_per_model_dan_ukuran():
    chosen = [(TENSORRT, {"trt_engine_cache_enable": True}), CUDA]
    out = face_onnx._with_cache_prefix(chosen, "scrfd_10g_bnkps_320")
    assert out[0][1]["trt_engine_cache_prefix"] == "scrfd_10g_bnkps_320"
    assert chosen[0][1] == {"trt_engine_cache_enable": True}, "opsi bersama tidak boleh ikut berubah"


# --------------------------------------------------------------------------
# sesi: TensorRT diminta tetapi tidak aktif = ditolak
# --------------------------------------------------------------------------

class OrtPalsu:
    __version__ = "1.23.2"

    def __init__(self, available, active):
        self.available = available
        self.active = active
        self.calls = []

    def get_available_providers(self):
        return list(self.available)

    def InferenceSession(self, path, providers):  # noqa: N802 -- meniru API onnxruntime
        self.calls.append(providers)
        active = self.active
        return SimpleNamespace(get_providers=lambda: list(active))


@pytest.fixture
def model_file(tmp_path):
    path = tmp_path / "glintr100.onnx"
    path.write_bytes(b"palsu")
    return str(path)


def _pasang(monkeypatch, ort):
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setattr(face_onnx, "_preload_tensorrt_dlls", lambda: None)


def test_build_onnxruntime_tanpa_tensorrt_ditolak(monkeypatch, model_file, tmp_path):
    _pasang(monkeypatch, OrtPalsu([CUDA, "CPUExecutionProvider"], [CUDA, "CPUExecutionProvider"]))
    providers = provider_list(None, None, tensorrt_options(str(tmp_path / "c")))
    with pytest.raises(ProviderUnavailable, match="tidak membawanya"):
        face_onnx._session(model_file, providers)


def test_tensorrt_jatuh_ke_cuda_ditolak_bukan_diam_diam(monkeypatch, model_file, tmp_path):
    _pasang(monkeypatch, OrtPalsu([TENSORRT, CUDA, "CPUExecutionProvider"], [CUDA, "CPUExecutionProvider"]))
    providers = provider_list(None, None, tensorrt_options(str(tmp_path / "c")))
    with pytest.raises(ProviderUnavailable, match="tidak aktif") as caught:
        face_onnx._session(model_file, providers)
    assert isinstance(caught.value, ModelConfigMismatch), "harus berujung kode keluar 2"


def test_tensorrt_aktif_dengan_prefix_cache(monkeypatch, model_file, tmp_path, caplog):
    ort = OrtPalsu([TENSORRT, CUDA, "CPUExecutionProvider"], [TENSORRT, CUDA, "CPUExecutionProvider"])
    _pasang(monkeypatch, ort)
    providers = provider_list(None, None, tensorrt_options(str(tmp_path / "c")))
    caplog.set_level("WARNING", logger="engine.identity.face_onnx")
    face_onnx._session(model_file, providers)
    sent = ort.calls[0][0]
    assert sent[0] == TENSORRT and sent[1]["trt_engine_cache_prefix"] == "glintr100"
    assert any("membangun engine" in r.getMessage() for r in caplog.records), "cache kosong harus diumumkan"
    caplog.clear()
    Path(sent[1]["trt_engine_cache_path"], "glintr100_abc_sm89.engine").write_bytes(b"x")
    face_onnx._session(model_file, providers)
    assert not any("membangun engine" in r.getMessage() for r in caplog.records)


def test_tanpa_tensorrt_sesi_tidak_berubah(monkeypatch, model_file):
    ort = OrtPalsu([TENSORRT, CUDA, "CPUExecutionProvider"], [CUDA, "CPUExecutionProvider"])
    _pasang(monkeypatch, ort)
    face_onnx._session(model_file, [CUDA, "CPUExecutionProvider"])
    assert ort.calls == [[CUDA, "CPUExecutionProvider"]], "TensorRT tersedia tidak boleh dipakai tanpa diminta"


def test_tensorrt_tidak_aktif_keluar_kode_2(tmp_path, monkeypatch):
    from engine.runtime import __main__ as entry

    def tolak(*_args, **_kwargs):
        raise ProviderUnavailable("TensorrtExecutionProvider diminta tetapi tidak aktif")

    monkeypatch.setattr(entry, "_build_runtime", tolak)
    assert entry.main(["--tcp", "127.0.0.1:0", "--outbox", str(tmp_path / "o.sqlite3"), "--quiet"]) == 2


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def test_default_tensorrt_mati_dan_profil_demo_juga():
    assert load_config().recognition.onnx_tensorrt is False
    demo = load_config("engine/config/demo-4060.yaml").recognition
    assert demo.onnx_tensorrt is False
    assert TENSORRT not in [face_onnx._provider_name(p) for p in (recognition_providers(demo) or [])]


def test_config_tensorrt_dibaca(tmp_path):
    path = tmp_path / "c.yaml"
    cache = (tmp_path / "trt").as_posix()
    path.write_text(f"recognition:\n  onnx_tensorrt: true\n  onnx_tensorrt_fp16: false\n"
                    f"  onnx_tensorrt_cache_dir: \"{cache}\"\n", encoding="utf-8")
    rec = load_config(str(path)).recognition
    assert rec.onnx_tensorrt and rec.onnx_tensorrt_fp16 is False
    entries = recognition_providers(rec)
    assert entries[0][0] == TENSORRT and entries[0][1]["trt_fp16_enable"] is False
    assert entries[0][1]["trt_engine_cache_path"].startswith(str(Path(cache)))


def test_config_tensorrt_dengan_cpu_saja_ditolak():
    rec = load_config().recognition
    with pytest.raises(ValueError, match="CUDAExecutionProvider"):
        dataclasses.replace(rec, onnx_tensorrt=True, onnx_providers=("CPUExecutionProvider",))
    with pytest.raises(ValueError, match="cache"):
        dataclasses.replace(rec, onnx_tensorrt=True, onnx_tensorrt_cache_dir=" ")


# --------------------------------------------------------------------------
# face_bench
# --------------------------------------------------------------------------

class DetPalsu:
    """Satu wajah per potongan; `hilang` = indeks potongan tanpa wajah."""

    def __init__(self, hilang=()):
        self.hilang = set(hilang)

    def detect(self, crop):
        index = int(crop[0, 0, 0])
        if index in self.hilang:
            return []
        lm = np.array([[30, 40], [70, 40], [50, 60], [35, 80], [65, 80]], np.float32)
        return [FaceDetection(bbox=(0.0, 0.0, 100.0, 100.0), score=0.9, landmarks=lm)]


class EmbPalsu:
    input_size = 112

    def __init__(self, noise=0.0):
        self.noise = noise

    def embed(self, aligned):
        rng = np.random.default_rng(int(aligned.sum()) % 1000)
        vector = np.ones(512, np.float32) + self.noise * rng.standard_normal(512).astype(np.float32)
        return vector / np.linalg.norm(vector)


def _potongan(n: int) -> List[np.ndarray]:
    crops = []
    for i in range(n):
        crop = np.full((120, 120, 3), 80, np.uint8)
        crop[0, 0, 0] = i
        crop[40:80, 40:80] = (i * 7) % 255
        crops.append(crop)
    return crops


def _builder(table):
    def build(variant):
        return table[variant.name]
    return build


def test_face_bench_membandingkan_dengan_pembanding():
    crops = _potongan(20)
    ref = face_bench.Variant("cuda", 640, "scrfd.onnx")
    trt = face_bench.Variant("trt16", 640, "scrfd.onnx")
    kecil = face_bench.Variant("trt16", 320, "scrfd_dinamis.onnx")
    table = {"cuda@640": (DetPalsu(), EmbPalsu()), "trt16@640": (DetPalsu(), EmbPalsu(noise=0.002)),
             "trt16@320": (DetPalsu(hilang={3, 4, 5}), EmbPalsu(noise=0.002))}
    report = face_bench.run(crops, ref, [ref, trt, kecil], _builder(table), repeat=1)
    assert report.reference.faces == 20 and len(report.variants) == 2, "pembanding tidak diukur dua kali"
    same, small = report.variants
    assert same.lost == 0 and same.cos_embedder_min > 0.99
    assert small.lost == 3 and small.faces == 17
    text = face_bench.format_report(report)
    text.encode("cp1252")
    assert "embedding setara" in text and "hilang 3 (15.0%)" in text


def test_face_bench_embedding_bergeser_diperingatkan():
    crops = _potongan(10)
    ref = face_bench.Variant("cuda", 640, "m.onnx")
    trt = face_bench.Variant("trt16", 640, "m.onnx")
    table = {"cuda@640": (DetPalsu(), EmbPalsu()), "trt16@640": (DetPalsu(), EmbPalsu(noise=0.5))}
    report = face_bench.run(crops, ref, [trt], _builder(table), repeat=1)
    assert report.variants[0].cos_embedder_min < face_bench.COS_OK
    assert "PERINGATAN embedding bergeser" in face_bench.format_report(report)


def test_face_bench_varian_gagal_tidak_menggugurkan_laporan():
    crops = _potongan(5)
    ref = face_bench.Variant("cuda", 640, "m.onnx")
    trt = face_bench.Variant("trt16", 640, "m.onnx")

    def build(variant):
        if variant.provider == "trt16":
            raise ProviderUnavailable("TensorrtExecutionProvider diminta tetapi tidak aktif")
        return DetPalsu(), EmbPalsu()

    report = face_bench.run(crops, ref, [trt], build, repeat=1)
    assert report.variants[0].error and "GAGAL" in face_bench.format_report(report)


def test_head_crop_sama_dengan_jalur_runtime():
    image = np.arange(900 * 500 * 3, dtype=np.uint32).reshape(900, 500, 3).astype(np.uint8)
    box = SimpleNamespace(x1=10, y1=20, x2=210, y2=420)
    crop, origin = face_onnx.head_crop(image, box, 40.0)
    assert origin == (10, 20) and crop.shape == (180, 200, 3)
    assert face_onnx.head_crop(image, SimpleNamespace(x1=0, y1=0, x2=30, y2=300), 40.0) is None
