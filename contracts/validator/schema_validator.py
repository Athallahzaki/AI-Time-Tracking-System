"""Validasi satu pesan terhadap `schema/engine_protocol.schema.json`.

Kenapa tidak langsung memvalidasi terhadap `oneOf` di akar skema: kalau sebuah
pesan gagal, jsonschema melaporkan kegagalan seluruh 24 cabang sekaligus dan
pesan errornya tidak bisa dibaca manusia. Jadi di sini kita dispatch dulu
berdasarkan field `type`, lalu memvalidasi terhadap satu subskema saja.
`oneOf` di akar tetap ada untuk konsumen bahasa lain yang tidak punya lapisan
ini.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "butuh paket jsonschema: pip install 'jsonschema[format]>=4.18'"
    ) from exc


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "engine_protocol.schema.json"


@dataclass(frozen=True)
class ValidationIssue:
    """Satu pelanggaran. `line` 1-based kalau berasal dari file NDJSON."""

    line: Optional[int]
    message_type: Optional[str]
    path: str
    detail: str

    def __str__(self) -> str:
        where = f"baris {self.line}" if self.line is not None else "pesan"
        what = self.message_type or "<type tidak diketahui>"
        at = f" di `{self.path}`" if self.path else ""
        return f"{where} [{what}]{at}: {self.detail}"


def load_schema(path: Path = SCHEMA_PATH) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _build_type_index(schema: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Turunkan `type` -> nama $def dan `type` -> kanal, dari skema itu sendiri.

    Tidak ada daftar tertulis kedua di Python. Menambah pesan baru di JSON
    otomatis membuatnya dikenali di sini; tidak ada dua sumber kebenaran.
    """
    by_type: Dict[str, str] = {}
    channel_by_type: Dict[str, str] = {}

    for def_name, definition in schema.get("$defs", {}).items():
        if not isinstance(definition, dict):
            continue
        const = definition.get("properties", {}).get("type", {}).get("const")
        if not const:
            continue
        if const in by_type:
            raise ValueError(f"dua $defs mengklaim type `{const}`: {by_type[const]} dan {def_name}")
        by_type[const] = def_name
        channel_by_type[const] = definition.get("x-channel", "unknown")

    return by_type, channel_by_type


_SCHEMA = load_schema()
_TYPE_TO_DEF, CHANNEL_OF = _build_type_index(_SCHEMA)


class SchemaValidator:
    def __init__(self, schema: Optional[Dict[str, Any]] = None) -> None:
        self._schema = schema or _SCHEMA
        self._type_to_def, self._channel_of = (
            _build_type_index(self._schema) if schema else (_TYPE_TO_DEF, CHANNEL_OF)
        )
        self._cache: Dict[str, Draft202012Validator] = {}

    @property
    def known_types(self) -> List[str]:
        return sorted(self._type_to_def)

    def channel_of(self, message_type: str) -> str:
        return self._channel_of.get(message_type, "unknown")

    def _validator_for(self, message_type: str) -> Draft202012Validator:
        if message_type not in self._cache:
            def_name = self._type_to_def[message_type]
            sub = {
                "$schema": self._schema["$schema"],
                "$id": self._schema["$id"] + f"#{def_name}",
                "$defs": self._schema["$defs"],
                "$ref": f"#/$defs/{def_name}",
            }
            self._cache[message_type] = Draft202012Validator(
                sub, format_checker=FormatChecker()
            )
        return self._cache[message_type]

    def validate_message(
        self,
        message: Any,
        line: Optional[int] = None,
        expected_channel: Optional[str] = None,
    ) -> List[ValidationIssue]:
        if not isinstance(message, dict):
            return [ValidationIssue(line, None, "", "pesan bukan objek JSON")]

        message_type = message.get("type")
        if not isinstance(message_type, str):
            return [ValidationIssue(line, None, "type", "field `type` hilang atau bukan string")]

        if message_type not in self._type_to_def:
            return [
                ValidationIssue(
                    line,
                    message_type,
                    "type",
                    "type tidak dikenal. Pesan baru menambah $defs di skema, bukan "
                    "dipancarkan diam-diam: penerima lama akan membuangnya.",
                )
            ]

        issues: List[ValidationIssue] = []

        actual_channel = self.channel_of(message_type)
        if expected_channel is not None and actual_channel != expected_channel:
            issues.append(
                ValidationIssue(
                    line,
                    message_type,
                    "",
                    f"pesan kanal `{actual_channel}` muncul di kanal `{expected_channel}`",
                )
            )

        for error in sorted(self._validator_for(message_type).iter_errors(message), key=str):
            path = "/".join(str(part) for part in error.absolute_path)
            issues.append(ValidationIssue(line, message_type, path, error.message))

        return issues

    def validate_ndjson(
        self,
        lines: Iterable[str],
        expected_channel: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[ValidationIssue]]:
        """Kembalikan (pesan yang berhasil di-parse, daftar pelanggaran)."""
        messages: List[Dict[str, Any]] = []
        issues: List[ValidationIssue] = []

        for index, raw in enumerate(lines, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped)
            except json.JSONDecodeError as exc:
                issues.append(ValidationIssue(index, None, "", f"JSON tidak valid: {exc.msg}"))
                continue

            found = self.validate_message(message, line=index, expected_channel=expected_channel)
            issues.extend(found)
            if isinstance(message, dict):
                message["_line"] = index
                messages.append(message)

        return messages, issues
