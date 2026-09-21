"""CLI: `python -m contracts.validator rekaman.ndjson --channel events`

Keluar dengan kode 1 kalau ada pelanggaran, supaya bisa langsung dipakai di CI
tanpa membungkusnya dengan apa pun.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .conformance import ConformanceChecker
from .schema_validator import SchemaValidator


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="contracts.validator",
        description="Validasi rekaman NDJSON terhadap kontrak engine <-> backend.",
    )
    parser.add_argument("path", type=Path, help="berkas NDJSON; `-` untuk stdin")
    parser.add_argument(
        "--channel",
        choices=["control", "events", "view"],
        help="kalau diisi, pesan dari kanal lain dianggap pelanggaran",
    )
    parser.add_argument(
        "--allow-replay",
        action="store_true",
        help="izinkan seq mundur (rekaman yang memang berisi replay)",
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="lewati pemeriksaan lintas-pesan",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="perlakukan peringatan sebagai kegagalan",
    )
    args = parser.parse_args(argv)

    if str(args.path) == "-":
        lines = sys.stdin.readlines()
    else:
        lines = args.path.read_text(encoding="utf-8").splitlines()

    validator = SchemaValidator()
    messages, issues = validator.validate_ndjson(lines, expected_channel=args.channel)

    warnings = []
    if not args.schema_only:
        report = ConformanceChecker(allow_replay=args.allow_replay).check(messages)
        issues = issues + report.errors
        warnings = report.warnings

    for issue in warnings:
        print(f"PERINGATAN  {issue}")
    for issue in issues:
        print(f"GAGAL       {issue}")

    total = len(messages)
    if issues:
        print(f"\n{len(issues)} pelanggaran dari {total} pesan.")
        return 1

    if warnings and args.strict:
        print(f"\n{len(warnings)} peringatan dari {total} pesan (--strict).")
        return 1

    print(f"{total} pesan, tidak ada pelanggaran" + (f", {len(warnings)} peringatan." if warnings else "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
