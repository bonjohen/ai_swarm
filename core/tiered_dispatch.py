"""Tiered dispatcher — routes requests through Tier 0 → 1 → 2 → 3.

Tier 0: deterministic regex/command matching (no LLM).
Tier 1: micro LLM classification via ``MicroRouterAgent``.
Tier 2: light LLM reasoning (larger context, more tokens).
Tier 3: reserved for frontier provider pool (R4).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from core.command_registry import CommandRegistry
from core.routing import ModelRouter, compute_routing_score, DEFAULT_ROUTING_THRESHOLD
from core.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)

# Type alias matching core.routing.ModelCallable
ModelCallable = Callable[[str, str], str]

# Thresholds
DEFAULT_CONFIDENCE_THRESHOLD = 0.75
DEFAULT_QUALITY_THRESHOLD = 0.70
DEFAULT_MAX_TIER1_RETRIES = 2


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
    ) -> None:
        self.command_registry = command_registry
        self.model_router = model_router
        self.provider_registry = provider_registry
        self.tier1_model_call = tier1_model_call
        self.tier2_model_call = tier2_model_call
        self.confidence_threshold = confidence_threshold
        self.quality_threshold = quality_threshold

    def dispatch(self, request: str) -> DispatchResult:
        """Route *request* through the tier chain."""
        # Tier 0 — deterministic regex match
        match = self.command_registry.match(request)
        if match is not None:
            logger.info("Tier 0 match: action=%s target=%s args=%s",
                        match.action, match.target, match.args)
            return DispatchResult(
                tier=0,
                action=match.action,
                target=match.target,
                args=match.args,
                confidence=match.confidence,
            )

        # Tier 1 — micro LLM classification
        tier1_context: dict[str, Any] | None = None
        if self.tier1_model_call is not None:
            tier1_result, tier1_context = self._tier1_classify(request)
            if tier1_result is not None:
                return tier1_result

        # Tier 2 — light LLM reasoning
        if self.tier2_model_call is not None:
            tier2_result = self._tier2_reason(request, tier1_context)
            if tier2_result is not None:
                return tier2_result

        # No match at any available tier
        logger.info("No match at any tier for request, escalation needed")
        return DispatchResult(
            tier=-1,
            action="needs_escalation",
            target="",
            args={},
            confidence=0.0,
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
                delta = agent.run(state, model_call=self.tier1_model_call)
                break
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("Tier 1 classification failed (attempt %d): %s",
                               attempt + 1, exc)
                if attempt >= DEFAULT_MAX_TIER1_RETRIES:
                    logger.info("Tier 1 exhausted retries, escalating")
                    return None, None
                continue
        else:
            return None, None

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
            raw_response = self.tier2_model_call(system_prompt, user_message)
            data = json.loads(raw_response)
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
