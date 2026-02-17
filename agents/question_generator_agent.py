"""Question generator agent — generates question bank per objective with grounding."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent


class QuestionGeneratorInput(BaseModel):
    objectives: list[dict]
    claims: list[dict]
    modules: list[dict] = []


class QuestionGeneratorOutput(BaseModel):
    questions: list[dict]


class QuestionGeneratorAgent(BaseAgent):
    AGENT_ID = "question_generator"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = (
        "You are a question generation agent. For each certification objective, generate "
        "assessment questions. Question count should be proportional to the objective's weight.\n\n"
        "Supported question types (qtype): multiple_choice, true_false, short_answer, scenario.\n\n"
        "Every question must link to at least one grounding claim_id to ensure factual basis. "
        "Output valid JSON only."
    )
    USER_TEMPLATE = (
        "Generate questions for these objectives:\n{objectives}\n\n"
        "Available claims (you MUST use claim_id values from this list in grounding_claim_ids):\n{claims}\n\n"
        "Lesson modules for context:\n{modules}\n\n"
        "Return JSON with this exact schema:\n"
        '{{"questions": [{{"question_id": str, "objective_id": str, "qtype": str, '
        '"content_json": {{"question": str, "options": [...], "correct_answer": str, "explanation": str}}, '
        '"grounding_claim_ids": [str]}}]}}\n\n'
        "IMPORTANT: Every question MUST have a non-empty \"grounding_claim_ids\" array with at least one claim_id from the available claims.\n\n"
        "Example of ONE valid question:\n"
        '{{"question_id": "q-1", "objective_id": "obj-1", "qtype": "multiple_choice", '
        '"content_json": {{"question": "What is X?", "options": ["A", "B"], "correct_answer": "A", "explanation": "Because..."}}, '
        '"grounding_claim_ids": ["c1"]}}'
    )
    INPUT_SCHEMA = QuestionGeneratorInput
    OUTPUT_SCHEMA = QuestionGeneratorOutput
    POLICY = AgentPolicy(
        allowed_local_models=["local"],
        allowed_frontier_models=["frontier"],
        max_tokens=8192,
        confidence_threshold=0.7,
    )

    VALID_QTYPES = {"multiple_choice", "true_false", "short_answer", "scenario"}

    def parse(self, response: str) -> dict[str, Any]:
        data = json.loads(response)
        return {"questions": data.get("questions", [])}

    def validate(self, output: dict[str, Any]) -> None:
        questions = output.get("questions")
        if not isinstance(questions, list):
            raise ValueError("questions must be a list")
        for q in questions:
            if not q.get("question_id"):
                raise ValueError("Each question must have a question_id")
            if not q.get("objective_id"):
                raise ValueError(f"Question {q.get('question_id')} missing objective_id")
            if q.get("qtype") not in self.VALID_QTYPES:
                raise ValueError(
                    f"Question {q.get('question_id')} invalid qtype '{q.get('qtype')}', "
                    f"must be one of {self.VALID_QTYPES}"
                )
            content = q.get("content_json")
            if not isinstance(content, dict) or not content.get("question"):
                raise ValueError(f"Question {q.get('question_id')} must have content_json with 'question' field")
            grounding = q.get("grounding_claim_ids", [])
            if not grounding:
                raise ValueError(
                    f"Question {q.get('question_id')} has no grounding_claim_ids — "
                    "every question requires at least one"
                )
