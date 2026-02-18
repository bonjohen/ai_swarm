"""Tiered dispatcher — routes requests through Tier 0 → 1 → 2 → 3.

Tier 0: deterministic regex/command matching (no LLM).
Tier 1: micro LLM classification via ``MicroRouterAgent``.
Tier 2: light LLM reasoning (larger context, more tokens).
Tier 3: reserved for frontier provider pool (R4).
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from core.command_registry import CommandRegistry
from core.logging import get_metrics_collector
from core.routing import ModelRouter, compute_routing_score, DEFAULT_ROUTING_THRESHOLD
from core.gpu_monitor import HealthReport, check_health
from core.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)

# Type alias matching core.routing.ModelCallable
ModelCallable = Callable[[str, str], str]

# Thresholds
DEFAULT_CONFIDENCE_THRESHOLD = 0.75
DEFAULT_QUALITY_THRESHOLD = 0.70
DEFAULT_MAX_TIER1_RETRIES = 2
DEFAULT_MAX_INPUT_LENGTH = 10_000
DEFAULT_TIER1_TIMEOUT = 5.0   # seconds
DEFAULT_TIER2_TIMEOUT = 30.0  # seconds

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
]


@dataclass
class DispatchResult:
    """Outcome of dispatching a request through the tiered router."""

    tier: int
    action: str
    target: str
    args: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    provider: str | None = None
    model_response: str | None = None
    safety_flagged: bool = False
    safety_reason: str = ""


class TieredDispatcher:
    """Routes requests through the tiered inference chain.

    Tier 0: Deterministic regex/command matching (no LLM).
    Tier 1: Micro LLM classification (MicroRouterAgent).
    Tier 2: Light LLM reasoning (larger context/tokens).
    Tier 3: Frontier provider pool (future — R4).
    """

    def __init__(
        self,
        command_registry: CommandRegistry,
        model_router: ModelRouter | None = None,
        provider_registry: ProviderRegistry | None = None,
        *,
        tier1_model_call: ModelCallable | None = None,
        tier2_model_call: ModelCallable | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
        max_input_length: int = DEFAULT_MAX_INPUT_LENGTH,
    ) -> None:
        self.command_registry = command_registry
        self.model_router = model_router
        self.provider_registry = provider_registry
        self.tier1_model_call = tier1_model_call
        self.tier2_model_call = tier2_model_call
        self.confidence_threshold = confidence_threshold
        self.quality_threshold = quality_threshold
        self.max_input_length = max_input_length
        self.tier1_timeout = DEFAULT_TIER1_TIMEOUT
        self.tier2_timeout = DEFAULT_TIER2_TIMEOUT
        # Concurrency semaphores per tier (R6.3)
        self._tier1_semaphore = threading.Semaphore(8)
        self._tier2_semaphore = threading.Semaphore(4)

    def reload_config(self, path: str) -> None:
        """Hot-reload thresholds and timeouts from a router_config.yaml.

        Updates confidence/quality thresholds, per-tier timeouts, and
        concurrency limits. Does NOT replace model adapters or callables.
        If a ModelRouter is attached, reloads its config too.
        """
        from core.routing import load_router_config

        config = load_router_config(path)
        esc = config.escalation
        self.confidence_threshold = esc.min_confidence
        self.quality_threshold = getattr(esc, "synthesis_complexity_threshold", self.quality_threshold)
        self.tier1_timeout = config.tier1.timeout
        self.tier2_timeout = config.tier2.timeout
        self._tier1_semaphore = threading.Semaphore(config.tier1.concurrency)
        self._tier2_semaphore = threading.Semaphore(config.tier2.concurrency)
        if self.model_router is not None:
            self.model_router.reload_config(path)
        logger.info(
            "Dispatcher config reloaded: confidence=%.2f, tier1_timeout=%.1fs, tier2_timeout=%.1fs",
            self.confidence_threshold, self.tier1_timeout, self.tier2_timeout,
        )

    @staticmethod
    def _call_with_timeout(
        fn: Callable[..., Any],
        args: tuple,
        timeout: float,
    ) -> Any:
        """Run *fn(*args)* in a thread with a timeout.

        Raises TimeoutError if the call does not complete within *timeout* seconds.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, *args)
            return future.result(timeout=timeout)

    def _acquire_semaphore(self, tier: int, timeout: float = 5.0) -> bool:
        """Try to acquire the tier's concurrency semaphore. Returns True on success."""
        sem = {1: self._tier1_semaphore, 2: self._tier2_semaphore}.get(tier)
        if sem is None:
            return True
        acquired = sem.acquire(timeout=timeout)
        if not acquired:
            logger.warning("Tier %d concurrency limit reached, could not acquire semaphore", tier)
        return acquired

    def _release_semaphore(self, tier: int) -> None:
        """Release the tier's concurrency semaphore."""
        sem = {1: self._tier1_semaphore, 2: self._tier2_semaphore}.get(tier)
        if sem is not None:
            sem.release()

    def run_health_check(
        self,
        *,
        local_ollama_host: str = "http://localhost:11434",
        dgx_spark_host: str | None = None,
    ) -> HealthReport:
        """Run hardware health checks and update provider availability.

        - If local GPU VRAM > 90%: logs warning (routing still works, Ollama
          manages its own memory)
        - If DGX Spark unreachable and provider_registry exists: marks dgx
          providers unavailable
        - If DGX Spark comes back: marks dgx providers available again
        """
        report = check_health(
            local_ollama_host=local_ollama_host,
            dgx_spark_host=dgx_spark_host,
        )

        if self.provider_registry is not None:
            for entry in list(self.provider_registry._providers.values()):
                if entry.provider_type == "dgx":
                    if report.dgx_spark_reachable:
                        if not entry.available:
                            self.provider_registry.mark_available(entry.name)
                            logger.info("DGX Spark provider '%s' back online", entry.name)
                    else:
                        if entry.available:
                            self.provider_registry.mark_unavailable(entry.name)

        return report

    @staticmethod
    def detect_injection(text: str) -> str | None:
        """Check for prompt injection patterns. Returns reason if detected, else None."""
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                return f"injection pattern: {pattern.pattern}"
        return None

    def sanitize_input(self, request: str) -> tuple[str, str | None]:
        """Sanitize input: enforce max length and check for injection.

        Returns (sanitized_text, rejection_reason_or_None).
        """
        if len(request) > self.max_input_length:
            return "", f"input exceeds max length ({len(request)} > {self.max_input_length})"
        injection = self.detect_injection(request)
        if injection:
            return "", injection
        return request.strip(), None

    def dispatch(self, request: str) -> DispatchResult:
        """Route *request* through the tier chain."""
        t0 = time.monotonic()

        # Input sanitization — enforce max length and detect injection
        clean, rejection = self.sanitize_input(request)
        if rejection:
            logger.warning("Input rejected: %s", rejection)
            result = DispatchResult(
                tier=0,
                action="rejected",
                target="",
                confidence=1.0,
                safety_flagged=True,
                safety_reason=rejection,
            )
            self._log_routing_decision(result, t0)
            return result

        # Tier 0 — deterministic regex match
        match = self.command_registry.match(clean)
        if match is not None:
            logger.info("Tier 0 match: action=%s target=%s args=%s",
                        match.action, match.target, match.args)
            result = DispatchResult(
                tier=0,
                action=match.action,
                target=match.target,
                args=match.args,
                confidence=match.confidence,
            )
            self._log_routing_decision(result, t0)
            return result

        # Tier 1 — micro LLM classification (with concurrency control)
        tier1_context: dict[str, Any] | None = None
        if self.tier1_model_call is not None and self._acquire_semaphore(1):
            try:
                tier1_result, tier1_context = self._tier1_classify(clean)
            finally:
                self._release_semaphore(1)
            if tier1_result is not None:
                self._log_routing_decision(tier1_result, t0, tier1_context)
                return tier1_result

        # Tier 2 — light LLM reasoning (with concurrency control)
        if self.tier2_model_call is not None and self._acquire_semaphore(2):
            try:
                tier2_result = self._tier2_reason(clean, tier1_context)
            finally:
                self._release_semaphore(2)
            if tier2_result is not None:
                self._log_routing_decision(tier2_result, t0)
                return tier2_result

        # No match at any available tier
        logger.info("No match at any tier for request, escalation needed")
        result = DispatchResult(
            tier=-1,
            action="needs_escalation",
            target="",
            args={},
            confidence=0.0,
        )
        self._log_routing_decision(result, t0)
        return result

    def _log_routing_decision(
        self,
        result: DispatchResult,
        start_time: float,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Log a routing decision to the MetricsCollector."""
        latency_ms = (time.monotonic() - start_time) * 1000
        metrics = get_metrics_collector()
        escalated = result.tier == -1  # needs_escalation
        request_tier = 0  # dispatch always starts at tier 0
        metrics.record_routing_decision(
            chosen_tier=result.tier,
            provider=result.provider,
            escalated=escalated,
            request_tier=request_tier,
            latency_ms=latency_ms,
            quality_score=context.get("confidence") if context else None,
        )

    def _tier1_classify(
        self, request: str,
    ) -> tuple[DispatchResult | None, dict[str, Any] | None]:
        """Run Tier 1 micro classification.

        Returns (DispatchResult, tier1_context) — result is non-None if Tier 1
        can handle the request confidently.  tier1_context is always returned
        for Tier 2 to use.
        """
        from agents.micro_router_agent import MicroRouterAgent

        agent = MicroRouterAgent()
        state: dict[str, Any] = {
            "request_text": request,
            "available_actions": ["execute_graph", "answer_question", "analyze"],
            "available_graphs": ["certification", "dossier", "story", "lab"],
        }

        delta: dict[str, Any] | None = None
        for attempt in range(1 + DEFAULT_MAX_TIER1_RETRIES):
            try:
                delta = self._call_with_timeout(
                    agent.run, (state, self.tier1_model_call), self.tier1_timeout,
                )
                break
            except (concurrent.futures.TimeoutError, TimeoutError):
                logger.warning("Tier 1 classification timed out (attempt %d, %.1fs)",
                               attempt + 1, self.tier1_timeout)
                if attempt >= DEFAULT_MAX_TIER1_RETRIES:
                    logger.info("Tier 1 exhausted retries after timeout, escalating")
                    return None, None
                continue
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("Tier 1 classification failed (attempt %d): %s",
                               attempt + 1, exc)
                if attempt >= DEFAULT_MAX_TIER1_RETRIES:
                    logger.info("Tier 1 exhausted retries, escalating")
                    return None, None
                continue
        else:
            return None, None

        # Safety bypass — if Tier 1 flags the request, return immediately
        if delta.get("safety_flag"):
            reason = delta.get("safety_reason", "flagged by tier1 classifier")
            logger.warning("Tier 1 safety flag: %s", reason)
            result = DispatchResult(
                tier=1,
                action="rejected",
                target="",
                confidence=delta.get("confidence", 1.0),
                model_response=json.dumps(delta),
                safety_flagged=True,
                safety_reason=reason,
            )
            return result, delta

        confidence = delta.get("confidence", 0.0)
        complexity = delta.get("complexity_score", 0.5)
        recommended_tier = delta.get("recommended_tier", 2)

        # Compute composite routing score for escalation decision
        routing_score = compute_routing_score(complexity, confidence)

        # If Tier 1 is confident, recommends itself, and score is low, resolve directly
        if (recommended_tier == 1
                and confidence >= self.confidence_threshold
                and routing_score <= DEFAULT_ROUTING_THRESHOLD):
            logger.info("Tier 1 resolved: action=%s confidence=%.2f",
                        delta.get("action"), confidence)
            result = DispatchResult(
                tier=1,
                action=delta.get("action", ""),
                target=delta.get("target", ""),
                args={"intent": delta.get("intent", "")},
                confidence=confidence,
                model_response=json.dumps(delta),
            )
            return result, delta

        # Escalate — pass context to Tier 2
        logger.info("Tier 1 recommends tier=%d confidence=%.2f, escalating",
                    recommended_tier, confidence)
        return None, delta

    def _tier2_reason(
        self,
        request: str,
        tier1_context: dict[str, Any] | None = None,
    ) -> DispatchResult | None:
        """Run Tier 2 light reasoning.

        Uses the light model (larger context/tokens) with Tier 1 context.
        Returns a DispatchResult if Tier 2 can handle the request,
        or None to escalate to Tier 3.
        """
        # Build prompt with Tier 1 context
        context_section = ""
        if tier1_context:
            context_section = (
                f"\nTier 1 classification context:\n"
                f"  Intent: {tier1_context.get('intent', 'unknown')}\n"
                f"  Complexity: {tier1_context.get('complexity_score', 'unknown')}\n"
                f"  Confidence: {tier1_context.get('confidence', 'unknown')}\n"
                f"  Recommended tier: {tier1_context.get('recommended_tier', 'unknown')}\n"
            )

        system_prompt = (
            "You are a reasoning agent. Given a user request and optional classification context, "
            "provide a structured response with your analysis.\n\n"
            "Output a JSON object with these fields:\n"
            "- reasoning: string, your analysis of the request\n"
            "- action: string, the recommended action\n"
            "- target: string, the target (if applicable)\n"
            "- quality_score: float 0.0-1.0, your confidence in the quality of your response\n"
            "- reasoning_depth: integer 1-5, how deep the reasoning needed to be\n"
            "- escalate: boolean, true if this needs a more capable model\n\n"
            "Output valid JSON only."
        )
        user_message = f"Request: {request}{context_section}"

        try:
            raw_response = self._call_with_timeout(
                self.tier2_model_call, (system_prompt, user_message), self.tier2_timeout,
            )
            data = json.loads(raw_response)
        except (concurrent.futures.TimeoutError, TimeoutError):
            logger.warning("Tier 2 reasoning timed out (%.1fs), escalating", self.tier2_timeout)
            return None
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Tier 2 reasoning failed to parse: %s", exc)
            return None

        quality_score = float(data.get("quality_score", 0.0))
        escalate = bool(data.get("escalate", False))
        reasoning_depth = int(data.get("reasoning_depth", 1))

        # If quality is good and no escalation requested, return result
        if quality_score >= self.quality_threshold and not escalate:
            logger.info("Tier 2 resolved: quality=%.2f depth=%d",
                        quality_score, reasoning_depth)
            return DispatchResult(
                tier=2,
                action=data.get("action", ""),
                target=data.get("target", ""),
                args={"reasoning": data.get("reasoning", "")},
                confidence=quality_score,
                model_response=raw_response,
            )

        # Escalate to Tier 3
        logger.info("Tier 2 escalating: quality=%.2f depth=%d escalate=%s",
                    quality_score, reasoning_depth, escalate)
        return None
