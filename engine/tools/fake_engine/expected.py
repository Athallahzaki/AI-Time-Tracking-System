"""Ringkasan **observasional** dari sebuah rekaman, untuk `<nama>.expected.json`.

Batasnya sengaja ditarik ketat: berkas ini menuliskan apa yang aliran itu
*berisi*, tidak pernah apa yang seharusnya *disimpulkan*. Ia melaporkan bahwa
ada celah 195 detik antara dua interval, bahwa yang pertama berakhir di
`interior` dengan `occluded_timeout`, dan bahwa engine tidak menyambungnya.
Apakah celah itu dihitung sebagai ketidakhadiran adalah kebijakan, milik
backend, dan tidak boleh diputuskan oleh berkas yang tinggal di `engine/`.

Karena itu pula tidak ada satu pun angka kebijakan di sini — tidak ada tiga
puluh menit, tidak ada jam istirahat resmi, tidak ada ambang toleransi.
`contracts/tools/policy_grep.py` akan benar kalau suatu hari ia berubah merah
karena berkas ini.

Bentuk keluarannya itu yang dipakai tes backend: putar ulang `.ndjson`, turunkan
sesi menurut kebijakan kalian, lalu bandingkan celah yang kalian temukan dengan
`gaps[]` di sini. Kalau jumlah dan batasnya berbeda, yang salah adalah parser
kalian, bukan kebijakannya — dan itu dua kegagalan yang sangat berbeda, yang
selama ini tercampur.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .scenario import Scenario


def build_expected(scenario: Scenario, messages: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    events = [payload for channel, payload in messages if channel == "events"]
    intervals = [event for event in events if event["type"] == "presence.interval"]

    by_person: Dict[str, List[Dict[str, Any]]] = {}
    for interval in intervals:
        by_person.setdefault(interval["person_id"], []).append(interval)

    people: Dict[str, Any] = {}
    all_gaps: List[Dict[str, Any]] = []

    for person_id, person_intervals in sorted(by_person.items()):
        ordered = sorted(person_intervals, key=lambda i: i["start_at"])
        people[person_id] = {
            "interval_count": len(ordered),
            "intervals": [
                {
                    "interval_id": interval["interval_id"],
                    "camera_id": interval["camera_id"],
                    "start_at": interval["start_at"],
                    "end_at": interval["end_at"],
                    "start_zone": interval["start_zone"],
                    "end_zone": interval["end_zone"],
                    "start_source": interval["start_source"],
                    "end_source": interval["end_source"],
                    "end_reason": interval["end_reason"],
                    "prev_interval_id": interval.get("prev_interval_id"),
                }
                for interval in ordered
            ],
        }

        for earlier, later in zip(ordered, ordered[1:]):
            stitched = later.get("prev_interval_id") == earlier["interval_id"]
            gap = {
                "person_id": person_id,
                "after_interval": earlier["interval_id"],
                "before_interval": later["interval_id"],
                "duration_seconds": _seconds_between(earlier["end_at"], later["start_at"]),
                "same_camera": earlier["camera_id"] == later["camera_id"],
                "closed_by_engine": stitched,
                "evidence": {
                    "end_zone": earlier["end_zone"],
                    "end_reason": earlier["end_reason"],
                    "end_source": earlier["end_source"],
                    "next_start_zone": later["start_zone"],
                    "next_start_source": later["start_source"],
                },
            }
            all_gaps.append(gap)

    sequences = [event["seq"] for event in events if "seq" in event]

    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "what_this_file_is": (
            "Ringkasan observasional dari rekaman, bukan kesimpulan kebijakan. "
            "Celah dilaporkan beserta bukti batasnya; bagaimana ia diperlakukan "
            "diputuskan backend."
        ),
        "counts": {
            "events": len(events),
            "intervals": len(intervals),
            "tracks_started": sum(1 for e in events if e["type"] == "track.started"),
            "tracks_ended": sum(1 for e in events if e["type"] == "track.ended"),
            "seq_first": min(sequences) if sequences else None,
            "seq_last": max(sequences) if sequences else None,
        },
        "cameras": sorted({event["camera_id"] for event in events if "camera_id" in event}),
        "people": people,
        "gaps": all_gaps,
        # Klaim yang ditulis penulis skenario, apa adanya. Kosong kalau tidak ada.
        "asserts": scenario.expect,
    }


def _seconds_between(earlier_at: str, later_at: str) -> float:
    import datetime as dt

    def parse(value: str) -> dt.datetime:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))

    return round((parse(later_at) - parse(earlier_at)).total_seconds(), 3)
