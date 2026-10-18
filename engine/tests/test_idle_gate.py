"""Gerbang detector kamera kosong (`core.idle_fps`, paket eb-r11).

Default mati (perilaku lama). Bila diisi: kamera tanpa track/deteksi selama
`idle_after_seconds` hanya menjalankan detector `idle_fps` kali per detik dalam
detik PTS; satu deteksi membuatnya penuh lagi; frame tetap dibaca.
"""

from __future__ import annotations

import dataclasses
from typing import Any, List

import pytest

from engine import factory
from engine.config import load_config
from engine.perception import MockDetector
from engine.runtime.idle_gate import IdleDetectionGate


# ---------------------------------------------------------------------------
# gerbang murni
# ---------------------------------------------------------------------------

def _jalankan(gate: IdleDetectionGate, mulai: float, selesai: float, fps: float, aktif=lambda pts: False):
    hasil = []
    langkah = int(round((selesai - mulai) * fps))
    for i in range(langkah):
        pts = mulai + i / fps
        jalan = gate.should_detect(pts)
        hasil.append((round(pts, 3), jalan))
        gate.observe(pts, active=aktif(pts))
    return hasil


def test_aktif_sampai_idle_after_lalu_turun_ke_idle_fps():
    gate = IdleDetectionGate(idle_fps=2.0, idle_after_seconds=5.0)
    hasil = _jalankan(gate, 0.0, 15.0, fps=10.0)
    sebelum = [jalan for pts, jalan in hasil if pts < 5.0]
    sesudah = [pts for pts, jalan in hasil if pts >= 5.0 and jalan]
    assert all(sebelum) and len(sebelum) == 50
    # 5,0 .. 14,9 dtk pada 2 fps -> 20 kali, berjarak 0,5 dtk.
    assert len(sesudah) == 20
    assert all(abs((b - a) - 0.5) < 1e-6 for a, b in zip(sesudah, sesudah[1:]))
    assert gate.idle and gate.skipped == 150 - 50 - 20 and gate.idle_entries == 1


def test_satu_deteksi_langsung_kembali_penuh():
    gate = IdleDetectionGate(idle_fps=1.0, idle_after_seconds=2.0)
    _jalankan(gate, 0.0, 5.0, fps=10.0)
    assert gate.idle
    gate.should_detect(5.0)
    gate.observe(5.0, active=True)
    assert not gate.idle
    berikut = _jalankan(gate, 5.1, 7.0, fps=10.0)
    assert all(jalan for pts, jalan in berikut if pts < 7.0)


def test_track_hidup_menahan_kamera_tetap_aktif():
    gate = IdleDetectionGate(idle_fps=1.0, idle_after_seconds=2.0)
    hasil = _jalankan(gate, 0.0, 30.0, fps=5.0, aktif=lambda pts: True)
    assert all(jalan for _, jalan in hasil) and gate.skipped == 0 and gate.idle_entries == 0


def test_timeline_mundur_mulai_lagi_dari_aktif():
    gate = IdleDetectionGate(idle_fps=1.0, idle_after_seconds=2.0)
    _jalankan(gate, 100.0, 110.0, fps=10.0)
    assert gate.idle
    assert gate.should_detect(0.0) is True and not gate.idle
    assert all(jalan for _, jalan in _jalankan(gate, 0.1, 1.9, fps=10.0))


@pytest.mark.parametrize("fps, after", [(0.0, 1.0), (-1.0, 1.0), (1.0, -0.1)])
def test_nilai_salah_ditolak(fps, after):
    with pytest.raises(ValueError):
        IdleDetectionGate(idle_fps=fps, idle_after_seconds=after)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_config_default_mati_dan_profil_lama_tidak_berubah():
    config = load_config()
    assert config.idle_fps is None and config.idle_after_seconds == 10.0
    for name in ("demo-4060", "demo-4060-tick", "demo-1060"):
        assert load_config(f"engine/config/{name}.yaml").idle_fps is None


