#!/usr/bin/env python3
"""
The real engine and the real backend client, over a real socket.

`engine/tests/` may not import `backend/` — §6.8's dependency rule, enforced by
a test that scans imports — and that rule is right. It also means no test inside
either track can ever check the thing most likely to be wrong: whether the two
sides actually agree. So the check lives here, in `scripts/`, which belongs to
neither, and it drives the *real* `backend.services.engine_client.EngineClient`
against the *real* `engine.runtime.EngineRuntime`.

Two bugs were found by writing it, and neither was visible from either side
alone:

- the engine wrote control replies with no `channel` field, while the backend
  routes purely on that field. Every `ack` would therefore have been validated
  as a durable presence event, failed the schema, and — since the client closes
  the connection on any processing failure — torn down the link on the first
  `set_cameras`;
- `replay_gap` was tagged `events`, where the schema says it is `control`.

Run it:

    python scripts/integration_smoke.py

It exits non-zero on the first thing that does not hold.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dataclasses  # noqa: E402

from contracts.validator import ConformanceChecker, SchemaValidator  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.runtime import EngineRuntime, RuntimeOptions  # noqa: E402
from engine.runtime.camera import CameraSpec  # noqa: E402

CAMERAS = ["r1", "r2", "r3"]
FRAMES_PER_CAMERA = 60


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main() -> int:
    from backend.services.engine_client import EngineClient

    port = free_port()
    config = dataclasses.replace(
        load_config(), source_type="mock", auto_warmup=False, strict_mode=True
    )
    runtime = EngineRuntime(
        config=config,
        options=RuntimeOptions(
            tcp=("127.0.0.1", port),
            max_frames=FRAMES_PER_CAMERA,
            snapshot_interval_seconds=1.0,
            health_interval_seconds=1.0,
            view_fps=5.0,
        ),
    )
    runtime.listen()
    threading.Thread(target=runtime.api.serve_forever, daemon=True).start()

    events: List[Dict[str, Any]] = []
    views: List[Dict[str, Any]] = []
    controls: List[Dict[str, Any]] = []

    client = EngineClient(host="127.0.0.1", port=port)
    client.set_event_handler(events.append)
    client.set_view_handler(views.append)
    client.set_control_handler(controls.append)

    failures: List[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)
            print(f"  FAIL  {message}")
        else:
            print(f"  ok    {message}")

    try:
        hello_ack = client.connect()
        check(hello_ack.get("type") == "hello_ack", "backend handshake accepted")
        check(
            hello_ack.get("protocol_version") == 1,
            "protocol version agreed",
        )

        threading.Thread(target=client.receive_loop, daemon=True).start()

        client.send(
            {
                "type": "set_cameras",
                "v": 1,
                "ts": "2026-09-20T00:00:00.000Z",
                "cameras": [
                    {
                        "camera_id": camera_id,
                        "uri": "mock",
                        "door_region": [0.0, 0.0, 0.4, 0.4],
                        "enabled": True,
                    }
                    for camera_id in CAMERAS
                ],
            }
        )

        deadline = time.time() + 45
        while time.time() < deadline:
            cameras = runtime.cameras
            if len(cameras) == len(CAMERAS) and not any(c.alive for c in cameras.values()):
                break
            time.sleep(0.1)
        time.sleep(1.5)     # let the last events and one snapshot drain

        kinds = Counter(message["type"] for message in events)
        print(f"\n  events: {dict(kinds)}")
        print(f"  control replies: {[m['type'] for m in controls]}")
        print(f"  view frames: {len(views)}\n")

        # --- the seam that had two bugs in it ---------------------------
        check(
            any(m.get("type") == "ack" for m in controls),
            "set_cameras ack arrived on the control channel, not as an event",
        )
        check(
            not any(m.get("type") == "ack" for m in events),
            "no control reply leaked into the durable event stream",
        )

        # --- multi camera -----------------------------------------------
        online = [m for m in events if m["type"] == "camera.online"]
        check(
            {m["camera_id"] for m in online} == set(CAMERAS),
            f"all {len(CAMERAS)} cameras came online",
        )
        offsets = {m["camera_id"]: m["pts_wallclock_offset"] for m in online}
        check(
            all(isinstance(value, float) for value in offsets.values()),
            "each camera reported its own pts_wallclock_offset (§4.4)",
        )

        started = [m for m in events if m["type"] == "track.started"]
        check(
            {m["camera_id"] for m in started} == set(CAMERAS),
            "every camera produced tracks, so none of them silently did nothing",
        )
        ended = [m for m in events if m["type"] == "track.ended"]
        check(
            len(ended) == len(started),
            f"every track was closed ({len(started)} started, {len(ended)} ended)",
        )
        check(
            all("exit_zone" in m and "reason" in m for m in ended),
            "every track.ended carries reason and exit_zone (§7 checklist)",
        )

        snapshots = [m for m in events if m["type"] == "snapshot"]
        check(bool(snapshots), "a periodic snapshot was emitted (§4.5)")
        if snapshots:
            check(
                set(snapshots[-1]["pts_wallclock_offset"]) == set(CAMERAS),
                "the snapshot carries an offset per camera",
            )

        health = [m for m in events if m["type"] == "engine.health"]
        check(bool(health), "engine.health was emitted")
        if health:
            check(
                health[-1]["models_loaded"] is False,
                "health says models_loaded=false rather than pretending "
                "(no embedder is wired, and nobody was identified)",
            )

        # --- the sequence -----------------------------------------------
        seqs = [m["seq"] for m in events if "seq" in m]
        check(seqs == sorted(seqs), "seq never goes backwards")
        check(
            seqs == list(range(seqs[0], seqs[0] + len(seqs))) if seqs else False,
            "seq is contiguous across three camera threads (one outbox, one lock)",
        )

        # --- the contract, not my opinion of it -------------------------
        validator = SchemaValidator()
        issues = []
        for message in events:
            issues.extend(validator.validate_message(message, expected_channel="events"))
        for message in views:
            issues.extend(validator.validate_message(message, expected_channel="view"))
        check(not issues, f"every message validates against the schema ({len(issues)} issues)")
        for issue in issues[:5]:
            print(f"        {issue}")

        report = ConformanceChecker().check(events)
        check(report.ok, f"the event stream passes the conformance checker: {report.errors[:3]}")

    finally:
        # Teardown noise, not a result: the client's receive thread is mid-ack
        # when the engine's socket goes away, and it logs that as an exception.
        # Worth knowing rather than only silencing — in production every engine
        # restart will print this on the backend side, and it is the backend's
        # reconnect path that has to make it harmless.
        import logging as _logging

        _logging.getLogger("backend.services.engine_client").setLevel(_logging.CRITICAL)
        client.connected = False
        time.sleep(0.2)
        client.close()
        runtime.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("integration smoke: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
