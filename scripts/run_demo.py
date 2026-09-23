#!/usr/bin/env python3
"""Run engine + backend with a mock camera. Ctrl+C stops both."""

from __future__ import annotations

import argparse
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_VERSION = "2026.09.22-windows-v2"
MODE_CONFIGS = {
    "mock": ROOT / "backend" / "configs" / "cameras.demo.yaml",
    "direct": ROOT / "backend" / "configs" / "cameras.direct.yaml",
    "mediamtx": ROOT / "backend" / "configs" / "cameras.mediamtx.yaml",
}


def check_mediamtx() -> None:
    """Require a ready cam01 path before starting the MediaMTX profile."""
    url = "http://127.0.0.1:9997/v3/paths/list"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "MediaMTX belum berjalan. Jalankan `./deploy/mediamtx/start-mediamtx.ps1` "
            "(Windows) atau `sh deploy/mediamtx/start-mediamtx.sh` terlebih dahulu."
        ) from exc
    cam = next(
        (item for item in payload.get("items", []) if item.get("name") == "cam01"),
        None,
    )
    if not cam or not cam.get("ready"):
        raise RuntimeError(
            "MediaMTX hidup tetapi path cam01 belum READY. Periksa CAM01_SOURCE "
            "atau jalankan publisher FFmpeg untuk mode file."
        )


def ensure_port_free(port: int, label: str) -> None:
    """Fail before spawning children when an earlier demo still owns a port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(
                f"Port {port} untuk {label} sudah dipakai. Hentikan proses lama "
                f"atau periksa dengan `Get-NetTCPConnection -LocalPort {port}`."
            )


def resolve_npm() -> str:
    """Resolve npm correctly on Windows, where the executable is npm.cmd."""
    candidates = ("npm.cmd", "npm") if os.name == "nt" else ("npm",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError(
        "npm tidak ditemukan di PATH. Instal Node.js, buka terminal baru, "
        "lalu jalankan `npm ci` di folder frontend."
    )


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Each child is created in its own process group below. CTRL_BREAK
            # also reaches node.exe spawned by npm.cmd.
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=5)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete system in a selected mode")
    parser.add_argument("--frontend", action="store_true", help="also start Vite")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument(
        "--mode",
        choices=tuple(MODE_CONFIGS),
        default=os.getenv("AI_TIME_MODE", "mock"),
        help="camera profile: mock, direct MP4, or MediaMTX (default: mock)",
    )
    parser.add_argument(
        "--model",
        choices=("m", "s"),
        default=os.getenv("AI_TIME_DFINE", "m"),
        help="LibreYOLO D-FINE size: m (Medium, default) or s (Small)",
    )
    parser.add_argument(
        "--engine-config",
        default=None,
        help="engine YAML; overrides --model (default: engine/config/dfine-<model>.yaml)",
    )
    args = parser.parse_args()

    print(f"Demo launcher : {LAUNCHER_VERSION}")
    print(f"Script path   : {Path(__file__).resolve()}")
    print(f"Python        : {sys.executable}")
    print(f"Mode          : {args.mode}")
    print(f"Camera config : {MODE_CONFIGS[args.mode]}")
    engine_config = Path(
        args.engine_config or ROOT / "engine" / "config" / f"dfine-{args.model}.yaml"
    ).resolve()
    print(f"Engine config : {engine_config}")
    if not engine_config.exists():
        raise RuntimeError(f"Engine config tidak ditemukan: {engine_config}")
    if args.mode == "direct":
        direct_video = ROOT / "frontend" / "public" / "videos" / "video2.mp4"
        if not direct_video.exists():
            raise RuntimeError(
                f"Video direct tidak ditemukan: {direct_video}. Letakkan video2.mp4 "
                "di frontend/public/videos/."
            )
    ensure_port_free(8765, "engine")
    ensure_port_free(args.backend_port, "backend")
    if args.frontend:
        ensure_port_free(args.frontend_port, "frontend")
    if args.mode == "mediamtx":
        check_mediamtx()

    environment = os.environ.copy()
    environment.update({
        "ENGINE_HOST": "127.0.0.1",
        "ENGINE_PORT": "8765",
        "CAMERAS_CONFIG": str(MODE_CONFIGS[args.mode]),
        "POLICY_CONFIG": str(ROOT / "backend" / "configs" / "policy.yaml"),
    })

    commands = [
        [
            sys.executable, "-m", "engine.runtime",
            "--config", str(engine_config),
            "--tcp", "127.0.0.1:8765",
        ] + (["--loop-files"] if args.mode == "direct" else []),
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
         "--port", str(args.backend_port)],
    ]
    if args.frontend:
        commands.append([
            resolve_npm(), "run", "dev", "--", "--host", "127.0.0.1",
            "--port", str(args.frontend_port),
        ])

    processes: list[subprocess.Popen] = []
    try:
        for index, command in enumerate(commands):
            cwd = ROOT / "frontend" if index == 2 else ROOT
            label = ("engine", "backend", "frontend")[index]
            print(f"Starting {label}: {' '.join(command)}")
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            )
            try:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=environment,
                    creationflags=creationflags,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"Gagal menjalankan {label}; executable tidak ditemukan: {command[0]}"
                ) from exc
            processes.append(process)
            time.sleep(0.8)
            if process.poll() is not None:
                raise RuntimeError(
                    f"{label} berhenti saat startup dengan exit code {process.returncode}. "
                    "Lihat error tepat di atas baris ini."
                )
        print(f"Backend: http://127.0.0.1:{args.backend_port}/docs")
        if args.frontend:
            print(f"Frontend: http://127.0.0.1:{args.frontend_port}")
        print("Tekan Ctrl+C untuk berhenti.")
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        return next((process.returncode for process in processes if process.returncode), 0)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(processes):
            stop_process(process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
