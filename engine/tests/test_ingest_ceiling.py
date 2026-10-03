"""engine/tools/ingest_ceiling.py: alat diagnosis plafon fps tanpa GPU.

Diuji dengan fake `av` milik B4 supaya logikanya terbukti sebelum dipakai di
mesin dengan MediaMTX sungguhan: decimation sama dengan pipeline, lag dihitung
di dalam satu epoch, dan kesimpulannya membedakan "ingest menahan" dari "OK".
"""

from __future__ import annotations

import pytest

from engine.tests.test_b4_ingest import FakeAv, FakeStream, _ticks_at
from engine.tests.test_live_ingest_and_detector_prep import SlowCameraContainer
from engine.tools.ingest_ceiling import VariantResult, format_table, run_variant, verdict


def _factory(fps=100.0, frames=400):
    def make(settings):
        from engine.ingest.pyav_source import PyAVSource

        av = FakeAv([SlowCameraContainer(FakeStream(_ticks_at(fps, frames)), interval=1.0 / fps)])
        return PyAVSource(uri="rtsp://kamera/uji", av_module=av, reconnect_attempts=0, **settings)
    return make


@pytest.mark.parametrize("name", ["latest-auto", "none-auto"])
def test_varian_berjalan_dan_mengukur(name):
    result = run_variant(name, _factory(), seconds=0.6, work_ms=20.0, target_fps=12.0)
    assert result.error is None and result.analysed > 0
    assert result.decoded >= result.analysed
    assert 0 < result.analysed_fps <= 14.0, "decimation wajib sama dengan pipeline (target 12 fps)"
    if name.startswith("latest"):
        assert result.lag_median is not None, "lag hanya terukur dengan thread pembaca"


def test_kamera_cepat_pipeline_lambat_melewatkan_frame_utuh():
    result = run_variant("latest-auto", _factory(), seconds=0.6, work_ms=80.0, target_fps=30.0)
    assert result.replaced > 0 and result.analysed_fps < result.decoded_fps


def test_sumber_gagal_dibuka_dilaporkan_bukan_crash():
    def broken(settings):
        raise OSError("koneksi ditolak")
    result = run_variant("latest-auto", broken, seconds=0.1, work_ms=10.0)
    assert result.verdict == "GAGAL" and "koneksi ditolak" in result.error
    assert "GAGAL" in format_table([result])


def test_kesimpulan_membedakan_tertahan_dan_ok():
    def r(fps):
        return VariantResult(name="x", seconds=30, analysed=100, analysed_fps=fps, expected_fps=8.5)
    assert verdict(r(8.2)).startswith("OK")
    assert verdict(r(5.0)) == "TERTAHAN SEBAGIAN"
    assert verdict(r(3.97)) == "INGEST MENAHAN PIPELINE"


def test_varian_cuvid_tanpa_hwaccel_jadi_baris_gagal():
    """FakeAv tidak punya HWAccel: varian cuvid wajib GAGAL dengan alasan, bukan crash."""
    result = run_variant("latest-cuvid", _factory(), seconds=0.3, work_ms=10.0)
    assert result.verdict == "GAGAL" and "hwaccel" in (result.error or "")


def test_work_torch_tanpa_torch_jadi_baris_gagal(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("tidak ada torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_torch)
    result = run_variant("latest-auto", _factory(), seconds=0.3, work_ms=10.0, work_kind="torch")
    assert result.verdict == "GAGAL" and "torch" in (result.error or "")
