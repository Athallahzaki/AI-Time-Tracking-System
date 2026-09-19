"""Pemindai konstanta kebijakan di `engine/`.

`ARCHITECTURE.md` §16 menyebut ini sebagai cara konkret mengecek bahwa garis
"engine mengamati, backend memutuskan" belum bocor. Selama ia cuma kalimat di
dokumen, ia tidak menjaga apa pun. Ini versi yang bisa dijalankan CI.

    python contracts/tools/policy_grep.py engine/

Keluar 1 kalau ada temuan. Diharapkan MERAH sampai `AttendanceTracker` dan
`_is_break_time` benar-benar pindah ke backend; biarkan merah dengan sengaja,
supaya pekerjaan itu terlihat dan bukan aturan yang disepakati lalu dilupakan.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Sengaja TIDAK cocok dengan kata kunci `break` Python. Alat yang cerewet
    # akan dimatikan orang dalam seminggu, dan alat yang dimatikan tidak menjaga
    # apa pun.
    (
        "aturan istirahat",
        re.compile(
            r"\b(break[_\- ]?(time|start|end|hour|minute|duration|quota|window|limit)\w*"
            r"|is_break\w*|istirahat)\b",
            re.I,
        ),
    ),
    ("sanksi", re.compile(r"\b(penalt\w*|sanksi|warning_threshold)\b", re.I)),
    ("jatah", re.compile(r"\b(quota|jatah|allowance)\b", re.I)),
    ("jam kerja", re.compile(r"\b(work_start|work_end|shift|jam_kerja|office_hours)\b", re.I)),
    ("kehadiran sebagai kebijakan", re.compile(r"\b(attendance|absen\w*|late|terlambat)\b", re.I)),
    ("jam dinding literal", re.compile(r"\b(1[0-9]|[0-9])\s*:\s*[0-5][0-9]\b")),
    ("akumulasi harian", re.compile(r"\b(daily_total|total_today|accumulated_\w+)\b", re.I)),
]

# Konstanta perseptual yang sah dan kebetulan menyerempet pola di atas.
ALLOWLIST = re.compile(
    r"(track_buffer|min_confirmations|similarity|margin|ttl|retry|fps|quality|"
    r"occlusion|detection_interval|embedding)",
    re.I,
)

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "tests", "data", "models", "weights"}


def scan(root: Path) -> List[str]:
    findings: List[str] = []

    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.suffix not in {".py", ".yaml", ".yml", ".json", ".toml"}:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue

        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Baris komentar/docstring murni dilewati: sebagian besar sebutan
            # "attendance" di engine/ justru ada di kalimat yang menyatakan modul
            # itu TIDAK tahu soal absensi. Konstanta yang sebenarnya ada di kode
            # dan di YAML, bukan di prosa.
            if stripped.startswith(("#", "-", '"""', "'''", "*")):
                continue
            if ALLOWLIST.search(line):
                continue
            for label, pattern in PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append(
                        f"{path}:{number}: [{label}] {line.strip()[:110]}"
                    )
                    break

    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cari konstanta kebijakan di folder engine.")
    parser.add_argument("root", type=Path, nargs="?", default=Path("engine"))
    args = parser.parse_args(argv)

    if not args.root.exists():
        print(f"folder tidak ada: {args.root}", file=sys.stderr)
        return 2

    findings = scan(args.root)
    for finding in findings:
        print(finding)

    if findings:
        print(
            f"\n{len(findings)} kemungkinan konstanta kebijakan di `{args.root}`. "
            "Engine hanya boleh punya konstanta perseptual.",
            file=sys.stderr,
        )
        return 1

    print(f"tidak ada konstanta kebijakan di `{args.root}`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
