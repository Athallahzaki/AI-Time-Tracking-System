"""Cek sebelum gladi resik / demo: semua yang biasanya baru ketahuan di depan klien.

    python scripts/preflight_demo.py                         # profil demo-1060
    python scripts/preflight_demo.py --config engine/config/demo-1060.yaml --skip-mediamtx

Jalankan dari folder repo (path model di config relatif ke folder kerja).
Tidak memuat model ke GPU dan tidak menjalankan engine; untuk lingkungan GPU
pakai scripts/check_gpu_env.py.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CONFIG = "engine/config/demo-1060.yaml"
MEDIAMTX_API = "http://127.0.0.1:9997/v3/paths/list"
PORTS = ((8765, "engine"), (8000, "backend"), (5173, "frontend"))


@dataclass
class Check:
    status: str   # OK | PERINGATAN | GAGAL
    name: str
    detail: str


# -- pemeriksaan murni (dites tanpa GPU / jaringan) --------------------------

def check_config(path: str) -> "tuple[Check, object]":
    from engine.config import load_config

    try:
        config = load_config(path)
    except Exception as exc:  # noqa: BLE001 -- apa pun penyebabnya, engine juga akan gagal start
        return Check("GAGAL", "config", f"{path}: {exc}"), None
    detector = config.detector
    return Check("OK", "config", f"{path}: {detector.model_path}, half {detector.half}, "
                 f"cuda_graph {detector.cuda_graph}, target_fps {config.target_fps}, "
                 f"rekognisi {'nyala' if config.recognition.enabled else 'mati'}"), config


def check_face_models(config, base: Path) -> List[Check]:
    recognition = config.recognition
    if not recognition.enabled or recognition.recognizer != "onnx_face":
        return [Check("PERINGATAN", "model-wajah", "rekognisi mati di config: tidak ada nama di demo")]
    checks = []
    for label, value in (("scrfd", recognition.face_detector_model), ("embedder", recognition.face_embedder_model)):
        path = Path(value) if Path(value).is_absolute() else base / value
        if path.is_file() and path.stat().st_size > 1_000_000:
            checks.append(Check("OK", f"model-{label}", f"{path} ({path.stat().st_size / 1e6:.0f} MB)"))
        elif path.is_file():
            checks.append(Check("GAGAL", f"model-{label}", f"{path} hanya {path.stat().st_size} byte "
                                "(pointer Git LFS / unduhan terputus?)"))
        else:
            checks.append(Check("GAGAL", f"model-{label}", f"tidak ada: {path} (path relatif ke folder kerja)"))
    db = Path(recognition.reference_db_path)
    db = db if db.is_absolute() else base / db
    if db.is_file():
        checks.append(Check("OK", "roster", f"{db} ada; pastikan 2-3 orang sudah di-enroll lewat web"))
    elif db.parent.is_dir():
        checks.append(Check("PERINGATAN", "roster", f"{db} belum ada: belum ada yang di-enroll, "
                            "tidak akan ada nama di demo"))
    else:
        checks.append(Check("GAGAL", "roster", f"folder {db.parent} tidak ada"))
    return checks


def check_libreyolo_for_graph(config, version: Optional[str]) -> Check:
    from engine.perception.dfine_detector import version_tuple

    if not config.detector.cuda_graph:
        return Check("OK", "libreyolo", f"{version}; cuda_graph mati")
    if version is None:
        return Check("GAGAL", "libreyolo", "tidak terpasang")
    if version_tuple(version) < (1, 6):
        return Check("PERINGATAN", "libreyolo", f"{version}: cuda_graph butuh >= 1.6, engine jatuh ke eager")
    return Check("OK", "libreyolo", f"{version}; cuda_graph didukung")


def check_mediamtx(fetch: Callable[[str], dict]) -> Check:
    try:
        payload = fetch(MEDIAMTX_API)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return Check("GAGAL", "mediamtx", f"API tidak menjawab ({exc}); jalankan deploy/mediamtx/start-mediamtx.ps1")
    items = payload.get("items", []) if isinstance(payload, dict) else []
    cam = next((item for item in items if item.get("name") == "cam01"), None)
    if cam is None:
        return Check("GAGAL", "mediamtx", "path cam01 tidak ada di konfigurasi MediaMTX")
    if not cam.get("ready"):
        return Check("GAGAL", "mediamtx", "cam01 belum READY: jalankan scripts/publish_test_video.ps1")
    return Check("OK", "mediamtx", "cam01 READY (rtsp://127.0.0.1:8554/cam01)")


def check_ports(in_use: Callable[[int], bool], ports: Sequence = PORTS) -> List[Check]:
    busy = [f"{port} ({label})" for port, label in ports if in_use(port)]
    if busy:
        return [Check("PERINGATAN", "port", "sudah dipakai: " + ", ".join(busy)
                      + " -- sisa run lama? (Get-NetTCPConnection -LocalPort <port>)")]
    return [Check("OK", "port", "8765/8000/5173 bebas")]


def check_git(status_output: Optional[str], describe: Optional[str]) -> Check:
    if status_output is None:
        return Check("PERINGATAN", "git", "git tidak bisa dijalankan; versi tidak bisa dipastikan")
    lines = [line for line in status_output.splitlines() if line.strip()]
    conflicts = [line for line in lines if line[:2] in ("UU", "AA", "DD", "AU", "UA", "UD", "DU")]
    if conflicts:
        return Check("GAGAL", "git", f"{len(conflicts)} berkas masih konflik: "
                     + ", ".join(line[3:] for line in conflicts[:5]))
    if lines:
        return Check("PERINGATAN", "git", f"{len(lines)} perubahan belum di-commit ({describe}); "
                     "commit + tag sebelum demo")
    return Check("OK", "git", f"bersih, {describe}")


def check_conflict_markers(root: Path) -> Check:
    hits = []
    for path in sorted((root / "engine" / "config").glob("*.yaml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(line.startswith(("<<<<<<< ", ">>>>>>> ")) for line in text.splitlines()):
            hits.append(path.name)
    if hits:
        return Check("GAGAL", "penanda-konflik", "sisa <<<<<<< di " + ", ".join(hits))
    return Check("OK", "penanda-konflik", "tidak ada di engine/config")


# -- sisi yang menyentuh dunia luar -------------------------------------------

def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _dist_version(name: str) -> Optional[str]:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # noqa: BLE001
        return None


def collect(config_path: str, skip_mediamtx: bool = False) -> List[Check]:
    base = Path.cwd()
    checks = [check_conflict_markers(ROOT)]
    config_check, config = check_config(config_path)
    checks.append(config_check)
    if config is not None:
        checks.extend(check_face_models(config, base))
        checks.append(check_libreyolo_for_graph(config, _dist_version("libreyolo")))
    if not skip_mediamtx:
        checks.append(check_mediamtx(_fetch_json))
    checks.extend(check_ports(_port_in_use))
    describe = (_git("describe", "--tags", "--always", "--dirty") or "").strip() or None
    checks.append(check_git(_git("status", "--porcelain"), describe))
    return checks


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--skip-mediamtx", action="store_true", help="MediaMTX belum dinyalakan, cek sisanya saja")
    args = parser.parse_args(argv)
    checks = collect(args.config, args.skip_mediamtx)
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"{c.status:<10} {c.name:<{width}}  {c.detail}")
    failed = [c for c in checks if c.status == "GAGAL"]
    warned = [c for c in checks if c.status == "PERINGATAN"]
    if failed:
        print(f"\nKESIMPULAN: {len(failed)} GAGAL, perbaiki dulu sebelum gladi")
    elif warned:
        print(f"\nKESIMPULAN: bisa gladi, {len(warned)} peringatan dibereskan sebelum demo")
    else:
        print("\nKESIMPULAN: siap gladi")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
