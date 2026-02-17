"""Tests for scripts.provision_fleet CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.fleet import FleetConfig, FleetNode, FleetResult, NodeResult, CustomModelDef
from scripts.provision_fleet import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
FLEET_YAML = Path(__file__).parent.parent.parent / "config" / "fleet_config.yaml"


# ===========================================================================
# TestDryRun
# ===========================================================================
class TestDryRun:
    def test_dry_run_prints_plan(self, capsys):
        rc = main(["--config", str(FLEET_YAML), "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Dry-run" in out
        assert "desktop-rtx4070" in out
        assert "dgx-spark" in out
        # 12 GB node should get fallback
        assert "llama3:8b-instruct-q8_0" in out
        # 128 GB node should get Q8_0
        assert "llama3:70b-instruct-q8_0" in out

    def test_dry_run_single_node(self, capsys):
        rc = main(["--config", str(FLEET_YAML), "--dry-run", "--node", "macbook-pro-m4"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "macbook-pro-m4" in out
        assert "llama3:70b-instruct-q6_K" in out
        # Other nodes should NOT appear
        assert "dgx-spark" not in out

    def test_unknown_node_returns_1(self, capsys):
        rc = main(["--config", str(FLEET_YAML), "--node", "nonexistent"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "nonexistent" in out


# ===========================================================================
# TestProvisionCLI
# ===========================================================================
class TestProvisionCLI:
    @patch("scripts.provision_fleet.provision_fleet")
    @patch("scripts.provision_fleet.load_fleet_config")
    def test_success_returns_0(self, mock_load, mock_prov, capsys):
        mock_load.return_value = FleetConfig(
            nodes=[FleetNode("n1", "http://h:11434", "linux", "gpu", 64, 64)],
            base_models=["m1"],
            custom_models=[],
        )
        mock_prov.return_value = FleetResult(
            node_results=[NodeResult(node_name="n1", reachable=True, tier3_model="t3")]
        )
        rc = main(["--config", "dummy.yaml"])
        assert rc == 0
        mock_prov.assert_called_once()

    @patch("scripts.provision_fleet.provision_fleet")
    @patch("scripts.provision_fleet.load_fleet_config")
    def test_failure_returns_1(self, mock_load, mock_prov, capsys):
        mock_load.return_value = FleetConfig(
            nodes=[FleetNode("n1", "http://h:11434", "linux", "gpu", 64, 64)],
            base_models=["m1"],
            custom_models=[],
        )
        mock_prov.return_value = FleetResult(
            node_results=[NodeResult(
                node_name="n1", reachable=True,
                failed=["m1"], errors=["pull failed"],
            )]
        )
        rc = main(["--config", "dummy.yaml"])
        assert rc == 1
