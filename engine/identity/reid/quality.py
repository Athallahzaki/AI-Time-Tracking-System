"""Gerbang kualitas crop badan sebelum embedding ReID (dokumen 12 §3.6).

Murni geometri: menilai kotak track terhadap ukuran frame, tanpa menyentuh
piksel. Tiga alasan menolak, semuanya condong ke "lebih baik tidak ada
embedding daripada embedding yang menyesatkan":

- **terlalu kecil**: OSNet melihat 256x128. Orang setinggi 40 px yang
  diperbesar enam kali hanya menyisakan warna baju, dan dua orang berseragam
  sama jadi tak terbedakan.
- **rasio aspek janggal**: kotak yang terlalu lebar biasanya dua orang yang
  digabung detektor; terlalu sempit biasanya potongan tubuh. Batas atas
  sengaja longgar karena orang duduk (ruang hiburan, biliar) memang lebih lebar.
- **terpotong tepi frame**: tubuhnya hanya separuh di dalam gambar. Ditandai
  berkualitas RENDAH, bukan cacat: tidak dipakai untuk embedding (galeri yang
  diisi setengah badan mencocokkan setengah badan orang lain).
"""

from __future__ import annotations

from dataclasses import dataclass

GOOD = "good"
LOW = "low"
REJECT = "reject"

REASON_OK = "ok"
REASON_TOO_SMALL = "too_small"
REASON_ASPECT = "aspect"
REASON_TRUNCATED = "truncated"
REASON_EMPTY = "empty"


@dataclass(frozen=True)
class CropRules:
    min_height_px: float = 96.0
    min_aspect: float = 0.15   # lebar / tinggi
    max_aspect: float = 1.0
    edge_margin_px: float = 2.0

    def __post_init__(self) -> None:
        if self.min_height_px <= 0:
            raise ValueError("min_height_px harus positif")
        if not 0.0 < self.min_aspect < self.max_aspect:
            raise ValueError("harus 0 < min_aspect < max_aspect")
        if self.edge_margin_px < 0:
            raise ValueError("edge_margin_px tidak boleh negatif")


@dataclass(frozen=True)
class CropQuality:
    level: str            # good | low | reject
    reason: str
    box: tuple            # (x1, y1, x2, y2) int, sudah dijepit ke frame

    @property
    def usable(self) -> bool:
        """Hanya crop `good` yang di-embed."""
        return self.level == GOOD

    @property
    def truncated(self) -> bool:
        return self.reason == REASON_TRUNCATED


def assess_crop(x1: float, y1: float, x2: float, y2: float,
                frame_width: int, frame_height: int, rules: CropRules) -> CropQuality:
    """Nilai satu kotak (piksel frame). Kotak dijepit dulu ke dalam frame."""
    cx1, cy1 = max(0, int(round(x1))), max(0, int(round(y1)))
    cx2, cy2 = min(int(frame_width), int(round(x2))), min(int(frame_height), int(round(y2)))
    box = (cx1, cy1, cx2, cy2)
    width, height = cx2 - cx1, cy2 - cy1
    if width <= 0 or height <= 0:
        return CropQuality(REJECT, REASON_EMPTY, box)
    if height < rules.min_height_px:
        return CropQuality(REJECT, REASON_TOO_SMALL, box)
    aspect = width / float(height)
    if aspect < rules.min_aspect or aspect > rules.max_aspect:
        return CropQuality(REJECT, REASON_ASPECT, box)
    margin = rules.edge_margin_px
    if (x1 <= margin or y1 <= margin
            or x2 >= frame_width - margin or y2 >= frame_height - margin):
        return CropQuality(LOW, REASON_TRUNCATED, box)
    return CropQuality(GOOD, REASON_OK, box)
