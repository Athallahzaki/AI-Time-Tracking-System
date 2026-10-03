"""core.cpu_threads (batas thread CPU) dan ingest.hwaccel (decode NVDEC).

Dua knob untuk menguji dugaan plafon 4 fps di mesin GPU. Keduanya default mati,
jadi perilaku lama tidak berubah sampai config memintanya.
"""

from __future__ import annotations

import pytest

from engine.config import load_config
from engine.config.schema import EngineConfig, IngestConfig
from engine.runtime.threads import ENV_VARS, apply_cpu_threads


class FakeTorch:
    def __init__(self, interop_fails=False):
        self.threads = 8
        self.interop = None
        self._interop_fails = interop_fails

    def set_num_threads(self, n):
        self.threads = n

    def get_num_threads(self):
        return self.threads

    def set_num_interop_threads(self, n):
        if self._interop_fails:
            raise RuntimeError("Error: cannot set number of interop threads after parallel work has started")
        self.interop = n


class FakeCv2:
    def __init__(self):
        self.threads = 8

    def setNumThreads(self, n):  # noqa: N802 -- nama API OpenCV
        self.threads = n

    def getNumThreads(self):  # noqa: N802
        return self.threads


def test_nol_tidak_menyentuh_apa_pun():
    env, torch, cv2 = {}, FakeTorch(), FakeCv2()
    report = apply_cpu_threads(0, torch_module=torch, cv2_module=cv2, environ=env)
    assert env == {} and torch.threads == 8 and cv2.threads == 8
    assert report["torch"] is None and report["cv2"] is None


def test_batas_diterapkan_ke_env_torch_dan_opencv():
    env, torch, cv2 = {}, FakeTorch(), FakeCv2()
    report = apply_cpu_threads(2, torch_module=torch, cv2_module=cv2, environ=env)
    assert all(env[name] == "2" for name in ENV_VARS)
    assert torch.threads == 2 and torch.interop == 2 and cv2.threads == 2
    assert report["torch"] == 2 and report["cv2"] == 2


def test_interop_yang_terlambat_dilaporkan_bukan_crash():
    torch = FakeTorch(interop_fails=True)
    report = apply_cpu_threads(2, torch_module=torch, cv2_module=FakeCv2(), environ={})
    assert torch.threads == 2
    assert str(report["torch_interop"]).startswith("tidak diubah")


def test_config_default_mati_dan_terbaca(tmp_path):
    config = load_config("engine/config/dfine-m.yaml")
    assert config.cpu_threads == 0 and config.ingest.hwaccel == "none"
    path = tmp_path / "c.yaml"
    path.write_text("core:\n  cpu_threads: 2\ningest:\n  hwaccel: cuda\n", encoding="utf-8")
    config = load_config(path)
    assert config.cpu_threads == 2 and config.ingest.hwaccel == "cuda"


@pytest.mark.parametrize("bad", [lambda: EngineConfig(cpu_threads=-1), lambda: IngestConfig(hwaccel="vaapi")])
def test_nilai_salah_ditolak(bad):
    with pytest.raises(ValueError):
        bad()


class _HwModule:
    class HWAccel:
        def __init__(self, device_type, allow_software_fallback=True):
            self.device_type = device_type
            self.allow_software_fallback = allow_software_fallback


def _fake_av_with_hwaccel():
    from fractions import Fraction  # noqa: F401
    from engine.tests.test_b4_ingest import FakeAv, FakeContainer, FakeStream, _ticks_at

    av = FakeAv([FakeContainer(FakeStream(_ticks_at(25.0, 20)))])
    seen = {}
    real_open = av.open

    def open_(uri, options=None, **kwargs):
        seen.update(kwargs)
        return real_open(uri, options=options)

    av.open = open_
    av.codec = type("codec", (), {"hwaccel": _HwModule})
    return av, seen


def test_hwaccel_cuda_diteruskan_ke_av_open():
    from engine.ingest.pyav_source import PyAVSource

    av, seen = _fake_av_with_hwaccel()
    source = PyAVSource(uri="file.mp4", av_module=av, hwaccel="cuda")
    source.start()
    try:
        assert source.read() is not None
        assert seen["hwaccel"].device_type == "cuda"
        assert source.hwaccel_status == "requested"
        assert source.describe()["hwaccel"]["requested"] == "cuda"
    finally:
        source.stop()


def test_hwaccel_none_tidak_mengirim_argumen_baru():
    from engine.ingest.pyav_source import PyAVSource

    av, seen = _fake_av_with_hwaccel()
    source = PyAVSource(uri="file.mp4", av_module=av)
    source.start()
    try:
        source.read()
        assert "hwaccel" not in seen and source.hwaccel_status == "off"
    finally:
        source.stop()


def test_hwaccel_diminta_tapi_pyav_tidak_mampu_berhenti_keras():
    from engine.ingest.pyav_source import PyAVSource
    from engine.tests.test_b4_ingest import FakeAv, FakeContainer, FakeStream, _ticks_at

    av = FakeAv([FakeContainer(FakeStream(_ticks_at(25.0, 5)))])
    av.codec = type("codec", (), {"hwaccel": None})
    source = PyAVSource(uri="file.mp4", av_module=av, hwaccel="cuda")
    with pytest.raises(RuntimeError, match="hwaccel"):
        source.start()
    assert source.hwaccel_status.startswith("unavailable")
