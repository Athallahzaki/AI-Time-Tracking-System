"""Merakit interval kehadiran dari siklus hidup track dan keputusan identitas.

Folder ini ada karena perakitan interval bukan persepsi dan bukan penentuan
identitas: ia mengubah keduanya jadi satu-satunya keluaran yang backend pakai.
Menaruhnya di `identity/` akan membuat folder itu punya dua tujuan, dan
menaruhnya di `api/` akan membuat gerbang keluar ikut memutuskan apa yang
layak dipancarkan.

Yang TIDAK ada di sini: akumulasi harian. Menjumlahkan interval berarti
memutuskan celah mana yang dianggap masih hadir, dan itu kebijakan yang
menyamar sebagai aritmetika.
"""

from .assembler import AssemblerMetrics, PresenceAssembler
from .zones import ZONE_DOOR, ZONE_FRAME_EDGE, ZONE_INTERIOR, DoorRegion, ZoneLabeller

__all__ = [
    "AssemblerMetrics",
    "DoorRegion",
    "PresenceAssembler",
    "ZONE_DOOR",
    "ZONE_FRAME_EDGE",
    "ZONE_INTERIOR",
    "ZoneLabeller",
]
