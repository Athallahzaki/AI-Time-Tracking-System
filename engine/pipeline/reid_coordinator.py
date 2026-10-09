"""Koordinator ReID: satu inti identitas untuk semua kamera (dokumen 12 §3.6).

Memegang `identity.reid.PendingIdentities` (galeri harian + kelompok ANON +
aturan gabung) di bawah SATU kunci, dan menerjemahkan keputusannya:

- `Assignment` per track → label untuk kamera pemilik track itu, dititipkan ke
  kotak masuk kamera (deque). Kamera menerapkannya di thread-nya sendiri pada
  frame berikutnya (`reid_tap.py`), persis seperti hasil worker wajah P7:
  state presence tidak pernah diubah dari thread lain.
- `Resolution` → event `identity.resolved` (kontrak ea-k1), dipancarkan di
  bawah kunci yang sama dengan gerbang interval (`interval_gate`). Itulah yang
  menjamin urutan yang dicek conformance: setiap interval berlabel ANON terbit
  SEBELUM `identity.resolved`-nya dan masuk `moved_intervals`; interval yang
  ditutup sesudahnya langsung memakai person_id karyawan.

Urutan kunci: koordinator → emit runtime. Tidak ada jalur yang memegang kunci
emit lalu meminta kunci koordinator, jadi tidak ada deadlock.

Hari: galeri, kelompok ANON, dan rentang dikosongkan sekali sehari pada
`reid.daily_purge_time` (jam lokal mesin engine, default 00:00) — terjadwal
lewat ticker runtime (`maybe_purge`), jadi tetap terjadi walau tidak ada orang
yang terlihat sesudahnya, dan juga saat pengamatan pertama melewati batas itu.
"Hari" ReID = tanggal lokal dari (`at` - jam purge), sehingga jadwal dan
pengamatan selalu sepakat hari mana yang sedang berjalan. Kelompok ANON yang
belum selesai dilaporkan di log; interval mereka tetap berlabel ANON dan sampai
ke HR lewat backend. Track yang masih hidup saat purge TIDAK dicabut labelnya
(kehadirannya tidak hilang); ia dinilai ulang dari galeri kosong pada embedding
berikutnya.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import numpy as np

from ..api import events
from ..identity.reid import (
    Assignment, BodyObservation, PendingIdentities, ReidConfig, Resolution, TrackClosed,
)

logger = logging.getLogger("engine.pipeline.reid_coordinator")

Emit = Callable[[Dict[str, Any]], Any]

KIND_LABEL = "label"
KIND_RETRY = "retry"
SOURCE_REID_RETRO = "reid_retro"

# (kind, track_uuid, person_id, identity_source)
InboxItem = Tuple[str, str, Optional[str], Optional[str]]


def local_day(at: float, offset_seconds: float = 0.0) -> str:
    """Tanggal lokal hari ReID; hari berganti pada jam purge (offset dari 00:00)."""
    return datetime.fromtimestamp(at - offset_seconds).strftime("%Y-%m-%d")


def anon_id_factory(nonce: str) -> Callable[[str, int], str]:
    """`ANON-<hari><nonce><n>`. Nonce per proses: engine yang restart di tengah hari
    memulai hitungan dari 1 lagi, dan tanpa nonce `ANON-...0001` yang kedua akan
    digabung backend dengan orang lain yang memakai ID itu pagi tadi."""
    def make(day: str, n: int) -> str:
        return f"ANON-{day.replace('-', '')}{nonce}{n:04d}"
    return make


@dataclass
class ReidMetrics:
    observations: int = 0
    embeddings: int = 0
    embed_failed: int = 0
    anon_groups: int = 0
    reid_matches: int = 0
    resolutions: int = 0
    revoked: int = 0
    days_purged: int = 0

    def as_dict(self) -> Dict[str, int]:
        return dict(self.__dict__)


class ReidCoordinator:
    def __init__(self, config: ReidConfig, emit_event: Emit,
                 now: Callable[[], float] = time.time,
                 day_of: Optional[Callable[[float], str]] = None,
                 nonce: Optional[str] = None,
                 purge_offset_seconds: float = 0.0) -> None:
        self.config = config
        self._anon_ids = anon_id_factory(nonce or uuid_module.uuid4().hex[:4])
        self._emit = emit_event
        self._now = now
        offset = float(purge_offset_seconds)
        self._day_of = day_of or (lambda at: local_day(at, offset))
        self._lock = threading.RLock()
        self._core: Optional[PendingIdentities] = None
        self._inboxes: Dict[str, Deque[InboxItem]] = {}
        self._owner: Dict[str, str] = {}            # track_uuid -> camera_id
        self._resolved: Dict[str, str] = {}         # anon_id -> person_id
        self._anon_intervals: Dict[str, List[str]] = {}
        self._known_anon: set = set()
        self.metrics = ReidMetrics()

    # -- kamera ---------------------------------------------------------------

    def register(self, camera_id: str) -> Deque[InboxItem]:
        with self._lock:
            inbox = self._inboxes.get(camera_id)
            if inbox is None:
                inbox = self._inboxes[camera_id] = collections.deque()
            return inbox

    @property
    def core(self) -> Optional[PendingIdentities]:
        return self._core

    def snapshot_metrics(self) -> Dict[str, int]:
        with self._lock:
            return self.metrics.as_dict()

    # -- masukan --------------------------------------------------------------

    def observe(self, obs: BodyObservation) -> Assignment:
        with self._lock:
            core = self._core_for(obs.at)
            self._owner[obs.track_uuid] = obs.camera_id
            self.metrics.observations += 1
            if obs.embedding is not None:
                self.metrics.embeddings += 1
            assignment = core.observe(obs)
            self._route(assignment, obs.camera_id)
            return assignment

    def close(self, msg: TrackClosed) -> None:
        with self._lock:
            if self._core is not None:
                self._core.close(msg)

    def forget_person(self, person_id: str) -> Tuple[int, int]:
        """Hapus data tubuh orang ini (galeri + klaim ReID di track tanpa wajah).

        Dipanggil dari handler `forget_person` runtime. (prototipe, track dicabut).
        """
        with self._lock:
            if self._core is None:
                return 0, 0
            removed, revoked = self._core.forget_person(person_id)
            for uuid in revoked:
                self.metrics.revoked += 1
                self._push(self._owner.get(uuid), (KIND_LABEL, uuid, None, None))
            return removed, len(revoked)

    def maybe_purge(self, now: float) -> bool:
        """Dipanggil berkala oleh ticker runtime. True = cache baru saja dikosongkan."""
        with self._lock:
            if self._core is None:
                return False
            day = self._day_of(now)
            if day <= self._core.day:
                return False
            self._purge(day)
            return True

    def deliver(self, job: Any, vector: Optional[np.ndarray]) -> None:
        """Callback `ReidWorker`. None = crop tidak diproses; kamera boleh mencoba lagi."""
        if vector is None:
            self._push(job.camera_id, (KIND_RETRY, job.track_uuid, None, None))
            with self._lock:
                self.metrics.embed_failed += 1
            return
        try:
            obs = BodyObservation(
                camera_id=job.camera_id, track_id=job.track_id, track_uuid=job.track_uuid,
                at=job.at, embedding=vector, face_person_id=job.face_person_id, zone=job.zone,
            )
        except ValueError as error:
            logger.warning("embedding ReID %s ditolak: %s", job.track_uuid, error)
            self._push(job.camera_id, (KIND_RETRY, job.track_uuid, None, None))
            return
        self.observe(obs)

    # -- gerbang interval (dipanggil assembler di thread kamera) ---------------

    def interval_gate(self, person_id: str, track_uuid: str, emit: Callable[[str], str]) -> str:
        with self._lock:
            label = self._resolved.get(person_id, person_id)
            interval_id = emit(label)
            if label.upper().startswith("ANON-"):
                self._anon_intervals.setdefault(label, []).append(interval_id)
            return interval_id

    # -- internal -------------------------------------------------------------

    def _core_for(self, at: float) -> PendingIdentities:
        day = self._day_of(at)
        if self._core is None:
            self._core = PendingIdentities(day, self.config, anon_id_factory=self._anon_ids)
        elif day > self._core.day:
            self._purge(day)
        return self._core

    def _purge(self, day: str) -> None:
        """Kosongkan galeri tubuh, kelompok ANON, dan rentang (data penampilan harian)."""
        assert self._core is not None
        persons = len(self._core.gallery)
        report = self._core.purge_day(day)
        self.metrics.days_purged += 1
        logger.info("ReID: cache hari %s dikosongkan (%d orang di galeri, %d kelompok ANON belum selesai)",
                    report.day, persons, len(report.unresolved_anon_ids))
        if report.unresolved_anon_ids:
            logger.warning(
                "ReID hari %s ditutup: %d kelompok ANON tidak terselesaikan (%s)",
                report.day, len(report.unresolved_anon_ids),
                ", ".join(report.unresolved_anon_ids[:10]),
            )
        self._owner.clear()
        self._resolved.clear()
        self._anon_intervals.clear()
        self._known_anon.clear()

    def _push(self, camera_id: Optional[str], item: InboxItem) -> None:
        if camera_id is None:
            return
        inbox = self._inboxes.get(camera_id)
        if inbox is not None:
            inbox.append(item)

    def _route(self, assignment: Assignment, camera_id: str) -> None:
        if assignment.anon_id and assignment.anon_id not in self._known_anon:
            self._known_anon.add(assignment.anon_id)
            self.metrics.anon_groups += 1
            logger.info("[%s] kelompok %s dibuka untuk %s", camera_id,
                        assignment.anon_id, assignment.track_uuid)
        if assignment.identity_source == "reid" and assignment.person_id \
                and not assignment.person_id.upper().startswith("ANON-"):
            self.metrics.reid_matches += 1
        # Label hanya dikirim bila ada. "Tidak ada label" bukan pencabutan: track yang
        # belum punya embedding, atau yang hidup melintasi purge harian, tidak boleh
        # kehilangan label lamanya. Pencabutan selalu lewat `revoked` (termasuk diri sendiri).
        if assignment.person_id is not None:
            self._push(camera_id, (KIND_LABEL, assignment.track_uuid,
                                   assignment.person_id, assignment.identity_source))
        for uuid in assignment.revoked:
            self.metrics.revoked += 1
            self._push(self._owner.get(uuid), (KIND_LABEL, uuid, None, None))
        for resolution in assignment.resolutions:
            self._resolve(resolution)

    def _resolve(self, resolution: Resolution) -> None:
        moved = self._anon_intervals.pop(resolution.anon_id, [])
        self._resolved[resolution.anon_id] = resolution.person_id
        self.metrics.resolutions += 1
        self._emit(events.identity_resolved(
            self._now(), resolution.anon_id, resolution.person_id, resolution.at,
            resolution.reason, resolution.track_uuids, moved,
            trigger_track_uuid=resolution.trigger_track_uuid,
        ))
        logger.info("%s diselesaikan ke %s (%s, %d track, %d interval dipindah)",
                    resolution.anon_id, resolution.person_id, resolution.reason,
                    len(resolution.track_uuids), len(moved))
        for uuid in resolution.track_uuids:
            if uuid == resolution.trigger_track_uuid:
                continue
            self._push(self._owner.get(uuid),
                       (KIND_LABEL, uuid, resolution.person_id, SOURCE_REID_RETRO))


class ReidRuntime:
    """Yang dipegang `EngineRuntime` bila `reid.enabled`: koordinator + worker."""

    def __init__(self, settings: Any, coordinator: ReidCoordinator, worker: Any) -> None:
        self.settings = settings
        self.coordinator = coordinator
        self.worker = worker
        self.crop_rules = settings.crop_rules()

    def tap_for(self, camera_id: str, assembler: Any) -> Any:
        from .reid_tap import ReidCameraTap

        return ReidCameraTap(
            camera_id, self.coordinator, self.worker.submit, assembler.clock_for,
            assembler, self.crop_rules, self.settings.embed_interval_seconds,
        )

    def stop(self) -> None:
        self.worker.stop()

    def snapshot_metrics(self) -> Dict[str, Any]:
        return {"core": self.coordinator.snapshot_metrics(), "worker": self.worker.snapshot_metrics()}


def build_reid_runtime(settings: Any, emit_event: Emit,
                       embed: Optional[Callable[[List[np.ndarray]], np.ndarray]] = None,
                       start: bool = True) -> Optional[ReidRuntime]:
    """None bila `reid.enabled` false. Model gagal dimuat = ReidModelUnavailable (start ditolak).

    `embed` disuntikkan oleh tes (embedder palsu); engine asli memuat ONNX.
    """
    if not settings.enabled:
        return None
    from .reid_worker import ReidWorker

    if embed is None:
        from ..identity.reid.embedder_onnx import build_reid_embedder

        embed = build_reid_embedder(settings)
    merge_config = settings.merge_config()
    if settings.match_threshold is None:
        logger.warning(
            "reid.match_threshold kosong: memakai usulan %.2f yang BELUM dikalibrasi. "
            "Isi dari MODEL-CARD (eval_reid.py pada crop berlabel) sebelum uji akurasi.",
            merge_config.match_threshold,
        )
    coordinator = ReidCoordinator(merge_config, emit_event,
                                  purge_offset_seconds=settings.purge_offset_seconds())
    worker = ReidWorker(embed, coordinator.deliver, max_queue=settings.worker_queue,
                        max_batch=settings.max_batch, max_age_seconds=settings.max_age_seconds)
    if start:
        worker.start()
    logger.info("ReID aktif: ambang %.2f, margin %.2f, embedding tiap %.0f dtk/track, "
                "cache dikosongkan tiap hari pukul %s",
                merge_config.match_threshold, merge_config.match_margin,
                settings.embed_interval_seconds, settings.daily_purge_time)
    return ReidRuntime(settings, coordinator, worker)
