"""Aturan yang tidak bisa dinyatakan JSON Schema.

Ini implementasi daftar periksa kesesuaian di `ENGINE_PROTOCOL.md` §7, plus
beberapa aturan yang lahir dari review kode engine dan tidak ada di dokumen.
Skema memeriksa bentuk satu pesan; berkas ini memeriksa apakah sebuah ALIRAN
masuk akal.

Semua pemeriksaan di sini bekerja pada rekaman NDJSON, jadi ia berlaku sama
untuk `fake_engine` maupun engine sungguhan. Itu memang tujuannya: satu alat,
dua produsen, dan tidak ada ruang bagi engine asli untuk menyimpang dari engine
palsu tanpa ketahuan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .schema_validator import CHANNEL_OF, ValidationIssue

# Nama field yang tidak boleh muncul di kanal events. Ini penegakan §16
# ("engine mengamati, backend memutuskan") di batas protokol, bukan cuma di
# folder engine/. Akumulasi harian adalah kebijakan yang menyamar sebagai
# aritmetika, dan begitu ia muncul di sebuah pesan, garisnya sudah bocor.
POLICY_FIELD_PATTERNS: Sequence[re.Pattern] = (
    re.compile(r"break", re.I),
    re.compile(r"istirahat", re.I),
    re.compile(r"penalt", re.I),
    re.compile(r"sanksi", re.I),
    re.compile(r"quota|jatah", re.I),
    re.compile(r"warning|peringatan", re.I),
    re.compile(r"(daily|today|total|accumulat|akumulasi)", re.I),
    re.compile(r"shift|work_hours|jam_kerja", re.I),
    re.compile(r"late|terlambat|absent|alpha", re.I),
)

_ALLOWED_POLICY_LOOKALIKES = {
    # `total` di dalam nama ini bukan akumulasi kehadiran.
    "evidence_count",
}


@dataclass
class ConformanceReport:
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, line, mtype, path, detail) -> None:
        self.errors.append(ValidationIssue(line, mtype, path, detail))

    def warn(self, line, mtype, path, detail) -> None:
        self.warnings.append(ValidationIssue(line, mtype, path, detail))


@dataclass
class _TrackInfo:
    camera_id: Optional[str]
    started_pts: Optional[float]
    stream_epoch: Optional[int]
    ended: bool = False


class ConformanceChecker:
    """Jalankan seluruh aturan lintas-pesan atas satu rekaman.

    `allow_replay=True` mematikan aturan seq-mundur, untuk memeriksa rekaman
    yang memang berisi replay setelah reconnect.
    """

    def __init__(self, allow_replay: bool = False) -> None:
        self._allow_replay = allow_replay

    def check(self, messages: Sequence[Dict[str, Any]]) -> ConformanceReport:
        report = ConformanceReport()

        tracks: Dict[str, _TrackInfo] = {}
        intervals: Dict[str, Dict[str, Any]] = {}
        camera_failed: Dict[str, bool] = {}
        camera_epoch: Dict[str, int] = {}
        camera_offset: Dict[str, Dict[int, float]] = {}
        last_pts: Dict[tuple, float] = {}
        prev_seq: Optional[int] = None
        replay_gap_declared = False
        seen_hello = False
        seen_control = False

        for message in messages:
            line = message.get("_line")
            mtype = message.get("type")
            channel = CHANNEL_OF.get(mtype, "unknown")

            self._check_policy_leakage(message, line, mtype, channel, report)

            if channel == "control":
                if not seen_control and mtype != "hello":
                    report.error(
                        line, mtype, "",
                        "pesan control pertama bukan `hello`. hello wajib pertama setiap "
                        "koneksi terbentuk.",
                    )
                seen_control = True
                if mtype == "hello":
                    seen_hello = True
                if mtype == "replay_gap":
                    replay_gap_declared = True
                    if message.get("to_seq", 0) > message.get("from_seq", 0):
                        report.error(
                            line, mtype, "to_seq",
                            "to_seq (oldest_available_seq) lebih besar dari from_seq "
                            "(last_event_seq): itu bukan lubang, itu aritmetika terbalik.",
                        )
                continue

            if channel == "events":
                prev_seq, replay_gap_declared = self._check_seq(
                    message, line, mtype, prev_seq, replay_gap_declared, report
                )

            self._check_pts_space(
                message, line, mtype, camera_epoch, camera_offset, last_pts, tracks, report
            )

            handler = getattr(self, "_on_" + (mtype or "").replace(".", "_"), None)
            if handler is not None:
                handler(
                    message,
                    line=line,
                    tracks=tracks,
                    intervals=intervals,
                    camera_failed=camera_failed,
                    camera_epoch=camera_epoch,
                    camera_offset=camera_offset,
                    report=report,
                )

        if seen_control and not seen_hello:
            report.error(None, None, "", "aliran control tidak pernah memuat `hello`.")

        for interval_id, interval in intervals.items():
            prev = interval.get("prev_interval_id")
            if prev and prev not in intervals:
                report.error(
                    interval.get("_line"), "presence.interval", "prev_interval_id",
                    f"menunjuk `{prev}` yang tidak pernah dipancarkan. Rantai kehadiran "
                    "berkelanjutan jadi putus di backend.",
                )

        overlap = set(intervals) & set(tracks)
        if overlap:
            report.error(
                None, None, "",
                f"id dipakai sebagai interval_id sekaligus track_uuid: {sorted(overlap)}. "
                "Dua ruang nama harus terpisah.",
            )

        return report

    # ---------- aturan umum ----------

    def _check_policy_leakage(self, message, line, mtype, channel, report) -> None:
        if channel != "events":
            return
        for key in self._walk_keys(message):
            if key.startswith("_") or key in _ALLOWED_POLICY_LOOKALIKES:
                continue
            for pattern in POLICY_FIELD_PATTERNS:
                if pattern.search(key):
                    report.error(
                        line, mtype, key,
                        "nama field berbau konstanta kebijakan. Engine mengamati, backend "
                        "memutuskan: akumulasi dan aturan kantor tidak boleh lewat kanal ini.",
                    )
                    break

    @staticmethod
    def _walk_keys(node: Any):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from ConformanceChecker._walk_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from ConformanceChecker._walk_keys(item)

    def _check_seq(self, message, line, mtype, prev_seq, replay_gap_declared, report):
        seq = message.get("seq")
        if not isinstance(seq, int):
            return prev_seq, replay_gap_declared

        if prev_seq is None:
            return seq, replay_gap_declared

        if seq <= prev_seq:
            if self._allow_replay:
                return seq, replay_gap_declared
            report.error(
                line, mtype, "seq",
                f"seq mundur atau berulang ({prev_seq} -> {seq}). Hanya replay eksplisit "
                "yang boleh mengulang nomor.",
            )
            return seq, replay_gap_declared

        if seq > prev_seq + 1:
            if replay_gap_declared:
                replay_gap_declared = False
            else:
                report.error(
                    line, mtype, "seq",
                    f"lubang di seq ({prev_seq} -> {seq}) tanpa `replay_gap` mendahului. "
                    "Backend akan menganggap tidak ada kejadian, padahal ada.",
                )
        return seq, replay_gap_declared

    def _check_pts_space(
        self, message, line, mtype, camera_epoch, camera_offset, last_pts, tracks, report
    ) -> None:
        """pts hanya sebanding di dalam satu (camera_id, stream_epoch).

        Aturan ini menangkap kelas bug yang paling membingungkan di §6.6: offset
        PTS->wallclock yang lupa ditetapkan ulang setelah reconnect. Gejalanya
        bukan error, tapi satu kamera melaporkan interval di tahun yang salah.
        """
        pts = message.get("pts")
        epoch = message.get("stream_epoch")
        camera_id = message.get("camera_id")

        if camera_id is None:
            track_uuid = message.get("track_uuid")
            info = tracks.get(track_uuid) if track_uuid else None
            camera_id = info.camera_id if info else None

        if camera_id is None or epoch is None or not isinstance(pts, (int, float)):
            return

        known_epoch = camera_epoch.get(camera_id)
        if known_epoch is not None and epoch < known_epoch:
            report.error(
                line, mtype, "stream_epoch",
                f"stream_epoch mundur untuk kamera `{camera_id}` ({known_epoch} -> {epoch}).",
            )
            return

        if epoch not in camera_offset.get(camera_id, {}):
            report.warn(
                line, mtype, "stream_epoch",
                f"pts dipancarkan untuk kamera `{camera_id}` epoch {epoch} sebelum ada "
                "`camera.online` yang menetapkan pts_wallclock_offset untuk epoch itu. "
                "Backend tidak punya cara mengubahnya jadi jam dinding.",
            )

        key = (camera_id, epoch)
        previous = last_pts.get(key)
        if previous is not None and pts + 1e-6 < previous:
            report.warn(
                line, mtype, "pts",
                f"pts mundur di dalam satu stream_epoch untuk `{camera_id}` "
                f"({previous:.3f} -> {pts:.3f}).",
            )
        last_pts[key] = max(pts, previous or pts)

    # ---------- per jenis pesan ----------

    def _on_camera_online(self, message, *, line, camera_epoch, camera_offset, report, **_) -> None:
        camera_id = message["camera_id"]
        epoch = message["stream_epoch"]
        previous = camera_epoch.get(camera_id)

        if previous is not None and epoch <= previous:
            report.error(
                line, "camera.online", "stream_epoch",
                f"reconnect kamera `{camera_id}` tidak menaikkan stream_epoch "
                f"({previous} -> {epoch}). Ruang pts yang baru jadi tidak bisa dibedakan "
                "dari yang lama, dan offset lama akan dipakai untuk stream baru.",
            )

        camera_epoch[camera_id] = epoch
        camera_offset.setdefault(camera_id, {})[epoch] = message["pts_wallclock_offset"]

    def _on_camera_failed(self, message, *, camera_failed, **_) -> None:
        camera_failed[message["camera_id"]] = True

    def _on_track_started(self, message, *, tracks, camera_epoch, **_) -> None:
        tracks[message["track_uuid"]] = _TrackInfo(
            camera_id=message["camera_id"],
            started_pts=message["pts"],
            stream_epoch=message["stream_epoch"],
        )

    def _on_track_identified(self, message, *, line, tracks, report, **_) -> None:
        track_uuid = message["track_uuid"]
        info = tracks.get(track_uuid)
        if info is None:
            report.error(
                line, "track.identified", "track_uuid",
                f"`{track_uuid}` tidak pernah dibuka oleh `track.started`.",
            )
            return

        if info.started_pts is not None:
            declared = message["track_started_pts"]
            if abs(declared - info.started_pts) > 1e-6:
                report.error(
                    line, "track.identified", "track_started_pts",
                    f"berbeda dari pts `track.started` ({declared} vs {info.started_pts}). "
                    "Backend akan menghitung kehadiran dari saat wajah terbaca, bukan saat "
                    "orangnya masuk.",
                )

        if message["pts"] + 1e-6 < message["track_started_pts"]:
            report.error(
                line, "track.identified", "pts",
                "identifikasi terjadi sebelum track lahir.",
            )

    def _on_track_heartbeat(self, message, *, line, tracks, report, **_) -> None:
        self._require_open_track(message, line, "track.heartbeat", tracks, report)

    def _on_track_resumed(self, message, *, line, tracks, camera_epoch, report, **_) -> None:
        prev_uuid = message["prev_track_uuid"]
        previous = tracks.get(prev_uuid)
        if previous is None:
            report.error(
                line, "track.resumed", "prev_track_uuid",
                f"`{prev_uuid}` tidak pernah ada.",
            )
        elif not previous.ended:
            report.warn(
                line, "track.resumed", "prev_track_uuid",
                f"menyambung ke `{prev_uuid}` yang belum pernah `track.ended`.",
            )

        new_uuid = message["track_uuid"]
        if new_uuid not in tracks:
            tracks[new_uuid] = _TrackInfo(
                camera_id=previous.camera_id if previous else None,
                started_pts=message["pts"],
                stream_epoch=message.get("stream_epoch"),
            )

        if previous is not None and previous.camera_id and tracks[new_uuid].camera_id:
            if previous.camera_id != tracks[new_uuid].camera_id:
                report.error(
                    line, "track.resumed", "prev_track_uuid",
                    "penyambungan lintas kamera. Itu handoff, dan handoff adalah "
                    "penyambungan sesi milik backend, bukan bukti perseptual milik engine.",
                )

    def _on_track_ended(self, message, *, line, tracks, camera_failed, report, **_) -> None:
        track_uuid = message["track_uuid"]
        info = self._require_open_track(message, line, "track.ended", tracks, report)
        if info is None:
            return

        info.ended = True

        if info.camera_id and camera_failed.get(info.camera_id) and message["reason"] != "camera_lost":
            report.error(
                line, "track.ended", "reason",
                f"kamera `{info.camera_id}` sedang putus, tapi track berakhir dengan "
                f"`{message['reason']}`. Kamera putus bukan alasan menandai orang pulang; "
                "reason wajib `camera_lost`.",
            )

    def _on_presence_interval(self, message, *, line, intervals, tracks, report, **_) -> None:
        interval_id = message["interval_id"]

        if interval_id in intervals:
            report.error(
                line, "presence.interval", "interval_id",
                f"`{interval_id}` dipancarkan dua kali.",
            )

        if message["end_pts"] + 1e-6 < message["start_pts"]:
            report.error(
                line, "presence.interval", "end_pts",
                "interval berakhir sebelum ia mulai.",
            )

        if message["end_at"] < message["start_at"]:
            report.error(
                line, "presence.interval", "end_at",
                "end_at lebih awal dari start_at.",
            )

        track_uuid = message.get("track_uuid")
        if track_uuid and track_uuid not in tracks:
            report.warn(
                line, "presence.interval", "track_uuid",
                f"merujuk track `{track_uuid}` yang tidak ada di rekaman ini.",
            )

        if message["end_zone"] == "interior" and message["end_reason"] == "left_frame":
            report.warn(
                line, "presence.interval", "end_reason",
                "berakhir di tengah ruangan tapi alasannya `left_frame`. Kombinasi ini "
                "hampir selalu kegagalan tracking yang salah label, dan backend akan "
                "menghitungnya sebagai kepergian nyata.",
            )

        intervals[interval_id] = message

    def _on_snapshot(self, message, *, line, report, **_) -> None:
        offsets = message["pts_wallclock_offset"]
        for entry in message["live"]:
            camera_id = entry["camera_id"]
            if camera_id not in offsets:
                report.error(
                    line, "snapshot", "pts_wallclock_offset",
                    f"tidak memuat offset untuk kamera `{camera_id}` yang punya track hidup.",
                )
                continue
            if offsets[camera_id]["stream_epoch"] != entry["stream_epoch"]:
                report.error(
                    line, "snapshot", "pts_wallclock_offset",
                    f"offset kamera `{camera_id}` untuk epoch "
                    f"{offsets[camera_id]['stream_epoch']}, tapi track hidup ada di epoch "
                    f"{entry['stream_epoch']}.",
                )

    @staticmethod
    def _require_open_track(message, line, mtype, tracks, report) -> Optional[_TrackInfo]:
        track_uuid = message["track_uuid"]
        info = tracks.get(track_uuid)
        if info is None:
            report.error(line, mtype, "track_uuid", f"`{track_uuid}` tidak pernah dibuka.")
            return None
        if info.ended:
            report.error(line, mtype, "track_uuid", f"`{track_uuid}` sudah berakhir.")
            return None
        return info
