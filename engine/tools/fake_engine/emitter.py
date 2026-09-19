"""Turunkan aliran protokol lengkap dari timeline skenario.

Semua aritmetika waktu ada di sini, dan hanya di sini.

Tiga aturan yang menanggung beban paling berat, dan tiga-tiganya adalah tempat
implementasi asli akan tergoda salah:

**Interval dimulai saat track lahir, bukan saat wajah terbaca** (§4.4). Orang
masuk 10:00:00, wajahnya terbaca 10:00:08; kalau `start_pts` diisi waktu
identifikasi, delapan detik itu dicuri dari jatah tiga puluh menitnya. Lima
belas kali keluar-masuk sehari jadi dua menit.

**pts nol lagi setiap reconnect, `at` tidak.** pts relatif terhadap awal stream;
`stream_epoch` menandai stream mana. `pts_wallclock_offset` untuk epoch baru
dihitung supaya jam dinding tetap kontinu — itu yang membuat backend bisa
menyambung interval sebelum dan sesudah reconnect tanpa tahu apa pun soal RTSP.

**Kamera putus mengakhiri track dengan `camera_lost`, bukan `left_frame`.**
Kalau salah, satu ruangan penuh orang ditandai pulang pada detik yang sama, dan
itu baru ketahuan saat penggajian.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .scenario import Scenario, Step

Message = Tuple[str, Dict[str, Any]]  # (channel, payload)


def _rfc3339(unix_seconds: float) -> str:
    moment = dt.datetime.fromtimestamp(unix_seconds, dt.timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class _Track:
    uuid: str
    camera_id: str
    stream_epoch: int
    started_pts: float
    start_zone: str
    person_id: Optional[str] = None
    identity_source: str = "face"
    identified_at_pts: Optional[float] = None
    interval_start_pts: Optional[float] = None
    interval_start_zone: str = "door"
    interval_start_source: str = "face"
    prev_interval_id: Optional[str] = None
    confidence: float = 0.9
    evidence_count: int = 0
    ended: bool = False
    box_seed: int = 0


@dataclass
class _Camera:
    spec: Any
    stream_epoch: int = -1
    epoch_started_at: float = 0.0
    online: bool = False
    offset: float = 0.0


class Emitter:
    """Ubah satu `Scenario` jadi daftar pesan protokol, berurut waktu skenario.

    Keluarannya deterministik: id diturunkan dari label di skenario, dan satu-
    satunya keacakan (gerak bbox di kanal `view`) di-seed. Fixture yang
    di-commit karenanya stabil, dan diff-nya berarti sesuatu benar-benar berubah.
    """

    def __init__(self, scenario: Scenario, seed: int = 42, view_fps: float = 5.0) -> None:
        self._scenario = scenario
        self._random = random.Random(seed)
        self._view_fps = view_fps

        self._seq = 0
        self._tracks: Dict[str, _Track] = {}
        self._cameras: Dict[str, _Camera] = {
            camera.camera_id: _Camera(spec=camera) for camera in scenario.cameras
        }
        self._interval_counter: Dict[str, int] = {}
        self._last_interval_of_track: Dict[str, str] = {}
        self._pending_resume: Dict[str, str] = {}

    # ---------------- waktu ----------------

    def _pts(self, camera_id: str, when: float) -> float:
        camera = self._cameras[camera_id]
        return round(max(0.0, when - camera.epoch_started_at), 3)

    def _at(self, camera_id: str, when: float) -> str:
        return _rfc3339(self._cameras[camera_id].spec.pts_offset + when)

    def _envelope(self, channel: str, message_type: str, when: float, camera_id: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "type": message_type,
            "v": 1,
            "ts": self._at(camera_id, when),
        }
        if channel == "events":
            self._seq += 1
            payload["seq"] = self._seq
        return payload

    # ---------------- id ----------------

    def _next_interval_id(self, camera_id: str) -> str:
        self._interval_counter[camera_id] = self._interval_counter.get(camera_id, 0) + 1
        return f"iv_{camera_id}-{self._interval_counter[camera_id]:04d}"

    @staticmethod
    def _track_uuid(label: str) -> str:
        return label if label.startswith("tr_") else f"tr_{label}"

    # ---------------- jalan ----------------

    def run(self) -> List[Message]:
        messages: List[Message] = []
        for when, kind, payload in self._merged_timeline():
            if kind == "step":
                messages.extend(self._on_step(payload, when))
            elif kind == "heartbeat":
                messages.extend(self._heartbeats(when))
            elif kind == "snapshot":
                messages.extend(self._snapshot(when))
            elif kind == "health":
                messages.extend(self._health(when))
            elif kind == "view":
                messages.extend(self._view(when))
        messages.extend(self._shutdown(self._scenario.duration + 1.0))
        return messages

    def _merged_timeline(self):
        scenario = self._scenario
        entries: List[Tuple[float, int, str, Any]] = []

        for order, step in enumerate(scenario.timeline):
            entries.append((step.at, 0, "step", step))

        end = scenario.duration
        for kind, interval in (
            ("heartbeat", scenario.heartbeat_interval),
            ("snapshot", scenario.snapshot_interval),
            ("health", scenario.health_interval),
            ("view", 1.0 / self._view_fps if self._view_fps > 0 else 0),
        ):
            if interval <= 0:
                continue
            tick = interval
            while tick <= end:
                entries.append((tick, 1, kind, None))
                tick = round(tick + interval, 6)

        entries.sort(key=lambda item: (item[0], item[1]))
        for when, _, kind, payload in entries:
            yield when, kind, payload

    # ---------------- directive ----------------

    def _on_step(self, step: Step, when: float) -> List[Message]:
        handler = getattr(self, "_do_" + step.emit.replace(".", "_"), None)
        if handler is None:
            return []
        return handler(step, when)

    def _do_camera_online(self, step: Step, when: float) -> List[Message]:
        camera_id = step.get("camera")
        camera = self._cameras[camera_id]
        camera.stream_epoch += 1
        camera.epoch_started_at = when
        camera.online = True
        # Offset dihitung supaya jam dinding kontinu melintasi reconnect: pts
        # kembali ke nol, `at` tidak melompat. Inilah yang membuat backend bisa
        # menyambung interval sebelum dan sesudah tanpa tahu soal RTSP.
        camera.offset = camera.spec.pts_offset + when

        payload = self._envelope("events", "camera.online", when, camera_id)
        payload.update(
            camera_id=camera_id,
            stream_epoch=camera.stream_epoch,
            fps=camera.spec.fps,
            pts_wallclock_offset=camera.offset,
        )
        return [("events", payload)]

    def _do_camera_failed(self, step: Step, when: float) -> List[Message]:
        camera_id = step.get("camera")
        camera = self._cameras[camera_id]
        camera.online = False

        out: List[Message] = []
        payload = self._envelope("events", "camera.failed", when, camera_id)
        payload.update(
            camera_id=camera_id,
            reason=step.get("reason", "connection_refused"),
            retry_in_seconds=float(step.get("retry_in_seconds", 5.0)),
        )
        out.append(("events", payload))

        # Semua track di kamera itu berakhir serentak -- tapi TIDAK seorang pun
        # pulang. Kode alasannya yang membedakan, dan ini satu-satunya tempat
        # yang boleh memancarkan `forced`.
        for track in list(self._tracks.values()):
            if track.camera_id != camera_id or track.ended:
                continue
            out.extend(
                self._end_track(
                    track,
                    when,
                    reason="camera_lost",
                    exit_zone=track.start_zone if track.start_zone != "door" else "interior",
                    end_source="forced",
                )
            )
        return out

    def _do_camera_degraded(self, step: Step, when: float) -> List[Message]:
        camera_id = step.get("camera")
        payload = self._envelope("events", "camera.degraded", when, camera_id)
        payload.update(
            camera_id=camera_id,
            reason=step.get("reason", "fps_below_target"),
            fps=float(step.get("fps", 3.1)),
        )
        return [("events", payload)]

    def _do_camera_coverage(self, step: Step, when: float) -> List[Message]:
        camera_id = step.get("camera")
        payload = self._envelope("events", "camera.coverage", when, camera_id)
        payload.update(
            camera_id=camera_id,
            observed_regions=step.get("observed", [[0.1, 0.2, 0.9, 0.95]]),
            never_observed=step.get("never_observed", [[0.0, 0.0, 0.1, 1.0]]),
        )
        return [("events", payload)]

    def _do_track_started(self, step: Step, when: float) -> List[Message]:
        camera_id = step.get("camera")
        camera = self._cameras[camera_id]
        uuid = self._track_uuid(step.get("track"))
        zone = step.get("zone", "door")
        pts = self._pts(camera_id, when)

        self._tracks[uuid] = _Track(
            uuid=uuid,
            camera_id=camera_id,
            stream_epoch=camera.stream_epoch,
            started_pts=pts,
            start_zone=zone,
            interval_start_pts=pts,
            interval_start_zone=zone,
            interval_start_source="face",
            box_seed=self._random.randrange(1 << 30),
        )

        payload = self._envelope("events", "track.started", when, camera_id)
        payload.update(
            track_uuid=uuid,
            camera_id=camera_id,
            stream_epoch=camera.stream_epoch,
            pts=pts,
            at=self._at(camera_id, when),
            zone=zone,
        )
        return [("events", payload)]

    def _do_track_identified(self, step: Step, when: float) -> List[Message]:
        uuid = self._track_uuid(step.get("track"))
        track = self._tracks[uuid]
        track.person_id = str(step.get("person"))
        track.identity_source = "face"
        track.confidence = float(step.get("confidence", step.get("similarity", 0.9)))
        track.evidence_count = int(step.get("evidence_count", 3))
        pts = self._pts(track.camera_id, when)
        track.identified_at_pts = pts

        payload = self._envelope("events", "track.identified", when, track.camera_id)
        payload.update(
            track_uuid=uuid,
            person_id=track.person_id,
            pts=pts,
            at=self._at(track.camera_id, when),
            # §4.4: batas interval dimundurkan ke saat track lahir.
            track_started_pts=track.started_pts,
            similarity=float(step.get("similarity", 0.88)),
            margin=float(step.get("margin", 0.11)),
            evidence_count=track.evidence_count,
        )
        return [("events", payload)]

    def _do_track_identity_changed(self, step: Step, when: float) -> List[Message]:
        """Identitas berpindah di tengah track.

        Interval lama ditutup dengan `identity_released` dan interval baru
        dibuka: satu track, dua interval. Inilah kenapa `interval_id` tidak
        boleh sama dengan `track_uuid`.
        """
        uuid = self._track_uuid(step.get("track"))
        track = self._tracks[uuid]
        to_person = step.get("person") or step.get("to_person")
        pts = self._pts(track.camera_id, when)
        out: List[Message] = []

        if track.person_id is not None:
            out.extend(
                self._emit_interval(
                    track,
                    when,
                    end_pts=pts,
                    end_zone=step.get("zone", "interior"),
                    end_source="tracking",
                    end_reason="identity_released",
                )
            )

        payload = self._envelope("events", "track.identity_changed", when, track.camera_id)
        payload.update(
            track_uuid=uuid,
            from_person_id=track.person_id,
            to_person_id=str(to_person) if to_person else None,
            reason=step.get("reason", "sustained_disagreement"),
            disagreement_count=int(step.get("disagreement_count", 3)),
            pts=pts,
            at=self._at(track.camera_id, when),
        )
        out.append(("events", payload))

        track.person_id = str(to_person) if to_person else None
        track.interval_start_pts = pts
        track.interval_start_zone = step.get("zone", "interior")
        track.interval_start_source = "face"
        track.prev_interval_id = None
        return out

    def _do_track_resumed(self, step: Step, when: float) -> List[Message]:
        uuid = self._track_uuid(step.get("track"))
        previous_uuid = self._track_uuid(step.get("prev_track"))
        previous = self._tracks[previous_uuid]
        track = self._tracks[uuid]

        track.person_id = str(step.get("person", previous.person_id or ""))
        track.identity_source = "tracking"
        track.prev_interval_id = self._last_interval_of_track.get(previous_uuid)
        track.interval_start_source = "tracking"

        pts = self._pts(track.camera_id, when)
        gap = float(step.get("gap_seconds", 0.0))

        payload = self._envelope("events", "track.resumed", when, track.camera_id)
        payload.update(
            track_uuid=uuid,
            prev_track_uuid=previous_uuid,
            person_id=track.person_id,
            gap_seconds=gap,
            pts=pts,
            at=self._at(track.camera_id, when),
            stream_epoch=track.stream_epoch,
        )
        return [("events", payload)]

    def _do_person_unidentified_present(self, step: Step, when: float) -> List[Message]:
        uuid = self._track_uuid(step.get("track"))
        track = self._tracks[uuid]
        payload = self._envelope("events", "person.unidentified_present", when, track.camera_id)
        payload.update(
            track_uuid=uuid,
            camera_id=track.camera_id,
            duration_seconds=float(step.get("duration_seconds", when - 0.0)),
            attempts=int(step.get("attempts", 18)),
            reason=step.get("reason", "no_face_detected"),
        )
        return [("events", payload)]

    def _do_track_ended(self, step: Step, when: float) -> List[Message]:
        uuid = self._track_uuid(step.get("track"))
        track = self._tracks[uuid]
        return self._end_track(
            track,
            when,
            reason=step.get("reason", "left_frame"),
            exit_zone=step.get("zone", "door"),
            end_source=step.get("end_source"),
        )

    def _do_enrollment_needed(self, step: Step, when: float) -> List[Message]:
        camera_id = self._scenario.cameras[0].camera_id
        payload = self._envelope("events", "enrollment_needed", when, camera_id)
        payload.update(person_ids=[str(p) for p in step.get("persons", [])])
        return [("events", payload)]

    def _do_client_disconnect(self, step: Step, when: float) -> List[Message]:
        return [("_harness", {"action": "disconnect", "at": when})]

    def _do_engine_trim_outbox(self, step: Step, when: float) -> List[Message]:
        return [("_harness", {"action": "trim_outbox", "keep_from_seq": int(step.get("keep_from_seq", 1)), "at": when})]

    # ---------------- penurunan ----------------

    def _end_track(self, track: _Track, when: float, reason: str, exit_zone: str, end_source: Optional[str]) -> List[Message]:
        pts = self._pts(track.camera_id, when)
        out: List[Message] = []

        if end_source is None:
            end_source = "tracking" if track.identity_source == "tracking" else "face"
        if reason in {"camera_lost", "engine_shutdown"}:
            end_source = "forced"

        if track.person_id is not None:
            out.extend(
                self._emit_interval(
                    track, when, end_pts=pts, end_zone=exit_zone,
                    end_source=end_source, end_reason=reason,
                )
            )

        payload = self._envelope("events", "track.ended", when, track.camera_id)
        payload.update(
            track_uuid=track.uuid,
            pts=pts,
            at=self._at(track.camera_id, when),
            reason=reason,
            exit_zone=exit_zone,
        )
        out.append(("events", payload))
        track.ended = True
        return out

    def _emit_interval(self, track: _Track, when: float, end_pts: float, end_zone: str,
                       end_source: str, end_reason: str) -> List[Message]:
        interval_id = self._next_interval_id(track.camera_id)
        start_pts = track.interval_start_pts if track.interval_start_pts is not None else track.started_pts

        payload = self._envelope("events", "presence.interval", when, track.camera_id)
        payload.update(
            interval_id=interval_id,
            person_id=track.person_id,
            camera_id=track.camera_id,
            stream_epoch=track.stream_epoch,
            track_uuid=track.uuid,
            start_pts=start_pts,
            end_pts=end_pts,
            start_at=self._at(track.camera_id, self._when_of(track.camera_id, start_pts)),
            end_at=self._at(track.camera_id, when),
            start_source=track.interval_start_source,
            end_source=end_source,
            start_zone=track.interval_start_zone,
            end_zone=end_zone,
            end_reason=end_reason,
            identity_confidence=round(track.confidence, 3),
            evidence_count=max(1, track.evidence_count),
        )
        if track.prev_interval_id:
            payload["prev_interval_id"] = track.prev_interval_id

        self._last_interval_of_track[track.uuid] = interval_id
        return [("events", payload)]

    def _when_of(self, camera_id: str, pts: float) -> float:
        return self._cameras[camera_id].epoch_started_at + pts

    def _heartbeats(self, when: float) -> List[Message]:
        out: List[Message] = []
        for track in self._tracks.values():
            if track.ended or not self._cameras[track.camera_id].online:
                continue
            payload = self._envelope("events", "track.heartbeat", when, track.camera_id)
            payload.update(
                track_uuid=track.uuid,
                person_id=track.person_id,
                pts=self._pts(track.camera_id, when),
                at=self._at(track.camera_id, when),
                identity_source=track.identity_source,
                confidence=round(track.confidence * 0.85, 3),
            )
            out.append(("events", payload))
        return out

    def _snapshot(self, when: float) -> List[Message]:
        live = [
            {
                "track_uuid": track.uuid,
                "camera_id": track.camera_id,
                "stream_epoch": track.stream_epoch,
                "person_id": track.person_id,
                "identity_source": track.identity_source,
                "since_pts": track.started_pts,
            }
            for track in self._tracks.values()
            if not track.ended and self._cameras[track.camera_id].online
        ]

        offsets = {
            camera_id: {"stream_epoch": camera.stream_epoch, "offset": camera.offset}
            for camera_id, camera in self._cameras.items()
            if camera.online
        }

        anchor = self._scenario.cameras[0].camera_id
        payload = self._envelope("events", "snapshot", when, anchor)
        payload.update(pts_wallclock_offset=offsets, live=live)
        return [("events", payload)]

    def _health(self, when: float) -> List[Message]:
        anchor = self._scenario.cameras[0].camera_id
        payload = self._envelope("events", "engine.health", when, anchor)
        payload.update(
            models_loaded=True,
            gpu_util=0.62,
            vram_mb=3100,
            queue_depth=len([t for t in self._tracks.values() if not t.ended]),
            drop_rate=0.02,
            cameras={
                camera_id: ("online" if camera.online else "failed")
                for camera_id, camera in self._cameras.items()
            },
        )
        return [("events", payload)]

    def _view(self, when: float) -> List[Message]:
        """Bbox per frame untuk overlay browser.

        Gerakannya sinusoidal dan di-seed, bukan realistis — tujuannya supaya
        frontend bisa membangun penyelarasan overlay tanpa kamera dan tanpa
        engine. Yang penting benar di sini cuma dua: koordinat ternormalisasi,
        dan `at` yang bisa dicocokkan ke EXT-X-PROGRAM-DATE-TIME.
        """
        import math

        out: List[Message] = []
        by_camera: Dict[str, List[Dict[str, Any]]] = {}

        for track in self._tracks.values():
            if track.ended or not self._cameras[track.camera_id].online:
                continue
            phase = (track.box_seed % 1000) / 1000.0
            centre_x = 0.5 + 0.28 * math.sin(when * 0.15 + phase * 6.283)
            centre_y = 0.55 + 0.08 * math.cos(when * 0.11 + phase * 6.283)
            half_w, half_h = 0.065, 0.28
            box = [
                round(max(0.0, centre_x - half_w), 4),
                round(max(0.0, centre_y - half_h), 4),
                round(min(1.0, centre_x + half_w), 4),
                round(min(1.0, centre_y + half_h), 4),
            ]
            by_camera.setdefault(track.camera_id, []).append(
                {
                    "track_uuid": track.uuid,
                    "bbox": box,
                    "person_id": track.person_id,
                    "identity_source": track.identity_source,
                }
            )

        for camera_id, boxes in by_camera.items():
            payload = self._envelope("view", "view.frame", when, camera_id)
            payload.update(
                camera_id=camera_id,
                stream_epoch=self._cameras[camera_id].stream_epoch,
                pts=self._pts(camera_id, when),
                at=self._at(camera_id, when),
                boxes=boxes,
            )
            out.append(("view", payload))

        return out

    def _shutdown(self, when: float) -> List[Message]:
        """Track yang masih hidup saat skenario habis ditutup `engine_shutdown`.

        Bukan kerapian: track yang menggantung tanpa `track.ended` membuat
        backend punya kehadiran terbuka selamanya, dan fixture-nya jadi tidak
        bisa dipakai menguji apa pun tentang penutupan.
        """
        out: List[Message] = []
        for track in list(self._tracks.values()):
            if track.ended or not self._cameras[track.camera_id].online:
                continue
            out.extend(
                self._end_track(
                    track, when, reason="engine_shutdown",
                    exit_zone=track.start_zone, end_source="forced",
                )
            )
        return out
