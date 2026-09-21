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
    # Bukan "ada HH:MM di baris ini" -- itu menandai setiap template anotasi
    # dan setiap contoh di dokumentasi. Yang berbahaya adalah engine MEMBANDINGKAN
    # jam dinding dengan sebuah angka, karena itulah bentuk `_is_break_time()`.
    ("perbandingan jam dinding", re.compile(r"\.hour\s*(==|!=|>=|<=|<|>)|\bhour\s*(==|>=|<=)\s*\d")),
    ("akumulasi harian", re.compile(r"\b(daily_total|total_today|accumulated_\w+)\b", re.I)),
]

# Konstanta perseptual yang sah dan kebetulan menyerempet pola di atas.
ALLOWLIST = re.compile(
    r"(track_buffer|min_confirmations|similarity|margin|ttl|retry|fps|quality|"
    r"occlusion|detection_interval|embedding)",
    re.I,
)

# `scenarios/` adalah data uji yang MENGGAMBARKAN situasi, bukan kode yang
# dijalankan engine. Satu skenario bernama `istirahat-asli` tidak menaruh
# aturan kantor di dalam sensor; ia menamai keadaan yang harus bisa dibedakan.
# Carve-out ini sempit dengan sengaja: hanya folder skenario, bukan
# `engine/tools/fake_engine/` seluruhnya -- emitter dan server tetap dipindai,
# dan di situlah konstanta kebijakan benar-benar akan berbahaya kalau muncul.
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules",
    "tests", "data", "models", "weights", "scenarios",
}


def _prose_lines(source: str) -> set:
    """Baris yang berisi komentar atau docstring, bukan kode.

    Dipakai untuk melewatkannya. Heuristik "baris yang diawali #" tidak cukup:
    sebagian besar sebutan `istirahat` atau `attendance` di repo ini ada di
    tengah paragraf docstring yang justru MENJELASKAN kenapa hal itu tidak
    boleh ada di engine. Alat yang menandai dokumentasi aturannya sendiri
    sebagai pelanggaran aturan itu akan dimatikan orang dalam seminggu.

    Karena itu dipakai parser, bukan pola. String literal biasa TIDAK
    dilewatkan -- `"break_start_hour"` sebagai kunci dict tetap kode.
    """
    import ast
    import io
    import tokenize

    skip: set = set()

    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                skip.update(range(token.start[0], token.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return skip

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            skip.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    return skip


def scan(root: Path) -> List[str]:
    findings: List[str] = []

    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.suffix not in {".py", ".yaml", ".yml", ".json", ".toml"}:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        lines = source.splitlines()
        skip = _prose_lines(source) if path.suffix == ".py" else set()

        for number, line in enumerate(lines, start=1):
            if number in skip:
                continue
            stripped = line.strip()
            # Untuk YAML/JSON tidak ada parser prosa; komentarnya dilewati
            # dengan cara yang sederhana.
            if stripped.startswith(("#", "//")):
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
