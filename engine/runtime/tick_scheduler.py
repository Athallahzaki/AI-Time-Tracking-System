"""Penjadwal berdetak tetap (dokumen 04 §14, dokumen 12 §3.9).

Masalah yang diselesaikan: di struktur lama setiap kamera punya thread yang
berjalan *secepat mungkin* (`CameraSupervisor`). Ritme tiap kamera ditentukan
penjadwalan thread sistem operasi, batching ke detector bersama terjadi
kebetulan (tunggu 4 ms), dan setiap gangguan kecil langsung terlihat sebagai fps
yang turun. Di laptop Windows itu tampil sebagai fps berayun 10 <-> 6.

Di sini ritme dipegang SATU jam detak. Isi modul, dari yang dipakai sekarang
sampai yang disiapkan untuk tahap berikutnya:

- `TickClock` -- aturan waktu saja: periode, detak berikutnya, dan "detak yang
  molor tidak dikejar". Dipakai kedua tahap.
- `TickGate` -- **tahap 1, sudah bisa dipakai** (`core.scheduler: tick`).
  Thread kamera tetap ada, tetapi sebelum setiap langkah ia menunggu detak.
  Semua kamera dilepas bersamaan, sehingga permintaan ke detector bersama datang
  hampir serentak dan bisa dikumpulkan jadi satu batch (`wait_for_all`).
  Perubahan ke `camera.py` hanya satu baris tunggu.
- `TickScheduler` -- **tahap 2, kerangka** (pekerjaan EB minggu 2). Satu thread
  menjalankan semua kamera: ambil frame terbaru tiap kamera, satu batch
  inferensi, lalu langkah per kamera, lalu sisa waktu untuk rekognisi/ReID.
  Kamera hanya men-decode ke mailbox (`ingest/mailbox.py`). Belum dirakit ke
  `service.py`; yang ada di sini adalah loop dan kontraknya, diuji dengan
  kamera tiruan.

Aturan yang sama untuk kedua tahap (dokumen 04 §14.3):

1. Kamera tanpa frame baru dilewati pada detak itu; yang lain tidak menunggu.
2. Detak yang molor tidak dikejar: detak berikutnya langsung jalan, detak yang
   terlewat dihitung (`late_ticks`, `skipped_ticks`).
3. Pekerjaan identitas memakai sisa waktu sampai detak berikutnya.
4. Frekuensi detak dipilih DI BAWAH kapasitas terukur; cadangan itulah yang
   membuat sistem stabil.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

logger = logging.getLogger("engine.runtime.tick")

STOP_POLL_SECONDS = 0.2
SUMMARY_INTERVAL_SECONDS = 60.0


# -- aturan waktu -------------------------------------------------------------


@dataclass
class TickStats:
    ticks: int = 0
    late_ticks: int = 0          # detak yang jalan setelah tenggatnya lewat
    skipped_ticks: int = 0       # detak yang dilompati karena tidak dikejar
    max_lateness_seconds: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ticks": self.ticks,
            "late_ticks": self.late_ticks,
            "skipped_ticks": self.skipped_ticks,
            "max_lateness_seconds": round(self.max_lateness_seconds, 4),
        }


class TickClock:
    """Jadwal detak berperiode tetap tanpa mengejar ketinggalan.

    Detak ke-n dijadwalkan di `start + n * period`. Bila pemanggil terlambat
    melewati satu atau lebih tenggat, detak yang terlewat TIDAK dijalankan
    beruntun; jadwal melompat ke kelipatan periode berikutnya. Mengejar
    ketinggalan hanya memperpanjang antrean, persis masalah yang mau dihindari.
    """

    # Terlambat kurang dari ini dianggap tepat waktu (jitter sleep OS).
    LATE_TOLERANCE_FRACTION = 0.1

    def __init__(self, fps: float, clock: Callable[[], float] = time.monotonic) -> None:
        if not fps or fps <= 0:
            raise ValueError("fps detak harus > 0")
        self.fps = float(fps)
        self.period = 1.0 / self.fps
        self._clock = clock
        self._deadline: Optional[float] = None
        self.stats = TickStats()

    def reset(self) -> None:
        self._deadline = None

    def seconds_until_next(self) -> float:
        """Berapa lama sampai detak berikutnya (0 bila sudah waktunya)."""
        if self._deadline is None:
            return 0.0
        return max(0.0, self._deadline - self._clock())

    @property
    def next_deadline(self) -> Optional[float]:
        return self._deadline

    def fire(self) -> float:
        """Catat satu detak sekarang; kembalikan keterlambatannya (detik).

        Dipanggil tepat setelah menunggu `seconds_until_next()`.
        """
        now = self._clock()
        if self._deadline is None:
            self._deadline = now
        lateness = max(0.0, now - self._deadline)
        self.stats.ticks += 1
        if lateness > self.period * self.LATE_TOLERANCE_FRACTION:
            self.stats.late_ticks += 1
            self.stats.max_lateness_seconds = max(self.stats.max_lateness_seconds, lateness)
        # Lompat ke tenggat berikutnya yang masih di depan.
        missed = int(math.floor(lateness / self.period))
        self.stats.skipped_ticks += missed
        self._deadline = self._deadline + (missed + 1) * self.period
        return lateness


# -- tahap 1: gerbang detak untuk thread kamera yang sudah ada ----------------


@dataclass
class _Participant:
    seen_tick: int = 0
    waits: int = 0
    missed_ticks: int = 0        # detak yang lewat saat kamera masih sibuk


class TickGate:
    """Melepas semua thread kamera bersamaan, sekali per detak.

    Kamera memanggil `wait(camera_id, stop)` sebelum setiap langkah. Bila kamera
    masih sibuk ketika satu atau lebih detak lewat, `wait` langsung kembali (tidak
    menunggu detak berikutnya) dan detak yang terlewat dihitung sebagai
    `missed_ticks` kamera itu. Kamera tidak pernah menjalankan dua langkah untuk
    satu detak.
    """

    def __init__(
        self,
        fps: float,
        clock: Callable[[], float] = time.monotonic,
        name: str = "tick-gate",
    ) -> None:
        self.clock = TickClock(fps, clock=clock)
        self._name = name
        self._cond = threading.Condition()
        self._tick = 0
        self._participants: Dict[str, _Participant] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_summary = 0.0

    # -- siklus hidup --------------------------------------------------------

    def start(self) -> "TickGate":
        if self._thread is None:
            self._stop.clear()
            self._last_summary = time.monotonic()
            self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
            self._thread.start()
            logger.info("penjadwal berdetak (tahap 1) aktif: %.2f detak/detik", self.clock.fps)
        return self

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
        self._log_summary(force=True)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- peserta -------------------------------------------------------------

    def register(self, camera_id: str) -> None:
        with self._cond:
            # Mulai dari detak saat ini: kamera baru tidak "berutang" detak lama.
            self._participants[camera_id] = _Participant(seen_tick=self._tick)

    def unregister(self, camera_id: str) -> None:
        with self._cond:
            self._participants.pop(camera_id, None)

    @property
    def participants(self) -> List[str]:
        with self._cond:
            return list(self._participants)

    def wait(self, camera_id: str, stop: Optional[threading.Event] = None) -> bool:
        """Blok sampai ada detak baru untuk kamera ini. False = harus berhenti."""
        with self._cond:
            participant = self._participants.get(camera_id)
            if participant is None:
                participant = _Participant(seen_tick=self._tick)
                self._participants[camera_id] = participant
            while participant.seen_tick >= self._tick:
                if self._stop.is_set() or (stop is not None and stop.is_set()):
                    return False
                self._cond.wait(STOP_POLL_SECONDS)
            gap = self._tick - participant.seen_tick
            if gap > 1:
                participant.missed_ticks += gap - 1
            participant.seen_tick = self._tick
            participant.waits += 1
        return not (stop is not None and stop.is_set())

    # -- thread detak ----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            delay = self.clock.seconds_until_next()
            if delay > 0 and self._stop.wait(delay):
                break
            self.clock.fire()
            with self._cond:
                self._tick += 1
                self._cond.notify_all()
            self._log_summary()

    def snapshot(self) -> Dict[str, Any]:
        with self._cond:
            cameras = {
                camera_id: {"steps": p.waits, "missed_ticks": p.missed_ticks}
                for camera_id, p in self._participants.items()
            }
        data = self.clock.stats.as_dict()
        data["fps"] = self.clock.fps
        data["cameras"] = cameras
        return data

    def _log_summary(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_summary < SUMMARY_INTERVAL_SECONDS:
            return
        self._last_summary = now
        snap = self.snapshot()
        if not snap["ticks"]:
            return
        missed = ", ".join(f"{cid}:{c['missed_ticks']}" for cid, c in sorted(snap["cameras"].items()))
        logger.info(
            "detak %.1f/dtk: %d detak, %d telat (maks %.0f ms), %d dilompati; detak terlewat per kamera: %s",
            snap["fps"], snap["ticks"], snap["late_ticks"], snap["max_lateness_seconds"] * 1000.0,
            snap["skipped_ticks"], missed or "-",
        )


# -- tahap 2: satu thread menjalankan semua kamera (kerangka) ------------------


class CameraUnit(Protocol):
    """Satu kamera dilihat dari penjadwal tahap 2.

    Dipenuhi oleh `runtime/camera.py` setelah dirombak menjadi state per kamera
    (pekerjaan EB). Tidak ada thread di dalamnya.
    """

    camera_id: str

    def prepare(self) -> Optional[Any]:
        """Ambil frame terbaru dari mailbox dan siapkan input detector.

        None = tidak ada frame baru; kamera dilewati pada detak ini.
        """

    def finish(self, detection_result: Any) -> None:
        """Tracker -> zona -> binding -> presence -> event/view untuk frame itu."""

    def fail(self, error: BaseException) -> None:
        """Kesalahan di kamera ini saja. Kamera lain tetap jalan."""


@dataclass
class SchedulerStats:
    batches: int = 0
    frames: int = 0
    empty_ticks: int = 0          # detak tanpa satu pun frame baru
    unit_failures: int = 0
    batch_failures: int = 0
    infer_seconds: float = 0.0
    idle_seconds: float = 0.0     # waktu yang diberikan ke pekerjaan identitas
    per_camera_frames: Dict[str, int] = field(default_factory=dict)


class TickScheduler:
    """Loop tahap 2: satu detak = satu batch untuk semua kamera.

    `infer_batch(inputs) -> results` dipanggil sekali per detak dengan semua
    input yang siap, dan harus mengembalikan hasil sebanyak input dengan urutan
    yang sama (kontrak `predict_images` detector yang sudah ada).

    `idle(deadline)` -- opsional -- menerima sisa waktu sampai detak berikutnya
    (waktu monotonic absolut) untuk rekognisi wajah/ReID, dan WAJIB kembali
    sebelum tenggat itu.
    """

    def __init__(
        self,
        fps: float,
        units: Callable[[], Sequence[CameraUnit]],
        infer_batch: Callable[[List[Any]], List[Any]],
        idle: Optional[Callable[[float], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.clock = TickClock(fps, clock=clock)
        self._units = units
        self._infer_batch = infer_batch
        self._idle = idle
        self._now = clock
        self._sleep = sleep
        self.stats = SchedulerStats()

    def run_tick(self) -> int:
        """Satu detak penuh. Mengembalikan jumlah frame yang diproses."""
        ready: List[CameraUnit] = []
        inputs: List[Any] = []
        for unit in list(self._units()):
            try:
                prepared = unit.prepare()
            except BaseException as error:  # noqa: BLE001 -- satu kamera, bukan semua
                self.stats.unit_failures += 1
                unit.fail(error)
                continue
            if prepared is None:
                continue
            ready.append(unit)
            inputs.append(prepared)

        if not inputs:
            self.stats.empty_ticks += 1
            return 0

        started = self._now()
        try:
            results = self._infer_batch(inputs)
            if len(results) != len(inputs):
                raise RuntimeError(f"infer_batch mengembalikan {len(results)} hasil untuk {len(inputs)} input")
        except BaseException as error:  # noqa: BLE001 -- dilaporkan ke semua kamera di batch ini
            self.stats.batch_failures += 1
            for unit in ready:
                unit.fail(error)
            return 0
        self.stats.infer_seconds += self._now() - started
        self.stats.batches += 1

        for unit, result in zip(ready, results):
            try:
                unit.finish(result)
            except BaseException as error:  # noqa: BLE001
                self.stats.unit_failures += 1
                unit.fail(error)
                continue
            self.stats.frames += 1
            self.stats.per_camera_frames[unit.camera_id] = self.stats.per_camera_frames.get(unit.camera_id, 0) + 1
        return len(ready)

    def run(self, stop: threading.Event) -> None:
        """Loop sampai `stop` di-set. Menunggu memakai `stop.wait` supaya responsif."""
        while not stop.is_set():
            delay = self.clock.seconds_until_next()
            if delay > 0:
                if self._sleep is not None:
                    self._sleep(delay)
                elif stop.wait(delay):
                    break
            self.clock.fire()
            self.run_tick()
            deadline = self.clock.next_deadline
            if self._idle is not None and deadline is not None and self._now() < deadline:
                idle_started = self._now()
                self._idle(deadline)
                self.stats.idle_seconds += self._now() - idle_started


def tick_fps_for(scheduler: str, tick_fps: Optional[float], target_fps: Optional[float]) -> Optional[float]:
    """Frekuensi detak efektif, atau None bila penjadwal tidak dipakai."""
    if scheduler != "tick":
        return None
    fps = tick_fps if tick_fps else target_fps
    if not fps or fps <= 0:
        raise ValueError("core.scheduler: tick butuh core.tick_fps atau core.target_fps > 0")
    return float(fps)
