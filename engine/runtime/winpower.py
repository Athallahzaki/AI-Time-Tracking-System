"""Keluar dari "power throttling" (EcoQoS) Windows untuk proses engine.

Gladi 60 menit di laptop RTX 4060 (4 Okt 08:15-09:15, Intel hybrid P/E-core):
fps berganti-ganti antara ±10 (target) dan ±6 dalam fase beberapa menit. Di fase
6 fps, `lag_s` tetap ±0,03 tetapi umur kotak naik ±0,7 dtk per detik sampai
5-8 dtk, jumlah frame yang dibuang thread pembaca hampir berhenti bertambah, lalu
umur jatuh tiba-tiba ke ±1 dtk. Artinya decode sendiri yang lebih lambat dari
waktu nyata (pembaca tertinggal dari soket RTSP), sampai MediaMTX membuang paket
("reader is too slow") dan engine melompat ke frame terbaru. GPU di P0 ±1,6-2 GHz
dengan utilisasi 10-20%, jadi GPU tidak terlibat. Laptop 1060 (Coffee Lake, tanpa
E-core) tidak menunjukkan pola ini.

Dugaan: Windows 11 memberi EcoQoS pada proses yang jendelanya tidak di depan
(terminal engine kalah fokus dari browser dashboard), sehingga thread-nya
dipindah ke E-core pada clock rendah. Ini cocok dengan CPU ±15-20% dan clock
rendah yang terlihat di HWiNFO 3 Okt. Dugaan, bukan fakta: tombolnya ada supaya
bisa diuji, dan log start mencatat apakah panggilan berhasil.

API: SetProcessInformation(ProcessPowerThrottling) dengan ControlMask berisi
EXECUTION_SPEED dan StateMask 0, artinya "jangan pernah throttle proses ini".
Tersedia sejak Windows 10 1709. IGNORE_TIMER_RESOLUTION baru ada di Windows 11,
jadi bila ditolak, dicoba ulang tanpanya.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("engine.runtime.winpower")

PROCESS_POWER_THROTTLING = 4                  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
EXECUTION_SPEED = 0x1
IGNORE_TIMER_RESOLUTION = 0x4


def _state_struct():
    import ctypes

    class ProcessPowerThrottlingState(ctypes.Structure):
        # ULONG Windows = 32 bit; c_uint32 eksplisit supaya ukurannya 12 byte di mana pun.
        _fields_ = [
            ("Version", ctypes.c_uint32),
            ("ControlMask", ctypes.c_uint32),
            ("StateMask", ctypes.c_uint32),
        ]

    return ProcessPowerThrottlingState


def _kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetProcessInformation.restype = wintypes.BOOL
    return kernel32


def disable_power_throttling(kernel32: Any = None, os_name: Optional[str] = None) -> str:
    """Matikan EcoQoS untuk proses ini. Mengembalikan ringkasan untuk log; tidak pernah melempar."""
    if (os_name or os.name) != "nt":
        return "bukan Windows, tidak ada yang diubah"
    try:
        import ctypes

        api = kernel32 if kernel32 is not None else _kernel32()
        state_type = _state_struct()
        handle = api.GetCurrentProcess()
        for mask, label in (
            (EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION, "execution speed + timer resolution"),
            (EXECUTION_SPEED, "execution speed"),
        ):
            state = state_type(PROCESS_POWER_THROTTLING_CURRENT_VERSION, mask, 0)
            if api.SetProcessInformation(handle, PROCESS_POWER_THROTTLING, ctypes.byref(state),
                                         ctypes.sizeof(state)):
                return f"power throttling Windows dimatikan ({label})"
        error = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
        return f"power throttling Windows TIDAK bisa dimatikan (error {error})"
    except Exception as exc:  # noqa: BLE001 -- engine tetap jalan; hanya dicatat
        return f"power throttling Windows TIDAK bisa dimatikan ({exc!r})"
