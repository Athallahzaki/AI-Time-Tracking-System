"""Pembentukan pesan: satu-satunya tempat event engine lahir.

Modul lain DILARANG menulis dict protokol sendiri. Alasannya bukan kerapian:
`ENGINE_PROTOCOL.md` §7 mendaftar sebelas hal yang harus selalu benar —
`track.identified` selalu membawa `track_started_pts`, `track.ended` selalu
membawa `reason` DAN `exit_zone`, kamera putus selalu menghasilkan
`camera_lost`. Kalau pesan bisa dibentuk di sepuluh tempat, sebelas aturan itu
harus diingat di sepuluh tempat, dan cukup satu yang lupa untuk membuat backend
menandai satu ruangan penuh orang sebagai pulang.

Di sini aturan-aturan itu jadi tanda tangan fungsi: parameternya wajib, jadi
melupakannya adalah `TypeError` saat impor, bukan data salah di bulan ketiga.

Konversi waktu juga hanya terjadi di sini. Engine memiliki waktu untuk semua
yang dilaporkannya dan backend tidak pernah menghitung durasi dari jamnya
sendiri (§6.6); `PtsClock` yang di bawah adalah satu-satunya jembatan
pts→wallclock, dan ia memegang `stream_epoch` supaya offset yang salah tidak
bisa dipakai diam-diam setelah kamera reconnect.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

PROTOCOL_VERSION = 1

ZONES = {"door", "interior", "frame_edge"}
BOUNDARY_SOURCES = {"face", "tracking", "forced"}
END_REASONS = {
    "left_frame", "occluded_timeout", "merged_into_other_track",
    "camera_lost", "engine_shutdown", "identity_released",
}


class ProtocolError(ValueError):
    """Pesan yang dibentuk melanggar kontrak. Gagal di sini, bukan di backend."""


def rfc3339(unix_seconds: float) -> str:
    moment = dt.datetime.fromtimestamp(unix_seconds, dt.timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class PtsClock:
    """Pemetaan pts→jam dinding untuk satu kamera pada satu stream_epoch.

    `stream_epoch` naik setiap koneksi RTSP dibangun ulang, dan offset ikut
    ditetapkan ulang. §6.6 mewajibkan itu tapi tidak memberi backend cara tahu
    offset mana berlaku untuk pesan mana; `stream_epoch` yang ikut di setiap
    pesan adalah jawabannya. Tanpa itu, kamera yang sempat putus akan
    melaporkan interval di tahun yang salah — dan hanya kamera itu.
    """

    camera_id: str
    stream_epoch: int = 0
    offset: float = 0.0

    def reconnect(self, wallclock_now: float) -> "PtsClock":
        """Stream baru: epoch naik, offset ditetapkan ulang."""
        return PtsClock(self.camera_id, self.stream_epoch + 1, wallclock_now)

    def at(self, pts: float) -> str:
        if pts < 0:
            raise ProtocolError(f"pts negatif: {pts}. pts relatif awal stream, bukan jam dinding.")
        return rfc3339(self.offset + pts)


def _envelope(message_type: str, now_wallclock: float) -> Dict[str, Any]:
    return {"type": message_type, "v": PROTOCOL_VERSION, "ts": rfc3339(now_wallclock)}


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise ProtocolError(detail)


# --------------------------------------------------------------------------
# siklus hidup track
# --------------------------------------------------------------------------


def track_started(clock: PtsClock, track_uuid: str, pts: float, zone: str) -> Dict[str, Any]:
    _require(zone in ZONES, f"zone tidak dikenal: {zone}")
    message = _envelope("track.started", clock.offset + pts)
    message.update(
        track_uuid=track_uuid, camera_id=clock.camera_id,
        stream_epoch=clock.stream_epoch, pts=pts, at=clock.at(pts), zone=zone,
    )
    return message


def track_identified(
    clock: PtsClock,
    track_uuid: str,
    person_id: str,
    pts: float,
    track_started_pts: float,
    similarity: float,
    margin: float,
    evidence_count: int,
) -> Dict[str, Any]:
    """`track_started_pts` wajib, dan itu bukan formalitas.

    Orang masuk 10:00:00, wajahnya terbaca 10:00:08. Tanpa field ini backend
    menghitung kehadirannya mulai dari saat wajah terbaca, dan delapan detik
    per kejadian menumpuk jadi menit di jatah yang cuma tiga puluh menit.
    """
    _require(track_started_pts <= pts, "track dikenali sebelum ia lahir")
    _require(margin >= 0.0, "margin tidak boleh negatif")
    _require(evidence_count >= 1, "identifikasi tanpa bukti")

    message = _envelope("track.identified", clock.offset + pts)
    message.update(
        track_uuid=track_uuid, person_id=person_id, pts=pts, at=clock.at(pts),
        track_started_pts=track_started_pts, similarity=similarity,
        margin=margin, evidence_count=evidence_count,
    )
    return message


def track_heartbeat(
    clock: PtsClock, track_uuid: str, pts: float,
    identity_source: str, confidence: float, person_id: Optional[str] = None,
) -> Dict[str, Any]:
    _require(identity_source in {"face", "tracking"}, f"identity_source tidak dikenal: {identity_source}")
    message = _envelope("track.heartbeat", clock.offset + pts)
    message.update(
        track_uuid=track_uuid, person_id=person_id, pts=pts, at=clock.at(pts),
        identity_source=identity_source, confidence=confidence,
    )
    return message


def track_resumed(
    clock: PtsClock, track_uuid: str, prev_track_uuid: str,
    person_id: str, gap_seconds: float, pts: float,
) -> Dict[str, Any]:
    _require(gap_seconds >= 0.0, "jeda negatif")
    message = _envelope("track.resumed", clock.offset + pts)
    message.update(
        track_uuid=track_uuid, prev_track_uuid=prev_track_uuid, person_id=person_id,
        gap_seconds=gap_seconds, pts=pts, at=clock.at(pts), stream_epoch=clock.stream_epoch,
    )
    return message


def track_identity_changed(
    clock: PtsClock, track_uuid: str, from_person_id: Optional[str],
    to_person_id: Optional[str], reason: str, disagreement_count: int, pts: float,
) -> Dict[str, Any]:
    _require(disagreement_count >= 1, "perubahan identitas tanpa ketidaksetujuan")
    message = _envelope("track.identity_changed", clock.offset + pts)
    message.update(
        track_uuid=track_uuid, from_person_id=from_person_id, to_person_id=to_person_id,
        reason=reason, disagreement_count=disagreement_count, pts=pts, at=clock.at(pts),
    )
    return message


def track_ended(clock: PtsClock, track_uuid: str, pts: float, reason: str, exit_zone: str) -> Dict[str, Any]:
    """`reason` DAN `exit_zone` dua-duanya wajib.

    Kalau satu kamera mati, semua track di kamera itu berakhir serentak padahal
    tidak ada seorang pun yang pulang. Tanpa kode alasan, backend menandai satu
    ruangan penuh orang sebagai pulang pada detik yang sama — dan itu bug yang
    baru ketahuan saat penggajian.
    """
    _require(reason in END_REASONS, f"end_reason tidak dikenal: {reason}")
    _require(exit_zone in ZONES, f"exit_zone tidak dikenal: {exit_zone}")

    message = _envelope("track.ended", clock.offset + pts)
    message.update(
        track_uuid=track_uuid, pts=pts, at=clock.at(pts), reason=reason, exit_zone=exit_zone,
    )
    return message


# --------------------------------------------------------------------------
# keluaran utama
# --------------------------------------------------------------------------


def presence_interval(
    clock: PtsClock,
    interval_id: str,
    person_id: str,
    start_pts: float,
    end_pts: float,
    start_source: str,
    end_source: str,
    start_zone: str,
    end_zone: str,
    end_reason: str,
    identity_confidence: float,
    evidence_count: int,
    track_uuid: Optional[str] = None,
    prev_interval_id: Optional[str] = None,
    evidence_crop: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Output utama engine. Yang TIDAK boleh ada di sini: akumulasi harian.

    Menjumlahkan interval berarti memutuskan celah mana yang dianggap masih
    hadir, dan itu kebijakan yang menyamar sebagai aritmetika. Milik backend.
    """
    _require(interval_id.startswith("iv_"), f"interval_id wajib berawalan iv_: {interval_id}")
    _require(
        track_uuid is None or track_uuid.startswith("tr_"),
        f"track_uuid wajib berawalan tr_: {track_uuid}",
    )
    _require(start_pts <= end_pts, "interval berakhir sebelum ia mulai")
    _require(start_source in BOUNDARY_SOURCES, f"start_source tidak dikenal: {start_source}")
    _require(end_source in BOUNDARY_SOURCES, f"end_source tidak dikenal: {end_source}")
    _require(start_zone in ZONES and end_zone in ZONES, "zona tidak dikenal")
    _require(end_reason in END_REASONS, f"end_reason tidak dikenal: {end_reason}")

    message = _envelope("presence.interval", clock.offset + end_pts)
    message.update(
        interval_id=interval_id, person_id=person_id, camera_id=clock.camera_id,
        stream_epoch=clock.stream_epoch,
        start_pts=start_pts, end_pts=end_pts,
        start_at=clock.at(start_pts), end_at=clock.at(end_pts),
        start_source=start_source, end_source=end_source,
        start_zone=start_zone, end_zone=end_zone, end_reason=end_reason,
        identity_confidence=identity_confidence, evidence_count=max(1, evidence_count),
    )
    if track_uuid:
        message["track_uuid"] = track_uuid
    if prev_interval_id:
        message["prev_interval_id"] = prev_interval_id
    if evidence_crop:
        message["evidence_crop"] = evidence_crop
    return message


