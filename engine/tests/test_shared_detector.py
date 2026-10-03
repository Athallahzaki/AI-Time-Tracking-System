"""Satu detector untuk semua kamera (+ batching opsional).

Model asli tidak ada di CI; yang diuji adalah kontraknya: setiap kamera
mendapat hasil untuk frame-nya sendiri, ByteTrack tiap kamera membaca
`last_result` miliknya, dan batching tidak pernah mengubah jawaban.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from engine.perception.shared_detector import SharedDetector, supports_sharing
from engine.ports.frame import Frame, FrameMetadata


class FakeInner:
    """Detector palsu: hasil = id gambar, mencatat ukuran setiap panggilan."""

    class_names = {0: "person"}
    device = "cpu"

    def __init__(self, delay=0.0, fail=False):
        self.calls = []
        self.warmups = 0
        self._delay = delay
        self._fail = fail

    def warmup(self):
        self.warmups += 1

    def predict_images(self, images, confidence=None):
        self.calls.append((len(images), confidence))
        if self._fail:
            raise ValueError("model rusak")
        time.sleep(self._delay)
        return [SimpleNamespace(tag=int(image[0, 0, 0]), confidence=confidence) for image in images]

    def note_result(self, result):
        pass

    def postprocess(self, frame, result):
        return [result.tag]


def _frame(tag, frame_id=1):
    image = np.full((4, 4, 3), tag, dtype=np.uint8)
    return Frame(image=image, metadata=FrameMetadata(frame_id=frame_id))


def test_satu_kamera_tidak_menunggu_dan_hasilnya_milik_frame_itu():
    shared = SharedDetector(FakeInner(), batch_wait_ms=50).start()
    try:
        handle = shared.handle("cam01")
        started = time.monotonic()
        assert handle.detect(_frame(7)) == [7]
        assert time.monotonic() - started < 0.04, "satu kamera aktif: tidak menunggu kamera lain"
        assert handle.last_result.tag == 7 and handle.last_result_frame_id == 1
    finally:
        shared.stop()


def test_banyak_kamera_digabung_dan_tiap_kamera_dapat_hasilnya_sendiri():
    inner = FakeInner(delay=0.01)
    shared = SharedDetector(inner, max_batch=8, batch_wait_ms=30).start()
    handles = [shared.handle(f"cam{i:02d}") for i in range(5)]
    answers = {}
    barrier = threading.Barrier(len(handles))

    def run(index, handle):
        barrier.wait()
        for round_ in range(5):
            tag = index * 10 + round_
            answers[(index, round_)] = (handle.detect(_frame(tag, frame_id=round_)), handle.last_result.tag)

    threads = [threading.Thread(target=run, args=(i, h)) for i, h in enumerate(handles)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    shared.stop()

    for (index, round_), (detections, last) in answers.items():
        assert detections == [index * 10 + round_] and last == index * 10 + round_
    assert len(answers) == 25
    assert shared.metrics.largest_batch > 1, "permintaan kamera lain harus ikut panggilan yang sama"
    assert shared.metrics.images == 25 and shared.metrics.batches < 25


def test_last_result_tidak_bocor_antar_kamera():
    shared = SharedDetector(FakeInner()).start()
    try:
        a, b = shared.handle("cam01"), shared.handle("cam02")
        a.detect(_frame(1, frame_id=100))
        b.detect(_frame(2, frame_id=100))
        assert a.last_result.tag == 1 and b.last_result.tag == 2
        assert shared.handle("cam01") is a
    finally:
        shared.stop()


def test_kepercayaan_berbeda_tidak_digabung_satu_panggilan():
    inner = FakeInner()
    shared = SharedDetector(inner, batch_wait_ms=0).start()
    try:
        handle = shared.handle("cam01")
        assert handle.predict_raw(_frame(3), confidence=0.1).confidence == 0.1
        handle.detect(_frame(4))
        assert {conf for _, conf in inner.calls} == {0.1, None}
    finally:
        shared.stop()


def test_kesalahan_model_sampai_ke_kamera_dan_dispatcher_tetap_hidup():
    inner = FakeInner(fail=True)
    shared = SharedDetector(inner).start()
    try:
        with pytest.raises(ValueError, match="model rusak"):
            shared.handle("cam01").detect(_frame(1))
        inner._fail = False
        assert shared.handle("cam01").detect(_frame(5)) == [5]
    finally:
        shared.stop()


def test_warmup_sekali_untuk_semua_kamera():
    inner = FakeInner()
    shared = SharedDetector(inner)
    shared.handle("cam01").warmup()
    shared.handle("cam02").warmup()
    assert inner.warmups == 1


def test_mock_detector_tidak_dibagi():
    from engine.perception.mock_detector import MockDetector

    assert not supports_sharing(MockDetector())
    with pytest.raises(TypeError):
        SharedDetector(MockDetector())


# -- DFINEDetector.predict_images ---------------------------------------------

class ListModel:
    """LibreYOLO palsu. `batch=True`: menerima list dan mengembalikan list."""

    names = {0: "person"}

    def __init__(self, batch):
        self.batch = batch
        self.calls = []

    def __call__(self, image, **kwargs):
        if isinstance(image, list):
            self.calls.append(("list", len(image)))
            if not self.batch:
                raise TypeError("list tidak didukung")
            return [self._one(item) for item in image]
        self.calls.append(("one", 1))
        return self._one(image)

    @staticmethod
    def _one(image):
        return SimpleNamespace(boxes=None, orig_shape=image.shape[:2], tag=int(image[0, 0, 0]))


def _dfine(model, **kwargs):
    from engine.perception.dfine_detector import DFINEDetector

    detector = DFINEDetector(device="cpu", load_model=False, **kwargs)
    detector._model = model
    return detector


def _images(*tags, size=8):
    return [np.full((size, size, 3), tag, dtype=np.uint8) for tag in tags]


def test_batch_didukung_satu_panggilan_urutan_terjaga():
    model = ListModel(batch=True)
    results = _dfine(model, batch_inference=True).predict_images(_images(1, 2, 3))
    assert [r.tag for r in results] == [1, 2, 3]
    assert model.calls == [("list", 3)]


def test_batch_tidak_didukung_jatuh_ke_per_gambar_dan_diingat():
    model = ListModel(batch=False)
    detector = _dfine(model, batch_inference=True)
    assert [r.tag for r in detector.predict_images(_images(1, 2))] == [1, 2]
    assert [r.tag for r in detector.predict_images(_images(3, 4))] == [3, 4]
    assert model.calls.count(("list", 2)) == 1, "percobaan batch hanya sekali"
    assert detector._batch_supported is False


def test_batch_mati_selalu_per_gambar():
    model = ListModel(batch=True)
    _dfine(model).predict_images(_images(1, 2))
    assert model.calls == [("one", 1), ("one", 1)]


def test_format_warna_campur_tidak_dibatch():
    model = ListModel(batch=True)
    detector = _dfine(model, batch_inference=True, pre_resize=True, image_size=8)
    small = np.full((4, 4, 3), 9, dtype=np.uint8)          # tidak di-resize: bgr
    large = np.full((16, 16, 3), 5, dtype=np.uint8)        # di-resize: rgb
    detector.predict_images([small, large])
    assert ("list", 2) not in model.calls


# -- runtime ---------------------------------------------------------------------

def _runtime(monkeypatch, inner_factory, **detector_kwargs):
    import dataclasses

    from engine import factory
    from engine.config import load_config
    from engine.runtime.service import EngineRuntime

    config = load_config("engine/config/dfine-m.yaml")
    config = dataclasses.replace(config, detector=dataclasses.replace(config.detector, **detector_kwargs))
    built = []

    def build(cfg):
        built.append(cfg)
        return inner_factory()

    monkeypatch.setattr(factory, "build_detector", build)
    return EngineRuntime(config=config), config, built


def test_runtime_memuat_detector_sekali_untuk_semua_kamera(monkeypatch):
    runtime, config, built = _runtime(monkeypatch, FakeInner)
    try:
        a = runtime._detector_for("cam01", config)
        b = runtime._detector_for("cam02", config)
        assert len(built) == 1 and a is not b
        assert a._shared is b._shared and a._shared.inner.warmups == 1
        assert runtime._shared_detector.active_cameras == 2
        runtime._release_detector("cam02")
        assert runtime._shared_detector.active_cameras == 1
    finally:
        runtime.close()


def test_runtime_tanpa_berbagi_kamera_memuat_sendiri(monkeypatch):
    runtime, config, built = _runtime(monkeypatch, FakeInner, share_across_cameras=False)
    try:
        assert runtime._detector_for("cam01", config) is None and built == []
    finally:
        runtime.close()


def test_runtime_detector_yang_tidak_bisa_dibagi_dikembalikan_apa_adanya(monkeypatch):
    from engine.perception.mock_detector import MockDetector

    runtime, config, _ = _runtime(monkeypatch, MockDetector)
    try:
        assert isinstance(runtime._detector_for("cam01", config), MockDetector)
        assert runtime._shared_detector is None
    finally:
        runtime.close()


def test_config_detector_baru(tmp_path):
    from engine.config import load_config
    from engine.config.schema import DetectorConfig

    config = load_config("engine/config/dfine-m.yaml")
    assert config.detector.share_across_cameras is True and config.detector.batch_inference is False
    path = tmp_path / "c.yaml"
    path.write_text("detector:\n  batch_inference: true\n  max_batch: 5\n  cudnn_benchmark: true\n"
                    "recognition:\n  onnx_gpu_mem_limit_mb: 1024\n", encoding="utf-8")
    config = load_config(path)
    assert config.detector.batch_inference and config.detector.max_batch == 5 and config.detector.cudnn_benchmark
    assert config.recognition.onnx_gpu_mem_limit_mb == 1024
    with pytest.raises(ValueError):
        DetectorConfig(max_batch=0)


class ShareableMock:
    """MockDetector yang bisa dibagi: dipakai untuk uji ujung ke ujung runtime."""

    class_names = {0: "person"}
    device = "cpu"

    def __init__(self):
        from engine.perception.mock_detector import MockDetector

        self._mock = MockDetector()
        self._lock = threading.Lock()

    def warmup(self):
        pass

    def predict_images(self, images, confidence=None):
        return list(images)

    def note_result(self, result):
        pass

    def postprocess(self, frame, result):
        with self._lock:
            return self._mock.detect(frame)


def test_ujung_ke_ujung_dua_kamera_memakai_satu_detector(monkeypatch):
    import dataclasses

    from engine import factory
    from engine.config import load_config
    from engine.runtime.camera import CameraSpec
    from engine.runtime.service import EngineRuntime

    built = []
    monkeypatch.setattr(factory, "build_detector", lambda cfg: built.append(cfg) or ShareableMock())
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    runtime = EngineRuntime(config=config)
    try:
        runtime._reconcile({cid: CameraSpec(cid, "mock") for cid in ("cam01", "cam02")})
        deadline = time.time() + 5
        while time.time() < deadline:
            cams = list(runtime._cameras.values())
            if len(cams) == 2 and all(c.stats.frames > 5 for c in cams):
                break
            time.sleep(0.05)
        assert all(c.stats.frames > 5 for c in runtime._cameras.values())
        assert len(built) == 1, "dua kamera, satu detector"
        assert runtime._shared_detector.metrics.images > 10
    finally:
        runtime.close()
