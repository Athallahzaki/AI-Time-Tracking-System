"""Wasit identitas: satu-satunya tempat klaim dibuka, dipertahankan, dan dicabut.

Empat bug kebenaran §9 diselesaikan di sini, dan semuanya bug yang membuat
sistem mencatat data salah **tanpa memunculkan satu pun error**:

1. **Satu match tunggal tidak lagi membuka identitas** (§9.1). Implementasi
   lama menyetel `CONFIRMED` pada match pertama dan menyalinnya ke hilir; satu
   frame cukup untuk seseorang tercatat hadir. Sekarang konfirmasi menuntut
   bukti yang cukup banyak dan cukup tersebar (`evidence.py`), dan **tidak ada
   jalan lain** memasang `person_id` selain lewat `_confirm`.

2. **Uji margin ditegakkan** (§9.2), di `matcher.py`.

3. **Verifikasi yang tidak setuju menurunkan kepercayaan, bukan menukar
   identitas** (§9.4). Dulu satu frame buruk bisa merebut track yang sudah
   stabil: `update_with_match` menukar `identity` lalu mereset penghitung, dan
   tetap menyetel `CONFIRMED`. Sekarang pelepasan klaim butuh D ketidaksetujuan
   **berturut-turut terhadap orang yang sama**; satu frame nyasar hanya
   menurunkan kepercayaan.

4. **Dedup identitas antar track** (§9.5). Dua track di satu kamera tidak boleh
   sama-sama mengklaim karyawan yang sama. Yang similarity-nya lebih rendah
   melepas klaim.

Dan satu hal yang bukan bug melainkan kelalaian: identitas yang bertahan tanpa
wajah terlihat sekarang punya nama sendiri (`HELD`) dan kepercayaan yang
meluruh, bukan diam-diam ikut mengalir ke hilir seolah baru saja diverifikasi.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .evidence import (
    DEFAULT_MIN_EVIDENCE,
    DEFAULT_MIN_SPREAD_SECONDS,
    DEFAULT_WINDOW,
    EvidenceWindow,
)
from .matcher import MatrixMatcher
from .ports import Evidence, IdentityState, Match, TrackIdentity

# Konstanta perseptual. Semuanya tentang penglihatan dan tracker; tidak satu
# pun tentang peraturan kantor.
DEFAULT_DISAGREEMENTS_TO_RELEASE = 3
DEFAULT_HELD_AFTER_SECONDS = 3.0      # tanpa wajah selama ini -> dipegang tracker
DEFAULT_TTL_SECONDS = 60.0            # sejak wajah terakhir -> perlu verifikasi ulang
DEFAULT_HELD_HALFLIFE_SECONDS = 120.0 # peluruhan kepercayaan saat HELD


class Outcome(str, enum.Enum):
    """Apa yang harus dipancarkan lapisan api sebagai akibat pengamatan ini."""

    NOTHING = "nothing"
    IDENTIFIED = "identified"
    IDENTITY_CHANGED = "identity_changed"
    IDENTITY_RELEASED = "identity_released"
    STATE_CHANGED = "state_changed"


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    identity: TrackIdentity
    match: Optional[Match] = None
    from_person_id: Optional[str] = None
    reason: Optional[str] = None


class IdentityArbiter:
    def __init__(
        self,
        matcher: MatrixMatcher,
        window: int = DEFAULT_WINDOW,
        min_evidence: int = DEFAULT_MIN_EVIDENCE,
        min_spread_seconds: float = DEFAULT_MIN_SPREAD_SECONDS,
        disagreements_to_release: int = DEFAULT_DISAGREEMENTS_TO_RELEASE,
        held_after_seconds: float = DEFAULT_HELD_AFTER_SECONDS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        held_halflife_seconds: float = DEFAULT_HELD_HALFLIFE_SECONDS,
    ) -> None:
        self._matcher = matcher
        self._window = window
        self._min_evidence = min_evidence
        self._min_spread = min_spread_seconds
        self._disagreements_to_release = disagreements_to_release
        self._held_after = held_after_seconds
        self._ttl = ttl_seconds
        self._halflife = held_halflife_seconds

        self._identities: Dict[str, TrackIdentity] = {}
        self._windows: Dict[str, EvidenceWindow] = {}
        # (camera_id, person_id) -> track_uuid pemegang klaim saat ini.
        self._claims: Dict[Tuple[str, str], str] = {}

    # ---------------- siklus hidup track ----------------

    def open_track(self, track_uuid: str, camera_id: str) -> TrackIdentity:
        identity = self._identities.get(track_uuid)
        if identity is None:
            identity = TrackIdentity(track_uuid=track_uuid, camera_id=camera_id)
            self._identities[track_uuid] = identity
            self._windows[track_uuid] = EvidenceWindow(
                window=self._window,
                min_evidence=self._min_evidence,
                min_spread_seconds=self._min_spread,
            )
        return identity

    def close_track(self, track_uuid: str) -> Optional[TrackIdentity]:
        identity = self._identities.pop(track_uuid, None)
        self._windows.pop(track_uuid, None)
        if identity and identity.person_id:
            self._claims.pop((identity.camera_id, identity.person_id), None)
        return identity

    def identity_of(self, track_uuid: str) -> Optional[TrackIdentity]:
        return self._identities.get(track_uuid)

    def adopt(self, track_uuid: str, camera_id: str, previous_uuid: str) -> Optional[TrackIdentity]:
        """Pindahkan klaim dari track yang disambung (`track.resumed`).

        Penyambungannya sendiri keputusan perseptual milik pemanggil — orang
        yang sama, kamera yang sama, jeda dalam batas tracker. Di sini yang
        terjadi cuma pemindahan klaim, dan identitas yang pindah masuk sebagai
        `HELD`: ia tidak berasal dari wajah yang baru dibaca.
        """
        previous = self._identities.get(previous_uuid)
        if previous is None or previous.person_id is None:
            return None

        identity = self.open_track(track_uuid, camera_id)
        identity.person_id = previous.person_id
        identity.state = IdentityState.HELD
        identity.confidence = previous.confidence
        identity.similarity = previous.similarity
        identity.margin = previous.margin
        identity.evidence_count = previous.evidence_count
        identity.confirmed_at_pts = previous.confirmed_at_pts
        identity.last_face_pts = previous.last_face_pts
        identity.history.append(f"adopted_from:{previous_uuid}")

        self._claims[(camera_id, previous.person_id)] = track_uuid
        previous.person_id = None
        previous.state = IdentityState.EXPIRED
        return identity

    # ---------------- pengamatan ----------------

    def observe(self, track_uuid: str, camera_id: str, evidence: Evidence) -> Decision:
        identity = self.open_track(track_uuid, camera_id)
        window = self._windows[track_uuid]
        window.add(evidence)
        identity.last_face_pts = evidence.pts
        identity.evidence_count = len(window)

        fused = window.fused()
        if fused is None:
            return Decision(Outcome.NOTHING, identity)

        # DUA pencocokan, dan pemisahannya penting.
        #
        # Klaim dipegang oleh vektor GABUNGAN, karena fusi itulah yang meredam
        # derau pose dan blur. Tapi ketidaksetujuan dihitung dari bukti TUNGGAL
        # yang baru masuk, karena kalau ia juga diukur dari gabungan, satu frame
        # nyasar akan larut ke dalam rata-rata dan penghitung ketidaksetujuan
        # tidak akan pernah menyala sampai jendela sudah berisi mayoritas orang
        # lain -- saat itu "ketidaksetujuan berkelanjutan" sudah terlambat jadi
        # istilah yang berarti apa pun.
        #
        # Dipisah begini, keduanya bekerja sendiri-sendiri: satu frame buruk
        # tidak menggeser klaim, dan tiga frame berturut-turut yang menunjuk
        # orang yang sama tetap bisa mencabutnya.
        fused_match = self._matcher.match(fused, query_version=evidence.embedding_version)

        if identity.person_id is None:
            return self._consider_new_claim(identity, window, fused_match)

        single_match = self._matcher.match(
            evidence.embedding, query_version=evidence.embedding_version
        )
        return self._reconcile_existing_claim(
            identity, window, fused_match, single_match, evidence.pts
        )

    def tick(self, pts: float) -> List[Decision]:
        """Jalankan peluruhan waktu. Dipanggil sekali per frame atau per detik.

        Tanpa ini, identitas yang dipegang tracker terlihat sama meyakinkannya
        dengan yang baru dibaca dari wajah, dan backend tidak punya cara
        membedakan kehadiran yang benar-benar teramati dari kehadiran yang
        cuma belum dibantah.
        """
        changes: List[Decision] = []

        for identity in self._identities.values():
            if identity.person_id is None or identity.last_face_pts is None:
                continue

            since_face = pts - identity.last_face_pts
            previous_state = identity.state

            if since_face >= self._ttl:
                identity.state = IdentityState.EXPIRED
            elif since_face >= self._held_after:
                identity.state = IdentityState.HELD
            # Di bawah ambang HELD, state dibiarkan apa adanya: wajahnya masih
            # baru terlihat.

            if identity.state in {IdentityState.HELD, IdentityState.EXPIRED}:
                identity.confidence = self._decayed(identity, since_face)

            if identity.state is not previous_state:
                identity.history.append(f"{previous_state.value}->{identity.state.value}@{pts:.2f}")
                changes.append(Decision(Outcome.STATE_CHANGED, identity))

        return changes

    # ---------------- internal ----------------

    def _consider_new_claim(self, identity: TrackIdentity, window: EvidenceWindow, match: Match) -> Decision:
        if not match.is_match:
            identity.state = IdentityState.PROVISIONAL if len(window) else IdentityState.PENDING
            identity.similarity = match.similarity
            identity.margin = match.margin
            return Decision(Outcome.NOTHING, identity, match, reason=match.rejected_because)

        if not window.is_confirmable:
            # Ada match yang lolos threshold dan margin, tapi buktinya belum
            # cukup banyak atau belum cukup tersebar. Ini titik persis tempat
            # implementasi lama menyerah dan memasang identitas.
            identity.state = IdentityState.PROVISIONAL
            identity.similarity = match.similarity
            identity.margin = match.margin
            return Decision(Outcome.NOTHING, identity, match, reason="not_enough_evidence")

        loser = self._resolve_conflict(identity, match)
        if loser is identity:
            identity.state = IdentityState.PROVISIONAL
            return Decision(Outcome.NOTHING, identity, match, reason="dedup_lost_claim")

        self._confirm(identity, match, window)
        return Decision(Outcome.IDENTIFIED, identity, match)

    def _reconcile_existing_claim(
        self,
        identity: TrackIdentity,
        window: EvidenceWindow,
        fused_match: Match,
        single_match: Match,
        pts: float,
    ) -> Decision:
        agrees = single_match.is_match and single_match.person_id == identity.person_id

        if agrees:
            identity.disagreements = 0
            identity.disagreeing_with = None
            previous_state = identity.state
            # Yang dipakai memperbarui klaim tetap hasil fusi, bukan bukti
            # tunggal: satu frame bagus tidak lebih meyakinkan dari lima.
            confirming = fused_match if fused_match.person_id == identity.person_id else single_match
            self._confirm(identity, confirming, window)
            outcome = Outcome.STATE_CHANGED if previous_state is not IdentityState.CONFIRMED else Outcome.NOTHING
            return Decision(outcome, identity, confirming)

        match = single_match

        # Tidak setuju. Klaim TIDAK ditukar di sini -- itu persis bug §9.4.
        if match.is_match and match.person_id == identity.disagreeing_with:
            identity.disagreements += 1
        elif match.is_match:
            identity.disagreeing_with = match.person_id
            identity.disagreements = 1
        else:
            # Gagal mencocokkan sama sekali bukan ketidaksetujuan; ia ketiadaan
            # bukti. Menghitungnya sebagai suara menentang berarti punggung
            # orang bisa mencabut identitasnya sendiri.
            identity.confidence = max(0.0, identity.confidence * 0.95)
            return Decision(Outcome.NOTHING, identity, match, reason=match.rejected_because)

        identity.confidence = max(0.0, identity.confidence * 0.8)

        if identity.disagreements < self._disagreements_to_release:
            return Decision(Outcome.NOTHING, identity, match, reason="disagreement_below_threshold")

        previous_person = identity.person_id
        self._release(identity)
        window.clear()
        identity.history.append(f"released:{previous_person}@{pts:.2f}")

        return Decision(
            Outcome.IDENTITY_RELEASED,
            identity,
            match,
            from_person_id=previous_person,
            reason="sustained_disagreement",
        )

    def _confirm(self, identity: TrackIdentity, match: Match, window: EvidenceWindow) -> None:
        identity.person_id = match.person_id
        identity.state = IdentityState.CONFIRMED
        identity.similarity = match.similarity
        identity.margin = match.margin
        identity.evidence_count = len(window)
        identity.confidence = _confidence_from(match)
        if identity.confirmed_at_pts is None:
            identity.confirmed_at_pts = window.last_pts
        self._claims[(identity.camera_id, match.person_id)] = identity.track_uuid

    def _release(self, identity: TrackIdentity) -> None:
        if identity.person_id:
            claim = (identity.camera_id, identity.person_id)
            if self._claims.get(claim) == identity.track_uuid:
                self._claims.pop(claim, None)
        identity.person_id = None
        identity.state = IdentityState.PROVISIONAL
        identity.confidence = 0.0
        identity.disagreements = 0
        identity.disagreeing_with = None
        identity.confirmed_at_pts = None

    def _resolve_conflict(self, claimant: TrackIdentity, match: Match) -> Optional[TrackIdentity]:
        """Kembalikan track yang KALAH, atau None kalau tidak ada tabrakan.

        Dua track di satu kamera tidak boleh sama-sama mengklaim karyawan yang
        sama: salah satunya pasti keliru, dan membiarkan keduanya berarti satu
        orang tercatat hadir dua kali di ruangan yang sama.
        """
        holder_uuid = self._claims.get((claimant.camera_id, match.person_id))
        if holder_uuid is None or holder_uuid == claimant.track_uuid:
            return None

        holder = self._identities.get(holder_uuid)
        if holder is None or holder.person_id != match.person_id:
            return None

        if match.similarity > holder.similarity:
            holder.history.append(f"lost_claim:{match.person_id}->{claimant.track_uuid}")
            self._release(holder)
            return holder

        return claimant

    def _decayed(self, identity: TrackIdentity, since_face: float) -> float:
        if self._halflife <= 0:
            return identity.confidence
        return float(identity.confidence * (0.5 ** (since_face / self._halflife)))


def _confidence_from(match: Match) -> float:
    """Kepercayaan gabungan dari similarity dan seberapa jauh kandidat kedua.

    Dijaga di [0, 1] supaya bisa dipancarkan sebagai `identity_confidence`
    tanpa penafsiran tambahan di backend.
    """
    similarity = max(0.0, min(1.0, (match.similarity + 1.0) / 2.0))
    separation = max(0.0, min(1.0, match.margin / 0.3))
    return round(min(1.0, 0.7 * similarity + 0.3 * separation), 4)
