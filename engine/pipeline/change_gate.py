"""Gerbang analisis berbasis perubahan kotak (overhaul, keputusan tim 3 Nov).

Rekognisi wajah dan embedding ReID mahal. Orang yang berdiri diam membelakangi
kamera tidak akan berubah jadi wajah kalau dicoba tiap detik; yang dibayar cuma
GPU. Gerbang ini menjawab satu pertanyaan per track per jenis analisis ("face",
"reid"): **apakah ada yang berubah sejak snapshot terakhir yang dianalisis?**

Pemicu (masing-masing memberi KREDIT analisis, bukan satu kali coba):

- `new`      track baru.
- `change`   kotak bergeser/membesar/berubah bentuk terhadap snapshot terakhir,
             bertahan `sustain_frames` frame berturut-turut. Kotak dihaluskan EMA
             dulu, jadi jitter/drift sesaat tidak dihitung. Geseran diukur relatif
             tinggi badan, jadi orang dekat dan jauh dinilai sama.
- `lost`     track hilang >= `lost_recheck_seconds` lalu kembali (bisa jadi orang
             lain). Hilang lebih singkat diabaikan; kotaknya disemai ulang tanpa
             dianggap perubahan, karena itu anomali tracker, bukan gerakan.
- `overlap`  dua kotak bertumpuk (IoU puncak >= `swap_iou`) SEBENTAR
             (<= `fast_overlap_seconds`) lalu berpisah: saat itulah tracker paling
             mungkin menukar ID. Kedua track mendapat `overlap_recheck` kredit.
             Tumpukan lama (orang berdiri berdampingan) tidak memicu ini; ia
             ditangani pemicu `change` biasa.
- `interval` pengaman: tidak ada analisis selama `max_interval_seconds`. null = mati.

Kredit, bukan sekali coba: arbiter butuh beberapa bukti tersebar (min_evidence)
untuk mengonfirmasi wajah. Satu pemicu = satu percobaan berarti orang yang diam
menghadap kamera tidak akan pernah dikenali. `face_burst` default 3.

Satu objek per kamera; `observe` dipanggil dari thread kamera itu dan idempoten
per frame (antrean rekognisi dan tap ReID sama-sama memanggilnya).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from ..ports.tracking import TrackState

KINDS = ("face", "reid")
_LIVE = (TrackState.NEW, TrackState.TRACKED)

Box = Tuple[float, float, float, float]  # cx, cy, w, h


@dataclass
class _Entry:
    smooth: Optional[Box] = None
    last_seen: float = 0.0
    lost_since: Optional[float] = None
    snap: Dict[str, Optional[Box]] = field(default_factory=lambda: {k: None for k in KINDS})
    over: Dict[str, int] = field(default_factory=lambda: {k: 0 for k in KINDS})
    credits: Dict[str, int] = field(default_factory=lambda: {k: 0 for k in KINDS})
    last_mark: Dict[str, Optional[float]] = field(default_factory=lambda: {k: None for k in KINDS})
    # track_id lawan -> (mulai, IoU puncak)
    overlaps: Dict[int, Tuple[float, float]] = field(default_factory=dict)


def _box(track: Any) -> Box:
    b = track.bbox
    w = max(1e-6, float(b.x2) - float(b.x1))
    h = max(1e-6, float(b.y2) - float(b.y1))
    return float(b.x1) + w / 2.0, float(b.y1) + h / 2.0, w, h


def _iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


class ChangeGate:
    def __init__(self, params: Any) -> None:
        # `params`: config.schema.AnalysisTriggerConfig. Boleh diganti saat jalan
        # (pengaturan realtime); dibaca ulang setiap frame.
        self.params = params
        self._entries: Dict[int, _Entry] = {}
        self._last_frame: Any = object()
        self.triggers: Dict[str, int] = {}
        self.skipped: Dict[str, int] = {k: 0 for k in KINDS}

    # -- per frame ---------------------------------------------------------------

    def observe(self, frame_id: Any, tracks: Sequence[Any], pts: float) -> None:
        if frame_id is not None and frame_id == self._last_frame:
            return
        self._last_frame = frame_id
        p = self.params
        live: Dict[int, Box] = {}
        for track in tracks:
            tid = int(track.track_id)
            entry = self._entries.get(tid)
            if entry is None or track.state is TrackState.NEW:
                entry = self._entries[tid] = _Entry()
                self._grant(entry, "new", p.face_burst, p.reid_burst)
            if track.state in _LIVE:
                box = _box(track)
                live[tid] = box
                self._update_box(entry, box, pts)
            elif track.state is TrackState.LOST and entry.lost_since is None:
                entry.lost_since = pts
        self._observe_overlaps(live, pts)
        self._interval_fallback(pts)
        forget = max(30.0, 2.0 * float(p.lost_recheck_seconds))
        for tid in [t for t, e in self._entries.items() if pts - e.last_seen > forget and t not in live]:
            del self._entries[tid]

    def _update_box(self, entry: _Entry, box: Box, pts: float) -> None:
        p = self.params
        if entry.lost_since is not None:
            gone = pts - entry.lost_since
            entry.lost_since = None
            entry.smooth = box  # disemai ulang: lompatan setelah hilang bukan gerakan
            if gone >= p.lost_recheck_seconds:
                self._grant(entry, "lost", p.face_burst, p.reid_burst)
        elif entry.smooth is None:
            entry.smooth = box
        else:
            a = float(p.smoothing_alpha)
            entry.smooth = tuple(a * n + (1.0 - a) * o for n, o in zip(box, entry.smooth))  # type: ignore[assignment]
        entry.last_seen = pts
        for kind in KINDS:
            snap = entry.snap[kind]
            if snap is None:
                continue
            if self.change_score(entry.smooth, snap) >= 1.0:
                entry.over[kind] += 1
            else:
                entry.over[kind] = 0
            if entry.over[kind] >= p.sustain_frames:
                entry.over[kind] = 0
                entry.snap[kind] = entry.smooth  # jangkar baru: satu gerakan = satu pemicu
                self._grant_kind(entry, kind, "change", self._burst(kind))

    def _observe_overlaps(self, live: Dict[int, Box], pts: float) -> None:
        p = self.params
        ids = sorted(live)
        touching: Dict[int, set] = {tid: set() for tid in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                iou = _iou(live[a], live[b])
                if iou < p.overlap_iou:
                    continue
                touching[a].add(b)
                touching[b].add(a)
                for me, other in ((a, b), (b, a)):
                    start, peak = self._entries[me].overlaps.get(other, (pts, 0.0))
                    self._entries[me].overlaps[other] = (start, max(peak, iou))
        for tid in ids:
            entry = self._entries[tid]
            for other in [o for o in entry.overlaps if o not in touching[tid]]:
                start, peak = entry.overlaps.pop(other)
                if peak >= p.swap_iou and pts - start <= p.fast_overlap_seconds:
                    self._grant(entry, "overlap", p.overlap_recheck, p.overlap_recheck)

    def _interval_fallback(self, pts: float) -> None:
        limit = self.params.max_interval_seconds
        if limit is None:
            return
        for entry in self._entries.values():
            if entry.lost_since is not None:
                continue
            for kind in KINDS:
                last = entry.last_mark[kind]
                if last is not None and pts - last >= limit and entry.credits[kind] == 0:
                    self._grant_kind(entry, kind, "interval", 1)
                    entry.last_mark[kind] = pts

    # -- dibaca antrean rekognisi / tap ReID ------------------------------------

    def due(self, track_id: int, kind: str) -> bool:
        """True bila analisis jenis ini layak sekarang. Track tak dikenal = True (gagal terbuka)."""
        entry = self._entries.get(int(track_id))
        return entry is None or entry.credits[kind] > 0

    def mark(self, track_id: int, kind: str, pts: float) -> None:
        """Analisis dijalankan: satu kredit terpakai, snapshot = kotak sekarang."""
        entry = self._entries.get(int(track_id))
        if entry is None:
            return
        entry.credits[kind] = max(0, entry.credits[kind] - 1)
        entry.snap[kind] = entry.smooth
        entry.over[kind] = 0
        entry.last_mark[kind] = pts

    def skip(self, kind: str) -> None:
        self.skipped[kind] += 1

    # -- util -------------------------------------------------------------------

    def change_score(self, now: Box, ref: Box) -> float:
        """>= 1 berarti berubah. Maksimum dari tiga rasio terhadap ambangnya."""
        p = self.params
        displacement = math.hypot(now[0] - ref[0], now[1] - ref[1]) / max(ref[3], 1e-6)
        scale = abs(math.log(now[3] / ref[3]))
        aspect = abs(math.log((now[2] / now[3]) / (ref[2] / ref[3])))
        return max(displacement / p.displacement_ratio,
                   scale / math.log1p(p.scale_ratio),
                   aspect / math.log1p(p.aspect_ratio))

    def _burst(self, kind: str) -> int:
        return int(self.params.face_burst if kind == "face" else self.params.reid_burst)

    def _grant(self, entry: _Entry, reason: str, face: int, reid: int) -> None:
        self._grant_kind(entry, "face", reason, face)
        self._grant_kind(entry, "reid", reason, reid)

    def _grant_kind(self, entry: _Entry, kind: str, reason: str, credits: int) -> None:
        if credits <= 0:
            return
        entry.credits[kind] = max(entry.credits[kind], int(credits))
        key = f"{kind}_{reason}"
        self.triggers[key] = self.triggers.get(key, 0) + 1

    def metrics(self) -> Dict[str, int]:
        out = {f"trigger_{k}": v for k, v in self.triggers.items()}
        out.update({f"trigger_skipped_{k}": v for k, v in self.skipped.items()})
        return out

    def tracked(self) -> Iterable[int]:
        return self._entries.keys()
