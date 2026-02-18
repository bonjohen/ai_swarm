"""Base agent class — all agents inherit from this."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


def repair_json(text: str) -> str:
    """Fix common JSON errors produced by LLMs via single-pass state machine.

    Handles:
    - Unescaped double quotes inside string values (e.g. dialogue)
    - Literal newlines / tabs / carriage returns inside strings
    A quote inside a string is considered *structural* (closes the string)
    only if the next non-whitespace character is one of  : , } ]
    Otherwise it is treated as content and escaped.
    """
    _log = logging.getLogger(__name__)
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError as e:
        _log.debug(
            "repair_json: error at pos=%d len=%d, context=...%r...",
            e.pos, len(text), text[max(0, e.pos - 40):e.pos + 40],
        )

    # --- Pass 1: state-machine fix for unescaped quotes and newlines ---
    out: list[str] = []
    i = 0
    in_string = False
    n = len(text)

    while i < n:
        ch = text[i]

        # Inside a string: handle escapes and special chars
        if in_string:
            if ch == '\\' and i + 1 < n:
                # Already-escaped char — pass through both
                out.append(ch)
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                # Decide: structural close or content quote?
                j = i + 1
                while j < n and text[j] in ' \t\r\n':
                    j += 1
                if j >= n or text[j] in ':,}]':
                    # Structural: closes the string
                    in_string = False
                    out.append(ch)
                else:
                    # Content quote inside prose — escape it
                    out.append('\\"')
                i += 1
                continue
            if ch == '\n':
                out.append('\\n')
                i += 1
                continue
            if ch == '\r':
                out.append('\\r')
                i += 1
                continue
            if ch == '\t':
                out.append('\\t')
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        # Outside a string
        if ch == '"':
            in_string = True
        out.append(ch)
        i += 1

    repaired = ''.join(out)

    # --- Pass 2: close truncated JSON (missing brackets at EOF) ---
    try:
        json.loads(repaired)
        return repaired
    except json.JSONDecodeError:
        pass

    # If still in a string, close it
    if in_string:
        repaired += '"'

    # Count open brackets and close any that are missing
    stack: list[str] = []
    s_in = False
    k = 0
    rn = len(repaired)
    while k < rn:
        c = repaired[k]
        if c == '\\' and s_in:
            k += 2
            continue
        if c == '"':
            s_in = not s_in
        elif not s_in:
            if c in ('{', '['):
                stack.append('}' if c == '{' else ']')
            elif c in ('}', ']') and stack:
                stack.pop()
        k += 1

    # Strip trailing comma before adding closers
    stripped = repaired.rstrip()
    if stripped.endswith(','):
        stripped = stripped[:-1]
    for closer in reversed(stack):
        stripped += closer

    return stripped


def extract_json(text: str) -> str:
    """Extract JSON from an LLM response that may contain markdown fences or prose.

    Handles:
    - Clean JSON (returned as-is after strip)
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Preamble/postamble text around a JSON object or array
    """
    stripped = text.strip()

    # 1. Strip markdown code fences
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 2. Find outermost { ... } or [ ... ] (whichever appears first)
    pairs = [("{", "}"), ("[", "]")]
    brace_pos = stripped.find("{")
    bracket_pos = stripped.find("[")
    if bracket_pos != -1 and (brace_pos == -1 or bracket_pos < brace_pos):
        pairs = [("[", "]"), ("{", "}")]
    for open_ch, close_ch in pairs:
        start = stripped.find(open_ch)
        if start == -1:
            continue
        end = stripped.rfind(close_ch)
        if end > start:
            return stripped[start:end + 1]

    # 3. Fall through — return stripped text and let json.loads give the error
    return stripped


class AgentPolicy(BaseModel):
    """Routing + budget + constraint policy for an agent."""
    allowed_local_models: list[str] = []
    allowed_frontier_models: list[str] = []
    max_tokens: int = 4096
    confidence_threshold: float = 0.7
    required_citations: bool = False
    preferred_tier: int = 2
    min_tier: int = 1
    max_tokens_by_tier: dict[int, int] = {}


class BaseAgent(ABC):
    """Abstract base for all swarm agents.

    Subclasses must define the class-level attributes and implement
    parse() and validate().
    """

    # --- required class attributes (set by subclass) ---
    AGENT_ID: str
    VERSION: str
    SYSTEM_PROMPT: str
    USER_TEMPLATE: str  # Python format-string using state keys
    INPUT_SCHEMA: type[BaseModel]
    OUTPUT_SCHEMA: type[BaseModel]
    POLICY: AgentPolicy

    # --- runtime contract ---

    def build_prompt(self, state: dict[str, Any]) -> tuple[str, str]:
        """Return (system_prompt, user_message) from current state."""
        safe = {k: (str(v) if not isinstance(v, str) else v) for k, v in state.items()}
        return self.SYSTEM_PROMPT, self.USER_TEMPLATE.format_map(
            type("_SafeDict", (dict,), {"__missing__": lambda s, k: f"{{{k}}}"})(**safe)
        )

    @abstractmethod
    def parse(self, response: str) -> dict[str, Any]:
        """Parse raw model response into a delta_state dict."""
        ...

    @abstractmethod
    def validate(self, output: dict[str, Any]) -> None:
        """Validate parsed output. Raise on failure."""
        ...

    MAX_REPAIR_ATTEMPTS: int = 2

    def _try_json_recovery(
        self, raw_text: str, model_call: Any = None,
    ) -> dict[str, Any] | None:
        """Attempt to recover structured JSON from malformed output.

        Uses the *same* model that produced the output (via ``model_call``)
        so it has full context and capability to repair its own response.
        Falls back to the small 1.5b recovery model when no model_call is
        provided (e.g. in tests).

        Returns the parsed+validated dict on success, or None on failure.
        """
        _log = logging.getLogger(__name__)

        # Build a concise schema description from OUTPUT_SCHEMA
        schema_json = self.OUTPUT_SCHEMA.model_json_schema()

        recovery_system = (
            "You are a JSON repair assistant. "
            "The user will provide text that was meant to be valid JSON but has syntax errors. "
            "Also provided is the expected JSON schema. "
            "Reconstruct ONLY valid JSON matching the schema from the data in the text. "
            "Preserve all content — do not summarise or omit fields. "
            "Return the JSON object only, no commentary."
        )
        recovery_user = (
            f"Expected JSON schema:\n{schema_json}\n\n"
            f"Malformed text to repair:\n{raw_text}\n\n"
            f"Return valid JSON only."
        )

        # Prefer same model; fall back to 1.5b recovery adapter
        call = model_call
        label = "same-model"
        if call is None:
            try:
                from core.adapters import make_json_recovery_adapter
                adapter = make_json_recovery_adapter()
                call = adapter.call
                label = "1.5b"
            except ImportError:
                return None

        try:
            recovered = call(recovery_system, recovery_user)
            delta_state = self.parse(extract_json(recovered))
            self.validate(delta_state)
            _log.info(
                "Agent %s: JSON recovery succeeded via %s",
                self.AGENT_ID, label,
            )
            return delta_state
        except Exception as exc:
            _log.warning(
                "Agent %s: JSON recovery via %s failed: %s",
                self.AGENT_ID, label, exc,
            )
            return None

    def run(self, state: dict[str, Any], model_call: Any = None) -> dict[str, Any]:
        """Execute the agent: build prompt, call model, parse, validate.

        On parse/validation failure:
        1. Try JSON recovery via the 1.5b model (fast structured extraction).
        2. If recovery fails, send the error back to the original model as a
           repair prompt and retry up to MAX_REPAIR_ATTEMPTS times.

        model_call: a callable(system_prompt, user_message) -> str.
        Returns delta_state to be merged into run state.
        """
        _log = logging.getLogger(__name__)
        system_prompt, user_message = self.build_prompt(state)
        if model_call is None:
            raise RuntimeError("model_call must be provided")
        last_error: Exception | None = None
        raw_response = model_call(system_prompt, user_message)

        for attempt in range(1 + self.MAX_REPAIR_ATTEMPTS):
            try:
                delta_state = self.parse(extract_json(raw_response))
                self.validate(delta_state)
                return delta_state
            except (ValueError, KeyError, TypeError) as exc:
                last_error = exc

                # First failure: try programmatic repair, then LLM recovery
                if attempt == 0:
                    # Step 1: programmatic fix for common escaping errors
                    try:
                        extracted = extract_json(raw_response)
                        repaired = repair_json(extracted)
                        changed = repaired != extracted
                        _log.info(
                            "Agent %s: programmatic repair %s text (len %d→%d)",
                            self.AGENT_ID,
                            "changed" if changed else "did NOT change",
                            len(extracted), len(repaired),
                        )
                        delta_state = self.parse(repaired)
                        self.validate(delta_state)
                        _log.info(
                            "Agent %s: programmatic JSON repair succeeded",
                            self.AGENT_ID,
                        )
                        return delta_state
                    except (ValueError, KeyError, TypeError) as repair_exc:
                        _log.warning(
                            "Agent %s: programmatic repair failed: %s",
                            self.AGENT_ID, repair_exc,
                        )

                    # Step 2: LLM-based recovery via same model + schema
                    _log.info(
                        "Agent %s: parse failed, attempting JSON recovery — %s",
                        self.AGENT_ID, exc,
                    )
                    recovered = self._try_json_recovery(raw_response, model_call)
                    if recovered is not None:
                        return recovered

                if attempt >= self.MAX_REPAIR_ATTEMPTS:
                    break
                _log.warning(
                    "Agent %s parse/validate failed (attempt %d/%d): %s — sending repair prompt",
                    self.AGENT_ID, attempt + 1, self.MAX_REPAIR_ATTEMPTS + 1, exc,
                )
                repair_prompt = (
                    f"Your previous JSON response had an error:\n{exc}\n\n"
                    f"Original request:\n{user_message}\n\n"
                    "Please fix the error and return valid JSON only."
                )
                raw_response = model_call(system_prompt, repair_prompt)

        raise last_error  # type: ignore[misc]
