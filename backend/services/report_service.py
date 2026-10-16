from __future__ import annotations

import io
import threading
import time
import zipfile
from datetime import datetime, timedelta
from html import escape
from typing import Any, Dict, Iterable, List
from zoneinfo import ZoneInfo

from backend.core.database import (
    claim_report_run, finish_report_run, get_app_setting, get_corrections,
    get_employees, get_hr_reviews, get_known_person_ids, get_presence_intervals,
    get_report_runs, get_violations, get_dirty_report_runs, clear_report_dirty,
)
from backend.services.break_policy import break_policy
from backend.services.email_service import email_service
from backend.services.free_time import free_time_ledger


class ReportService:
    def daily(self, report_date: str, person_id: str | None = None) -> Dict[str, Any]:
        start, end = break_policy.day_bounds(report_date)
        employees = get_employees()
        employee_map = {str(item["employee_id"]): item for item in employees}
        people = set(get_known_person_ids()) | set(employee_map)
        if person_id:
            people = {person_id}
            employees = [item for item in employees if str(item["employee_id"]) == person_id]
        free_time = []
        attendance = []
        for pid in sorted(people):
            usage = free_time_ledger.usage(pid, report_date)
            free_time.append({
                "person_id": pid,
                "employee_name": employee_map.get(pid, {}).get("name", "Unknown"),
                "used_seconds": usage["used_seconds"],
                "remaining_seconds": usage["remaining_seconds"],
                "status": usage["status"],
                "visit_count": len(usage["visits"]),
            })
            intervals = get_presence_intervals(start, end, pid)
            attendance.append({
                "person_id": pid,
                "interval_count": len(intervals),
                "first_seen": min((item.get("start_at") for item in intervals), default=None),
                "last_seen": max((item.get("end_at") for item in intervals), default=None),
            })
        violations = get_violations(person_id=person_id, local_date=report_date, limit=10000)
        corrections = get_corrections(person_id=person_id, local_date=report_date, limit=10000)
        known = set(employee_map)
        anonymous = [item for item in attendance if item["person_id"] not in known]
        reviews = get_hr_reviews(unresolved_only=False)
        return {
            "date": report_date,
            "timezone": break_policy.timezone_name,
            "summary": {
                "employee_count": len(employees), "observed_people": len(people),
                "violation_count": len(violations), "correction_count": len(corrections),
                "anonymous_count": len(anonymous),
                "needs_hr_review": sum(1 for item in reviews if item["reviewed_at"] is None),
            },
            "employees": employees, "attendance": attendance, "free_time": free_time,
            "violations": violations, "corrections": corrections,
            "anonymous": anonymous, "hr_review": reviews,
        }

    def xlsx(self, report_date: str, person_id: str | None = None) -> bytes:
        report = self.daily(report_date, person_id)
        sheets = [
            ("Summary", [["Metric", "Value"]] + [[k, v] for k, v in report["summary"].items()]),
            ("Attendance", _rows(report["attendance"])),
            ("Free Time", _rows(report["free_time"])),
            ("Violations", _rows(report["violations"])),
            ("Needs HR Review", _rows(report["hr_review"])),
        ]
        return _xlsx(sheets)

    def list_runs(self) -> List[Dict[str, Any]]:
        return get_report_runs()

    def generate_and_send(self, report_date: str, revision: int = 1) -> bool:
        run_id = claim_report_run(report_date, revision=revision)
        if run_id is None:
            return False
        try:
            content = self.xlsx(report_date)
            config = get_app_setting("report_schedule", {}) or {}
            recipients = list(config.get("recipients", []))
            cc = list(config.get("cc", []))
            if not recipients:
                raise ValueError("report recipients are not configured")
            email_service.send_report(
                f"[AI Time Tracking] Daily Report {report_date}",
                f"Laporan harian {report_date} terlampir.",
                f"ai-time-report-{report_date}-r{revision}.xlsx", content, recipients, cc,
            )
            finish_report_run(run_id, "sent")
            return True
        except Exception as exc:
            finish_report_run(run_id, "failed", str(exc))
            raise


class ReportScheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="daily-report-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(30):
            config = get_app_setting("report_schedule", {}) or {}
            if not config.get("enabled"):
                continue
            try:
                timezone = ZoneInfo(config.get("timezone", break_policy.timezone_name))
            except Exception:
                timezone = break_policy.timezone
            now = datetime.now(timezone)
            # >= gives startup recovery when the backend was down at the exact
            # configured minute; report-run uniqueness keeps this idempotent.
            if now.strftime("%H:%M") >= config.get("send_time", "18:00"):
                target = (now.date() - timedelta(days=1)).isoformat()
                try:
                    report_service.generate_and_send(target)
                except Exception:
                    pass
            for dirty in get_dirty_report_runs():
                try:
                    if report_service.generate_and_send(
                        dirty["report_date"], revision=int(dirty["revision"]) + 1
                    ):
                        clear_report_dirty(int(dirty["id"]))
                except Exception:
                    pass


def _rows(items: Iterable[Dict[str, Any]]) -> List[List[Any]]:
    items = list(items)
    if not items:
        return [["No data"]]
    columns = list(items[0])
    return [columns] + [[item.get(column) for column in columns] for item in items]


def _cell(ref: str, value: Any) -> str:
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = "" if value is None else str(value)
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def _column(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _xlsx(sheets: List[tuple[str, List[List[Any]]]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1)) + '</Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        workbook_sheets = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1))
        archive.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{workbook_sheets}</sheets></workbook>')
        relationships = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1))
        archive.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}</Relationships>')
        for sheet_index, (_, rows) in enumerate(sheets, 1):
            xml_rows = []
            for row_index, row in enumerate(rows, 1):
                cells = "".join(_cell(f"{_column(col)}{row_index}", value) for col, value in enumerate(row, 1))
                xml_rows.append(f'<row r="{row_index}">{cells}</row>')
            archive.writestr(f"xl/worksheets/sheet{sheet_index}.xml", '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(xml_rows) + '</sheetData></worksheet>')
    return output.getvalue()


report_service = ReportService()
report_scheduler = ReportScheduler()
