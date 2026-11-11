"""Paket G: pemantau kondisi gambar (IR, gelap, buram, beku) dan gerbang embedding ReID."""

from __future__ import annotations

import numpy as np
import pytest

from engine.config import load_config
from engine.config.schema import ImageConditionConfig
from engine.runtime.image_condition import ImageConditionMonitor

ON = ImageConditionConfig(enabled=True, hold_samples=2)
RNG = np.random.default_rng(5)


def _scene(brightness: int = 120, color: bool = True, detail: bool = True) -> np.ndarray:
    """Adegan 240x320: kotak-kotak tajam; berwarna (siang) atau abu-abu (IR)."""
    image = np.full((240, 320, 3), brightness, dtype=np.int16)
    if detail:
        for row in range(0, 240, 40):
            for col in range(0, 320, 40):
                tint = RNG.integers(-60, 60, size=3) if color else np.repeat(RNG.integers(-60, 60), 3)
                image[row:row + 20, col:col + 20] += tint
    return np.clip(image, 0, 255).astype(np.uint8)


def _feed(monitor: ImageConditionMonitor, frames, start: float = 0.0) -> None:
    for index, frame in enumerate(frames):
        monitor.update(frame, start + index * 1.0)


def test_mati_secara_default_tidak_mengukur_dan_tidak_menahan_reid():
    monitor = ImageConditionMonitor(ImageConditionConfig())
    _feed(monitor, [_scene(color=False)] * 5)
    assert monitor.skip_reid is False and monitor.metrics() == {}


def test_adegan_berwarna_terang_tidak_memicu_apa_pun():
    monitor = ImageConditionMonitor(ON)
    _feed(monitor, [_scene() for _ in range(6)])
    assert monitor.flags == {"ir": False, "dark": False, "blurry": False, "frozen": False}
    assert monitor.skip_reid is False


def test_mode_ir_terdeteksi_dengan_histeresis_dan_menahan_reid():
    monitor = ImageConditionMonitor(ON)
    _feed(monitor, [_scene() for _ in range(3)])
    monitor.update(_scene(color=False), 3.0)
    assert monitor.flags["ir"] is False                 # satu sampel belum cukup: kamera sedang berpindah
    monitor.update(_scene(color=False), 4.0)
    assert monitor.flags["ir"] is True and monitor.skip_reid is True
    monitor.update(_scene(), 5.0)
    assert monitor.flags["ir"] is True                  # kembali ke warna juga butuh dua sampel
    monitor.update(_scene(), 6.0)
    assert monitor.flags["ir"] is False and monitor.skip_reid is False


def test_dinding_abu_abu_dengan_sedikit_warna_bukan_ir():
    """Ruangan pucat masih menyisakan warna (kulit, benda); IR sejati tidak."""
    wall = np.full((240, 320, 3), 150, dtype=np.uint8)
    wall[60:200, 100:220] = (130, 150, 185)             # satu orang berkulit/berbaju di depan dinding
    monitor = ImageConditionMonitor(ON)
    _feed(monitor, [wall + RNG.integers(0, 2, size=wall.shape, dtype=np.uint8) for _ in range(4)])
    assert monitor.flags["ir"] is False


def test_gelap_menahan_reid_dan_tidak_ikut_dilaporkan_buram():
    monitor = ImageConditionMonitor(ON)
    _feed(monitor, [_scene(brightness=8, detail=False) + RNG.integers(0, 3, size=(240, 320, 3), dtype=np.uint8)
                    for _ in range(3)])
    assert monitor.flags["dark"] is True and monitor.flags["blurry"] is False
    assert monitor.skip_reid is True


def test_lensa_tertutup_dilaporkan_buram_tetapi_reid_tidak_ditahan():
    monitor = ImageConditionMonitor(ON)
    flat = np.full((240, 320, 3), (90, 120, 150), dtype=np.uint8)   # terang, berwarna, tanpa tepi
    _feed(monitor, [flat + RNG.integers(0, 2, size=flat.shape, dtype=np.uint8) for _ in range(3)])
    assert monitor.flags["blurry"] is True and monitor.skip_reid is False


def test_frame_identik_dilaporkan_beku_dan_derau_sensor_tidak():
    frame = _scene()
    frozen = ImageConditionMonitor(ON)
    _feed(frozen, [frame] * 4)
    assert frozen.flags["frozen"] is True
    live = ImageConditionMonitor(ON)
    _feed(live, [np.clip(frame.astype(np.int16) + RNG.integers(-2, 3, size=frame.shape), 0, 255).astype(np.uint8)
                 for _ in range(4)])
    assert live.flags["frozen"] is False


def test_hanya_mengukur_sekali_per_interval_dan_metriknya_angka():
    monitor = ImageConditionMonitor(ImageConditionConfig(enabled=True, hold_samples=1, interval_seconds=1.0))
    monitor.update(_scene(), 10.0)
    monitor.update(_scene(color=False), 10.4)            # belum waktunya: diabaikan
    assert monitor.flags["ir"] is False
    monitor.update(_scene(color=False), 11.0)
    assert monitor.flags["ir"] is True
    metrics = monitor.metrics()
    assert metrics["image_ir"] == 1 and metrics["image_dark"] == 0
    assert all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in metrics.values())


def test_config_bagian_baru_dimuat_dan_kunci_asing_ditolak(tmp_path):
    path = tmp_path / "engine.yaml"
    path.write_text('core:\n  source_type: "mock"\nimage_condition:\n  enabled: true\n  dark_max_brightness: 25\n',
                    encoding="utf-8")
    config = load_config(str(path))
    assert config.image_condition.enabled is True and config.image_condition.dark_max_brightness == 25
    assert ImageConditionConfig().enabled is False
    path.write_text('core:\n  source_type: "mock"\nimage_condition:\n  auto_brighten: true\n', encoding="utf-8")
    with pytest.raises(Exception):
        load_config(str(path))
    with pytest.raises(ValueError):
        ImageConditionConfig(hold_samples=0)
