"""QA validator agent — enforces structural integrity and grounding constraints.

Supports global rules plus domain-specific gates for cert, dossier, and lab.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class QAValidatorInput(BaseModel):
    claims: list[dict]
    metrics: list[dict]
    metric_points: list[dict]
    doc_ids: list[str]
    segment_ids: list[str]
    snapshot_id: str | None = None
    delta_id: str | None = None


class QAValidatorOutput(BaseModel):
    gate_status: str  # PASS or FAIL
    violations: list[dict]


class QAValidatorAgent(BaseAgent):
    AGENT_ID = "qa_validator"
    VERSION = "0.2.0"
    SYSTEM_PROMPT = "You are a quality assurance validator."
    USER_TEMPLATE = "{_qa_bypass}"
    INPUT_SCHEMA = QAValidatorInput
    OUTPUT_SCHEMA = QAValidatorOutput
    POLICY = AgentPolicy(allowed_local_models=["local"], max_tokens=2048, preferred_tier=0)

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """QA validation is deterministic — no LLM call needed."""
        violations = self._check_all(state)
        gate_status = "FAIL" if violations else "PASS"
        result = {"gate_status": gate_status, "violations": violations}
        self.validate(result)
        return result

    def parse(self, response: str) -> dict[str, Any]:
        return json.loads(response)

    def validate(self, output: dict[str, Any]) -> None:
        if output.get("gate_status") not in ("PASS", "FAIL"):
            raise ValueError("gate_status must be PASS or FAIL")
        if not isinstance(output.get("violations"), list):
            raise ValueError("violations must be a list")

    def _check_all(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        # Global rules
        violations.extend(self._check_global_rules(state))

        # Domain-specific rules
        scope_type = state.get("scope_type", "")
        if scope_type == "cert":
            violations.extend(self._check_cert_rules(state))
        elif scope_type == "topic":
            violations.extend(self._check_dossier_rules(state))
        elif scope_type == "lab":
            violations.extend(self._check_lab_rules(state))
        elif scope_type == "story":
            violations.extend(self._check_story_rules(state))

        return violations

    def _check_global_rules(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Global rules that apply to all scope types."""
        violations: list[dict[str, Any]] = []
        scope_type = state.get("scope_type", "")
        known_doc_ids = set(state.get("doc_ids", []))
        known_segment_ids = set(state.get("segment_ids", []))

        # Story scope: citation rules are relaxed — uncited claims become
        # beliefs/legends that may seed future plots.  Skip citation checks.
        if scope_type != "story":
            # Rule 1: No claim without citations
            for claim in state.get("claims", []):
                citations = claim.get("citations", claim.get("citations_json", []))
                if not citations:
                    violations.append({
                        "rule": "claim_requires_citations",
                        "claim_id": claim.get("claim_id"),
                        "message": "Claim has no citations",
                    })
                # Rule 2: Every citation must resolve to a known doc+segment
                for cit in citations:
                    if cit.get("doc_id") not in known_doc_ids:
                        violations.append({
                            "rule": "citation_doc_resolves",
                            "claim_id": claim.get("claim_id"),
                            "doc_id": cit.get("doc_id"),
                            "message": "Citation references unknown doc_id",
                        })
                    if cit.get("segment_id") not in known_segment_ids:
                        violations.append({
                            "rule": "citation_segment_resolves",
                            "claim_id": claim.get("claim_id"),
                            "segment_id": cit.get("segment_id"),
                            "message": "Citation references unknown segment_id",
                        })

        # Rule 3: Metric points must include unit + dimensions
        metric_lookup = {m.get("metric_id"): m for m in state.get("metrics", [])}
        for pt in state.get("metric_points", []):
            metric = metric_lookup.get(pt.get("metric_id"))
            if metric is None:
                violations.append({
                    "rule": "metric_point_has_metric",
                    "point_id": pt.get("point_id"),
                    "message": "Metric point references unknown metric_id",
                })
            elif not metric.get("unit"):
                violations.append({
                    "rule": "metric_has_unit",
                    "metric_id": metric.get("metric_id"),
                    "message": "Metric missing unit",
                })

        # Rule 4: No publish without snapshot + delta
        if state.get("_check_publish"):
            if not state.get("snapshot_id"):
                violations.append({
                    "rule": "publish_requires_snapshot",
                    "message": "Cannot publish without a snapshot",
                })
            if not state.get("delta_id"):
                violations.append({
                    "rule": "publish_requires_delta",
                    "message": "Cannot publish without a delta",
                })

        return violations

    # ------------------------------------------------------------------
    # Certification-specific rules
    # ------------------------------------------------------------------

    def _check_cert_rules(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Every objective must have at least one module and min questions proportional to weight."""
        violations: list[dict[str, Any]] = []
        objectives = state.get("objectives", [])
        modules = state.get("modules", [])
        questions = state.get("questions", [])

        if not objectives:
            return violations

        # Build lookups
        modules_by_obj = {}
        for m in modules:
            obj_id = m.get("objective_id", "")
            modules_by_obj.setdefault(obj_id, []).append(m)

        questions_by_obj = {}
        for q in questions:
            obj_id = q.get("objective_id", "")
            questions_by_obj.setdefault(obj_id, []).append(q)

        for obj in objectives:
            obj_id = obj.get("objective_id", "")
            weight = obj.get("weight", 1.0)

            # Must have at least one module
            obj_modules = modules_by_obj.get(obj_id, [])
            if not obj_modules:
                violations.append({
                    "rule": "cert_objective_has_module",
                    "objective_id": obj_id,
                    "message": f"Objective '{obj_id}' has no lesson modules",
                })

            # Minimum question count proportional to weight
            min_questions = max(1, math.ceil(weight * 2))
            obj_questions = questions_by_obj.get(obj_id, [])
            if len(obj_questions) < min_questions:
                violations.append({
                    "rule": "cert_objective_min_questions",
                    "objective_id": obj_id,
                    "expected": min_questions,
                    "actual": len(obj_questions),
                    "message": (
                        f"Objective '{obj_id}' has {len(obj_questions)} questions, "
                        f"needs at least {min_questions} (weight={weight})"
                    ),
                })

        return violations

    # ------------------------------------------------------------------
    # Dossier-specific rules
    # ------------------------------------------------------------------

    def _check_dossier_rules(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Contradictions must be surfaced; disputed claims must have status='disputed'."""
        violations: list[dict[str, Any]] = []
        contradictions = state.get("contradictions", [])
        claims = state.get("claims", [])

        if not contradictions:
            return violations

        # Build claim lookup
        claim_lookup = {c.get("claim_id"): c for c in claims}

        # Collect all claim IDs referenced in contradictions
        disputed_ids: set[str] = set()
        for ctr in contradictions:
            for key in ("claim_a_id", "claim_b_id"):
                cid = ctr.get(key, "")
                if cid:
                    disputed_ids.add(cid)

            # Each contradiction must have a reason (structural field, not freeform)
            if not ctr.get("reason"):
                violations.append({
                    "rule": "dossier_contradiction_has_reason",
                    "claim_a_id": ctr.get("claim_a_id"),
                    "claim_b_id": ctr.get("claim_b_id"),
                    "message": "Contradiction missing structured reason field",
                })

        # Disputed claims must have status='disputed'
        for cid in disputed_ids:
            claim = claim_lookup.get(cid)
            if claim and claim.get("status") != "disputed":
                violations.append({
                    "rule": "dossier_disputed_claim_status",
                    "claim_id": cid,
                    "current_status": claim.get("status"),
                    "message": f"Claim '{cid}' is in a contradiction but status is '{claim.get('status')}', expected 'disputed'",
                })

        return violations

    # ------------------------------------------------------------------
    # Lab-specific rules
    # ------------------------------------------------------------------

    def _check_lab_rules(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Results must tie to model+hw spec; scoring produces required components."""
        violations: list[dict[str, Any]] = []

        synthesis = state.get("synthesis", {})
        models = state.get("models", [])
        hw_spec = state.get("hw_spec", {})

        # Must have hardware spec
        if not hw_spec:
            violations.append({
                "rule": "lab_has_hw_spec",
                "message": "Lab run missing hardware specification",
            })

        # Must have at least one model
        if not models:
            violations.append({
                "rule": "lab_has_models",
                "message": "Lab run has no models to test",
            })

        # If scores exist, every tested model should have a score
        scores = synthesis.get("scores", {})
        if scores:
            model_ids = {m.get("model_id") for m in models}
            for mid in model_ids:
                if mid and mid not in scores:
                    violations.append({
                        "rule": "lab_model_has_score",
                        "model_id": mid,
                        "message": f"Model '{mid}' was tested but has no score",
                    })

        # Metrics must be present if synthesis mentions them
        metrics = state.get("metrics", [])
        if synthesis.get("metrics_summary") and not metrics:
            violations.append({
                "rule": "lab_metrics_present",
                "message": "Synthesis references metrics but none are present",
            })

        return violations

    # ------------------------------------------------------------------
    # Story-specific rules
    # ------------------------------------------------------------------

    def _check_story_rules(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Story-domain QA gates — intentionally lenient.

        Story generation with small local models (8B) cannot reliably satisfy
        strict structural rules.  Only audience compliance FAIL is a hard
        violation.  Everything else is logged as a warning but does not block
        the pipeline.  Uncited claims become beliefs/legends — future plot hooks.
        """
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        # Soft: Character consistency — log unknown POV characters
        characters = state.get("characters", [])
        char_names_lower = {c.get("name", "").lower() for c in characters}
        scene_plans = state.get("scene_plans", [])
        for sp in scene_plans:
            pov = sp.get("pov_character", "")
            if pov and pov.lower() not in char_names_lower:
                warnings.append({
                    "rule": "story_pov_character_exists",
                    "scene_id": sp.get("scene_id"),
                    "pov_character": pov,
                    "message": f"POV character '{pov}' not found in character list (soft warning)",
                })

        # Soft: Thread tracking
        selected_threads = state.get("selected_threads", [])
        new_threads = state.get("new_threads", [])
        if not selected_threads and not new_threads:
            warnings.append({
                "rule": "story_thread_advanced",
                "message": "No thread was advanced or created in this episode (soft warning)",
            })

        # Hard: Audience compliance — this is a safety gate
        compliance_status = state.get("compliance_status", "")
        if compliance_status == "FAIL":
            violations.append({
                "rule": "story_audience_compliance",
                "message": "Audience compliance check failed",
                "violations": state.get("compliance_violations", []),
            })

        # Soft: Structural integrity — at least 1 scene required
        scenes = state.get("scenes", [])
        if len(scenes) < 1:
            violations.append({
                "rule": "story_min_scenes",
                "actual": len(scenes),
                "message": "Episode has no scenes",
            })
        elif len(scenes) < 2:
            warnings.append({
                "rule": "story_min_scenes",
                "actual": len(scenes),
                "message": f"Episode has {len(scenes)} scene (2+ preferred, soft warning)",
            })

        # Store warnings in state for observability, but don't fail on them
        if warnings:
            existing = state.setdefault("_qa_warnings", [])
            existing.extend(warnings)
            logger.info("Story QA: %d soft warning(s), %d hard violation(s)", len(warnings), len(violations))

        return violations

        return violations
