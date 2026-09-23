from pathlib import Path

import pytest

from backend.services.break_policy import load_break_policy


def test_policy_yaml_loads_company_rules(tmp_path: Path):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        "timezone: Asia/Jakarta\n"
        "daily_break_allowance_minutes: 45\n"
        "official_break:\n  start: '11:00'\n  end: '12:00'\n"
        "tracking_loss_threshold_seconds: 20\n"
        "warning_remaining_minutes: 10\n",
        encoding="utf-8",
    )
    policy = load_break_policy(policy_file)
    assert policy.daily_allowance_minutes == 45
    assert policy.break_start_hour == 11
    assert policy.tracking_loss_threshold == 20


def test_policy_rejects_warning_larger_than_allowance(tmp_path: Path):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        "daily_break_allowance_minutes: 10\nwarning_remaining_minutes: 20\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cannot exceed"):
        load_break_policy(policy_file)
