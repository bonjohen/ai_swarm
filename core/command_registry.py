"""Command registry — deterministic regex-based request dispatch (Tier 0).

Maps slash commands and JSON payloads to actions without any LLM call.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CommandPattern:
    """A registered command pattern."""

    pattern: str  # regex with named groups
    action: str
    target: str
    description: str
    _compiled: re.Pattern[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._compiled = re.compile(self.pattern)


@dataclass
class CommandMatch:
    """Result of a successful command match."""

    action: str
    target: str
    args: dict[str, str]
    confidence: float = 1.0  # always 1.0 for regex matches


class CommandRegistry:
    """Registry of deterministic command patterns.

    Matches input text against registered regex patterns and returns
    a ``CommandMatch`` on the first hit, or ``None`` if nothing matches.
    Also handles JSON payloads with a ``"command"`` key.
    """

    def __init__(self) -> None:
        self._patterns: list[CommandPattern] = []

    def register(self, pattern: CommandPattern) -> None:
        """Add a command pattern to the registry."""
        self._patterns.append(pattern)

    def match(self, text: str) -> CommandMatch | None:
        """Try to match *text* against all registered patterns.

        Returns the first ``CommandMatch`` found, or ``None``.
        Also checks for JSON payloads with a ``"command"`` key.
        """
        text = text.strip()

        # JSON payload detection
        json_match = self._try_json(text)
        if json_match is not None:
            return json_match

        # Regex matching
        for cp in self._patterns:
            m = cp._compiled.match(text)
            if m:
                return CommandMatch(
                    action=cp.action,
                    target=cp.target,
                    args=m.groupdict(),
                )
        return None

    @property
    def patterns(self) -> list[CommandPattern]:
        return list(self._patterns)

    def _try_json(self, text: str) -> CommandMatch | None:
        """Detect JSON payloads with a ``"command"`` key."""
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(data, dict) or "command" not in data:
            return None

        command = data["command"]
        # Re-match the command value against patterns
        for cp in self._patterns:
            m = cp._compiled.match(command)
            if m:
                args = m.groupdict()
                # Merge any extra JSON keys into args
                for k, v in data.items():
                    if k != "command" and k not in args:
                        args[k] = v
                return CommandMatch(
                    action=cp.action,
                    target=cp.target,
                    args=args,
                )

        # No pattern match but has a command key — return generic action
        return CommandMatch(
            action="unknown_command",
            target="",
            args=data,
        )


def register_defaults(registry: CommandRegistry) -> None:
    """Register the default slash command patterns."""
    registry.register(CommandPattern(
        pattern=r"^/cert\s+(?P<cert_id>\S+)$",
        action="execute_graph",
        target="run_cert.py",
        description="Run the certification graph",
    ))
    registry.register(CommandPattern(
        pattern=r"^/dossier\s+(?P<topic_id>\S+)$",
        action="execute_graph",
        target="run_dossier.py",
        description="Run the dossier graph",
    ))
    registry.register(CommandPattern(
        pattern=r"^/story\s+(?P<world_id>\S+)$",
        action="execute_graph",
        target="run_story.py",
        description="Run the story graph",
    ))
    registry.register(CommandPattern(
        pattern=r"^/lab\s+(?P<suite_id>\S+)$",
        action="execute_graph",
        target="run_lab.py",
        description="Run the lab graph",
    ))
    registry.register(CommandPattern(
        pattern=r"^/status$",
        action="show_status",
        target="",
        description="Show system status",
    ))
    registry.register(CommandPattern(
        pattern=r"^/help$",
        action="show_help",
        target="",
        description="Show help information",
    ))
