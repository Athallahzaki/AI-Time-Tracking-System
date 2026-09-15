"""
Unified System Launcher for AI Time Tracking System.
Runs the FastAPI Backend integrated with AI Vision Engine and provides status overview.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def parse_args():
    parser = argparse.ArgumentParser(
        description="AI Time Tracking System - Unified Backend & Vision Engine Launcher"
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    parser.add_argument("--device", type=str, default=None, help="Inference device: 'cuda', 'cpu', '0'")
    parser.add_argument("--no-face", action="store_true", help="Disable face recognition plugin")
    parser.add_argument("--gui", action="store_true", help="Open local OpenCV GUI window for debug")
    return parser.parse_args()


def main():
    args = parse_args()

    print("\n" + "=" * 60)
    print("      AI TIME TRACKING SYSTEM — INTEGRATED SERVICE")
    print("=" * 60)
    print(f" • Project Root : {PROJECT_ROOT}")
    print(f" • Backend API  : http://localhost:{args.port}")
    print(f" • API Docs     : http://localhost:{args.port}/docs")
    print(f" • SSE Stream   : http://localhost:{args.port}/api/detections/stream")
    print(f" • Stats API    : http://localhost:{args.port}/api/stats")
    print(f" • Cameras API  : http://localhost:{args.port}/api/cameras")
    print(f" • Frontend Dev : http://localhost:5173 (run 'npm run dev' in /frontend)")
    print("=" * 60 + "\n")

    # Apply CLI flag overrides to backend config
    from backend.core.config import settings

    if args.gui:
        settings.headless = False
    if args.no_face:
        settings.no_face_recognition = True
    if args.device:
        settings.device = args.device

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
