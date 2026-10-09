"""Zip ramping untuk diunggah ke sesi Claude (hemat konteks dan token).

Hanya berisi file yang perlu untuk bagian yang dikerjakan, plus CLAUDE.md dan
dokumen serah terima. Yang tidak pernah ikut: data/model/video, node_modules,
venv, lockfile besar, arsip, dan semua yang di-ignore git.

Pakai dari root repo:

    python scripts/pack_for_claude.py backend
    python scripts/pack_for_claude.py engine
    python scripts/pack_for_claude.py frontend
    python scripts/pack_for_claude.py backend frontend      # beberapa bagian
    python scripts/pack_for_claude.py semua                 # seluruh kode, tetap tanpa yang berat

Hasil: bench-out/claude-<bagian>-<tanggal-jam>.zip (bench-out/ di-ignore git).
Daftar file diambil dari `git ls-files` (termasuk file baru yang belum di-commit,
tetapi bukan yang di-ignore). Tanpa git, folder dijelajah dengan aturan yang sama.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence

ROOT = Path(__file__).resolve().parents[1]

# Selalu ikut: aturan, peta, status, konfigurasi tes.
ALWAYS = [
    "CLAUDE.md",
    "docs/SERAH-TERIMA.md",
    "docs/PETA-KODE.md",
    "pytest.ini",
    "requirements-dev.txt",
    ".gitattributes",
    ".gitignore",
]

# Folder per bagian. Kontrak ikut engine dan backend karena keduanya bergantung padanya.
PARTS = {
    "engine": ["engine/", "contracts/", "scripts/summarize_gladi.py", "scripts/lag_probe.py",
               "scripts/spike_nvdec.py", "scripts/check_gpu_env.py"],
    "backend": ["backend/", "contracts/", "engine/tools/fake_engine/"],
    "frontend": ["frontend/"],
    "deploy": ["deploy/", "docs/DEMO-REMOTE.md"],
    "docs": ["docs/"],
}
PARTS["semua"] = sorted({p for paths in PARTS.values() for p in paths} | {"scripts/"})

# Tidak pernah ikut, apa pun bagiannya.
EXCLUDE = [
    "docs/arsip/*",
    "docs/ARCHITECTURE.md",          # 74 KB, sebagian usang; minta khusus bila perlu
    "frontend/package-lock.json",
    "frontend/public/videos/*",
    "*/node_modules/*", "node_modules/*",
    "*/.venv/*", ".venv/*", "*/venv/*",
    "*/__pycache__/*", "*.pyc",
    "bench/*", "bench-out/*",
    "*.pt", "*.pth", "*.onnx", "*.engine", "*.safetensors",
    "*.sqlite3", "*.sqlite3-*", "*.db", "*.db-shm", "*.db-wal",
    "*.mp4", "*.mkv", "*.avi", "*.mov",
    "*.zip", "*.log",
    ".env", "*/.env", "stack.env", "*/stack.env",
]
# CHANGELOG ikut UTUH, walaupun besar. Kalau dipotong lalu sesi menambah entri dan
# mengirim file itu kembali di zip, menyalinnya akan menghapus riwayat. Hemat
# tokennya diatur di CLAUDE.md: baca hanya bagian atas (Read dengan batas baris).
CHANGELOG = "docs/CHANGELOG.md"


def _excluded(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in EXCLUDE)


def _git_files() -> List[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def _walk_files() -> List[str]:
    files = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "venv", "__pycache__")]
        for name in names:
            files.append(Path(base, name).relative_to(ROOT).as_posix())
    return files


def select(parts: Sequence[str], files: Iterable[str]) -> List[str]:
    prefixes = []
    for part in parts:
        if part not in PARTS:
            raise SystemExit(f"bagian tidak dikenal: {part} (pilihan: {', '.join(sorted(PARTS))})")
        prefixes.extend(PARTS[part])
    chosen = set()
    for path in files:
        if _excluded(path):
            continue
        if path in ALWAYS or any(path == p or (p.endswith("/") and path.startswith(p)) for p in prefixes):
            chosen.add(path)
    for path in ALWAYS:
        if (ROOT / path).is_file():
            chosen.add(path)
    return sorted(chosen)


def build(parts: Sequence[str], out: Path) -> List[str]:
    files = _git_files() or _walk_files()
    chosen = select(parts, files)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in chosen:
            source = ROOT / path
            if source.is_file():
                archive.write(source, path)
        changelog = ROOT / CHANGELOG
        if CHANGELOG not in chosen and changelog.is_file():
            archive.write(changelog, CHANGELOG)
            chosen.append(CHANGELOG)
    return chosen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zip ramping untuk sesi Claude.")
    parser.add_argument("bagian", nargs="+", help=f"salah satu/lebih dari: {', '.join(sorted(PARTS))}")
    parser.add_argument("--out", type=Path, default=None, help="path zip keluaran")
    parser.add_argument("--list", action="store_true", help="tampilkan daftar file saja, tanpa membuat zip")
    args = parser.parse_args(argv)

    if args.list:
        for path in select(args.bagian, _git_files() or _walk_files()):
            print(path)
        return 0

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
    out = args.out or ROOT / "bench-out" / f"claude-{'-'.join(args.bagian)}-{stamp}.zip"
    chosen = build(args.bagian, out)
    size_kb = out.stat().st_size / 1024
    print(f"{out}  ({len(chosen)} file, {size_kb:.0f} KB)")
    if size_kb > 2048:
        print("Peringatan: lebih dari 2 MB. Pertimbangkan bagian yang lebih sempit.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
