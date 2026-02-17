"""Tests for automation config loading."""

import textwrap

import pytest

from automation.config import (
    AutomationConfig,
    PathsConfig,
    ValidationConfig,
    WatcherConfig,
    default_config,
    load_config,
)


class TestLoadConfig:
    def test_load_config_full(self, tmp_path):
        cfg_yaml = textwrap.dedent("""\
            paths:
              base: my/base
              tasks: my/base/tasks
              processing: my/base/processing
              outputs: my/base/outputs
              archive: my/base/archive
              logs: my/base/logs
              schemas: my/base/schemas
            validation:
              require_meta: false
              require_success_criteria: false
            watcher:
              interval_seconds: 10
        """)
        f = tmp_path / "config.yaml"
        f.write_text(cfg_yaml)

        cfg = load_config(f)

        assert cfg.paths.base == "my/base"
        assert cfg.paths.tasks == "my/base/tasks"
        assert cfg.paths.processing == "my/base/processing"
        assert cfg.paths.outputs == "my/base/outputs"
        assert cfg.paths.archive == "my/base/archive"
        assert cfg.paths.logs == "my/base/logs"
        assert cfg.paths.schemas == "my/base/schemas"
        assert cfg.validation.require_meta is False
        assert cfg.validation.require_success_criteria is False
        assert cfg.watcher.interval_seconds == 10

    def test_load_config_defaults(self, tmp_path):
        """Missing sections should be filled with defaults."""
        cfg_yaml = textwrap.dedent("""\
            paths:
              base: custom/base
        """)
        f = tmp_path / "config.yaml"
        f.write_text(cfg_yaml)

        cfg = load_config(f)

        assert cfg.paths.base == "custom/base"
        # Other paths fields get their defaults
        assert cfg.paths.tasks == "automation/tasks"
        # Validation and watcher sections default entirely
        assert cfg.validation.require_meta is True
        assert cfg.watcher.interval_seconds == 5

    def test_load_config_empty_file(self, tmp_path):
        """An empty YAML file should return all defaults."""
        f = tmp_path / "config.yaml"
        f.write_text("")

        cfg = load_config(f)

        assert cfg.paths.base == "automation"
        assert cfg.validation.require_meta is True
        assert cfg.validation.require_success_criteria is True
        assert cfg.watcher.interval_seconds == 5

    def test_default_config(self):
        """default_config() returns a valid config with all defaults."""
        cfg = default_config()

        assert isinstance(cfg, AutomationConfig)
        assert isinstance(cfg.paths, PathsConfig)
        assert isinstance(cfg.validation, ValidationConfig)
        assert isinstance(cfg.watcher, WatcherConfig)
        assert cfg.paths.base == "automation"
        assert cfg.paths.tasks == "automation/tasks"
        assert cfg.validation.require_meta is True
        assert cfg.watcher.interval_seconds == 5
