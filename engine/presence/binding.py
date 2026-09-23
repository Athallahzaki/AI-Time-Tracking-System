"""Penyambung: pengamatan pipeline → identitas → interval → gerbang keluar.

Sampai berkas ini ada, `identity/`, `presence/`, dan `api/` adalah tiga lapisan
yang lengkap dan tidak saling bicara. Ini yang menyambungkannya, dan ia
memenuhi dua kontrak milik B sekaligus: `TrackListener` (dipanggil frame loop)
dan `RequestConsumer` (dipanggil `ZonePriorityQueue`).

Tiga hal yang diputuskan di sini karena tidak ada tempat lain yang bisa:

**`track_uuid` yang tidak pernah didaur ulang.** `pipeline/zoning.py` memakai
`f"{camera_id}-t{track.track_id}"` sebagai penahan sementara dan menandai
sendiri bahwa itu harus diganti. Alasannya bukan estetika: hasil pengenalan
datang terlambat beberapa frame, dan tracker mendaur ulang `track_id` untuk
orang lain. Kalau kuncinya `track_id`, embedding milik orang yang sudah pergi
akan dipasangkan ke orang yang baru masuk — tanpa error, dan yang tercatat
hadir adalah orang yang salah. Di sini uuid membawa nomor generasi yang naik
setiap kali id yang sama lahir kembali.

**Identitas ditulis balik ke `track.attributes`.** `ZonePriorityQueue`
membaca `identity_state` untuk menentukan prioritas, dan hari ini selalu
membaca `None` sehingga setiap track terlihat `PENDING` selamanya. Menulisnya
balik membuat penjadwalan berhenti membuang percobaan pada track yang sudah
terkonfirmasi.

**Engine yang tidak bisa mengenali siapa pun harus bersuara.** Tanpa
`recognize` yang terpasang, seluruh sistem tetap berjalan mulus dan mencatat
nol kehadiran: log bersih, dashboard hidup, tidak ada yang salah kelihatannya.
Itu mode kegagalan terburuk di §9.9, dan `health()` di bawah ada supaya ia
punya suara di `engine.health`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from ..identity import Evidence, IdentityArbiter, Outcome, RecognitionScheduler
from ..identity.ports import IdentityState
from ..ports.frame import Frame
from ..ports.tracking import Track, TrackState
from .assembler import PresenceAssembler
from .zones import ZONE_INTERIOR

logger = logging.getLogger("engine.presence.binding")

ZONE_ATTRIBUTE = "zone"
ENTRY_ZONE_ATTRIBUTE = "entry_zone"
IDENTITY_STATE_ATTRIBUTE = "identity_state"
IDENTITY_ATTRIBUTE = "identity"
TRACK_UUID_ATTRIBUTE = "track_uuid"

# Berapa lama track boleh hilang sebelum berakhirnya dianggap terhalang, bukan
# kepergian. Perseptual: ini soal tracker, bukan soal aturan kantor.
Recognizer = Callable[[Track, Frame], Optional[Evidence]]


@dataclass
class BindingMetrics:
    tracks_opened: int = 0
    tracks_closed: int = 0
    evidence_submitted: int = 0
    recognitions_attempted: int = 0
    recognitions_empty: int = 0
    identified: int = 0
    released: int = 0

    @property
    def ever_identified_anyone(self) -> bool:
        return self.identified > 0


class EngineBinding:
    """Memenuhi `TrackListener` dan `RequestConsumer` sekaligus."""

    def __init__(
        self,
        arbiter: IdentityArbiter,
        assembler: PresenceAssembler,
        scheduler: Optional[RecognitionScheduler] = None,
        recognize: Optional[Recognizer] = None,
        uuid_prefix: str = "tr",
    ) -> None:
        # The runtime passes `tr_<run nonce>` so a uuid is never reused across
        # engine restarts or camera rebuilds (contract: "tidak pernah didaur ulang").
        self._uuid_prefix = uuid_prefix
        self._arbiter = arbiter
        self._assembler = assembler
        self._scheduler = scheduler
        self._recognize = recognize

        self._uuid_of: Dict[tuple, str] = {}
        self._generation: Dict[tuple, int] = {}
        self._track_by_uuid: Dict[str, Track] = {}
        # uuid -> camera. Mencari balik lewat track_id saja akan mencocokkan
        # kamera yang salah begitu ada lima kamera: `track_id` unik per tracker,
        # bukan per sistem, dan dua kamera rutin memakai angka yang sama.
        self._camera_by_uuid: Dict[str, str] = {}
        self._frame_by_camera: Dict[str, Frame] = {}
        self.metrics = BindingMetrics()

    # ---------------- identitas track ----------------

    def uuid_for(self, camera_id: str, track_id: int) -> str:
        """Kunci yang unik seumur hidup track, bukan seumur hidup `track_id`.

        Generasi naik setiap kali pasangan (kamera, track_id) lahir kembali,
        jadi hasil pengenalan yang datang terlambat untuk generasi lama tidak
        bisa menempel ke orang yang menempati id itu sekarang.
        """
        key = (camera_id, track_id)
        existing = self._uuid_of.get(key)
        if existing is not None:
            return existing

        generation = self._generation.get(key, 0) + 1
        self._generation[key] = generation
        uuid = f"{self._uuid_prefix}_{camera_id}-t{track_id}-g{generation}"
        self._uuid_of[key] = uuid
        self._camera_by_uuid[uuid] = camera_id
        return uuid

    def _forget(self, camera_id: str, track_id: int) -> Optional[str]:
        return self._uuid_of.pop((camera_id, track_id), None)

    # ---------------- TrackListener ----------------

    def on_tracks_updated(self, tracks: Sequence[Track], frame: Frame) -> None:
        camera_id = frame.metadata.source_id
        pts = self._pts_of(frame)
        if pts is None:
            return

        self._frame_by_camera[camera_id] = frame

        for track in tracks:
            if track.state not in (TrackState.NEW, TrackState.TRACKED):
                continue

            uuid = self.uuid_for(camera_id, track.track_id)
            track.attributes[TRACK_UUID_ATTRIBUTE] = uuid
            self._track_by_uuid[uuid] = track

            identity = self._arbiter.identity_of(uuid)
            if identity is None:
                self._open(uuid, camera_id, track, pts, frame)
            else:
                self._assembler.track_moved(uuid, self._normalized(track, frame))

            self._publish_identity(track, uuid)

        # Peluruhan kepercayaan berjalan dari waktu frame, bukan jam dinding:
        # seluruh aritmetika interval memakai PTS (§6.6), dan benchmark yang
        # berjalan lebih cepat dari waktu nyata harus meluruh dengan laju yang
        # sama supaya angkanya sebanding.
        for decision in self._arbiter.tick(pts):
            track = self._track_by_uuid.get(decision.identity.track_uuid)
            if track is not None:
                self._publish_identity(track, decision.identity.track_uuid)

    def on_track_lost(self, track: Track) -> None:
        """Hilang sementara, bukan hilang permanen.

        State identitas sengaja DIPERTAHANKAN: inilah yang §3.1 sebut sebagai
        memegang identitas lewat tracking saat orangnya membelakangi kamera.
        Membuangnya di sini berarti setiap oklusi tiga detik menghasilkan celah.
        """
        return None

    def on_track_removed(self, track: Track) -> None:
        camera_id = self._camera_of(track)
        if camera_id is None:
            return

        uuid = self._forget(camera_id, track.track_id) or track.attributes.get(TRACK_UUID_ATTRIBUTE)
        if uuid is None:
            return

        frame = self._frame_by_camera.get(camera_id)
        pts = self._pts_of(frame) if frame is not None else None
        if pts is None:
            pts = float(track.last_seen_timestamp)

        zone = track.attributes.get(ZONE_ATTRIBUTE, ZONE_INTERIOR)
        self._assembler.track_ended(uuid, pts=pts, reason=_reason_for(zone), zone=zone)
        self._arbiter.close_track(uuid)
        if self._scheduler is not None:
            self._scheduler.forget(uuid)

        self._track_by_uuid.pop(uuid, None)
        self._camera_by_uuid.pop(uuid, None)
        self.metrics.tracks_closed += 1

    # ---------------- RequestConsumer ----------------

    def __call__(self, request: Any) -> None:
        """Dipanggil `ZonePriorityQueue` saat sebuah track memenangkan giliran."""
        uuid = getattr(request, "track_uuid", None)
        if uuid is None:
            return

        track = self._track_by_uuid.get(uuid)
        frame = self._frame_by_camera.get(getattr(request, "camera_id", ""))
        if track is None or frame is None or self._recognize is None:
            self._complete(uuid, produced_evidence=False)
            return

        self.metrics.recognitions_attempted += 1
        try:
            evidence = self._recognize(track, frame)
        except Exception:
            logger.exception("pengenalan gagal untuk %s", uuid)
            evidence = None

        if evidence is None:
            self.metrics.recognitions_empty += 1
            self._complete(uuid, produced_evidence=False)
            return

        self.metrics.evidence_submitted += 1
        self.submit_evidence(uuid, evidence)
        self._complete(uuid, produced_evidence=True)

    def _complete(self, uuid: str, produced_evidence: bool) -> None:
        if self._scheduler is not None:
            self._scheduler.complete(uuid, produced_evidence=produced_evidence)

    # ---------------- inti ----------------

    def submit_evidence(self, uuid: str, evidence: Evidence) -> None:
        """Satu bukti masuk; keputusannya diterjemahkan jadi pesan protokol."""
        track = self._track_by_uuid.get(uuid)
        if track is None:
            return
        camera_id = self._camera_of(track)
        if camera_id is None:
            return

        decision = self._arbiter.observe(uuid, camera_id, evidence)
        identity = decision.identity

        if decision.outcome is Outcome.IDENTIFIED:
            self.metrics.identified += 1
            self._assembler.identified(
                uuid, identity.person_id, pts=evidence.pts,
                similarity=identity.similarity, margin=identity.margin,
                evidence_count=identity.evidence_count, confidence=identity.confidence,
            )
        elif decision.outcome is Outcome.IDENTITY_RELEASED:
            self.metrics.released += 1
            self._assembler.identity_released(uuid, pts=evidence.pts)

        self._publish_identity(track, uuid)

    def _open(self, uuid: str, camera_id: str, track: Track, pts: float, frame: Frame) -> None:
        self._arbiter.open_track(uuid, camera_id)
        self._assembler.track_started(uuid, camera_id, pts=pts, bbox=self._normalized(track, frame))
        self.metrics.tracks_opened += 1

    def _publish_identity(self, track: Track, uuid: str) -> None:
        """Tulis balik ke `track.attributes` supaya penjadwal berhenti buta."""
        identity = self._arbiter.identity_of(uuid)
        if identity is None:
            return
        track.attributes[IDENTITY_STATE_ATTRIBUTE] = identity
        track.attributes[IDENTITY_ATTRIBUTE] = identity.person_id
        track.attributes["identity_source"] = identity.identity_source
        track.attributes["identity_confidence"] = identity.confidence

    # ---------------- kesehatan ----------------

    def health(self) -> Dict[str, Any]:
        """Bahan untuk `engine.health`, termasuk kalau engine sedang berbohong.

        `models_loaded=False` di sini berarti tidak ada pengenal terpasang sama
        sekali. Sistem akan berjalan mulus dan mencatat nol kehadiran, dan itu
        harus terlihat di dashboard alih-alih ditemukan saat penggajian.
        """
        degraded = []
        if self._recognize is None:
            degraded.append("recognizer_not_wired")
        if self.metrics.recognitions_attempted and not self.metrics.ever_identified_anyone:
            degraded.append("no_identity_ever_confirmed")

        return {
            "models_loaded": self._recognize is not None,
            "degraded_components": degraded,
            "tracks_open": len(self._track_by_uuid),
            **{f"metric_{key}": value for key, value in vars(self.metrics).items()},
        }

    # ---------------- util ----------------

    @staticmethod
    def _pts_of(frame: Optional[Frame]) -> Optional[float]:
        if frame is None:
            return None
        return frame.metadata.pts

    def _camera_of(self, track: Track) -> Optional[str]:
        """Kamera pemilik track ini.

        Atribut `track_uuid` dipakai kalau ada. Kalau tidak -- misalnya
        `on_track_removed` dipanggil dengan salinan objek track, yang tidak
        dilarang kontrak `TrackListener` -- dicari balik dari pemetaan uuid.
        Pencarian balik hanya dipercaya kalau jawabannya TUNGGAL: `track_id`
        unik per tracker, bukan per sistem, dan menebak kamera berarti menutup
        kehadiran orang di ruangan yang salah.
        """
        uuid = track.attributes.get(TRACK_UUID_ATTRIBUTE)
        if isinstance(uuid, str) and uuid in self._camera_by_uuid:
            return self._camera_by_uuid[uuid]

        matches = {
            camera_id for (camera_id, track_id) in self._uuid_of
            if track_id == track.track_id
        }
        if len(matches) == 1:
            return next(iter(matches))
        if matches:
            logger.warning(
                "track_id %s ada di %s kamera; penutupan dilewati daripada menebak",
                track.track_id, len(matches),
            )
        return None

    @staticmethod
    def _normalized(track: Track, frame: Frame) -> Sequence[float]:
        width = float(frame.metadata.width or 0) or 1.0
        height = float(frame.metadata.height or 0) or 1.0
        box = track.bbox
        return (
            max(0.0, min(1.0, box.x1 / width)),
            max(0.0, min(1.0, box.y1 / height)),
            max(0.0, min(1.0, box.x2 / width)),
            max(0.0, min(1.0, box.y2 / height)),
        )


def _reason_for(zone: str) -> str:
    """Alasan berakhir yang diturunkan dari zona terakhir (§4.2).

    Track yang berakhir di pintu atau di tepi frame punya penjelasan geometris;
    track yang berakhir di tengah ruangan hampir pasti kegagalan tracking, dan
    label itulah yang membuat backend bisa membedakan celah palsu dari celah
    nyata tanpa tahu apa pun tentang tracking.
    """
    return "left_frame" if zone in {"door", "frame_edge"} else "occluded_timeout"