def test_config_dibaca_dan_divalidasi(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("core:\n  target_fps: 6.0\n  idle_fps: 1.5\n  idle_after_seconds: 4\n", encoding="utf-8")
    config = load_config(str(path))
    assert config.idle_fps == 1.5 and config.idle_after_seconds == 4.0
    base = load_config()
    with pytest.raises(ValueError, match="idle_fps"):
        dataclasses.replace(base, idle_fps=0.0)
    with pytest.raises(ValueError, match="idle_fps"):
        dataclasses.replace(base, target_fps=6.0, idle_fps=6.0)
    with pytest.raises(ValueError, match="idle_after_seconds"):
        dataclasses.replace(base, idle_fps=1.0, idle_after_seconds=-1.0)


# ---------------------------------------------------------------------------
# Engine.step
# ---------------------------------------------------------------------------

class _DetectorRuangan:
    """Detector palsu: ruangan kosong sampai `masuk_pada` panggilan, lalu ada orang."""

    def __init__(self, masuk_pada: int | None = None) -> None:
        self._mock = MockDetector()
        self.panggilan = 0
        self._masuk_pada = masuk_pada

    def warmup(self) -> None:
        pass

    def detect(self, frame: Any) -> List[Any]:
        self.panggilan += 1
        if self._masuk_pada is None or self.panggilan < self._masuk_pada:
            return []
        return self._mock.detect(frame)


def _engine(detector, frames: int):
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    engine, _source, _fps = factory.build_engine(config, source_id="r1", max_frames=frames, detector=detector)
    engine.start()
    return engine


def _jalan(engine, gate=None):
    langkah, pts_terakhir = 0, None
    while True:
        frame, tracks = engine.step()
        if frame is None:
            return langkah, pts_terakhir
        langkah += 1
        pts_terakhir = frame.metadata.pts
        if gate is not None:
            gate.observe(float(frame.metadata.pts or 0.0),
                         active=bool(tracks) or engine.last_detection_count > 0)


def test_tanpa_gerbang_detector_di_setiap_langkah():
    detector = _DetectorRuangan()
    engine = _engine(detector, frames=60)
    langkah, _ = _jalan(engine)
    assert langkah == 60 and detector.panggilan == 60


def test_ruangan_kosong_detector_dihemat_frame_tetap_dibaca():
    detector = _DetectorRuangan()
    engine = _engine(detector, frames=200)
    gate = IdleDetectionGate(idle_fps=1.0, idle_after_seconds=1.0)
    engine.detection_gate = gate.should_detect
    langkah, pts = _jalan(engine, gate)
    assert langkah == 200, "frame harus tetap dibaca"
    assert detector.panggilan < langkah / 3
    assert detector.panggilan + gate.skipped == langkah
    assert pts and pts > 2.0


def test_orang_masuk_ruangan_kosong_membangunkan_kamera():
    detector = _DetectorRuangan(masuk_pada=6)
    engine = _engine(detector, frames=200)
    gate = IdleDetectionGate(idle_fps=1.0, idle_after_seconds=1.0)
    engine.detection_gate = gate.should_detect
    dilihat = []
    while True:
        frame, tracks = engine.step()
        if frame is None:
            break
        gate.observe(float(frame.metadata.pts or 0.0),
                     active=bool(tracks) or engine.last_detection_count > 0)
        dilihat.append((engine.last_detection_count, bool(tracks)))
    pertama = next(i for i, (n, _) in enumerate(dilihat) if n > 0)
    sesudah = dilihat[pertama:]
    # Begitu orang terlihat, detector jalan di SETIAP langkah berikutnya dan track terbentuk.
    assert all(n > 0 for n, _ in sesudah)
    assert any(ada for _, ada in sesudah)
    assert not gate.idle


# ---------------------------------------------------------------------------
# CameraSupervisor: config -> gerbang terpasang
# ---------------------------------------------------------------------------

def _kamera(idle_fps, detector, frames=150):
    from engine.runtime.camera import CameraSpec, CameraSupervisor

    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False,
                                 idle_fps=idle_fps, idle_after_seconds=1.0)
    return CameraSupervisor(
        spec=CameraSpec("r1", "mock", None), config=config,
        emit_event=lambda m: m, emit_view=lambda m: m,
        max_frames=frames, detector_provider=lambda camera_id, cfg: detector,
    )


def _tunggu_selesai(camera, timeout=60.0):
    import time

    camera.start()
    batas = time.time() + timeout
    while time.time() < batas and camera.stats.state not in ("stopped", "finished", "failed"):
        if camera.stats.frames >= 150:
            break
        time.sleep(0.02)
    camera.stop()


def test_kamera_dengan_idle_fps_menghemat_detector():
    detector = _DetectorRuangan()
    camera = _kamera(1.0, detector)
    _tunggu_selesai(camera)
    assert camera.stats.frames >= 100
    assert detector.panggilan < camera.stats.frames / 3
    assert camera._idle_gate is not None and camera._idle_gate.skipped > 0


def test_kamera_tanpa_idle_fps_perilaku_lama():
    detector = _DetectorRuangan()
    camera = _kamera(None, detector)
    _tunggu_selesai(camera)
    assert camera._idle_gate is None
    assert detector.panggilan >= camera.stats.frames - 1


@pytest.mark.parametrize("name, fps, idle", [("demo-1060-hemat", 4.0, 1.0), ("demo-4060-hemat", 6.0, 2.0)])
def test_profil_hemat_dimuat(name, fps, idle):
    config = load_config(f"engine/config/{name}.yaml")
    assert config.target_fps == fps and config.idle_fps == idle
    assert config.recognition.face_detector_input_size == 320
    assert config.recognition.face_detector_model.endswith("_dinamis.onnx")
    # Gerbang embedding sengaja mati (uji ea-r10).
    assert config.recognition.embed_min_face_px is None
    assert config.recognition.embed_min_score is None
    assert config.recognition.embed_max_yaw is None
