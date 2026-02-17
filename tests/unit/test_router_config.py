"""Tests for router config loading — TierConfig, ProviderConfig, RouterConfig."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from core.routing import (
    EscalationCriteria,
    ModelRouter,
    ProviderConfig,
    RouterConfig,
    TierConfig,
    load_router_config,
)


SAMPLE_CONFIG = {
    "tier1": {
        "model": "deepseek-r1:1.5b",
        "context_length": 2048,
        "max_tokens": 128,
        "temperature": 0.0,
        "concurrency": 8,
    },
    "tier2": {
        "model": "deepseek-r1:1.5b",
        "context_length": 4096,
        "max_tokens": 1024,
        "temperature": 0.2,
        "concurrency": 4,
    },
    "tier3_providers": [
        {
            "name": "dgx_spark",
            "provider_type": "dgx",
            "model": "llama3:70b",
            "host": "http://dgx-spark:11434",
            "cost_per_1k_input": 0.001,
            "cost_per_1k_output": 0.002,
            "quality_score": 0.85,
            "max_context": 8192,
            "tags": ["local", "dgx", "frontier"],
        },
        {
            "name": "anthropic_claude",
            "provider_type": "anthropic",
            "model": "claude-sonnet-4-5-20250929",
            "cost_per_1k_input": 0.003,
            "cost_per_1k_output": 0.015,
            "quality_score": 0.95,
            "max_context": 200000,
            "tags": ["cloud", "frontier"],
        },
    ],
    "escalation": {
        "min_confidence": 0.75,
        "max_missing_citations": 2,
        "max_contradiction_ambiguity": 0.5,
        "synthesis_complexity_threshold": 0.8,
    },
    "provider_selection_strategy": "prefer_local",
    "daily_frontier_cap": 100,
}


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "router_config.yaml"
    path.write_text(yaml.dump(SAMPLE_CONFIG))
    return path


class TestLoadRouterConfig:
    def test_parses_yaml(self, config_path: Path) -> None:
        cfg = load_router_config(config_path)
        assert isinstance(cfg, RouterConfig)
        assert cfg.provider_selection_strategy == "prefer_local"
        assert cfg.daily_frontier_cap == 100

    def test_loads_actual_config_file(self) -> None:
        """Verify the shipped config/router_config.yaml parses."""
        cfg = load_router_config("config/router_config.yaml")
        assert cfg.tier1.model == "deepseek-r1:1.5b"
        assert len(cfg.tier3_providers) == 3


class TestTierConfig:
    def test_tier1_values(self, config_path: Path) -> None:
        cfg = load_router_config(config_path)
        assert cfg.tier1.model == "deepseek-r1:1.5b"
        assert cfg.tier1.context_length == 2048
        assert cfg.tier1.max_tokens == 128
        assert cfg.tier1.temperature == 0.0
        assert cfg.tier1.concurrency == 8

    def test_tier2_values(self, config_path: Path) -> None:
        cfg = load_router_config(config_path)
        assert cfg.tier2.model == "deepseek-r1:1.5b"
        assert cfg.tier2.context_length == 4096
        assert cfg.tier2.max_tokens == 1024
        assert cfg.tier2.temperature == 0.2
        assert cfg.tier2.concurrency == 4


class TestProviderConfig:
    def test_provider_list(self, config_path: Path) -> None:
        cfg = load_router_config(config_path)
        assert len(cfg.tier3_providers) == 2
        names = [p.name for p in cfg.tier3_providers]
        assert "dgx_spark" in names
        assert "anthropic_claude" in names

    def test_provider_fields(self, config_path: Path) -> None:
        cfg = load_router_config(config_path)
        dgx = next(p for p in cfg.tier3_providers if p.name == "dgx_spark")
        assert dgx.provider_type == "dgx"
        assert dgx.model == "llama3:70b"
        assert dgx.host == "http://dgx-spark:11434"
        assert dgx.cost_per_1k_input == 0.001
        assert dgx.quality_score == 0.85
        assert "local" in dgx.tags

    def test_escalation_criteria(self, config_path: Path) -> None:
        cfg = load_router_config(config_path)
        assert cfg.escalation.min_confidence == 0.75
        assert cfg.escalation.max_missing_citations == 2
        assert cfg.escalation.max_contradiction_ambiguity == 0.5
        assert cfg.escalation.synthesis_complexity_threshold == 0.8


class TestRouterWithConfig:
    def test_model_router_accepts_config(self, config_path: Path) -> None:
        cfg = load_router_config(config_path)
        router = ModelRouter(
            escalation_criteria=cfg.escalation,
            config=cfg,
        )
        assert router.config is cfg
        assert router.escalation_criteria.min_confidence == 0.75