# --------------------------------------------------------------------------
# kamera dan kesehatan
# --------------------------------------------------------------------------


def camera_online(clock: PtsClock, fps: float) -> Dict[str, Any]:
    message = _envelope("camera.online", clock.offset)
    message.update(
        camera_id=clock.camera_id, stream_epoch=clock.stream_epoch,
        fps=fps, pts_wallclock_offset=clock.offset,
    )
    return message


def camera_failed(camera_id: str, now_wallclock: float, reason: str, retry_in_seconds: float) -> Dict[str, Any]:
    message = _envelope("camera.failed", now_wallclock)
    message.update(camera_id=camera_id, reason=reason, retry_in_seconds=retry_in_seconds)
    return message


def camera_degraded(camera_id: str, now_wallclock: float, reason: str, fps: Optional[float] = None) -> Dict[str, Any]:
    message = _envelope("camera.degraded", now_wallclock)
    message.update(camera_id=camera_id, reason=reason)
    if fps is not None:
        message["fps"] = fps
    return message


def camera_coverage(camera_id: str, now_wallclock: float, observed: List[List[float]], never_observed: List[List[float]]) -> Dict[str, Any]:
    message = _envelope("camera.coverage", now_wallclock)
    message.update(camera_id=camera_id, observed_regions=observed, never_observed=never_observed)
    return message


