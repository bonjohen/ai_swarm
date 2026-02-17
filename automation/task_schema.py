"""Task file schema — dataclasses and parser for the markdown task format.

Task files use markdown headers for metadata and ``## SECTION`` blocks
for content.  This module parses them into typed dataclasses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

MODES = {"FAST", "BALANCED", "PREMIUM"}
TASK_TYPES = {"ARCHITECTURE", "REFACTOR", "ANALYSIS", "DESIGN", "REVIEW"}
PRIORITIES = {"LOW", "MEDIUM", "HIGH"}
OUTPUT_FORMATS = {"MARKDOWN", "JSON", "TEXT"}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskHeader:
    """Metadata parsed from the ``# KEY: VALUE`` lines at the top of a task file."""
    task_id: str
    mode: str
    task_type: str
    priority: str
    output_format: str
    created_at: str
    parent_task: str | None = None


@dataclass
class TaskFile:
    """Full parsed task file: header metadata + body sections."""
    header: TaskHeader
    context: str
    constraints: str
    deliverable: str
    success_criteria: str


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^#\s+(\w+):\s*(.+)$")
_SECTION_RE = re.compile(r"^##\s+(\w+(?:\s+\w+)*)$")


def parse_task_file(path: str | Path) -> TaskFile:
    """Parse a markdown task file into a :class:`TaskFile`.

    Raises ``ValueError`` for missing required headers or sections.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # --- Parse headers ---
    headers: dict[str, str] = {}
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            headers[m.group(1).upper()] = m.group(2).strip()

    missing_headers = []
    for key in ("TASK_ID", "MODE", "TASK_TYPE", "PRIORITY", "OUTPUT_FORMAT", "CREATED_AT"):
        if key not in headers:
            missing_headers.append(key)
    if missing_headers:
        raise ValueError(f"Missing required headers: {', '.join(missing_headers)}")

    header = TaskHeader(
        task_id=headers["TASK_ID"],
        mode=headers["MODE"],
        task_type=headers["TASK_TYPE"],
        priority=headers["PRIORITY"],
        output_format=headers["OUTPUT_FORMAT"],
        created_at=headers["CREATED_AT"],
        parent_task=headers.get("PARENT_TASK"),
    )

    # --- Parse sections ---
    sections = _parse_sections(lines)

    missing_sections = []
    for name in ("CONTEXT", "CONSTRAINTS", "DELIVERABLE", "SUCCESS_CRITERIA"):
        # Normalise: section headings use space, keys use underscore
        key = name.replace("_", " ")
        if key not in sections and name not in sections:
            missing_sections.append(name)
    if missing_sections:
        raise ValueError(f"Missing required sections: {', '.join(missing_sections)}")

    def _get(name: str) -> str:
        key = name.replace("_", " ")
        return sections.get(key, sections.get(name, "")).strip()

    return TaskFile(
        header=header,
        context=_get("CONTEXT"),
        constraints=_get("CONSTRAINTS"),
        deliverable=_get("DELIVERABLE"),
        success_criteria=_get("SUCCESS_CRITERIA"),
    )


def _parse_sections(lines: list[str]) -> dict[str, str]:
    """Extract ``## SECTION`` blocks into a dict mapping name → body text."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    for line in lines:
        m = _SECTION_RE.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf)
            current = m.group(1).upper()
            buf = []
        elif current is not None:
            buf.append(line)

    if current is not None:
        sections[current] = "\n".join(buf)

    return sections


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def generate_task_id(tasks_dir: str | Path) -> str:
    """Generate the next ``YYYY-MM-DD-###`` task ID.

    Scans *tasks_dir* for existing files matching today's date prefix and
    increments the sequence number.
    """
    tasks_dir = Path(tasks_dir)
    today = date.today().isoformat()  # e.g. "2026-02-17"
    prefix = today + "-"

    existing: list[int] = []
    if tasks_dir.exists():
        for p in tasks_dir.iterdir():
            name = p.stem  # filename without extension
            if name.startswith(prefix):
                seq_str = name[len(prefix):]
                if seq_str.isdigit():
                    existing.append(int(seq_str))

    next_seq = max(existing, default=0) + 1
    return f"{today}-{next_seq:03d}"
