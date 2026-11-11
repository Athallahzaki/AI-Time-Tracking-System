"""Pemantau kondisi gambar per kamera (docs/ANALISIS-KETAHANAN.md §5.5).

Tanpa model: empat ukuran murah atas frame yang diperkecil, kira-kira sekali
per detik. Tujuannya bukan memperbaiki gambar, melainkan TAHU kapan gambar
tidak layak:

- `ir`      kamera di mode inframerah (ketiga kanal nyaris sama di tiap piksel).
            Warna pakaian hilang, jadi embedding tubuh tidak sebanding dengan
            galeri siang.
- `dark`    terlalu gelap untuk di-embed.
- `blurry`  buram atau lensa tertutup (nyaris tanpa tepi).
- `frozen`  frame berturut-turut identik (sumber macet).

Saat `ir` atau `dark`, embedding ReID ditahan (`skip_reid`): lebih baik terpecah
daripada tertukar. Semua status dilaporkan sebagai angka di
`engine.health.camera_metrics` (tanpa perubahan kontrak). Default mati; ambang
harus dikalibrasi dari rekaman kamera sungguhan.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from ..config.schema import ImageConditionConfig

FLAGS = ("ir", "dark", "blurry", "frozen")
_SAMPLE_WIDTH = 160   # cukup untuk statistik; murah (±19 ribu piksel)


class ImageConditionMonitor:
    def __init__(self, params: ImageConditionConfig) -> None:
        self.params = params
        self.flags: Dict[str, bool] = {name: False for name in FLAGS}
        self._streak: Dict[str, int] = {name: 0 for name in FLAGS}
        self._next_at: Optional[float] = None
        self._previous: Optional[np.ndarray] = None
        self._brightness = 0.0
        self._sharpness = 0.0
        self._channel_diff = 0.0

    @property
    def skip_reid(self) -> bool:
        return self.params.enabled and (self.flags["ir"] or self.flags["dark"])

    def update(self, image: Any, at: float) -> None:
        """`image` BGR uint8; `at` detik (PTS). Murah bila belum waktunya atau mati."""
        if not self.params.enabled or image is None or getattr(image, "ndim", 0) != 3:
            return
        if self._next_at is not None and at < self._next_at and at >= self._next_at - self.params.interval_seconds:
            return                                      # `at` mundur (stream baru) = langsung ukur
        self._next_at = at + self.params.interval_seconds

        step = max(1, image.shape[1] // _SAMPLE_WIDTH)
        sample = image[::step, ::step, :3].astype(np.int16)
        blue, green, red = sample[..., 0], sample[..., 1], sample[..., 2]
        gray = (blue + green + red) // 3
        self._channel_diff = float((np.abs(blue - green).mean() + np.abs(green - red).mean()) / 2.0)
        self._brightness = float(gray.mean())
        laplacian = (4 * gray[1:-1, 1:-1] - gray[:-2, 1:-1] - gray[2:, 1:-1]
                     - gray[1:-1, :-2] - gray[1:-1, 2:])
        self._sharpness = float(laplacian.var()) if laplacian.size else 0.0
        frozen = (self._previous is not None and self._previous.shape == gray.shape
                  and float(np.abs(gray - self._previous).mean()) <= self.params.frozen_max_change)
        self._previous = gray

        dark = self._brightness <= self.params.dark_max_brightness
        self._debounce("ir", self._channel_diff <= self.params.ir_max_channel_diff)
        self._debounce("dark", dark)
        # Gelap gulita juga "tanpa tepi": jangan dilaporkan dua kali sebagai buram.
        self._debounce("blurry", not dark and self._sharpness <= self.params.blur_max_sharpness)
        self._debounce("frozen", frozen)

    def _debounce(self, name: str, observed: bool) -> None:
        """Status berganti hanya setelah `hold_samples` pengukuran berturut-turut tidak setuju."""
        if observed == self.flags[name]:
            self._streak[name] = 0
            return
        self._streak[name] += 1
        if self._streak[name] >= self.params.hold_samples:
            self.flags[name] = observed
            self._streak[name] = 0

    def metrics(self) -> Dict[str, float]:
        """Angka saja: `camera_metrics` dibaca backend lama dan baru tanpa skema baru."""
        if not self.params.enabled:
            return {}
        out: Dict[str, float] = {f"image_{name}": int(value) for name, value in self.flags.items()}
        out["image_brightness"] = round(self._brightness, 1)
        out["image_sharpness"] = round(self._sharpness, 1)
        out["image_channel_diff"] = round(self._channel_diff, 2)
        return out
