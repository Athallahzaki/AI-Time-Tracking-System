"""Pelabelan zona: di pintu, di tengah ruangan, atau di tepi frame.

Satu field yang paling murah dan paling berdampak di seluruh sistem (§4.2).
`door_region` yang sama dipakai dua arah: di §3.2 untuk mendahulukan track baru
di pintu saat pengenalan, dan di sini untuk sisi sebaliknya — track yang
berakhir **di region pintu** kemungkinan besar orangnya benar-benar keluar,
track yang berakhir **di tengah ruangan** hampir pasti kegagalan tracking.

Satu field, dan backend bisa membedakan celah nyata dari celah palsu tanpa tahu
apa pun tentang tracking. Tanpa field ini, dua belas menit orang yang duduk
membelakangi kamera terlihat persis sama dengan dua belas menit orang yang
pergi ke kantin, dan yang pertama menghasilkan surat peringatan.

Koordinat di sini ternormalisasi, selalu. Engine melihat mainstream sementara
`door_region` dikonfigurasi orang yang melihat substream di dashboard; kalau
satuannya piksel, region-nya bergeser di resolusi yang berbeda.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

ZONE_DOOR = "door"
ZONE_INTERIOR = "interior"
ZONE_FRAME_EDGE = "frame_edge"

# Seberapa dekat ke tepi frame sebelum sebuah track dianggap berakhir di tepi.
# Perseptual: di bawah ini, sebagian badan sudah keluar pandangan dan tracker
# kehilangan objeknya karena alasan geometris, bukan karena orangnya pergi.
DEFAULT_EDGE_MARGIN = 0.03


@dataclass(frozen=True)
class DoorRegion:
    """`[x1, y1, x2, y2]` ternormalisasi 0–1."""

    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def from_sequence(cls, values: Sequence[float]) -> "DoorRegion":
        if len(values) != 4:
            raise ValueError(f"door_region butuh empat angka, dapat {len(values)}")
        x1, y1, x2, y2 = (float(v) for v in values)
        if not all(0.0 <= v <= 1.0 for v in (x1, y1, x2, y2)):
            raise ValueError("door_region wajib ternormalisasi 0-1")
        if x2 <= x1 or y2 <= y1:
            raise ValueError("door_region kosong atau terbalik")
        return cls(x1, y1, x2, y2)

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2


class ZoneLabeller:
    """Melabeli posisi jadi zona, per kamera.

    Kamera tanpa `door_region` terkonfigurasi melaporkan `interior` untuk
    apa pun yang tidak di tepi frame — **bukan** `door`. Defaultnya sengaja ke
    sisi yang mencurigai kegagalan tracking: menebak `door` untuk kamera yang
    belum dikonfigurasi berarti diam-diam menandai setiap celah sebagai
    kepergian nyata, dan itu arah kesalahan yang menghasilkan surat peringatan.
    """

    def __init__(
        self,
        door_regions: Optional[Dict[str, Sequence[float]]] = None,
        edge_margin: float = DEFAULT_EDGE_MARGIN,
    ) -> None:
        self._regions: Dict[str, DoorRegion] = {}
        for camera_id, values in (door_regions or {}).items():
            self._regions[camera_id] = DoorRegion.from_sequence(values)
        self._edge_margin = edge_margin

    def set_region(self, camera_id: str, values: Optional[Sequence[float]]) -> None:
        """Dipanggil saat `set_cameras` datang dari backend."""
        if values is None:
            self._regions.pop(camera_id, None)
            return
        self._regions[camera_id] = DoorRegion.from_sequence(values)

    def has_region(self, camera_id: str) -> bool:
        return camera_id in self._regions

    @property
    def unconfigured_default(self) -> str:
        return ZONE_INTERIOR

    def label(self, camera_id: str, bbox: Sequence[float]) -> str:
        """Zona untuk satu bbox ternormalisasi `[x1, y1, x2, y2]`."""
        if len(bbox) != 4:
            raise ValueError("bbox butuh empat angka ternormalisasi")

        x1, y1, x2, y2 = (float(v) for v in bbox)
        centre_x = (x1 + x2) / 2.0
        centre_y = (y1 + y2) / 2.0

        region = self._regions.get(camera_id)
        if region is not None and region.contains(centre_x, centre_y):
            return ZONE_DOOR

        margin = self._edge_margin
        if x1 <= margin or y1 <= margin or x2 >= 1.0 - margin or y2 >= 1.0 - margin:
            # Di tepi tapi di luar region pintu. Bukan `door` karena tidak ada
            # bukti ia lewat pintu, tapi juga bukan `interior` karena hilangnya
            # punya penjelasan geometris.
            return ZONE_FRAME_EDGE

        return ZONE_INTERIOR

    def label_point(self, camera_id: str, x: float, y: float) -> str:
        return self.label(camera_id, (x, y, x, y))
