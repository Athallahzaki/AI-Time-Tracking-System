"""Error GPU fatal, kebocoran per track, dan metrik dispatcher (paket ea-r8).

Uji 4060 (12 Okt, eb-r1): batch + cuda_graph membuat CUDA `illegal memory
access`, dan sesudahnya tidak ada kamera yang pulih dalam proses yang sama. Dulu
kamera menganggapnya kamera putus dan mencoba ulang selamanya, sementara berkas
detak tetap segar, jadi watchdog tidak pernah menyalakan ulang engine. Di sini
diuji: error itu dikenali, model tidak disentuh lagi, kamera berhenti dan
melapor, runtime berhenti sekali, dan `retry_in_seconds` mengumumkan jeda yang
sebenarnya.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List

import numpy as np
import pytest

from contracts.validator import SchemaValidator
from engine.config import load_config
from engine.perception.dfine_detector import DFINEDetector
from engine.perception.gpu_fatal import describe, is_fatal_gpu_error
from engine.perception.shared_detector import SharedDetector
from engine.ports.frame import Frame, FrameMetadata
from engine.presence import PresenceAssembler, ZoneLabeller
from engine.runtime import EngineRuntime, RuntimeOptions
from engine.runtime import camera as camera_module
from engine.runtime.camera import CameraSpec, CameraSupervisor
from engine.runtime.service import (
    ALLOW_BATCH_CUDA_GRAPH_ENV,
    EXIT_CODE_GPU_FATAL,
    _refuse_known_crash,
)

CUDA_RUSAK = "CUDA error: an illegal memory access was encountered"


def _config(**changes: Any):
    base = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False, strict_mode=True)
    return dataclasses.replace(base, **changes) if changes else base


def _collector():
    messages: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def emit(message: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            message = dict(message)
            message.setdefault("seq", len(messages) + 1)
            messages.append(message)
            return message

    return messages, emit


def _patch_engine_gagal(monkeypatch, sesudah_frame: int, error: BaseException) -> None:
    """Engine mock yang `step()`-nya melempar `error` sesudah N frame, di setiap run."""
    from engine import factory

    real_build = factory.build_engine

    def build(config, **kwargs):
        engine, source, fps = real_build(config, **kwargs)
        original = engine.step
        hitung = {"n": 0}

        def step():
            hitung["n"] += 1
            if hitung["n"] > sesudah_frame:
                raise error
            return original()

        engine.step = step
        return engine, source, fps

    monkeypatch.setattr("engine.factory.build_engine", build)


def _tunggu(kondisi, batas: float = 20.0) -> bool:
    akhir = time.time() + batas
    while time.time() < akhir:
        if kondisi():
            return True
        time.sleep(0.02)
    return kondisi()


# --------------------------------------------------------------------------
# pengenal error
# --------------------------------------------------------------------------

@pytest.mark.parametrize("teks", [
    CUDA_RUSAK,
    "CUDA error: device-side assert triggered",
    "CUDA error: unspecified launch failure",
    "CUDA error: the launch timed out and was terminated",
    "CUBLAS_STATUS_EXECUTION_FAILED when calling cublasSgemm",
])
def test_error_cuda_sticky_dikenali_fatal(teks):
    assert is_fatal_gpu_error(RuntimeError(teks))


@pytest.mark.parametrize("error", [
    RuntimeError("CUDA out of memory. Tried to allocate 20.00 MiB"),
    ValueError("model rusak"),
    ConnectionRefusedError("connection refused"),
    TimeoutError("timed out"),
])
def test_bukan_error_fatal(error):
    assert not is_fatal_gpu_error(error)


def test_error_fatal_di_dalam_rantai_penyebab_tetap_dikenali():
    try:
        try:
            raise RuntimeError(CUDA_RUSAK)
        except RuntimeError as inner:
            raise ValueError("LibreYOLO predict gagal") from inner
    except ValueError as outer:
        assert is_fatal_gpu_error(outer)


def test_tipe_accelerator_error_pytorch_baru_dianggap_fatal():
    AcceleratorError = type("AcceleratorError", (RuntimeError,), {})
    assert is_fatal_gpu_error(AcceleratorError("sesuatu di GPU"))


def test_ringkasan_satu_baris_dan_dipotong():
    teks = describe(RuntimeError("baris1\nbaris2 " + "x" * 500))
    assert "\n" not in teks and len(teks) <= 300 and teks.startswith("RuntimeError: baris1")


# --------------------------------------------------------------------------
# detector bersama dan D-FINE
# --------------------------------------------------------------------------

class InnerRusak:
    class_names = {0: "person"}
    device = "cpu"

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    def warmup(self):
        pass

    def predict_images(self, images, confidence=None):
        self.calls += 1
        raise self.error

    def note_result(self, result):
        pass

    def postprocess(self, frame, result):
        return []


def _frame():
    return Frame(image=np.zeros((4, 4, 3), np.uint8), metadata=FrameMetadata(frame_id=1))


def test_detector_bersama_berhenti_memanggil_model_sesudah_error_fatal():
    inner = InnerRusak(RuntimeError(CUDA_RUSAK))
    shared = SharedDetector(inner).start()
    try:
        handle = shared.handle("cam01")
        with pytest.raises(RuntimeError, match="illegal memory access"):
            handle.detect(_frame())
        assert shared.fatal_error is not None
        with pytest.raises(RuntimeError, match="illegal memory access"):
            handle.detect(_frame())
        assert inner.calls == 1, "model disentuh lagi dengan konteks CUDA yang sudah rusak"
    finally:
        shared.stop()


def test_detector_bersama_error_biasa_tidak_menandai_fatal():
    inner = InnerRusak(ValueError("model rusak"))
    shared = SharedDetector(inner).start()
    try:
        handle = shared.handle("cam01")
        for _ in range(2):
            with pytest.raises(ValueError):
                handle.detect(_frame())
        assert shared.fatal_error is None and inner.calls == 2
    finally:
        shared.stop()


class ModelBatchRusak:
    names = {0: "person"}

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, image, **kwargs):
        self.calls.append(kwargs)
        if "batch" in kwargs:
            raise RuntimeError(CUDA_RUSAK)
        return SimpleNamespace(boxes=None)


def test_batch_dengan_error_fatal_tidak_jatuh_ke_per_gambar():
    """Fallback per gambar setelah konteks CUDA rusak hanya menyamarkan penyebabnya."""
    model = ModelBatchRusak()
    detector = DFINEDetector(device=0, load_model=False, batch_inference=True)
    detector._model = model
    images = [np.zeros((8, 8, 3), np.uint8) for _ in range(3)]
    with pytest.raises(RuntimeError, match="illegal memory access"):
        detector.predict_images(images)
    assert len(model.calls) == 1, "per gambar dicoba sesudah error fatal"
    assert detector._batch_supported is not False, "error GPU bukan bukti LibreYOLO tak mendukung batch"


# --------------------------------------------------------------------------
# kamera
# --------------------------------------------------------------------------

def test_kamera_berhenti_dan_melapor_sekali_pada_error_fatal(monkeypatch):
    _patch_engine_gagal(monkeypatch, sesudah_frame=3, error=RuntimeError(CUDA_RUSAK))
    messages, emit = _collector()
    laporan: List[tuple] = []
    camera = CameraSupervisor(
        spec=CameraSpec("r1", "mock"), config=_config(), emit_event=emit,
        emit_view=lambda m: m, on_fatal=lambda cam, detail: laporan.append((cam, detail)),
    )
    camera.start()
    assert _tunggu(lambda: not camera.alive), "kamera tetap mencoba ulang dengan GPU rusak"
    camera.stop()

    failed = [m for m in messages if m["type"] == "camera.failed"]
    assert len(failed) == 1
    assert failed[0]["reason"] == "gpu_fatal"
    assert laporan and laporan[0][0] == "r1" and "illegal memory access" in laporan[0][1]
    validator = SchemaValidator()
    for message in messages:
        assert not validator.validate_message(message), message


def test_tanpa_on_fatal_perilaku_lama_dan_retry_mengumumkan_jeda_sebenarnya(monkeypatch):
    monkeypatch.setattr(camera_module, "RETRY_INITIAL_SECONDS", 0.05)
    monkeypatch.setattr(camera_module, "RETRY_MAX_SECONDS", 0.2)
    _patch_engine_gagal(monkeypatch, sesudah_frame=2, error=RuntimeError(CUDA_RUSAK))
    messages, emit = _collector()
    camera = CameraSupervisor(spec=CameraSpec("r1", "mock"), config=_config(),
                              emit_event=emit, emit_view=lambda m: m)
    camera.start()
    try:
        assert _tunggu(lambda: sum(m["type"] == "camera.failed" for m in messages) >= 4)
    finally:
        camera.stop()
    jeda = [m["retry_in_seconds"] for m in messages if m["type"] == "camera.failed"][:4]
    assert jeda == pytest.approx([0.05, 0.1, 0.2, 0.2]), "retry_in_seconds tidak mengikuti backoff"


def test_percobaan_rekognisi_per_track_tidak_tumbuh_selamanya():
    _, emit = _collector()
    camera = CameraSupervisor(spec=CameraSpec("r1", "mock"), config=_config(),
                              emit_event=emit, emit_view=lambda m: m)
    frame = Frame(image=np.zeros((4, 4, 3), np.uint8),
                  metadata=FrameMetadata(frame_id=1, width=4, height=4, stream_epoch=0))
    camera._live["tr_pergi"] = {"track_uuid": "tr_pergi"}
    camera.stats.attempts_by_uuid.update({"tr_pergi": 2, "tr_tak_pernah_hidup": 1})
    camera._remember_live(frame, tracks=[], pts=1.0)   # tidak ada track tersisa di frame
    assert camera.stats.attempts_by_uuid == {}
    camera.stats.attempts_by_uuid["tr_x"] = 1
    camera._reset_run_state()
    assert camera.stats.attempts_by_uuid == {}
    assert not hasattr(camera.stats, "evidence_by_uuid")


# --------------------------------------------------------------------------
# runtime
# --------------------------------------------------------------------------

def _runtime(**config_changes: Any) -> EngineRuntime:
    return EngineRuntime(config=_config(**config_changes),
                         options=RuntimeOptions(tcp=("127.0.0.1", 0), max_frames=200))


def test_runtime_berhenti_sekali_saat_kamera_melapor_error_fatal(monkeypatch):
    _patch_engine_gagal(monkeypatch, sesudah_frame=3, error=RuntimeError(CUDA_RUSAK))
    runtime = _runtime()
    dipanggil: List[str] = []
    terpanggil = threading.Event()

    def on_fatal(reason: str) -> None:
        dipanggil.append(reason)
        terpanggil.set()

    runtime.on_fatal = on_fatal
    try:
        runtime._open(CameraSpec("r1", "mock"))
        assert terpanggil.wait(20), "runtime tidak diberi tahu"
        runtime._on_camera_fatal("r2", "error kedua")
        time.sleep(0.1)
        assert len(dipanggil) == 1
        assert runtime.fatal_reason.startswith("r1: ") and "illegal memory access" in runtime.fatal_reason
    finally:
        runtime.close()
    assert EXIT_CODE_GPU_FATAL == 3


def test_gpu_fatal_action_retry_tidak_memasang_on_fatal():
    runtime = _runtime(gpu_fatal_action="retry")
    try:
        camera = runtime._open(CameraSpec("r1", "mock"))
        assert camera._on_fatal is None
    finally:
        runtime.close()


def test_config_gpu_fatal_action(tmp_path):
    assert load_config().gpu_fatal_action == "exit"
    path = tmp_path / "c.yaml"
    path.write_text("core:\n  gpu_fatal_action: retry\n", encoding="utf-8")
    assert load_config(str(path)).gpu_fatal_action == "retry"
    with pytest.raises(ValueError, match="gpu_fatal_action"):
        dataclasses.replace(load_config(), gpu_fatal_action="abaikan")


def test_batch_dan_cuda_graph_ditolak_saat_start(monkeypatch):
    monkeypatch.delenv(ALLOW_BATCH_CUDA_GRAPH_ENV, raising=False)
    config = _config()
    rusak = dataclasses.replace(config, detector=dataclasses.replace(
        config.detector, batch_inference=True, cuda_graph=True))
    with pytest.raises(ValueError, match="illegal memory access"):
        _refuse_known_crash(rusak)
    # Masing-masing sendiri tetap boleh.
    _refuse_known_crash(dataclasses.replace(config, detector=dataclasses.replace(
        config.detector, batch_inference=True)))
    _refuse_known_crash(dataclasses.replace(config, detector=dataclasses.replace(
        config.detector, cuda_graph=True)))
    monkeypatch.setenv(ALLOW_BATCH_CUDA_GRAPH_ENV, "1")
    _refuse_known_crash(rusak)


def test_rasio_sibuk_dispatcher():
    runtime = _runtime()
    try:
        assert runtime._sample_busy_ratio(100.0, 0.0) is None
        assert runtime._sample_busy_ratio(110.0, 5.0) == pytest.approx(0.5)
        assert runtime._sample_busy_ratio(120.0, 16.0) == pytest.approx(1.0)
        assert runtime._sample_busy_ratio(119.0, 16.0) is None, "jam mundur"
        assert runtime.detector_busy_ratio == pytest.approx(1.0)
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# perakit: kandidat sambungan tidak menumpuk
# --------------------------------------------------------------------------

DOOR = {"r1": [0.62, 0.10, 0.95, 0.55]}
DI_TENGAH = [0.40, 0.30, 0.55, 0.80]


def _kunjungan(assembler, track, start, end, person="4471"):
    assembler.track_started(track, "r1", pts=start, bbox=DI_TENGAH)
    assembler.identified(track, person, pts=start + 0.5, similarity=0.9,
                         margin=0.2, evidence_count=3, confidence=0.9)
    assembler.track_ended(track, pts=end, reason="left_frame", zone="interior")


def test_kandidat_sambungan_dan_pemetaan_track_tidak_tumbuh_selamanya():
    keluaran: List[dict] = []
    assembler = PresenceAssembler(emit=keluaran.append, zones=ZoneLabeller(DOOR),
                                  stitch_window_seconds=5.0)
    assembler.camera_online("r1", 1758240000.0, fps=10.0)
    for i in range(200):
        start = i * 100.0
        _kunjungan(assembler, f"tr_{i}", start, start + 30.0, person=f"p{i}")
    assert len(assembler._closed) <= 2
    assert len(assembler._resumed_from) <= 2


def test_sambungan_masih_jalan_untuk_track_lama_yang_baru_dikenali():
    """Track yang lahir sebelum interval lain ditutup tetap boleh menyambung."""
    keluaran: List[dict] = []
    assembler = PresenceAssembler(emit=keluaran.append, zones=ZoneLabeller(DOOR),
                                  stitch_window_seconds=5.0)
    assembler.camera_online("r1", 1758240000.0, fps=10.0)
    _kunjungan(assembler, "tr_a", 0.0, 50.0, person="4471")
    assembler.track_started("tr_b", "r1", pts=52.0, bbox=DI_TENGAH)   # belum dikenali
    _kunjungan(assembler, "tr_c", 53.0, 80.0, person="9999")            # orang lain, menutup di 80
    assembler.identified("tr_b", "4471", pts=81.0, similarity=0.9,
                         margin=0.2, evidence_count=3, confidence=0.9)
    resumed = [m for m in keluaran if m["type"] == "track.resumed"]
    assert resumed and resumed[-1]["prev_track_uuid"] == "tr_a"
