"""Skenario: apa yang terjadi, ditulis tangan; sisanya diturunkan.

Penulis skenario menuliskan **kejadian penting** saja — track lahir, track
dikenali, track berakhir, kamera putus. `emitter.py` yang menurunkan
`presence.interval`, `track.heartbeat`, `snapshot`, seluruh timestamp jam
dinding, dan penomoran seq.

Alasannya bukan kenyamanan. Kalau penulis skenario harus mengisi
`presence.interval` sendiri, ia akan mengisinya dengan apa yang *ia kira*
engine hitung, dan skenario berhenti menguji apa pun: ia cuma mengulang
asumsi penulisnya. Dengan diturunkan, aturan penurunannya ada di satu tempat
dan sama untuk keempat belas skenario.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Directive yang boleh muncul di `timeline`. Sengaja lebih sedikit daripada
# jumlah tipe pesan di protokol: yang tidak ada di sini adalah yang diturunkan.
EMITTABLE = {
    "track.started",
    "track.identified",
    "track.ended",
    "track.resumed",
    "track.identity_changed",
    "person.unidentified_present",
    "camera.online",
    "camera.failed",
    "camera.degraded",
    "camera.coverage",
    "enrollment_needed",
    # Bukan pesan, tapi instruksi ke harness:
    "client.disconnect",
    "engine.trim_outbox",
}

DERIVED = {"presence.interval", "track.heartbeat", "snapshot", "engine.health"}


class ScenarioError(ValueError):
    """Skenario tidak masuk akal. Gagal saat memuat, bukan di tengah jalan."""


@dataclass
class CameraSpec:
    camera_id: str
    online_at: float = 0.0
    pts_offset: float = 1758240000.0
    door_region: List[float] = field(default_factory=lambda: [0.62, 0.10, 0.95, 0.55])
    fps: float = 10.0


@dataclass
class Step:
    at: float
    emit: str
    raw: Dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


@dataclass
class Scenario:
    name: str
    description: str
    protocol_version: int
    cameras: List[CameraSpec]
    persons: List[str]
    timeline: List[Step]
    heartbeat_interval: float
    snapshot_interval: float
    health_interval: float
    stitch_window_seconds: float
    # Kanal view mati secara bawaan. Satu frame bbox per 200 ms selama lima
    # menit adalah 1.500 baris per kamera, dan empat belas skenario yang
    # semuanya merekamnya membuat repo naik beberapa megabyte untuk data yang
    # cuma dibutuhkan satu orang. Skenario yang memang dipakai frontend
    # menyalakannya sendiri.
    view_fps: float
    expect: Dict[str, Any]
    source_path: Optional[Path] = None

    def camera(self, camera_id: str) -> CameraSpec:
        for camera in self.cameras:
            if camera.camera_id == camera_id:
                return camera
        raise ScenarioError(f"skenario menyebut kamera `{camera_id}` yang tidak dideklarasikan")

    @property
    def duration(self) -> float:
        return max((step.at for step in self.timeline), default=0.0)


def load(path: Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ScenarioError(f"{path}: isinya bukan mapping YAML")
    return from_mapping(raw, source_path=Path(path))


def from_mapping(raw: Dict[str, Any], source_path: Optional[Path] = None) -> Scenario:
    """Bangun dan validasi sekaligus.

    Dipisah dari `load` supaya skenario bisa dibangun dari dict di tes, tapi
    lewat jalur yang SAMA -- termasuk validasinya. Membangun tanpa memvalidasi
    adalah cara paling mudah menulis tes yang lulus terhadap kode yang rusak.
    """
    scenario = _build(raw, source_path=source_path)
    _validate(scenario)
    return scenario


def _build(raw: Dict[str, Any], source_path: Optional[Path] = None) -> Scenario:
    cameras = [
        CameraSpec(
            camera_id=entry["id"],
            online_at=float(entry.get("online_at", 0.0)),
            pts_offset=float(entry.get("pts_offset", 1758240000.0)),
            door_region=list(entry.get("door_region", [0.62, 0.10, 0.95, 0.55])),
            fps=float(entry.get("fps", 10.0)),
        )
        for entry in raw.get("cameras", [])
    ]

    timeline: List[Step] = []
    for index, entry in enumerate(raw.get("timeline", [])):
        if "at" not in entry or "emit" not in entry:
            raise ScenarioError(f"langkah #{index} butuh `at` dan `emit`")
        timeline.append(Step(at=float(entry["at"]), emit=str(entry["emit"]), raw=dict(entry)))

    timeline.sort(key=lambda step: step.at)

    return Scenario(
        name=raw.get("name") or (source_path.stem if source_path else "tanpa-nama"),
        description=raw.get("description", ""),
        protocol_version=int(raw.get("protocol_version", 1)),
        cameras=cameras,
        persons=[str(person) for person in raw.get("persons", [])],
        timeline=timeline,
        heartbeat_interval=float(raw.get("heartbeat_interval", 30.0)),
        snapshot_interval=float(raw.get("snapshot_interval", 10.0)),
        health_interval=float(raw.get("health_interval", 60.0)),
        stitch_window_seconds=float(raw.get("stitch_window_seconds", 5.0)),
        view_fps=float(raw.get("view_fps", 0.0)),
        expect=dict(raw.get("expect", {})),
        source_path=source_path,
    )


def _validate(scenario: Scenario) -> None:
    if not scenario.cameras:
        raise ScenarioError("skenario tanpa kamera")

    known_cameras = {camera.camera_id for camera in scenario.cameras}
    known_persons = set(scenario.persons)
    open_tracks: Dict[str, str] = {}
    ended_tracks: set = set()

    for step in scenario.timeline:
        if step.emit in DERIVED:
            raise ScenarioError(
                f"`{step.emit}` diturunkan otomatis dan tidak boleh ditulis tangan. "
                "Skenario yang menuliskannya sendiri cuma mengulang asumsi penulisnya."
            )
        if step.emit not in EMITTABLE:
            raise ScenarioError(f"`{step.emit}` bukan directive yang dikenal")

        camera_id = step.get("camera")
        if camera_id is not None and camera_id not in known_cameras:
            raise ScenarioError(f"kamera `{camera_id}` tidak dideklarasikan")

        person = step.get("person")
        if person is not None and str(person) not in known_persons:
            raise ScenarioError(
                f"orang `{person}` tidak ada di `persons`. Roster skenario harus eksplisit, "
                "supaya `set_roster` bisa diuji."
            )

        track = step.get("track")

        if step.emit == "track.started":
            if track in open_tracks:
                raise ScenarioError(f"track `{track}` dibuka dua kali")
            if camera_id is None:
                raise ScenarioError(f"`track.started` untuk `{track}` tanpa `camera`")
            open_tracks[track] = camera_id

        elif step.emit == "track.resumed":
            previous = step.get("prev_track")
            if previous is None:
                raise ScenarioError(f"`track.resumed` `{track}` tanpa `prev_track`")
            if previous not in ended_tracks and previous not in open_tracks:
                raise ScenarioError(f"`track.resumed` menunjuk `{previous}` yang tidak pernah ada")
            open_tracks.setdefault(track, open_tracks.get(previous, ""))

        elif step.emit in {"track.identified", "track.identity_changed", "person.unidentified_present"}:
            if track not in open_tracks:
                raise ScenarioError(f"`{step.emit}` untuk track `{track}` yang belum dibuka")

        elif step.emit == "track.ended":
            if track not in open_tracks:
                raise ScenarioError(f"`track.ended` untuk track `{track}` yang belum dibuka")
            ended_tracks.add(track)
            open_tracks.pop(track, None)

    if scenario.stitch_window_seconds <= 0:
        raise ScenarioError("stitch_window_seconds harus > 0")
