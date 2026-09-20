"""Perakit interval kehadiran: mengubah siklus hidup track jadi `presence.interval`.

Ini benda yang menyambungkan `identity/` ke `api/`, dan tempat tiga aturan §4
benar-benar ditegakkan:

**Interval dimulai saat track lahir, bukan saat wajah terbaca** (§4.4). Orang
masuk 10:00:00, wajahnya terbaca 10:00:08. Delapan detik per kejadian, lima
belas kali keluar-masuk sehari, dua menit yang dicuri dari jatah yang cuma tiga
puluh menit — oleh latensi pengenalan, bukan oleh orangnya.

**Kamera putus mengakhiri semua track serentak, dengan `camera_lost`** (§2.3).
Tidak seorang pun pulang. Kode alasannya yang membedakan, dan tanpa itu satu
ruangan penuh orang ditandai pulang pada detik yang sama.

**Penyambungan hanya atas bukti perseptual** (§4.3). Orang yang teroklusi tiga
detik tidak boleh menghasilkan dua interval dan satu celah.

Soal penyambungan, satu koreksi terhadap dugaan yang wajar tapi salah: interval
yang ditutup **tidak perlu ditahan** menunggu kemungkinan tersambung. Rantainya
dibawa MAJU oleh interval kedua lewat `prev_interval_id`, bukan mundur oleh
yang pertama — jadi menahan yang pertama justru menghalangi, karena yang kedua
butuh id-nya sudah terbit. Yang dibutuhkan cuma ingatan pendek: interval yang
baru ditutup disimpan selama N detik supaya bisa ditunjuk.

Dan keputusan menyambung memang tidak bisa diambil saat track lahir, karena
saat itu identitasnya belum diketahui — ia diambil saat track baru terkonfirmasi.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..api import events
from ..api.events import PtsClock
from .zones import ZONE_INTERIOR, ZoneLabeller

Emit = Callable[[dict], None]

# Konstanta perseptual, sementara. Nilai sebenarnya keluar dari rekaman B1
# (§13, §15): berapa lama jeda masih bisa diyakini tracker sebagai kehadiran
# yang sama. Ini BUKAN konstanta kebijakan -- "tiga menit terlalu singkat untuk
# dihitung istirahat" adalah kalimat yang tidak boleh ada di engine.
DEFAULT_STITCH_WINDOW_SECONDS = 5.0


@dataclass
class _Presence:
    """Satu kehadiran yang sedang berjalan di bawah satu track."""

    track_uuid: str
    camera_id: str
    stream_epoch: int
    track_started_pts: float
    start_zone: str
    person_id: Optional[str] = None
    start_pts: Optional[float] = None
    start_source: str = "face"
    confidence: float = 0.0
    evidence_count: int = 1
    prev_interval_id: Optional[str] = None
    last_zone: str = ZONE_INTERIOR


@dataclass(frozen=True)
class _Closed:
    """Interval yang baru ditutup, disimpan selama jendela penyambungan."""

    interval_id: str
    camera_id: str
    stream_epoch: int
    person_id: str
    end_pts: float
    end_zone: str


@dataclass
class AssemblerMetrics:
    intervals_emitted: int = 0
    stitches: int = 0
    unidentified_closed: int = 0


class PresenceAssembler:
    def __init__(
        self,
        emit: Emit,
        zones: Optional[ZoneLabeller] = None,
        stitch_window_seconds: float = DEFAULT_STITCH_WINDOW_SECONDS,
        interval_prefix: str = "iv",
    ) -> None:
        self._emit = emit
        self._zones = zones or ZoneLabeller()
        self._stitch_window = stitch_window_seconds
        self._prefix = interval_prefix

        self._clocks: Dict[str, PtsClock] = {}
        self._open: Dict[str, _Presence] = {}
        self._closed: List[_Closed] = []
        self._counters: Dict[str, itertools.count] = {}
        # Di __init__, BUKAN sebagai atribut kelas: dict yang dideklarasikan di
        # badan kelas dibagi semua instance, dan dua kamera yang dirakit dua
        # assembler berbeda akan saling melihat interval masing-masing.
        self._resumed_from: Dict[str, str] = {}
        self.metrics = AssemblerMetrics()

    # ---------------- kamera ----------------

    def camera_online(self, camera_id: str, wallclock_now: float, fps: float,
                      door_region: Optional[Sequence[float]] = None) -> PtsClock:
        """Stream baru: epoch naik, offset ditetapkan ulang, pts kembali nol."""
        previous = self._clocks.get(camera_id)
        clock = (
            previous.reconnect(wallclock_now)
            if previous is not None
            else PtsClock(camera_id=camera_id, stream_epoch=0, offset=wallclock_now)
        )
        self._clocks[camera_id] = clock

        if door_region is not None:
            self._zones.set_region(camera_id, door_region)

        self._emit(events.camera_online(clock, fps=fps))
        return clock

    def camera_failed(self, camera_id: str, wallclock_now: float, pts: float,
                      reason: str = "connection_refused", retry_in_seconds: float = 5.0) -> None:
        """Semua track di kamera ini berakhir serentak — dan tidak seorang pun pulang."""
        self._emit(events.camera_failed(camera_id, wallclock_now, reason, retry_in_seconds))

        for track_uuid in [
            uuid for uuid, presence in self._open.items() if presence.camera_id == camera_id
        ]:
            self.track_ended(
                track_uuid, pts=pts, reason="camera_lost",
                zone=self._open[track_uuid].last_zone, end_source="forced",
            )

    def clock_for(self, camera_id: str) -> PtsClock:
        clock = self._clocks.get(camera_id)
        if clock is None:
            raise KeyError(f"kamera `{camera_id}` belum online")
        return clock

    # ---------------- siklus hidup track ----------------

    def track_started(self, track_uuid: str, camera_id: str, pts: float,
                      bbox: Optional[Sequence[float]] = None) -> str:
        clock = self.clock_for(camera_id)
        zone = self._zones.label(camera_id, bbox) if bbox is not None else self._zones.unconfigured_default

        self._open[track_uuid] = _Presence(
            track_uuid=track_uuid, camera_id=camera_id, stream_epoch=clock.stream_epoch,
            track_started_pts=pts, start_zone=zone, last_zone=zone,
        )
        self._emit(events.track_started(clock, track_uuid, pts, zone))
        return zone

    def track_moved(self, track_uuid: str, bbox: Sequence[float]) -> None:
        """Perbarui zona terakhir yang diketahui.

        Zona saat track BERAKHIR yang menanggung beban, dan saat itu bbox
        terakhir sering sudah tidak tersedia -- track berakhir justru karena
        tidak terlihat lagi. Jadi zona terakhir diingat selagi masih terlihat.
        """
        presence = self._open.get(track_uuid)
        if presence is None:
            return
        presence.last_zone = self._zones.label(presence.camera_id, bbox)

    def identified(self, track_uuid: str, person_id: str, pts: float,
                   similarity: float, margin: float, evidence_count: int,
                   confidence: float) -> Optional[str]:
        """Track terkonfirmasi. Di sinilah keputusan menyambung diambil.

        Mengembalikan `prev_interval_id` kalau tersambung.
        """
        presence = self._open.get(track_uuid)
        if presence is None:
            return None

        clock = self.clock_for(presence.camera_id)
        presence.person_id = person_id
        presence.confidence = confidence
        presence.evidence_count = evidence_count
        # §4.4: batas dimundurkan ke kelahiran track, bukan ke saat wajah terbaca.
        presence.start_pts = presence.track_started_pts
        presence.start_source = "face"

        self._emit(events.track_identified(
            clock, track_uuid, person_id, pts=pts,
            track_started_pts=presence.track_started_pts,
            similarity=similarity, margin=margin, evidence_count=evidence_count,
        ))

        stitched = self._find_stitch(presence, pts)
        if stitched is not None:
            gap = round(presence.track_started_pts - stitched.end_pts, 3)
            presence.prev_interval_id = stitched.interval_id
            presence.start_source = "tracking"
            presence.start_zone = stitched.end_zone
            self._closed.remove(stitched)
            self.metrics.stitches += 1
            self._emit(events.track_resumed(
                clock, track_uuid, prev_track_uuid=_track_of(stitched.interval_id, self._resumed_from),
                person_id=person_id, gap_seconds=max(0.0, gap), pts=pts,
            ))
            return stitched.interval_id

        return None

    def identity_released(self, track_uuid: str, pts: float) -> None:
        """Klaim dicabut di tengah track: interval ditutup, track berlanjut.

        Satu track, dua interval — dan itu persis kenapa `interval_id` tidak
        boleh sama dengan `track_uuid`.
        """
        presence = self._open.get(track_uuid)
        if presence is None or presence.person_id is None:
            return

        self._close_interval(presence, pts, presence.last_zone, "tracking", "identity_released")

        presence.person_id = None
        presence.start_pts = None
        presence.prev_interval_id = None
        presence.track_started_pts = pts
        presence.start_zone = presence.last_zone

    def track_ended(self, track_uuid: str, pts: float, reason: str,
                    zone: Optional[str] = None, end_source: Optional[str] = None) -> None:
        presence = self._open.pop(track_uuid, None)
        if presence is None:
            return

        clock = self.clock_for(presence.camera_id)
        exit_zone = zone or presence.last_zone

        if presence.person_id is None:
            # Tanpa identitas tidak ada kehadiran yang bisa dicatat atas nama
            # siapa pun. Tapi orangnya ADA -- itu yang `person.unidentified_present`
            # laporkan, dan bukan tugas perakit ini.
            self.metrics.unidentified_closed += 1
        else:
            if end_source is None:
                end_source = "forced" if reason in {"camera_lost", "engine_shutdown"} else "tracking"
            self._close_interval(presence, pts, exit_zone, end_source, reason)

        self._emit(events.track_ended(clock, track_uuid, pts, reason, exit_zone))

    # ---------------- internal ----------------

    def _close_interval(self, presence: _Presence, end_pts: float, end_zone: str,
                        end_source: str, end_reason: str) -> str:
        clock = self.clock_for(presence.camera_id)
        interval_id = self._next_interval_id(presence.camera_id)
        start_pts = presence.start_pts if presence.start_pts is not None else presence.track_started_pts

        self._emit(events.presence_interval(
            clock, interval_id, presence.person_id,
            start_pts=start_pts, end_pts=max(start_pts, end_pts),
            start_source=presence.start_source, end_source=end_source,
            start_zone=presence.start_zone, end_zone=end_zone,
            end_reason=end_reason, identity_confidence=presence.confidence,
            evidence_count=presence.evidence_count, track_uuid=presence.track_uuid,
            prev_interval_id=presence.prev_interval_id,
        ))
        self.metrics.intervals_emitted += 1

        self._closed.append(_Closed(
            interval_id=interval_id, camera_id=presence.camera_id,
            stream_epoch=presence.stream_epoch, person_id=presence.person_id,
            end_pts=end_pts, end_zone=end_zone,
        ))
        self._resumed_from[interval_id] = presence.track_uuid
        return interval_id

    def _find_stitch(self, presence: _Presence, pts: float) -> Optional[_Closed]:
        """Kehadiran yang sama berlanjut, atau bukan.

        Empat syarat, semuanya perseptual: orang yang sama, kamera yang sama,
        ruang pts yang sama, dan jeda dalam batas yang masih bisa diyakini
        tracker. Tidak ada syarat kelima yang berbunyi "terlalu singkat untuk
        dihitung istirahat" -- yang itu kebijakan, dan begitu ia masuk ke sini
        aturan kantor sudah bersembunyi di dalam sensor.
        """
        self._prune_closed(presence.track_started_pts)

        candidates = [
            closed for closed in self._closed
            if closed.person_id == presence.person_id
            and closed.camera_id == presence.camera_id
            # Lintas epoch tidak disambung: setelah reconnect, pts kembali nol
            # sehingga jedanya tidak bisa dihitung, dan tracker kehilangan
            # seluruh state-nya -- bukti perseptualnya memang sudah tidak ada.
            and closed.stream_epoch == presence.stream_epoch
            and 0.0 <= presence.track_started_pts - closed.end_pts <= self._stitch_window
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda closed: closed.end_pts)

    def _prune_closed(self, now_pts: float) -> None:
        self._closed = [
            closed for closed in self._closed
            if now_pts - closed.end_pts <= self._stitch_window
        ]

    def _next_interval_id(self, camera_id: str) -> str:
        counter = self._counters.setdefault(camera_id, itertools.count(1))
        return f"{self._prefix}_{camera_id}-{next(counter):04d}"


def _track_of(interval_id: str, mapping: Dict[str, str]) -> str:
    return mapping.get(interval_id, interval_id.replace("iv_", "tr_", 1))
