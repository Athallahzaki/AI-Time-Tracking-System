"""Aturan penggabungan ReID (dokumen 12 §3.6 butir 4).

Tiga aturan, semuanya condong ke "lebih baik terpecah daripada tertukar":

1. **Cannot-link.** Dua track yang hidup bersamaan adalah dua tubuh, jadi tidak
   pernah orang yang sama — seberapa pun miripnya. Ini yang mencegah dua orang
   berseragam sama di kamera berbeda dilebur jadi satu.
2. **Waktu tempuh minimum** antar lokasi. Track A berakhir di lobby pukul t,
   track B muncul di biliar pada t+3 detik: mustahil orang yang sama bila
   perjalanannya butuh 20 detik. Pasangan lokasi yang tidak tercantum di config
   memakai `default_min_travel_seconds` yang sengaja besar (ketat).
3. **Ambang ketat + margin.** Kandidat terbaik harus melewati ambang DAN
   unggul cukup jauh dari kandidat kedua. Dua kandidat yang sama-sama mirip
   berarti kita tidak tahu, dan "tidak tahu" berarti tidak digabung.

Modul ini murni: tidak menyimpan keadaan, hanya menilai. Keadaan dipegang
`pending.PendingIdentities`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, Mapping, NamedTuple, Optional, Sequence, Tuple, TypeVar

from .gallery import DEFAULT_CAPACITY, DEFAULT_MERGE_SIMILARITY

# Kosinus embedding tubuh: orang yang sama lintas sudut wajar 0,7–0,9, orang
# berbeda berseragam sama bisa menyentuh 0,7. Default di atas wilayah abu-abu.
DEFAULT_MATCH_THRESHOLD = 0.80
DEFAULT_MATCH_MARGIN = 0.05
# Waktu tempuh untuk pasangan lokasi yang tidak dicantumkan. Besar dengan
# sengaja: menolak sambungan sah hanya membuat kelompok terpecah (bisa disatukan
# lagi oleh wajah), menerima sambungan mustahil menukar orang.
DEFAULT_MIN_TRAVEL_SECONDS = 30.0
# Tumpang-tindih rentang hidup yang masih ditoleransi (detik). Nol = ketat.
# Hanya berpengaruh di lokasi yang sama; lihat `check_pair`.
DEFAULT_OVERLAP_TOLERANCE_SECONDS = 0.0

K = TypeVar("K")


@dataclass(frozen=True)
class ReidConfig:
    match_threshold: float = DEFAULT_MATCH_THRESHOLD
    match_margin: float = DEFAULT_MATCH_MARGIN
    default_min_travel_seconds: float = DEFAULT_MIN_TRAVEL_SECONDS
    # frozenset({lokasi_a, lokasi_b}) -> detik; simetris.
    min_travel_seconds: Mapping[FrozenSet[str], float] = field(default_factory=dict)
    overlap_tolerance_seconds: float = DEFAULT_OVERLAP_TOLERANCE_SECONDS
    gallery_capacity: int = DEFAULT_CAPACITY
    prototype_merge_similarity: float = DEFAULT_MERGE_SIMILARITY

    def __post_init__(self) -> None:
        if not -1.0 <= self.match_threshold <= 1.0:
            raise ValueError("match_threshold harus di [-1, 1]")
        if self.match_margin < 0:
            raise ValueError("match_margin tidak boleh negatif")
        if self.default_min_travel_seconds < 0 or self.overlap_tolerance_seconds < 0:
            raise ValueError("waktu tempuh/toleransi tidak boleh negatif")
        for pair, seconds in self.min_travel_seconds.items():
            if len(pair) != 2 or seconds < 0:
                raise ValueError(f"waktu tempuh tidak valid: {sorted(pair)} = {seconds}")

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "ReidConfig":
        """Dari blok config (YAML). Waktu tempuh ditulis bersarang:

            min_travel_seconds:
              lobby: {smoking: 12, biliar: 25}
              luar:  {lobby: 8}
        """
        raw = dict(raw or {})
        travel_raw = raw.pop("min_travel_seconds", None) or {}
        known = set(cls.__dataclass_fields__) - {"min_travel_seconds"}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"kunci reid tidak dikenal: {sorted(unknown)}")
        travel: Dict[FrozenSet[str], float] = {}
        for a, row in travel_raw.items():
            if not isinstance(row, Mapping):
                raise ValueError(f"min_travel_seconds.{a} harus mapping lokasi -> detik")
            for b, seconds in row.items():
                if a == b:
                    raise ValueError(f"waktu tempuh {a}->{a} tidak bermakna")
                key = frozenset((str(a), str(b)))
                if key in travel and travel[key] != float(seconds):
                    raise ValueError(f"waktu tempuh {a}<->{b} ditulis dua kali berbeda")
                travel[key] = float(seconds)
        return cls(min_travel_seconds=travel, **raw)

    def travel_seconds(self, a: str, b: str) -> float:
        if a == b:
            return 0.0
        return self.min_travel_seconds.get(frozenset((a, b)), self.default_min_travel_seconds)


@dataclass
class TrackSpan:
    """Rentang hidup satu track: kapan dan di mana pertama/terakhir terlihat."""

    track_uuid: str
    camera_id: str
    first_at: float
    last_at: float
    first_location: str
    last_location: str
    ended: bool = False

    def extend(self, at: float, location: str) -> None:
        if at < self.first_at:
            self.first_at = at
            self.first_location = location
        if at >= self.last_at:
            self.last_at = at
            self.last_location = location


class Verdict(NamedTuple):
    ok: bool
    reason: str  # "ok" | "cannot_link" | "travel_time"


OK = Verdict(True, "ok")


def check_pair(a: TrackSpan, b: TrackSpan, cfg: ReidConfig) -> Verdict:
    """Bolehkah dua track ini orang yang sama, dilihat dari waktu dan tempat saja."""
    if a.track_uuid == b.track_uuid:
        return OK
    overlap = min(a.last_at, b.last_at) - max(a.first_at, b.first_at)
    if overlap > cfg.overlap_tolerance_seconds:
        return Verdict(False, "cannot_link")
    earlier, later = (a, b) if a.first_at <= b.first_at else (b, a)
    # Tumpang-tindih kecil yang ditoleransi membuat gap negatif; di dua lokasi
    # berbeda itu tetap gugur oleh waktu tempuh, jadi toleransi hanya berlaku
    # di lokasi yang sama (selisih jam antar kamera, pergantian ID tracker).
    gap = later.first_at - earlier.last_at
    need = cfg.travel_seconds(earlier.last_location, later.first_location)
    if gap < need:
        return Verdict(False, "travel_time")
    return OK


def check_group(members: Iterable[TrackSpan], candidate: TrackSpan, cfg: ReidConfig) -> Verdict:
    """Kandidat harus cocok dengan SETIAP anggota, bukan hanya yang terdekat."""
    for span in members:
        verdict = check_pair(span, candidate, cfg)
        if not verdict.ok:
            return verdict
    return OK


def pick_best(scored: Sequence[Tuple[K, float]], cfg: ReidConfig) -> Optional[K]:
    """Kandidat terbaik bila lolos ambang dan margin; selain itu None.

    `scored` harus terurut menurun dan memuat SEMUA kandidat (termasuk yang
    nanti gugur oleh aturan waktu): margin dihitung atas skor mentah supaya
    dua kandidat sama-sama mirip tetap terbaca sebagai "tidak tahu".
    """
    if not scored:
        return None
    best_key, best = scored[0]
    if best < cfg.match_threshold:
        return None
    if len(scored) > 1 and best - scored[1][1] < cfg.match_margin:
        return None
    return best_key
