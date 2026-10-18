"""Aturan identitas bersama: awalan ANON- dicadangkan untuk kelompok ReID tanpa wajah.

Kontrak (`$defs.anon_id` di contracts/schema/engine_protocol.schema.json): ID ini
bukan karyawan. Backend tidak boleh menghitungnya sebagai kehadiran, menilai
pelanggarannya, atau menerimanya sebagai employee_id, sampai `identity.resolved`.
"""

from __future__ import annotations

from typing import Any

ANON_PREFIX = "ANON-"


def is_anon_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(ANON_PREFIX)
