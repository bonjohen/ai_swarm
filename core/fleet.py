"""Fleet provisioner — deploy Ollama models across mixed hardware.

Reads a fleet config YAML, checks connectivity, pulls models progressively,
creates custom tier configs, and selects the right llama3:70b quant per-node
based on available memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quant selection table: (min_vram_gb, tag, approx_size_gb)
# Ordered from highest quality to lowest; first fit wins.
# ---------------------------------------------------------------------------
_TIER3_70B_QUANTS: list[tuple[int, str, int]] = [
    (74, "llama3:70b-instruct-q8_0", 70),
    (48, "llama3:70b-instruct-q6_K", 54),
    (44, "llama3:70b-instruct-q4_K_M", 40),
    (30, "llama3:70b-instruct-q2_K", 26),
]

_TIER3_FALLBACK_TAG = "llama3:8b-instruct-q8_0"
_TIER3_FALLBACK_SIZE = 8

HEADROOM_GB = 4


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class FleetNode:
    name: str
    host: str
    platform: str
    gpu_type: str
    gpu_vram_gb: int
    total_memory_gb: int


@dataclass
class CustomModelDef:
    name: str
    from_model: str
    parameters: dict[str, Any]


@dataclass
class FleetConfig:
    nodes: list[FleetNode]
    base_models: list[str]
    custom_models: list[CustomModelDef]


@dataclass
class NodeResult:
    node_name: str
    reachable: bool = False
    pulled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tier3_model: str | None = None


@dataclass
class FleetResult:
    node_results: list[NodeResult]

    @property
    def all_ok(self) -> bool:
        return all(
            nr.reachable and not nr.failed and not nr.errors
            for nr in self.node_results
        )


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def load_fleet_config(path: str | Path) -> FleetConfig:
    """Parse a fleet YAML config into a FleetConfig."""
    raw = yaml.safe_load(Path(path).read_text())
    nodes = [
        FleetNode(
            name=n["name"],
            host=n["host"],
            platform=n["platform"],
            gpu_type=n["gpu_type"],
            gpu_vram_gb=n["gpu_vram_gb"],
            total_memory_gb=n["total_memory_gb"],
        )
        for n in raw.get("nodes", [])
    ]
    base_models = list(raw.get("base_models", []))
    custom_models = [
        CustomModelDef(
            name=cm["name"],
            from_model=cm["from"],
            parameters=dict(cm.get("parameters", {})),
        )
        for cm in raw.get("custom_models", [])
    ]
    return FleetConfig(nodes=nodes, base_models=base_models, custom_models=custom_models)


# ---------------------------------------------------------------------------
# Quant selection
# ---------------------------------------------------------------------------
def select_tier3_model(available_memory_gb: int) -> tuple[str, int]:
    """Pick the best llama3 quant that fits in *available_memory_gb*.

    Returns ``(model_tag, approx_size_gb)``.  Falls back to 8b if no 70b
    quant fits with HEADROOM_GB headroom.
    """
    for min_vram, tag, size in _TIER3_70B_QUANTS:
        if available_memory_gb >= size + HEADROOM_GB:
            return tag, size
    return _TIER3_FALLBACK_TAG, _TIER3_FALLBACK_SIZE


# ---------------------------------------------------------------------------
# Modelfile builder
# ---------------------------------------------------------------------------
def build_modelfile(custom: CustomModelDef) -> str:
    """Generate an Ollama Modelfile string for a custom model definition."""
    lines = [f"FROM {custom.from_model}"]
    for key, value in custom.parameters.items():
        lines.append(f"PARAMETER {key} {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama client helpers (lazy import)
# ---------------------------------------------------------------------------
def _get_client(host: str) -> Any:
    """Return an ``ollama.Client`` for *host*.

    The import is lazy so pure-logic functions work without the package.
    """
    import ollama  # noqa: E402

    return ollama.Client(host=host)


def check_connectivity(host: str) -> bool:
    """Return True if the Ollama server at *host* is reachable."""
    try:
        client = _get_client(host)
        client.list()
        return True
    except Exception:
        return False


def list_existing_models(host: str) -> set[str]:
    """Return the set of model tags already present on *host*."""
    client = _get_client(host)
    response = client.list()
    names: set[str] = set()
    models = response.get("models", []) if isinstance(response, dict) else getattr(response, "models", [])
    for m in models:
        name = m.get("name", "") if isinstance(m, dict) else getattr(m, "model", "")
        if name:
            # Normalise `:latest` suffix — "foo:latest" -> "foo"
            clean = name.removesuffix(":latest")
            names.add(clean)
            names.add(name)  # keep original too for exact-match checks
    return names


def pull_model(host: str, tag: str) -> None:
    """Pull *tag* on the Ollama instance at *host*."""
    client = _get_client(host)
    client.pull(model=tag)


def create_custom_model(host: str, custom: CustomModelDef) -> None:
    """Create a custom model on *host* from a CustomModelDef."""
    modelfile = build_modelfile(custom)
    client = _get_client(host)
    client.create(model=custom.name, modelfile=modelfile)


# ---------------------------------------------------------------------------
# Node provisioning
# ---------------------------------------------------------------------------
def provision_node(node: FleetNode, config: FleetConfig) -> NodeResult:
    """Provision a single fleet node: connectivity, pull, create, tier3."""
    result = NodeResult(node_name=node.name)

    # 1. Connectivity check
    if not check_connectivity(node.host):
        result.errors.append(f"Node {node.name} unreachable at {node.host}")
        return result
    result.reachable = True

    # 2. List existing models to skip re-pulls
    try:
        existing = list_existing_models(node.host)
    except Exception as exc:
        result.errors.append(f"Failed to list models: {exc}")
        return result

    # 3. Pull base models
    for tag in config.base_models:
        if tag in existing:
            result.skipped.append(tag)
            logger.info("[%s] Skipping %s (already present)", node.name, tag)
            continue
        try:
            pull_model(node.host, tag)
            result.pulled.append(tag)
            logger.info("[%s] Pulled %s", node.name, tag)
        except Exception as exc:
            result.failed.append(tag)
            result.errors.append(f"Pull failed for {tag}: {exc}")
            logger.error("[%s] Pull failed for %s: %s", node.name, tag, exc)

    # 4. Create custom models
    for cm in config.custom_models:
        if cm.name in existing:
            result.skipped.append(cm.name)
            logger.info("[%s] Skipping custom %s (already present)", node.name, cm.name)
            continue
        try:
            create_custom_model(node.host, cm)
            result.created.append(cm.name)
            logger.info("[%s] Created custom model %s", node.name, cm.name)
        except Exception as exc:
            result.failed.append(cm.name)
            result.errors.append(f"Create failed for {cm.name}: {exc}")
            logger.error("[%s] Create failed for %s: %s", node.name, cm.name, exc)

    # 5. Select and pull tier3 model
    tier3_tag, tier3_size = select_tier3_model(node.gpu_vram_gb)
    result.tier3_model = tier3_tag
    if tier3_tag in existing:
        result.skipped.append(tier3_tag)
        logger.info("[%s] Skipping tier3 %s (already present)", node.name, tier3_tag)
    else:
        try:
            pull_model(node.host, tier3_tag)
            result.pulled.append(tier3_tag)
            logger.info("[%s] Pulled tier3 %s (~%d GB)", node.name, tier3_tag, tier3_size)
        except Exception as exc:
            result.failed.append(tier3_tag)
            result.errors.append(f"Pull failed for tier3 {tier3_tag}: {exc}")
            logger.error("[%s] Tier3 pull failed for %s: %s", node.name, tier3_tag, exc)

    return result


# ---------------------------------------------------------------------------
# Fleet-level provisioning
# ---------------------------------------------------------------------------
def provision_fleet(config: FleetConfig) -> FleetResult:
    """Provision all nodes in the fleet config. Returns FleetResult."""
    results = [provision_node(node, config) for node in config.nodes]
    return FleetResult(node_results=results)
