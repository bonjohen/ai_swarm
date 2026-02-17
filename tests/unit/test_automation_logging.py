"""Tests for the automation structured logging module."""

from pathlib import Path

import pytest

from automation.config import AutomationConfig, PathsConfig
from automation.logging import ACTIONS, log_event, log_path, read_log


def _cfg(tmp_path) -> AutomationConfig:
    paths = PathsConfig(
        base=str(tmp_path / "auto"),
        tasks=str(tmp_path / "auto" / "tasks"),
        processing=str(tmp_path / "auto" / "processing"),
        outputs=str(tmp_path / "auto" / "outputs"),
        archive=str(tmp_path / "auto" / "archive"),
        logs=str(tmp_path / "auto" / "logs"),
        schemas=str(tmp_path / "auto" / "schemas"),
    )
    return AutomationConfig(paths=paths)


class TestLogEvent:
    def test_correct_structure(self, tmp_path):
        cfg = _cfg(tmp_path)
        entry = log_event(cfg, action="task_created", task_id="t-001",
                          status="ok", details="Created task")

        assert "timestamp" in entry
        assert entry["task_id"] == "t-001"
        assert entry["action"] == "task_created"
        assert entry["status"] == "ok"
        assert entry["details"] == "Created task"

        # Persisted to disk
        entries = read_log(cfg)
        assert len(entries) == 1
        assert entries[0]["action"] == "task_created"

    def test_all_actions_produce_entries(self, tmp_path):
        cfg = _cfg(tmp_path)

        for action in sorted(ACTIONS):
            log_event(cfg, action=action, task_id="t-000",
                      details=f"Testing {action}")

        entries = read_log(cfg)
        logged_actions = {e["action"] for e in entries}
        assert ACTIONS == logged_actions

    def test_log_file_appends(self, tmp_path):
        """Multiple writes append rather than overwrite."""
        cfg = _cfg(tmp_path)

        log_event(cfg, action="task_created", task_id="t-001")
        log_event(cfg, action="task_completed", task_id="t-001")
        log_event(cfg, action="watcher_poll")

        entries = read_log(cfg)
        assert len(entries) == 3
        assert entries[0]["action"] == "task_created"
        assert entries[1]["action"] == "task_completed"
        assert entries[2]["action"] == "watcher_poll"


class TestReadLog:
    def test_empty_log(self, tmp_path):
        cfg = _cfg(tmp_path)
        assert read_log(cfg) == []

    def test_creates_logs_directory(self, tmp_path):
        cfg = _cfg(tmp_path)
        lp = log_path(cfg)
        assert lp.parent.exists()
