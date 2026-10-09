"""Identitas tertunda `ANON-xxxx` dan atribusi mundur (dokumen 12 §3.6 butir 3).

Inti ReID yang memegang keadaan sepanjang hari. Masukannya pesan dari
`messages.py`; keluarannya `Assignment` per pengamatan dan `Resolution` — data
untuk event `identity.resolved` (kontrak paket ea-k1).

Alur per track tanpa wajah, saat embedding pertamanya datang:

1. Cocokkan ke galeri berjangkar wajah. Lolos ambang + margin dan lolos aturan
   waktu terhadap semua track orang itu → `person_id` orang itu, sumber `reid`.
2. Kalau tidak, cocokkan ke kelompok ANON yang belum selesai (aturan sama).
3. Kalau tidak, buka kelompok ANON baru.

Saat wajah terkonfirmasi di salah satu track kelompok, seluruh kelompok
diselesaikan ke karyawan itu (`face_confirmed`), lalu kelompok ANON lain yang
cocok dengan galeri orang itu ikut diselesaikan (`group_merged`).

Batas yang dijaga:

- ReID tidak pernah menetapkan identitas sendiri: setiap `person_id` karyawan
  di sini berasal dari wajah, langsung atau lewat galeri yang diisi wajah.
- ReID tidak pernah membatalkan wajah: pengamatan berwajah selalu menang, dan
  saat rentang hidup memanjang lalu bertabrakan, yang dicabut adalah klaim
  ReID, tidak pernah klaim wajah.
- `moved_intervals` TIDAK diisi di sini. Interval milik lapisan presence;
  perakit event menambahkannya dari `Resolution.track_uuids`.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Tuple

from .gallery import DailyGallery, PrototypeSet
from .merge import ReidConfig, TrackSpan, check_group, pick_best
from .messages import BodyObservation, TrackClosed

# Nilai identity_source di kontrak ($defs.identity_source).
SOURCE_FACE = "face"
SOURCE_TRACKING = "tracking"
SOURCE_REID = "reid"
SOURCE_REID_RETRO = "reid_retro"

REASON_FACE_CONFIRMED = "face_confirmed"
REASON_GROUP_MERGED = "group_merged"

# Urutan kekuatan klaim saat dua track satu orang bertabrakan waktu.
_STRENGTH = {SOURCE_FACE: 3, SOURCE_REID_RETRO: 2, SOURCE_REID: 1}


@dataclass(frozen=True)
class Resolution:
    """Data untuk satu event `identity.resolved` (tanpa amplop dan interval)."""

    anon_id: str
    person_id: str
    at: float
    reason: str
    track_uuids: Tuple[str, ...]
    trigger_track_uuid: Optional[str] = None

    def event_fields(self) -> Dict[str, object]:
        fields: Dict[str, object] = {
            "type": "identity.resolved",
            "anon_id": self.anon_id,
            "person_id": self.person_id,
            "at": format_at(self.at),
            "reason": self.reason,
            "track_uuids": list(self.track_uuids),
        }
        if self.trigger_track_uuid is not None:
            fields["trigger_track_uuid"] = self.trigger_track_uuid
        return fields


@dataclass(frozen=True)
class Assignment:
    """Identitas track sesudah satu pesan diproses.

    `person_id` bisa `ANON-...` (sumber `reid`) atau `None` (belum ada
    embedding, atau klaimnya baru dicabut). `revoked` = track lain yang klaim
    ReID-nya dicabut oleh pesan ini (mereka akan dinilai ulang pada embedding
    berikutnya).
    """

    track_uuid: str
    person_id: Optional[str]
    identity_source: Optional[str]
    anon_id: Optional[str] = None
    resolutions: Tuple[Resolution, ...] = ()
    revoked: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PurgeReport:
    day: str
    persons_purged: int
    unresolved_anon_ids: Tuple[str, ...]


@dataclass
class _Track:
    span: TrackSpan
    seq: int
    person_id: Optional[str] = None  # karyawan (face/reid/reid_retro)
    source: Optional[str] = None
    from_face: bool = False          # pernah membawa identitas wajah
    anon_id: Optional[str] = None    # kelompok, selesai maupun belum


@dataclass
class _Group:
    anon_id: str
    protos: PrototypeSet
    members: Set[str] = field(default_factory=set)
    resolved_to: Optional[str] = None


def format_at(at: float) -> str:
    stamp = datetime.fromtimestamp(at, tz=timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"


class PendingIdentities:
    """Inti ReID: galeri harian + kelompok ANON + aturan gabung."""

    def __init__(self, day: str, config: Optional[ReidConfig] = None,
                 anon_id_factory: Optional[Callable[[str, int], str]] = None) -> None:
        self.config = config or ReidConfig()
        self.gallery = DailyGallery(day, self.config.gallery_capacity,
                                    self.config.prototype_merge_similarity)
        self._anon_factory = anon_id_factory or _default_anon_id
        self._reset_state()

    def _reset_state(self) -> None:
        self._tracks: Dict[str, _Track] = {}
        self._groups: Dict[str, _Group] = {}
        self._seq = itertools.count(1)
        self._anon_seq = itertools.count(1)

    # ------------------------------------------------------------------ query

    @property
    def day(self) -> str:
        return self.gallery.day

    def identity_of(self, track_uuid: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
        track = self._tracks.get(track_uuid)
        if track is None:
            return None
        return self._effective(track)

    def group_members(self, anon_id: str) -> Tuple[str, ...]:
        group = self._groups.get(anon_id)
        return tuple(sorted(group.members)) if group else ()

    def unresolved_anon_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(a for a, g in self._groups.items()
                            if g.resolved_to is None and g.members))

    # ---------------------------------------------------------------- masukan

    def close(self, msg: TrackClosed) -> None:
        track = self._tracks.get(msg.track_uuid)
        if track is not None:
            track.span.extend(msg.at, track.span.last_location)
            track.span.ended = True

    def observe(self, obs: BodyObservation) -> Assignment:
        track = self._tracks.get(obs.track_uuid)
        if track is None:
            span = TrackSpan(obs.track_uuid, obs.camera_id, obs.at, obs.at,
                             obs.location, obs.location)
            track = self._tracks[obs.track_uuid] = _Track(span, next(self._seq))
        else:
            track.span.extend(obs.at, obs.location)

        if obs.face_person_id is not None:
            return self._observe_face(track, obs)

        revoked: List[str] = []
        if track.person_id is None and track.anon_id is None:
            if obs.embedding is not None:
                self._assign_without_face(track, obs)
        else:
            if obs.embedding is not None:
                group = self._groups.get(track.anon_id) if track.anon_id else None
                if group is not None and group.resolved_to is None:
                    group.protos.add(obs.embedding)
            revoked = self._enforce(track)
        person_id, source = self._effective(track)
        if source == SOURCE_FACE:
            # Identitas dari wajah yang kini dipegang tracker (pesan ini tanpa wajah).
            source = SOURCE_TRACKING
        return Assignment(track.span.track_uuid, person_id, source, track.anon_id,
                          revoked=tuple(revoked))

    # ------------------------------------------------------------- jalur wajah

    def _observe_face(self, track: _Track, obs: BodyObservation) -> Assignment:
        person = obs.face_person_id
        assert person is not None
        if obs.embedding is not None:
            self.gallery.add_observation(obs)

        resolutions: List[Resolution] = []
        group = self._groups.get(track.anon_id) if track.anon_id else None
        if group is not None and group.resolved_to is None:
            resolutions.append(self._resolve(group, person, obs.at,
                                             REASON_FACE_CONFIRMED, track.span.track_uuid))
        elif group is not None and group.resolved_to != person:
            # Kelompok sudah selesai ke orang lain; wajah menang, track keluar.
            group.members.discard(track.span.track_uuid)
            track.anon_id = None

        track.person_id = person
        track.source = SOURCE_FACE
        track.from_face = True

        revoked = self._enforce(track)
        resolutions.extend(self._sweep_groups(person, obs.at))
        return Assignment(track.span.track_uuid, person, SOURCE_FACE, track.anon_id,
                          tuple(resolutions), tuple(revoked))

    def _resolve(self, group: _Group, person: str, at: float, reason: str,
                 trigger: Optional[str]) -> Resolution:
        group.resolved_to = person
        for uuid in group.members:
            member = self._tracks[uuid]
            if not member.from_face:
                member.person_id = person
                member.source = SOURCE_REID_RETRO
        return Resolution(group.anon_id, person, at, reason,
                          tuple(sorted(group.members)), trigger)

    def _sweep_groups(self, person: str, at: float) -> List[Resolution]:
        """Kelompok ANON lain yang kini cocok dengan galeri orang ini."""
        out: List[Resolution] = []
        for group in list(self._groups.values()):
            if group.resolved_to is not None or not group.members or not len(group.protos):
                continue
            if pick_best(self.gallery.scores_set(group.protos), self.config) != person:
                continue
            person_spans = self._person_spans(person)
            if all(check_group(person_spans, self._tracks[u].span, self.config).ok
                   for u in group.members):
                out.append(self._resolve(group, person, at, REASON_GROUP_MERGED, None))
        return out

    # -------------------------------------------------------- jalur tanpa wajah

    def _assign_without_face(self, track: _Track, obs: BodyObservation) -> None:
        assert obs.embedding is not None
        person = pick_best(self.gallery.scores(obs.embedding), self.config)
        if person is not None and check_group(self._person_spans(person), track.span,
                                              self.config).ok:
            track.person_id = person
            track.source = SOURCE_REID
            return

        scored = [(g.anon_id, g.protos.score(obs.embedding)) for g in self._groups.values()
                  if g.resolved_to is None and g.members]
        scored.sort(key=lambda item: item[1], reverse=True)
        anon = pick_best(scored, self.config)
        if anon is not None:
            group = self._groups[anon]
            members = [self._tracks[u].span for u in group.members]
            if check_group(members, track.span, self.config).ok:
                self._join(group, track, obs)
                return
        anon = self._anon_factory(self.day, next(self._anon_seq))
        group = self._groups[anon] = _Group(
            anon, PrototypeSet(self.config.gallery_capacity,
                               self.config.prototype_merge_similarity))
        self._join(group, track, obs)

    @staticmethod
    def _join(group: _Group, track: _Track, obs: BodyObservation) -> None:
        group.members.add(track.span.track_uuid)
        assert obs.embedding is not None
        group.protos.add(obs.embedding)
        track.anon_id = group.anon_id
        track.source = SOURCE_REID

    # ---------------------------------------------------- tabrakan belakangan

    def _person_spans(self, person: str) -> List[TrackSpan]:
        return [t.span for t in self._tracks.values() if t.person_id == person]

    def _enforce(self, track: _Track) -> List[str]:
        """Rentang hidup memanjang bisa membuat klaim lama jadi mustahil.

        Yang dicabut selalu klaim yang lebih lemah (ReID sebelum wajah; sesama
        ReID: yang bergabung belakangan). Dua klaim wajah yang bertabrakan
        bukan urusan ReID — itu urusan arbiter — dan dibiarkan.
        """
        if track.person_id is not None:
            peers = [t for t in self._tracks.values() if t.person_id == track.person_id]
        elif track.anon_id is not None:
            group = self._groups[track.anon_id]
            peers = [self._tracks[u] for u in group.members]
        else:
            return []
        revoked: List[str] = []
        for other in peers:
            if other is track or other.span.track_uuid in revoked:
                continue
            if check_group([other.span], track.span, self.config).ok:
                continue
            weaker = self._weaker(track, other)
            if weaker is None:
                continue
            self._revoke(weaker)
            revoked.append(weaker.span.track_uuid)
            if weaker is track:
                break
        return revoked

    @staticmethod
    def _weaker(a: _Track, b: _Track) -> Optional[_Track]:
        sa, sb = _STRENGTH.get(a.source or "", 0), _STRENGTH.get(b.source or "", 0)
        if a.source == SOURCE_FACE and b.source == SOURCE_FACE:
            return None
        if sa != sb:
            return a if sa < sb else b
        return a if a.seq > b.seq else b

    def _revoke(self, track: _Track) -> None:
        if track.anon_id is not None:
            group = self._groups.get(track.anon_id)
            if group is not None:
                group.members.discard(track.span.track_uuid)
        track.anon_id = None
        track.person_id = None
        track.source = None

    def _effective(self, track: _Track) -> Tuple[Optional[str], Optional[str]]:
        if track.person_id is not None:
            return track.person_id, track.source
        if track.anon_id is not None:
            return track.anon_id, SOURCE_REID
        return None, None

    # ---------------------------------------------------------------- harian

    def purge_day(self, new_day: str) -> PurgeReport:
        """Akhir hari: galeri, kelompok, dan rentang dikosongkan.

        ANON yang belum selesai dilaporkan supaya bisa masuk alur "tidak
        dikenal" ke HR; ID-nya tidak dipakai lagi (awalan hari berbeda).
        """
        unresolved = self.unresolved_anon_ids()
        old_day = self.gallery.day
        purged = self.gallery.purge_day(new_day)
        self._reset_state()
        return PurgeReport(old_day, purged, unresolved)


def _default_anon_id(day: str, n: int) -> str:
    return f"ANON-{day.replace('-', '')}{n:04d}"
