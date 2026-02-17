"""Automation config — directory layout and settings for the file-based task bridge.

Loads YAML config into dataclasses.  Missing sections fall back to defaults.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PathsConfig:
    """Directory paths for the automation file bridge."""
    base: str = "automation"
    tasks: str = "automation/tasks"
    processing: str = "automation/processing"
    outputs: str = "automation/outputs"
    archive: str = "automation/archive"
    logs: str = "automation/logs"
    schemas: str = "automation/schemas"


@dataclass
class ValidationConfig:
    """Task validation settings."""
    require_meta: bool = True
    require_success_criteria: bool = True


@dataclass
class WatcherConfig:
    """File-watcher polling settings."""
    interval_seconds: int = 5


@dataclass
class AutomationConfig:
    """Top-level automation configuration."""
    paths: PathsConfig = field(default_factory=PathsConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)


def load_config(path: str | Path) -> AutomationConfig:
    """Parse a YAML file into an AutomationConfig.

    Missing sections are filled with defaults.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}

    paths_raw = raw.get("paths", {})
    validation_raw = raw.get("validation", {})
    watcher_raw = raw.get("watcher", {})

    return AutomationConfig(
        paths=PathsConfig(**paths_raw),
        validation=ValidationConfig(**validation_raw),
        watcher=WatcherConfig(**watcher_raw),
    )


def default_config() -> AutomationConfig:
    """Return an AutomationConfig with all defaults."""
    return AutomationConfig()
