"""Kotak surat frame: satu slot, hanya frame terbaru (dokumen 04 §14.3).

Untuk penjadwal berdetak tahap 2: decoder kamera mengisi, penjadwal mengambil
sekali per detak. Frame lama yang belum diambil ditimpa dan dihitung, bukan
diantrekan; antrean frame adalah cara paling pasti membuat analisis makin
tertinggal dari kamera.

`PyAVSource` dengan `live_buffer: latest` sudah punya slot serupa di dalamnya
(`_slot`, `_take_latest`). Kelas ini memisahkan mekanisme itu dari PyAV supaya
dipakai juga oleh sumber NVDEC (`nvdec_source.py`) dan oleh penjadwal yang tidak
boleh memblok: `take()` tidak pernah menunggu.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class MailboxStats:
    put: int = 0
    taken: int = 0
    overwritten: int = 0       # frame yang ditimpa sebelum sempat diambil


class FrameMailbox(Generic[T]):
    """Slot tunggal yang aman antar-thread. Satu penulis, satu atau lebih pembaca."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._item: Optional[T] = None
        self._closed = False
        self.stats = MailboxStats()

    def put(self, item: T) -> None:
        with self._cond:
            if self._closed:
                return
            if self._item is not None:
                self.stats.overwritten += 1
            self._item = item
            self.stats.put += 1
            self._cond.notify_all()

    def take(self) -> Optional[T]:
        """Frame terbaru yang belum pernah diambil, atau None. Tidak memblok."""
        with self._cond:
            item, self._item = self._item, None
        if item is not None:
            self.stats.taken += 1
        return item

    def wait_take(self, timeout: float) -> Optional[T]:
        """Seperti `take`, tetapi menunggu paling lama `timeout` detik."""
        with self._cond:
            if self._item is None and not self._closed:
                self._cond.wait(timeout)
            item, self._item = self._item, None
        if item is not None:
            self.stats.taken += 1
        return item

    def close(self) -> None:
        """Penulis selesai (stream putus/berhenti). Pembaca yang menunggu dibangunkan."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def reopen(self) -> None:
        with self._cond:
            self._closed = False
            self._item = None

    @property
    def closed(self) -> bool:
        with self._cond:
            return self._closed

    @property
    def pending(self) -> bool:
        with self._cond:
            return self._item is not None
