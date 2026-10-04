"""runtime/winpower.py: keluar dari EcoQoS Windows (gladi 4060, 4 Okt)."""

from __future__ import annotations

from engine.runtime import winpower
from engine.runtime.__main__ import build_parser


class FakeKernel32:
    def __init__(self, accept_masks):
        self.accept = set(accept_masks)
        self.calls = []

    def GetCurrentProcess(self):
        return 42

    def SetProcessInformation(self, handle, info_class, state_ptr, size):
        state = state_ptr._obj
        self.calls.append((handle, info_class, state.Version, state.ControlMask, state.StateMask, size))
        return 1 if state.ControlMask in self.accept else 0


def test_bukan_windows_tidak_menyentuh_apa_pun():
    fake = FakeKernel32(accept_masks=[])
    assert "bukan Windows" in winpower.disable_power_throttling(fake, os_name="posix")
    assert fake.calls == []


def test_windows_11_mematikan_execution_speed_dan_timer():
    fake = FakeKernel32(accept_masks=[winpower.EXECUTION_SPEED | winpower.IGNORE_TIMER_RESOLUTION])
    result = winpower.disable_power_throttling(fake, os_name="nt")
    assert "dimatikan (execution speed + timer resolution)" in result
    handle, info_class, version, control, state, size = fake.calls[0]
    assert (handle, info_class, version, state, size) == (42, 4, 1, 0, 12)   # StateMask 0 = jangan throttle


def test_windows_10_tanpa_timer_resolution_dicoba_ulang():
    fake = FakeKernel32(accept_masks=[winpower.EXECUTION_SPEED])
    assert "dimatikan (execution speed)" in winpower.disable_power_throttling(fake, os_name="nt")
    assert [call[3] for call in fake.calls] == [0x5, 0x1]


def test_gagal_tidak_melempar():
    assert "TIDAK" in winpower.disable_power_throttling(FakeKernel32(accept_masks=[]), os_name="nt")

    class Broken:
        def GetCurrentProcess(self):
            raise OSError("tidak ada kernel32")

    assert "TIDAK" in winpower.disable_power_throttling(Broken(), os_name="nt")


def test_bisa_dimatikan_dari_cli():
    assert build_parser().parse_args([]).allow_power_throttling is False
    assert build_parser().parse_args(["--allow-power-throttling"]).allow_power_throttling is True
