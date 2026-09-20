from __future__ import annotations

from typing import Any, Dict, Optional

from contracts.validator import SchemaValidator, ValidationIssue

from contracts.validator import (
    ConformanceChecker,
    ConformanceReport,
    SchemaValidator,
    ValidationIssue,
)

class ProtocolValidationError(Exception):
    """Pesan engine tidak memenuhi kontrak protocol."""

    def __init__(
        self,
        message: str,
        issues: Optional[list[ValidationIssue]] = None,
    ) -> None:
        super().__init__(message)
        self.issues = issues or []


class EngineProtocolAdapter:
    """
    Boundary antara engine protocol dan backend.

    Tugas:
    - validasi message menggunakan contract resmi
    - cek channel bila diperlukan
    - hanya meneruskan message yang valid
    """

    def __init__(self) -> None:
        self.validator = SchemaValidator()

    def validate(
        self,
        message: Dict[str, Any],
        expected_channel: Optional[str] = None,
    ) -> Dict[str, Any]:

        issues = self.validator.validate_message(
            message,
            expected_channel=expected_channel,
        )

        if issues:
            raise ProtocolValidationError(
                "Engine protocol message is invalid",
                issues=issues,
            )

        return message

    def channel_of(self, message: Dict[str, Any]) -> str:
        message_type = message.get("type")

        if not isinstance(message_type, str):
            raise ProtocolValidationError(
                "Protocol message does not contain a valid 'type'"
            )

        return self.validator.channel_of(message_type)

    def check_conformance(
        self,
        messages: list[Dict[str, Any]],
        allow_replay: bool = False,
    ) -> ConformanceReport:
        # Layer 1: setiap message harus valid terhadap JSON Schema.
        for message in messages:
            self.validate(message)

        # Layer 2: seluruh sequence harus memenuhi aturan lintas-message.
        checker = ConformanceChecker(
            allow_replay=allow_replay,
        )

        return checker.check(messages)

    def test_conformance_empty_sequence():
        report = protocol_adapter.check_conformance([])

        assert report.ok is True
        assert report.errors == []
        
protocol_adapter = EngineProtocolAdapter()