"""Health check MediaMTX dan path cam01, tanpa dependency tambahan."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


API_URL = "http://127.0.0.1:9997/v3/paths/list"


def main() -> int:
    try:
        with urllib.request.urlopen(API_URL, timeout=5) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[ERROR] MediaMTX API belum siap: {exc}", file=sys.stderr)
        return 1

    items = payload.get("items", []) if isinstance(payload, dict) else []
    cam = next((item for item in items if item.get("name") == "cam01"), None)
    if cam is None:
        print("[ERROR] Path cam01 tidak ditemukan di MediaMTX.", file=sys.stderr)
        return 1

    ready = bool(cam.get("ready"))
    print("MediaMTX API : OK")
    print(f"Path cam01  : {'READY' if ready else 'NOT READY'}")
    print("Engine RTSP : rtsp://127.0.0.1:8554/cam01")
    print("Browser WHEP: http://127.0.0.1:8889/cam01/whep")
    print("Browser HLS : http://127.0.0.1:8888/cam01/index.m3u8")
    if not ready:
        print("Periksa CAM01_SOURCE, kredensial, jaringan CCTV, dan codec H.264.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

