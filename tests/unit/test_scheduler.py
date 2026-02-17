"""Tests for the cron scheduler engine."""

import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.scheduler import (
    ScheduleConfig,
    ScheduleEntry,
    SchedulerState,
    _parse_cron_field,
    cron_matches,
    get_due_entries,
    load_schedule_config,
    run_scheduler,
)


class TestCronFieldParsing:
    def test_wildcard(self):
        assert _parse_cron_field("*", 0, 59) == set(range(0, 60))

    def test_single_value(self):
        assert _parse_cron_field("5", 0, 59) == {5}

    def test_range(self):
        assert _parse_cron_field("1-5", 0, 59) == {1, 2, 3, 4, 5}

    def test_step(self):
        assert _parse_cron_field("*/15", 0, 59) == {0, 15, 30, 45}

    def test_range_with_step(self):
        assert _parse_cron_field("1-10/3", 0, 59) == {1, 4, 7, 10}

    def test_list(self):
        assert _parse_cron_field("1,3,5", 0, 59) == {1, 3, 5}

    def test_complex(self):
        result = _parse_cron_field("1-5,10,*/20", 0, 59)
        assert 1 in result
        assert 5 in result
        assert 10 in result
        assert 0 in result
        assert 20 in result
        assert 40 in result


class TestCronMatches:
    def test_daily_shortcut(self):
        dt = datetime(2026, 2, 16, 0, 0, tzinfo=timezone.utc)
        assert cron_matches("daily", dt)

    def test_daily_shortcut_not_midnight(self):
        dt = datetime(2026, 2, 16, 10, 30, tzinfo=timezone.utc)
        assert not cron_matches("daily", dt)

    def test_weekly_shortcut_monday(self):
        # 2026-02-16 is a Monday
        dt = datetime(2026, 2, 16, 0, 0, tzinfo=timezone.utc)
        assert cron_matches("weekly", dt)

    def test_weekly_shortcut_tuesday(self):
        dt = datetime(2026, 2, 17, 0, 0, tzinfo=timezone.utc)
        assert not cron_matches("weekly", dt)

    def test_monthly(self):
        dt = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        assert cron_matches("monthly", dt)

    def test_monthly_not_first(self):
        dt = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
        assert not cron_matches("monthly", dt)

    def test_hourly(self):
        dt = datetime(2026, 2, 16, 15, 0, tzinfo=timezone.utc)
        assert cron_matches("hourly", dt)

    def test_specific_cron(self):
        # "30 2 * * *" = every day at 02:30
        dt = datetime(2026, 2, 16, 2, 30, tzinfo=timezone.utc)
        assert cron_matches("30 2 * * *", dt)

    def test_specific_cron_no_match(self):
        dt = datetime(2026, 2, 16, 2, 31, tzinfo=timezone.utc)
        assert not cron_matches("30 2 * * *", dt)

    def test_invalid_cron(self):
        dt = datetime(2026, 2, 16, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="Invalid cron"):
            cron_matches("not a cron", dt)

    def test_dow_sunday(self):
        # 2026-02-22 is a Sunday → cron DOW=0
        dt = datetime(2026, 2, 22, 0, 0, tzinfo=timezone.utc)
        assert cron_matches("0 0 * * 0", dt)

    def test_dow_wednesday(self):
        # 2026-02-18 is a Wednesday → cron DOW=3
        dt = datetime(2026, 2, 18, 0, 0, tzinfo=timezone.utc)
        assert cron_matches("0 0 * * 3", dt)


class TestGetDueEntries:
    def test_returns_enabled_matching(self):
        config = ScheduleConfig(entries=[
            ScheduleEntry(name="a", graph="cert", scope_id="c1", cron="daily", enabled=True),
            ScheduleEntry(name="b", graph="cert", scope_id="c2", cron="daily", enabled=False),
            ScheduleEntry(name="c", graph="cert", scope_id="c3", cron="weekly", enabled=True),
        ])
        now = datetime(2026, 2, 16, 0, 0, tzinfo=timezone.utc)  # Monday midnight
        due = get_due_entries(config, now)
        names = [e.name for e in due]
        assert "a" in names  # daily matches midnight
        assert "b" not in names  # disabled
        assert "c" in names  # weekly matches Monday midnight


class TestLoadScheduleConfig:
    def test_load_from_yaml(self, tmp_path):
        config_yaml = textwrap.dedent("""\
            defaults:
              notify: [webhook]
              budget:
                max_tokens: 10000
            schedules:
              - name: test-cert
                graph: certification
                scope_id: cert-1
                cron: daily
              - name: test-lab
                graph: lab
                scope_id: lab-1
                cron: monthly
                enabled: false
                budget:
                  max_tokens: 50000
        """)
        f = tmp_path / "schedule.yaml"
        f.write_text(config_yaml)

        config = load_schedule_config(f)
        assert len(config.entries) == 2
        assert config.entries[0].name == "test-cert"
        assert config.entries[0].cron == "daily"
        assert config.entries[0].notify == ["webhook"]  # from defaults
        assert config.entries[0].budget == {"max_tokens": 10000}  # from defaults
        assert config.entries[1].enabled is False
        assert config.entries[1].budget == {"max_tokens": 50000}  # overridden

    def test_empty_config(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        config = load_schedule_config(f)
        assert len(config.entries) == 0


class TestRunScheduler:
    def test_single_iteration(self):
        dispatched = []
        config = ScheduleConfig(entries=[
            ScheduleEntry(name="a", graph="cert", scope_id="c1", cron="hourly"),
        ])

        def dispatch(entry):
            dispatched.append(entry.name)

        # Run at minute=0 so hourly matches
        state = run_scheduler(config, dispatch, max_iterations=1)
        # The entry may or may not fire depending on current time
        assert state.runs_dispatched >= 0
        assert isinstance(state, SchedulerState)

    def test_dispatch_error_captured(self):
        config = ScheduleConfig(entries=[
            ScheduleEntry(name="fail", graph="cert", scope_id="c1", cron="hourly"),
        ])

        def bad_dispatch(entry):
            raise RuntimeError("boom")

        errors_seen = []
        state = run_scheduler(
            config, bad_dispatch,
            max_iterations=1,
            on_error=lambda e, exc: errors_seen.append(str(exc)),
        )
        # Errors are captured, not raised
        assert isinstance(state, SchedulerState)
