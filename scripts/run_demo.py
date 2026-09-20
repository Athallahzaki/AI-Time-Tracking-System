#!/usr/bin/env python3
"""Run engine + backend with a mock camera. Ctrl+C stops both."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete mock demo")
    parser.add_argument("--frontend", action="store_true", help="also start Vite")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args()

    environment = os.environ.copy()
    environment.update({
        "ENGINE_HOST": "127.0.0.1",
        "ENGINE_PORT": "8765",
        "CAMERAS_CONFIG": str(ROOT / "backend" / "configs" / "cameras.demo.yaml"),
        "POLICY_CONFIG": str(ROOT / "backend" / "configs" / "policy.yaml"),
    })

    commands = [
        [sys.executable, "-m", "engine.runtime", "--tcp", "127.0.0.1:8765"],
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
         "--port", str(args.backend_port)],
    ]
    if args.frontend:
        commands.append([
            "npm", "run", "dev", "--", "--host", "127.0.0.1",
            "--port", str(args.frontend_port),
        ])

    processes: list[subprocess.Popen] = []
    try:
        for index, command in enumerate(commands):
            cwd = ROOT / "frontend" if index == 2 else ROOT
            processes.append(subprocess.Popen(command, cwd=cwd, env=environment))
            time.sleep(0.8)
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
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for process in reversed(processes):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
