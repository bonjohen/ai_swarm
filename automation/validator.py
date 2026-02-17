"""Validator — structural validation for task and result files.

Returns a list of :class:`ValidationError` instances rather than raising,
so callers can report all problems at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from automation.task_schema import (
    MODES,
    OUTPUT_FORMATS,
    PRIORITIES,
    TASK_TYPES,
    _HEADER_RE,
    _SECTION_RE,
    _parse_sections,
)

# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

SEVERITIES = {"error", "warning"}


@dataclass
class ValidationError:
    """A single validation finding."""
    field: str
    message: str
    severity: str = "error"


# ---------------------------------------------------------------------------
# Result file allowed values
# ---------------------------------------------------------------------------

RESULT_STATUSES = {"COMPLETE", "FAILED"}
QUALITY_LEVELS = {"LOW", "MEDIUM", "HIGH"}

# ---------------------------------------------------------------------------
# Task validation
# ---------------------------------------------------------------------------


def validate_task(path: str | Path) -> list[ValidationError]:
    """Validate a task markdown file.

    Checks:
    - TASK_ID present and matches filename
    - All required headers present
    - All required sections present
    - Enum values in allowed sets
    - CREATED_AT is valid ISO-8601
    """
    path = Path(path)
    errors: list[ValidationError] = []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [ValidationError("file", f"Cannot read file: {exc}")]

    lines = text.splitlines()

    # --- Parse headers ---
    headers: dict[str, str] = {}
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            headers[m.group(1).upper()] = m.group(2).strip()

    # Required headers
    required_headers = ["TASK_ID", "MODE", "TASK_TYPE", "PRIORITY", "OUTPUT_FORMAT", "CREATED_AT"]
    for key in required_headers:
        if key not in headers:
            errors.append(ValidationError(key, f"Missing required header: {key}"))

    # TASK_ID vs filename
    if "TASK_ID" in headers:
        expected_stem = headers["TASK_ID"]
        if path.stem != expected_stem:
            errors.append(ValidationError(
                "TASK_ID",
                f"TASK_ID {expected_stem!r} does not match filename {path.stem!r}",
            ))

    # Enum checks
    _check_enum(errors, headers, "MODE", MODES)
    _check_enum(errors, headers, "TASK_TYPE", TASK_TYPES)
    _check_enum(errors, headers, "PRIORITY", PRIORITIES)
    _check_enum(errors, headers, "OUTPUT_FORMAT", OUTPUT_FORMATS)

    # ISO-8601
    if "CREATED_AT" in headers:
        _check_iso8601(errors, "CREATED_AT", headers["CREATED_AT"])

    # Required sections
    sections = _parse_sections(lines)
    for name in ("CONTEXT", "CONSTRAINTS", "DELIVERABLE", "SUCCESS CRITERIA"):
        if name not in sections:
            errors.append(ValidationError(name, f"Missing required section: {name}"))

    return errors


# ---------------------------------------------------------------------------
# Result validation
# ---------------------------------------------------------------------------


def validate_result(path: str | Path) -> list[ValidationError]:
    """Validate a result markdown file.

    Checks:
    - RESULT_FOR present and well-formed
    - STATUS present and in allowed set
    - QUALITY_LEVEL present and in allowed set
    - COMPLETED_AT is valid ISO-8601
    - OUTPUT section present and non-empty (if COMPLETE)
    - ERROR section present (if FAILED)
    - META section with Assumptions, Risks, Suggested_Followups
    """
    path = Path(path)
    errors: list[ValidationError] = []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [ValidationError("file", f"Cannot read file: {exc}")]

    lines = text.splitlines()

    # --- Parse headers ---
    headers: dict[str, str] = {}
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            headers[m.group(1).upper()] = m.group(2).strip()

    # Required headers
    for key in ("RESULT_FOR", "STATUS", "QUALITY_LEVEL", "COMPLETED_AT"):
        if key not in headers:
            errors.append(ValidationError(key, f"Missing required header: {key}"))

    _check_enum(errors, headers, "STATUS", RESULT_STATUSES)
    _check_enum(errors, headers, "QUALITY_LEVEL", QUALITY_LEVELS)

    if "COMPLETED_AT" in headers:
        _check_iso8601(errors, "COMPLETED_AT", headers["COMPLETED_AT"])

    # --- Parse sections ---
    sections = _parse_sections(lines)

    status = headers.get("STATUS", "")

    # OUTPUT section required if COMPLETE
    if status == "COMPLETE":
        if "OUTPUT" not in sections:
            errors.append(ValidationError("OUTPUT", "Missing required section: OUTPUT"))
        elif not sections["OUTPUT"].strip():
            errors.append(ValidationError("OUTPUT", "OUTPUT section is empty"))

    # ERROR section required if FAILED
    if status == "FAILED":
        if "ERROR" not in sections:
            errors.append(ValidationError("ERROR", "Missing required section: ERROR"))

    # META section
    if "META" not in sections:
        errors.append(ValidationError("META", "Missing required section: META"))
    else:
        meta_text = sections["META"]
        for sub in ("Assumptions", "Risks", "Suggested_Followups"):
            # Check for ### subsection header
            pattern = r"###\s+" + sub.replace("_", "[_ ]")
            if not re.search(pattern, meta_text, re.IGNORECASE):
                errors.append(ValidationError(
                    f"META.{sub}",
                    f"Missing META subsection: {sub}",
                ))

    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_enum(
    errors: list[ValidationError],
    headers: dict[str, str],
    key: str,
    allowed: set[str],
) -> None:
    if key in headers and headers[key] not in allowed:
        errors.append(ValidationError(
            key,
            f"Invalid {key}: {headers[key]!r} (allowed: {sorted(allowed)})",
        ))


def _check_iso8601(errors: list[ValidationError], field: str, value: str) -> None:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        errors.append(ValidationError(field, f"Invalid ISO-8601 datetime: {value!r}"))
