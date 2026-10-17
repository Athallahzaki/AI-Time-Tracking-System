#!/usr/bin/env python3
"""Real SMTP smoke test. Reads credentials from environment; never prints them."""

from __future__ import annotations

import argparse
from datetime import datetime

from backend.core.database import init_database
from backend.services.break_policy import break_policy
from backend.services.email_service import email_service
from backend.services.report_service import report_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Send real test, violation, and XLSX report emails")
    parser.add_argument("--person-id", help="employee_id used to test employee/HR routing")
    parser.add_argument("--date", default=datetime.now(break_policy.timezone).date().isoformat())
    args = parser.parse_args()
    init_database()

    print("1/3 sending SMTP configuration test...")
    email_service.send_test_email()
    print("    sent")

    print("2/3 sending violation routing test...")
    email_service.send_notification_now({
        "person_id": args.person_id or "SMTP-SMOKE", "type": "free_time_exceeded",
        "title": "Uji routing pelanggaran", "event_at": datetime.now().timestamp(),
        "payload": {"date": args.date, "used_seconds": 1860, "allowance_seconds": 1800},
    })
    print("    sent")

    print("3/3 sending XLSX report attachment test...")
    content = report_service.xlsx(args.date)
    from backend.core.config import settings
    if not settings.smtp_to:
        raise RuntimeError("SMTP_TO must contain at least one report recipient")
    email_service.send_report(
        f"[AI Time Tracking] SMTP smoke report {args.date}",
        "Attachment smoke test.", f"smtp-smoke-{args.date}.xlsx", content, list(settings.smtp_to),
    )
    print("    sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
