"""Tests for core.fleet — fleet provisioning library."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.fleet import (
    CustomModelDef,
    FleetConfig,
    FleetNode,
    FleetResult,
    NodeResult,
    build_modelfile,
    check_connectivity,
    create_custom_model,
    delete_model,
    list_existing_models,
    load_fleet_config,
    provision_fleet,
    provision_node,
    pull_model,
    select_tier3_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_yaml(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "fleet.yaml"
    p.write_text(textwrap.dedent(text))
    return p


def _make_node(name: str = "test-node", host: str = "http://localhost:11434",
               gpu_vram_gb: int = 64, total_memory_gb: int = 64) -> FleetNode:
    return FleetNode(
        name=name, host=host, platform="linux",
        gpu_type="test-gpu", gpu_vram_gb=gpu_vram_gb,
        total_memory_gb=total_memory_gb,
    )


def _make_config(nodes=None, base_models=None, custom_models=None) -> FleetConfig:
    return FleetConfig(
        nodes=nodes or [_make_node()],
        base_models=base_models or ["deepseek-r1:1.5b"],
        custom_models=custom_models or [
            CustomModelDef(name="deepseek-r1:1.5b-tier1-micro", from_model="deepseek-r1:1.5b",
                           parameters={"num_ctx": 2048, "temperature": 0}),
        ],
    )


def _mock_client(models=None, pull_side_effect=None, create_side_effect=None):
    """Return a mock ollama.Client."""
    client = MagicMock()
    client.list.return_value = {"models": models or []}
    if pull_side_effect:
        client.pull.side_effect = pull_side_effect
    if create_side_effect:
        client.create.side_effect = create_side_effect
    return client


# ===========================================================================
# TestLoadFleetConfig
# ===========================================================================
class TestLoadFleetConfig:
    def test_parses_full_config(self, tmp_path):
        p = _write_yaml(tmp_path, """\
            nodes:
              - name: n1
                host: "http://h1:11434"
                platform: linux
                gpu_type: A100
                gpu_vram_gb: 80
                total_memory_gb: 256
            base_models:
              - "deepseek-r1:1.5b"
            custom_models:
              - name: my-model
                from: "deepseek-r1:1.5b"
                parameters:
                  num_ctx: 2048
        """)
        cfg = load_fleet_config(p)
        assert len(cfg.nodes) == 1
        assert cfg.nodes[0].name == "n1"
        assert cfg.nodes[0].gpu_vram_gb == 80
        assert cfg.base_models == ["deepseek-r1:1.5b"]
        assert len(cfg.custom_models) == 1
        assert cfg.custom_models[0].name == "my-model"
        assert cfg.custom_models[0].from_model == "deepseek-r1:1.5b"
        assert cfg.custom_models[0].parameters == {"num_ctx": 2048}

    def test_missing_custom_models(self, tmp_path):
        p = _write_yaml(tmp_path, """\
            nodes:
              - name: n1
                host: "http://h1:11434"
                platform: linux
                gpu_type: A100
                gpu_vram_gb: 80
                total_memory_gb: 256
            base_models:
              - "model:tag"
        """)
        cfg = load_fleet_config(p)
        assert cfg.custom_models == []
        assert cfg.base_models == ["model:tag"]

    def test_empty_nodes(self, tmp_path):
        p = _write_yaml(tmp_path, """\
            nodes: []
            base_models: []
        """)
        cfg = load_fleet_config(p)
        assert cfg.nodes == []


# ===========================================================================
# TestSelectTier3Model
# ===========================================================================
class TestSelectTier3Model:
    def test_128gb_gets_q8(self):
        tag, size = select_tier3_model(128)
        assert tag == "llama3:70b-instruct-q8_0"
        assert size == 70

    def test_64gb_gets_q6_k(self):
        # 64 >= 54 + 4 headroom → Q6_K fits
        tag, size = select_tier3_model(64)
        assert tag == "llama3:70b-instruct-q6_K"
        assert size == 54

    def test_24gb_gets_fallback(self):
        tag, size = select_tier3_model(24)
        assert tag == "llama3:8b-instruct-q8_0"
        assert size == 8

    def test_12gb_gets_fallback(self):
        tag, size = select_tier3_model(12)
        assert tag == "llama3:8b-instruct-q8_0"
        assert size == 8

    def test_boundary_74gb(self):
        # Exactly 74 GB = 70 + 4 headroom → Q8_0
        tag, _ = select_tier3_model(74)
        assert tag == "llama3:70b-instruct-q8_0"

    def test_boundary_73gb(self):
        # 73 GB < 70 + 4 headroom → falls to Q6_K (needs 54 + 4 = 58)
        tag, _ = select_tier3_model(73)
        assert tag == "llama3:70b-instruct-q6_K"

    def test_boundary_44gb(self):
        # 44 = 40 + 4 → Q4_K_M
        tag, _ = select_tier3_model(44)
        assert tag == "llama3:70b-instruct-q4_K_M"

    def test_boundary_30gb(self):
        # 30 = 26 + 4 → Q2_K
        tag, _ = select_tier3_model(30)
        assert tag == "llama3:70b-instruct-q2_K"

    def test_boundary_29gb_fallback(self):
        tag, _ = select_tier3_model(29)
        assert tag == "llama3:8b-instruct-q8_0"

    def test_zero_memory(self):
        tag, size = select_tier3_model(0)
        assert tag == "llama3:8b-instruct-q8_0"
        assert size == 8


# ===========================================================================
# TestBuildModelfile
# ===========================================================================
class TestBuildModelfile:
    def test_basic(self):
        cm = CustomModelDef(name="test", from_model="base:tag",
                            parameters={"num_ctx": 2048, "temperature": 0})
        mf = build_modelfile(cm)
        assert mf.startswith("FROM base:tag")
        assert "PARAMETER num_ctx 2048" in mf
        assert "PARAMETER temperature 0" in mf

    def test_empty_params(self):
        cm = CustomModelDef(name="test", from_model="base:tag", parameters={})
        mf = build_modelfile(cm)
        assert mf == "FROM base:tag"

    def test_multiple_params(self):
        cm = CustomModelDef(name="t", from_model="m",
                            parameters={"a": 1, "b": 2, "c": 3})
        mf = build_modelfile(cm)
        lines = mf.strip().split("\n")
        assert lines[0] == "FROM m"
        assert len(lines) == 4  # FROM + 3 PARAMETER lines


# ===========================================================================
# TestCheckConnectivity
# ===========================================================================
class TestCheckConnectivity:
    @patch("core.fleet._get_client")
    def test_reachable(self, mock_gc):
        client = MagicMock()
        client.list.return_value = {"models": []}
        mock_gc.return_value = client
        assert check_connectivity("http://localhost:11434") is True

    @patch("core.fleet._get_client")
    def test_unreachable(self, mock_gc):
        client = MagicMock()
        client.list.side_effect = ConnectionError("refused")
        mock_gc.return_value = client
        assert check_connectivity("http://localhost:11434") is False


# ===========================================================================
# TestListExistingModels
# ===========================================================================
class TestListExistingModels:
    @patch("core.fleet._get_client")
    def test_returns_names(self, mock_gc):
        client = MagicMock()
        client.list.return_value = {
            "models": [
                {"name": "deepseek-r1:1.5b"},
                {"name": "llama3:8b-instruct-q8_0"},
            ]
        }
        mock_gc.return_value = client
        names = list_existing_models("http://host:11434")
        assert "deepseek-r1:1.5b" in names
        assert "llama3:8b-instruct-q8_0" in names

    @patch("core.fleet._get_client")
    def test_handles_latest_suffix(self, mock_gc):
        client = MagicMock()
        client.list.return_value = {
            "models": [{"name": "mymodel:latest"}]
        }
        mock_gc.return_value = client
        names = list_existing_models("http://host:11434")
        assert "mymodel" in names
        assert "mymodel:latest" in names

    @patch("core.fleet._get_client")
    def test_empty_list(self, mock_gc):
        client = MagicMock()
        client.list.return_value = {"models": []}
        mock_gc.return_value = client
        names = list_existing_models("http://host:11434")
        assert names == set()


# ===========================================================================
# TestPullModel
# ===========================================================================
class TestPullModel:
    @patch("core.fleet._get_client")
    def test_calls_client_pull(self, mock_gc):
        client = MagicMock()
        mock_gc.return_value = client
        pull_model("http://host:11434", "model:tag")
        client.pull.assert_called_once_with(model="model:tag")


# ===========================================================================
# TestDeleteModel
# ===========================================================================
class TestDeleteModel:
    @patch("core.fleet._get_client")
    def test_calls_client_delete(self, mock_gc):
        client = MagicMock()
        mock_gc.return_value = client
        delete_model("http://host:11434", "model:tag")
        client.delete.assert_called_once_with(model="model:tag")


# ===========================================================================
# TestCreateCustomModel
# ===========================================================================
class TestCreateCustomModel:
    @patch("core.fleet._get_client")
    def test_calls_client_create(self, mock_gc):
        client = MagicMock()
        mock_gc.return_value = client
        cm = CustomModelDef(name="my-custom", from_model="base:tag",
                            parameters={"num_ctx": 4096})
        create_custom_model("http://host:11434", cm)
        client.create.assert_called_once_with(
            model="my-custom",
            from_="base:tag",
            parameters={"num_ctx": 4096},
        )

    @patch("core.fleet._get_client")
    def test_empty_params_passes_none(self, mock_gc):
        client = MagicMock()
        mock_gc.return_value = client
        cm = CustomModelDef(name="my-custom", from_model="base:tag", parameters={})
        create_custom_model("http://host:11434", cm)
        client.create.assert_called_once_with(
            model="my-custom",
            from_="base:tag",
            parameters=None,
        )


# ===========================================================================
# TestProvisionNode
# ===========================================================================
class TestProvisionNode:
    @patch("core.fleet._get_client")
    def test_full_provision_all_new(self, mock_gc):
        """All models are new — everything gets pulled/created."""
        client = _mock_client(models=[])
        mock_gc.return_value = client
        node = _make_node(gpu_vram_gb=64)
        config = _make_config()

        result = provision_node(node, config)

        assert result.reachable is True
        assert "deepseek-r1:1.5b" in result.pulled
        assert "deepseek-r1:1.5b-tier1-micro" in result.created
        assert result.tier3_model == "llama3:70b-instruct-q6_K"
        assert result.tier3_model in result.pulled
        assert not result.failed
        assert not result.errors

    @patch("core.fleet._get_client")
    def test_deletes_and_redeploys_existing(self, mock_gc):
        """Existing models are deleted then re-pulled/created."""
        client = _mock_client(models=[
            {"name": "deepseek-r1:1.5b"},
            {"name": "deepseek-r1:1.5b-tier1-micro"},
            {"name": "llama3:70b-instruct-q6_K"},
        ])
        mock_gc.return_value = client
        node = _make_node(gpu_vram_gb=64)
        config = _make_config()

        result = provision_node(node, config)

        assert result.reachable is True
        assert "deepseek-r1:1.5b" in result.deleted
        assert "deepseek-r1:1.5b-tier1-micro" in result.deleted
        assert "llama3:70b-instruct-q6_K" in result.deleted
        assert "deepseek-r1:1.5b" in result.pulled
        assert "deepseek-r1:1.5b-tier1-micro" in result.created
        assert result.tier3_model in result.pulled
        assert not result.failed
        assert client.delete.call_count == 3

    @patch("core.fleet._get_client")
    def test_unreachable_node(self, mock_gc):
        """Unreachable node returns early with error."""
        client = MagicMock()
        client.list.side_effect = ConnectionError("refused")
        mock_gc.return_value = client
        node = _make_node()
        config = _make_config()

        result = provision_node(node, config)

        assert result.reachable is False
        assert len(result.errors) == 1
        assert "unreachable" in result.errors[0].lower()

    @patch("core.fleet._get_client")
    def test_pull_failure(self, mock_gc):
        """A failed pull records the error but continues."""
        client = _mock_client(
            models=[],
            pull_side_effect=RuntimeError("network error"),
        )
        mock_gc.return_value = client
        node = _make_node(gpu_vram_gb=64)
        config = _make_config(base_models=["bad-model"])

        result = provision_node(node, config)

        assert result.reachable is True
        assert "bad-model" in result.failed
        assert any("bad-model" in e for e in result.errors)

    @patch("core.fleet._get_client")
    def test_12gb_fallback(self, mock_gc):
        """12 GB node falls back to 8b model."""
        client = _mock_client(models=[])
        mock_gc.return_value = client
        node = _make_node(gpu_vram_gb=12)
        config = _make_config(base_models=[], custom_models=[])

        result = provision_node(node, config)

        assert result.tier3_model == "llama3:8b-instruct-q8_0"
        assert result.tier3_model in result.pulled


# ===========================================================================
# TestProvisionFleet
# ===========================================================================
class TestProvisionFleet:
    @patch("core.fleet._get_client")
    def test_provisions_all_nodes(self, mock_gc):
        client = _mock_client(models=[])
        mock_gc.return_value = client
        config = _make_config(nodes=[
            _make_node("node-a", gpu_vram_gb=128),
            _make_node("node-b", gpu_vram_gb=12),
        ])

        result = provision_fleet(config)

        assert len(result.node_results) == 2
        assert result.node_results[0].node_name == "node-a"
        assert result.node_results[1].node_name == "node-b"
        assert result.node_results[0].tier3_model == "llama3:70b-instruct-q8_0"
        assert result.node_results[1].tier3_model == "llama3:8b-instruct-q8_0"

    @patch("core.fleet._get_client")
    def test_all_ok_true(self, mock_gc):
        client = _mock_client(models=[])
        mock_gc.return_value = client
        config = _make_config(nodes=[_make_node()])

        result = provision_fleet(config)
        assert result.all_ok is True

    @patch("core.fleet._get_client")
    def test_all_ok_false_on_failure(self, mock_gc):
        client = _mock_client(models=[], pull_side_effect=RuntimeError("fail"))
        mock_gc.return_value = client
        config = _make_config(nodes=[_make_node()])

        result = provision_fleet(config)
        assert result.all_ok is False


# ===========================================================================
# TestFleetResult
# ===========================================================================
class TestFleetResult:
    def test_all_ok_empty(self):
        fr = FleetResult(node_results=[])
        assert fr.all_ok is True

    def test_all_ok_mixed(self):
        ok = NodeResult(node_name="ok", reachable=True)
        bad = NodeResult(node_name="bad", reachable=True, failed=["x"], errors=["e"])
        fr = FleetResult(node_results=[ok, bad])
        assert fr.all_ok is False

    def test_all_ok_unreachable(self):
        nr = NodeResult(node_name="down", reachable=False)
        fr = FleetResult(node_results=[nr])
        assert fr.all_ok is False

    def test_all_ok_all_good(self):
        a = NodeResult(node_name="a", reachable=True)
        b = NodeResult(node_name="b", reachable=True)
        fr = FleetResult(node_results=[a, b])
        assert fr.all_ok is True
