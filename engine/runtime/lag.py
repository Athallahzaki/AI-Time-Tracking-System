"""Seberapa jauh analisis tertinggal dari kamera, per kamera (04 §6, P17).

Dua angka dan satu keadaan:

- `lag_seconds`: PTS terbaru yang sudah di-decode dikurangi PTS yang sedang
  dianalisis. Bebas dari jam dinding, jadi tidak tercemar bias offset (P18) atau
  jam mesin yang tidak sinkron. Hanya bermakna dengan thread pembaca
  (`live_buffer: latest`); tanpa itu keduanya frame yang sama dan lag
  bersembunyi di buffer socket.
- `effective_fps`: frame yang benar-benar dianalisis per detik, jendela 10 dtk.
- keadaan `degraded`: lag di atas ambang terus-menerus selama `hold` detik.
  Masuk dan keluar memakai ambang berbeda (histeresis), supaya satu lonjakan GPU
  tidak menghasilkan sepasang event setiap beberapa detik.

Ambang di sini adalah konstanta persepsi engine (seberapa basi sebuah kotak),
bukan kebijakan kantor; dampaknya ke penagihan diputuskan backend.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

LAG_ENTER_SECONDS = 1.0     # 04 §6: lompat ke frame terbaru di ±1 dtk; di atas itu kotak basi
LAG_EXIT_SECONDS = 0.5
LAG_HOLD_SECONDS = 5.0
FPS_WINDOW_SECONDS = 10.0


@dataclass(frozen=True)
class LagTransition:
    """`entered` = rentang lag dibuka; `exited` = ditutup. Waktu dalam jam dinding."""

    kind: str                   # "entered" | "exited"
    since_wallclock: float      # awal rentang (saat lag pertama kali melewati ambang)
    at_wallclock: float         # saat transisi diputuskan
    lag_seconds: float


class LagMonitor:
    def __init__(
        self,
        enter_seconds: float = LAG_ENTER_SECONDS,
        exit_seconds: float = LAG_EXIT_SECONDS,
        hold_seconds: float = LAG_HOLD_SECONDS,
        fps_window_seconds: float = FPS_WINDOW_SECONDS,
    ) -> None:
        if not 0 <= exit_seconds < enter_seconds:
            raise ValueError("exit_seconds wajib lebih kecil dari enter_seconds (histeresis)")
        self._enter = enter_seconds
        self._exit = exit_seconds
        self._hold = hold_seconds
        self._window = fps_window_seconds
        self._frames: Deque[float] = deque()
        self.lag_seconds: Optional[float] = None
        self.degraded = False
        self._since: Optional[float] = None       # awal rentang yang sedang/akan dibuka
        self._candidate: Optional[float] = None   # awal kondisi yang belum lewat hold

    def reset(self) -> None:
        """Reconnect: timeline baru. `camera.online` sudah menutup rentang lama."""
        self._frames.clear()
        self.lag_seconds = None
        self.degraded = False
        self._since = None
        self._candidate = None

    def observe(self, now: float, lag_seconds: Optional[float]) -> Optional[LagTransition]:
        self._frames.append(now)
        while self._frames and now - self._frames[0] > self._window:
            self._frames.popleft()
        if lag_seconds is None:
            return None
        lag = max(0.0, float(lag_seconds))
        self.lag_seconds = lag

        if not self.degraded:
            if lag >= self._enter:
                if self._candidate is None:
                    self._candidate = now
                if now - self._candidate >= self._hold:
                    self.degraded = True
                    self._since = self._candidate
                    self._candidate = None
                    return LagTransition("entered", self._since, now, lag)
            else:
                self._candidate = None
            return None

        if lag <= self._exit:
            if self._candidate is None:
                self._candidate = now
            if now - self._candidate >= self._hold:
                since = self._since if self._since is not None else self._candidate
                self.degraded = False
                self._since = None
                self._candidate = None
                return LagTransition("exited", since, now, lag)
        else:
            self._candidate = None
        return None

    @property
    def effective_fps(self) -> Optional[float]:
        if len(self._frames) < 2:
            return None
        span = self._frames[-1] - self._frames[0]
        return (len(self._frames) - 1) / span if span > 0 else None

    @property
    def open_since(self) -> Optional[float]:
        return self._since if self.degraded else None


def lag_between(latest: Optional[Tuple[int, float]], epoch: Optional[int], pts: Optional[float]) -> Optional[float]:
    """Lag hanya terdefinisi di dalam satu epoch: pts dua timeline tidak sebanding."""
    if latest is None or epoch is None or pts is None:
        return None
    latest_epoch, latest_pts = latest
    if latest_epoch != epoch:
        return None
    return latest_pts - pts
