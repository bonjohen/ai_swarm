"""GPU and hardware health monitoring for the AI Swarm platform.

Provides health checks for:
  - Local Ollama instances (loaded models via /api/tags)
  - Local GPU VRAM usage via nvidia-smi
  - Remote DGX Spark availability via HTTP ping
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class GPUStatus:
    """Snapshot of a GPU's health."""

    name: str = ""
    vram_total_mb: int = 0
    vram_used_mb: int = 0
    vram_free_mb: int = 0
    utilization_pct: int = 0
    temperature_c: int = 0

    @property
    def vram_usage_pct(self) -> float:
        if self.vram_total_mb == 0:
            return 0.0
        return (self.vram_used_mb / self.vram_total_mb) * 100

    @property
    def healthy(self) -> bool:
        return self.vram_usage_pct < 90.0


@dataclass
class OllamaHealth:
    """Health status for an Ollama instance."""

    host: str = ""
    reachable: bool = False
    loaded_models: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class HealthReport:
    """Aggregate health report for all monitored hardware."""

    gpu: GPUStatus | None = None
    ollama_local: OllamaHealth | None = None
    dgx_spark: OllamaHealth | None = None

    @property
    def local_gpu_healthy(self) -> bool:
        return self.gpu is not None and self.gpu.healthy

    @property
    def local_ollama_reachable(self) -> bool:
        return self.ollama_local is not None and self.ollama_local.reachable

    @property
    def dgx_spark_reachable(self) -> bool:
        return self.dgx_spark is not None and self.dgx_spark.reachable


def check_nvidia_smi() -> GPUStatus | None:
    """Query nvidia-smi for GPU status. Returns None if not available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            logger.debug("nvidia-smi failed: %s", result.stderr.strip())
            return None

        line = result.stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            return None

        return GPUStatus(
            name=parts[0],
            vram_total_mb=int(parts[1]),
            vram_used_mb=int(parts[2]),
            vram_free_mb=int(parts[3]),
            utilization_pct=int(parts[4]),
            temperature_c=int(parts[5]),
        )
    except FileNotFoundError:
        logger.debug("nvidia-smi not found")
        return None
    except (subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        logger.debug("nvidia-smi parse error: %s", exc)
        return None


def check_ollama(host: str = "http://localhost:11434", timeout: float = 3.0) -> OllamaHealth:
    """Check an Ollama instance for reachability and loaded models."""
    health = OllamaHealth(host=host)
    try:
        resp = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=timeout)
        if resp.status_code == 200:
            health.reachable = True
            data = resp.json()
            health.loaded_models = [
                m.get("name", "") for m in data.get("models", [])
            ]
        else:
            health.error = f"HTTP {resp.status_code}"
    except httpx.ConnectError as exc:
        health.error = f"connection error: {exc}"
    except httpx.TimeoutException:
        health.error = "timeout"
    except Exception as exc:
        health.error = str(exc)
    return health


def check_health(
    *,
    local_ollama_host: str = "http://localhost:11434",
    dgx_spark_host: str | None = None,
    check_gpu: bool = True,
) -> HealthReport:
    """Run all health checks and return an aggregate report."""
    report = HealthReport()

    if check_gpu:
        report.gpu = check_nvidia_smi()

    report.ollama_local = check_ollama(local_ollama_host)

    if dgx_spark_host:
        report.dgx_spark = check_ollama(dgx_spark_host)

    # Log warnings
    if report.gpu and not report.gpu.healthy:
        logger.warning(
            "GPU VRAM pressure: %.1f%% used (%d/%d MB)",
            report.gpu.vram_usage_pct,
            report.gpu.vram_used_mb,
            report.gpu.vram_total_mb,
        )
    if not report.local_ollama_reachable:
        logger.warning(
            "Local Ollama unreachable at %s: %s",
            local_ollama_host,
            report.ollama_local.error if report.ollama_local else "unknown",
        )
    if dgx_spark_host and not report.dgx_spark_reachable:
        logger.warning(
            "DGX Spark unreachable at %s: %s",
            dgx_spark_host,
            report.dgx_spark.error if report.dgx_spark else "unknown",
        )

    return report