def person_unidentified_present(
    camera_id: str, now_wallclock: float, track_uuid: str,
    duration_seconds: float, attempts: int, reason: str,
) -> Dict[str, Any]:
    message = _envelope("person.unidentified_present", now_wallclock)
    message.update(
        track_uuid=track_uuid, camera_id=camera_id,
        duration_seconds=duration_seconds, attempts=attempts, reason=reason,
    )
    return message


def engine_health(
    now_wallclock: float, models_loaded: bool, queue_depth: int,
    drop_rate: float, cameras: Dict[str, str],
    degraded_components: Optional[Iterable[str]] = None,
    gpu_util: Optional[float] = None, vram_mb: Optional[float] = None,
) -> Dict[str, Any]:
    """`models_loaded=False` berarti engine hidup tapi tidak mengenali siapa pun.

    Mode kegagalan terburuk bukan mati, tapi berbohong: log bersih, dashboard
    hidup, nol data tercatat. Field ini ada supaya keadaan itu punya suara.
    """
    message = _envelope("engine.health", now_wallclock)
    message.update(
        models_loaded=models_loaded, queue_depth=queue_depth,
        drop_rate=drop_rate, cameras=dict(cameras),
    )
    if degraded_components:
        message["degraded_components"] = list(degraded_components)
    if gpu_util is not None:
        message["gpu_util"] = gpu_util
    if vram_mb is not None:
        message["vram_mb"] = vram_mb
    return message


def snapshot(now_wallclock: float, clocks: Iterable[PtsClock], live: List[Dict[str, Any]]) -> Dict[str, Any]:
    message = _envelope("snapshot", now_wallclock)
    message.update(
        pts_wallclock_offset={
            clock.camera_id: {"stream_epoch": clock.stream_epoch, "offset": clock.offset}
            for clock in clocks
        },
        live=list(live),
    )
    return message


def enrollment_needed(now_wallclock: float, person_ids: Iterable[str]) -> Dict[str, Any]:
    message = _envelope("enrollment_needed", now_wallclock)
    message.update(person_ids=list(person_ids))
    return message


# --------------------------------------------------------------------------
# kanal view
# --------------------------------------------------------------------------


def view_frame(clock: PtsClock, pts: float, boxes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Dua timestamp, dan keduanya wajib.

    `pts` menyambungkan pesan ini ke event engine; `at` menyambungkannya ke
    video, karena MediaMTX menyajikan HLS dengan EXT-X-PROGRAM-DATE-TIME yang
    berbasis jam dinding. Browser menyelaraskan overlay lewat `at`, bukan `pts`.
    """
    for box in boxes:
        bbox = box.get("bbox") or []
        _require(len(bbox) == 4, "bbox harus empat angka")
        _require(
            all(0.0 <= value <= 1.0 for value in bbox),
            "bbox wajib ternormalisasi 0-1: engine melihat mainstream, browser substream",
        )

    message = _envelope("view.frame", clock.offset + pts)
    message.update(
        camera_id=clock.camera_id, stream_epoch=clock.stream_epoch,
        pts=pts, at=clock.at(pts), boxes=list(boxes),
    )
    return message
