"""Tests for the bootstrap_automation CLI script."""

import json
import textwrap

import pytest

from scripts.bootstrap_automation import bootstrap, main


class TestBootstrap:
    def test_bootstrap_creates_dirs(self, tmp_path, monkeypatch):
        """All configured directories are created."""
        monkeypatch.chdir(tmp_path)
        config_yaml = textwrap.dedent("""\
            paths:
              base: auto
              tasks: auto/tasks
              processing: auto/processing
              outputs: auto/outputs
              archive: auto/archive
              logs: auto/logs
              schemas: auto/schemas
            validation:
              require_meta: true
              require_success_criteria: true
            watcher:
              interval_seconds: 5
        """)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(config_yaml)

        results = bootstrap(cfg_path)

        for d in ["auto", "auto/tasks", "auto/processing", "auto/outputs",
                   "auto/archive", "auto/logs", "auto/schemas"]:
            assert (tmp_path / d).is_dir(), f"{d} should exist"
            assert results[d] == "created"

    def test_bootstrap_creates_queue_json(self, tmp_path, monkeypatch):
        """queue.json is initialised with empty lists."""
        monkeypatch.chdir(tmp_path)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("paths:\n  base: auto\n")

        bootstrap(cfg_path)

        queue_path = tmp_path / "auto" / "queue.json"
        assert queue_path.exists()
        data = json.loads(queue_path.read_text())
        assert data["pending"] == []
        assert data["processing"] == []
        assert data["completed"] == []
        assert data["failed"] == []
        assert data["parents"] == {}

    def test_bootstrap_idempotent(self, tmp_path, monkeypatch):
        """Running twice doesn't error or overwrite queue.json."""
        monkeypatch.chdir(tmp_path)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("paths:\n  base: auto\n  tasks: auto/tasks\n")

        first = bootstrap(cfg_path)
        assert first["auto"] == "created"

        # Write some data into queue.json to verify it isn't overwritten
        queue_path = tmp_path / "auto" / "queue.json"
        data = json.loads(queue_path.read_text())
        data["pending"] = ["existing-task"]
        queue_path.write_text(json.dumps(data))

        second = bootstrap(cfg_path)
        assert second["auto"] == "exists"
        assert second["auto/queue.json"] == "exists"

        # Verify existing data was preserved
        preserved = json.loads(queue_path.read_text())
        assert preserved["pending"] == ["existing-task"]

    def test_bootstrap_custom_config(self, tmp_path, monkeypatch):
        """--config flag is respected via the main() CLI."""
        monkeypatch.chdir(tmp_path)
        cfg_yaml = textwrap.dedent("""\
            paths:
              base: custom
              tasks: custom/tasks
              processing: custom/processing
              outputs: custom/outputs
              archive: custom/archive
              logs: custom/logs
              schemas: custom/schemas
        """)
        cfg_path = tmp_path / "my_config.yaml"
        cfg_path.write_text(cfg_yaml)

        rc = main(["--config", str(cfg_path)])
        assert rc == 0
        assert (tmp_path / "custom").is_dir()
        assert (tmp_path / "custom" / "tasks").is_dir()
        assert (tmp_path / "custom" / "queue.json").exists()
