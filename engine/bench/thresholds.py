"""
The go/no-go verdict — and why this file contains no numbers.

§13.7 says the pass marks must be fixed **before** anyone looks at the data,
because otherwise whatever comes out gets rationalised into acceptable. A
starting point is proposed in ARCHITECTURE.md §13.7 and deliberately not
repeated here, in any form, not even in a comment.

The reason is §16, which is blunt about where company numbers may live and
gives a concrete test: grep `engine/` for them. A constant in this module would
be that leak arriving through the back door of a benchmark, and
`contracts/tools/policy_grep.py` would be right to go red. So would prose that
merely restates the number — a docstring saying what the figure is puts the
figure in `engine/`, and when the rule changes that docstring becomes a
confident, wrong second opinion that nobody thinks to update.

So the pass marks live in a YAML file **outside `engine/`** — `bench/gonogo.yaml`
at the repository root — and this module only loads one and applies it. Which
also gets §13.7 right for free: they are a committed artefact with their own
history, so moving one after seeing the data is a diff with a name on it rather
than an edit nobody notices. The hash of the file used goes into the report.

With no thresholds file the bench still runs and still reports every
measurement. It just does not pronounce a verdict, because a verdict without a
pre-registered pass mark is an opinion with a JSON schema.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class ThresholdError(ValueError):
    """The thresholds file is unusable."""


@dataclass(frozen=True)
class Thresholds:
    """Pre-registered pass marks. Loaded, never defaulted."""

    max_false_gap_minutes_per_person_per_day: float
    min_track_lifetime_seconds_while_present: float
    min_recognizable_faces_per_person_hour: Optional[float]
    workday_hours: float
    stitch_window_for_verdict_seconds: float
    declared_on: str
    rationale: str
    source_path: str
    sha256: str
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "sha256": self.sha256,
            "declared_on": self.declared_on,
            "rationale": self.rationale,
            "max_false_gap_minutes_per_person_per_day": (
                self.max_false_gap_minutes_per_person_per_day
            ),
            "min_track_lifetime_seconds_while_present": (
                self.min_track_lifetime_seconds_while_present
            ),
            "min_recognizable_faces_per_person_hour": (
                self.min_recognizable_faces_per_person_hour
            ),
            "workday_hours": self.workday_hours,
            "stitch_window_for_verdict_seconds": self.stitch_window_for_verdict_seconds,
        }


def load_thresholds(path: Path) -> Thresholds:
    import yaml

    path = Path(path)
    if not path.exists():
        raise ThresholdError(
            f"Thresholds file not found: {path}. §13.7 requires the pass marks "
            f"to be written down before the data is seen; there is deliberately "
            f"no default in code."
        )
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ThresholdError(f"{path}: root must be a mapping.")

    required = (
        "max_false_gap_minutes_per_person_per_day",
        "min_track_lifetime_seconds_while_present",
        "workday_hours",
        "declared_on",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise ThresholdError(f"{path}: missing required keys: {', '.join(missing)}")

    return Thresholds(
        max_false_gap_minutes_per_person_per_day=float(
            raw["max_false_gap_minutes_per_person_per_day"]
        ),
        min_track_lifetime_seconds_while_present=float(
            raw["min_track_lifetime_seconds_while_present"]
        ),
        min_recognizable_faces_per_person_hour=(
            None
            if raw.get("min_recognizable_faces_per_person_hour") is None
            else float(raw["min_recognizable_faces_per_person_hour"])
        ),
        workday_hours=float(raw["workday_hours"]),
        stitch_window_for_verdict_seconds=float(
            raw.get("stitch_window_for_verdict_seconds", 5.0)
        ),
        declared_on=str(raw["declared_on"]),
        rationale=str(raw.get("rationale", "")),
        source_path=str(path),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        extra={k: v for k, v in raw.items() if k not in required},
    )


GO = "GO"
NO_GO = "NO_GO"
INCONCLUSIVE = "INCONCLUSIVE"


def verdict(report_metrics: Dict[str, Any], thresholds: Optional[Thresholds]) -> Dict[str, Any]:
    """
    GO, NO_GO or INCONCLUSIVE — and INCONCLUSIVE is not a soft NO_GO.

    A missing measurement can never produce GO. That is the whole mechanism: a
    benchmark whose unmeasured fields default to "fine" is the flattering lie
    §13.1 warns about, wearing a verdict.
    """
    if thresholds is None:
        return {
            "verdict": INCONCLUSIVE,
            "reasons": [
                "no thresholds file was supplied; §13.7 requires pass marks "
                "fixed before the data is seen, so none are assumed here"
            ],
            "checks": [],
            "thresholds": None,
        }

    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    window_key = f"N={thresholds.stitch_window_for_verdict_seconds:g}s"

    # --- metric 1: false gap minutes per person per day (§4.7, §13.7) -------
    gaps = report_metrics.get("false_gaps")
    measured = None
    if isinstance(gaps, dict) and "stitched" in gaps:
        entry = gaps["stitched"].get(window_key)
        if entry:
            measured = entry.get("projected_minutes_per_person_per_day")
            if entry.get("basis") != "annotated_identity":
                reasons.append(
                    f"false-gap figure at {window_key} was stitched on "
                    f"{entry.get('basis')}, which is not a sound basis for a "
                    f"verdict (§13.6)"
                )
                measured = None
    checks.append(
        _check(
            name=f"false_gap_minutes_per_person_per_day @ {window_key}",
            measured=measured,
            limit=thresholds.max_false_gap_minutes_per_person_per_day,
            direction="max",
        )
    )

    # --- metric 2: track lifetime while the person is still present (§4.7) --
    lifetime = report_metrics.get("track_lifetime", {})
    broken = lifetime.get("broken_while_person_present_seconds")
    measured_lifetime = (
        broken.get("p50") if isinstance(broken, dict) and "p50" in broken else None
    )
    checks.append(
        _check(
            name="track_lifetime_while_present_p50_seconds",
            measured=measured_lifetime,
            limit=thresholds.min_track_lifetime_seconds_while_present,
            direction="min",
        )
    )

    # --- metric 3: recognizable faces per person per hour (§3.1, §13.5) -----
    if thresholds.min_recognizable_faces_per_person_hour is not None:
        faces = report_metrics.get("recognizable_faces", {})
        measured_faces = (
            faces.get("per_person_hour") if isinstance(faces, dict) else None
        )
        checks.append(
            _check(
                name="recognizable_faces_per_person_hour",
                measured=measured_faces,
                limit=thresholds.min_recognizable_faces_per_person_hour,
                direction="min",
            )
        )

    if any(check["result"] == "fail" for check in checks):
        outcome = NO_GO
    elif any(check["result"] == "unmeasured" for check in checks):
        outcome = INCONCLUSIVE
    else:
        outcome = GO

    for check in checks:
        if check["result"] == "unmeasured":
            reasons.append(f"{check['name']} was not measured in this run")
        elif check["result"] == "fail":
            reasons.append(
                f"{check['name']} = {check['measured']} "
                f"({check['direction']} {check['limit']})"
            )

    return {
        "verdict": outcome,
        "reasons": reasons,
        "checks": checks,
        "thresholds": thresholds.as_dict(),
    }


def _check(
    name: str, measured: Optional[float], limit: float, direction: str
) -> Dict[str, Any]:
    if measured is None:
        result = "unmeasured"
    elif direction == "max":
        result = "pass" if measured <= limit else "fail"
    else:
        result = "pass" if measured >= limit else "fail"
    return {
        "name": name,
        "measured": measured,
        "limit": limit,
        "direction": direction,
        "result": result,
    }
