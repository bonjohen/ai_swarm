"""Result file writer — generate structured result markdown files.

Produces files that pass :func:`automation.validator.validate_result`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def write_result(
    output_dir: str | Path,
    task_id: str,
    status: str,
    quality_level: str,
    output: str,
    meta: dict[str, str],
    error: str | None = None,
) -> Path:
    """Write a result file to *output_dir* and return its path.

    Args:
        output_dir: Directory for result files.
        task_id: The originating task ID.
        status: ``COMPLETE`` or ``FAILED``.
        quality_level: ``LOW``, ``MEDIUM``, or ``HIGH``.
        output: Content for the ``## OUTPUT`` section.
        meta: Dict with keys ``assumptions``, ``risks``, ``suggested_followups``.
        error: Content for the ``## ERROR`` section (required if FAILED).
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines = [
        f"# RESULT_FOR: {task_id}",
        f"# STATUS: {status}",
        f"# QUALITY_LEVEL: {quality_level}",
        f"# COMPLETED_AT: {now}",
        "",
    ]

    if status == "COMPLETE":
        lines += [
            "## OUTPUT",
            "",
            output,
            "",
        ]

    if status == "FAILED" and error:
        lines += [
            "## ERROR",
            "",
            error,
            "",
        ]

    lines += [
        "## META",
        "",
        "### Assumptions",
        "",
        meta.get("assumptions", "None specified."),
        "",
        "### Risks",
        "",
        meta.get("risks", "None specified."),
        "",
        "### Suggested_Followups",
        "",
        meta.get("suggested_followups", "None specified."),
        "",
    ]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"{task_id}.result.md"
    result_path.write_text("\n".join(lines), encoding="utf-8")

    return result_path
