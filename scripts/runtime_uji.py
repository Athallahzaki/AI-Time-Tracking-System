"""
Engine ASLI (runtime: wajah + ReID + detector bersama) atas rekaman, tanpa backend.

    python scripts/runtime_uji.py --config engine/config/demo-4060.yaml \
        --source /kaggle/input/.../rekaman.mp4 --cameras 3 --seconds 600 --out runtime-out/r3

Menyalakan `python -m engine.runtime` di localhost, berperan sebagai backend
(hello -> set_cameras -> ack), mencatat semua pesan ke events.ndjson dan log
engine ke engine.log, lalu meringkas: fps/lag/drop per kamera, ms per tahap
(detector bersama, rekognisi, ReID), dan ANON.

Beda dengan engine.bench: ini runtime yang sama dengan pilot. File diputar
mengikuti jam dinding (PlaybackSource), jadi `effective_fps` = yang didapat
kamera sungguhan. N kamera = file yang sama N kali: angka ANON lintas kamera
tidak realistis (orang yang sama ada di N kamera sekaligus); untuk ANON pakai
--cameras 1.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

LOG_LINES = ("detector bersama:", "rekognisi:", "ReID:", "ReID tidak digabung", "klaim wajah lintas")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _send(sock: socket.socket, message: Dict[str, Any]) -> None:
    sock.sendall((json.dumps({"v": 1, "ts": _ts(), **message}) + "\n").encode())


def _connect(port: int, proc: subprocess.Popen, wait: float) -> socket.socket:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"engine keluar (kode {proc.returncode}) sebelum siap; lihat engine.log")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=2)
        except OSError:
            time.sleep(1)
    raise SystemExit(f"engine tidak membuka port {port} dalam {wait:.0f} dtk")


def run(args: argparse.Namespace) -> Path:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "ENGINE_SHARED_KEY"}  # localhost: tanpa auth
    cmd = [sys.executable, "-m", "engine.runtime", "--tcp", f"127.0.0.1:{args.port}",
           "--config", args.config, "--health-seconds", str(args.health_seconds),
           "--outbox", str(out / "outbox.sqlite3"), "--view-fps", "0", "--no-stderr-redirect"]
    log = open(out / "engine.log", "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
    events = open(out / "events.ndjson", "w", encoding="utf-8")
    try:
        sock = _connect(args.port, proc, args.startup_seconds)
        reader = sock.makefile("r", encoding="utf-8")
        _send(sock, {"type": "hello", "protocol_version": 1, "client": "runtime_uji", "last_event_seq": 0})
        sock.settimeout(args.startup_seconds)
        first = json.loads(reader.readline())
        if first.get("type") != "hello_ack":
            raise SystemExit(f"bukan hello_ack: {first}")
        cameras = [{"camera_id": f"cam{i}", "uri": args.source} for i in range(args.cameras)]
        _send(sock, {"type": "set_cameras", "cameras": cameras})
        print(f"engine siap; {args.cameras} kamera; merekam {args.seconds:.0f} dtk ke {out}", flush=True)

        sock.settimeout(None)
        lines: "queue.Queue[str]" = queue.Queue()
        # readline() di thread sendiri: file socket rusak setelah satu timeout.
        threading.Thread(target=lambda: [lines.put(x) for x in reader] + [lines.put("")],
                         daemon=True).start()
        end = time.monotonic() + args.seconds
        failed = set()
        while time.monotonic() < end and proc.poll() is None:
            try:
                line = lines.get(timeout=1.0)
            except queue.Empty:
                continue
            if not line:
                break
            events.write(line)
            msg = json.loads(line)
            if "seq" in msg:  # event durabel: tanpa ack outbox menumpuk
                _send(sock, {"type": "ack", "through_seq": msg["seq"]})
            if msg.get("type") == "camera.failed":
                failed.add(msg.get("camera_id"))
                if len(failed) == args.cameras:
                    print("semua kamera berhenti (rekaman habis?)", flush=True)
                    break
    finally:
        events.close()
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.close()
    return out


def summarize(out: Path, warmup_seconds: float = 30.0) -> Dict[str, Any]:
    msgs = [json.loads(line) for line in open(out / "events.ndjson", encoding="utf-8") if line.strip()]
    health = [m for m in msgs if m.get("type") == "engine.health"]
    t0 = health[0]["ts"] if health else None
    steady = [h for h in health if _secs(t0, h["ts"]) >= warmup_seconds] or health

    per_cam: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for h in steady:
        for cam, m in (h.get("camera_metrics") or {}).items():
            for key in ("effective_fps", "lag_seconds"):
                if key in m:
                    per_cam[cam][key].append(float(m[key]))
    last_cam = (health[-1].get("camera_metrics") or {}) if health else {}
    cams = {}
    for cam, series in sorted(per_cam.items()):
        fps, lag = series.get("effective_fps", []), series.get("lag_seconds", [])
        cams[cam] = {
            "fps_mean": _r(statistics.fmean(fps)) if fps else None,
            "fps_min": _r(min(fps)) if fps else None,
            "lag_mean_s": _r(statistics.fmean(lag)) if lag else None,
            "lag_max_s": _r(max(lag)) if lag else None,
            "frames_dropped_stale": last_cam.get(cam, {}).get("frames_dropped_stale"),
            "identified": last_cam.get(cam, {}).get("identified"),
        }

    started = Counter(m.get("camera_id") for m in msgs if m.get("type") == "track.started")
    label: Dict[str, Any] = {}
    for m in msgs:
        if m.get("type") == "track.heartbeat":
            label[m["track_uuid"]] = (m.get("person_id"), m.get("identity_source"))
    sources = Counter(src or "none" for _, src in label.values())
    anon = {pid for pid, _ in label.values() if pid and str(pid).startswith("ANON-")}
    people = {pid for pid, src in label.values() if pid and not str(pid).startswith("ANON-")}
    resolved = [m for m in msgs if m.get("type") == "identity.resolved"]

    log_tail: Dict[str, str] = {}
    for line in open(out / "engine.log", encoding="utf-8", errors="replace"):
        for key in LOG_LINES:
            if key in line:
                log_tail[key] = line.split(": ", 1)[-1].strip()

    return {
        "health_reports": len(health),
        "steady_reports": len(steady),
        "drop_rate_last": health[-1].get("drop_rate") if health else None,
        "gpu_util_mean": _r(statistics.fmean([h["gpu_util"] for h in steady if "gpu_util" in h])) if any("gpu_util" in h for h in steady) else None,
        "vram_mb_max": max((h["vram_mb"] for h in health if "vram_mb" in h), default=None),
        "degraded_last": health[-1].get("degraded_components") if health else None,
        "cameras": cams,
        "tracks_started": dict(sorted(started.items())),
        "tracks_by_last_source": dict(sources),
        "anon_ids": len(anon),
        "named_people": len(people),
        "identity_resolved": len(resolved),
        "identity_metrics_last": health[-1].get("identity_metrics") if health else None,
        "engine_log_last": log_tail,  # ms per tahap: detector bersama ms/gambar, rekognisi rata2 ms, ReID ms/batch
    }


def _secs(a: str, b: str) -> float:
    parse = lambda s: datetime.strptime(re.sub(r"(\.\d{6})\d*", r"\1", s.rstrip("Z")) if "." in s else s.rstrip("Z"),
                                        "%Y-%m-%dT%H:%M:%S.%f" if "." in s else "%Y-%m-%dT%H:%M:%S")
    return (parse(b) - parse(a)).total_seconds()


def _r(x: float) -> float:
    return round(float(x), 3)


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--config", required=True)
    p.add_argument("--source", required=False, help="rekaman, atau 'mock'")
    p.add_argument("--cameras", type=int, default=1)
    p.add_argument("--seconds", type=float, default=600.0, help="lama merekam (jam dinding)")
    p.add_argument("--out", default="runtime-out/run")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--health-seconds", type=float, default=5.0)
    p.add_argument("--startup-seconds", type=float, default=300.0, help="batas tunggu muat model")
    p.add_argument("--summarize-only", action="store_true", help="ringkas --out yang sudah ada")
    args = p.parse_args(argv)
    if not args.summarize_only:
        if not args.source:
            p.error("--source wajib kecuali --summarize-only")
        run(args)
    summary = summarize(Path(args.out))
    (Path(args.out) / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
