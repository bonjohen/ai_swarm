"""Tests for automation task file schema and parser."""

import textwrap
from datetime import date

import pytest

from automation.task_schema import (
    TaskFile,
    TaskHeader,
    generate_task_id,
    parse_task_file,
)

VALID_TASK = textwrap.dedent("""\
    # TASK_ID: 2026-02-17-001
    # MODE: PREMIUM
    # TASK_TYPE: ARCHITECTURE
    # PRIORITY: HIGH
    # OUTPUT_FORMAT: MARKDOWN
    # CREATED_AT: 2026-02-17T10:00:00

    ## CONTEXT

    Redesign the authentication module.

    ## CONSTRAINTS

    Must use standard library only.

    ## DELIVERABLE

    Architecture document with diagrams.

    ## SUCCESS CRITERIA

    All auth flows covered; no external deps.
""")


class TestParseTaskFile:
    def test_valid_task(self, tmp_path):
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(VALID_TASK)

        task = parse_task_file(f)

        assert isinstance(task, TaskFile)
        assert task.header.task_id == "2026-02-17-001"
        assert task.header.mode == "PREMIUM"
        assert task.header.task_type == "ARCHITECTURE"
        assert task.header.priority == "HIGH"
        assert task.header.output_format == "MARKDOWN"
        assert task.header.created_at == "2026-02-17T10:00:00"
        assert task.header.parent_task is None
        assert "authentication" in task.context
        assert "standard library" in task.constraints
        assert "Architecture document" in task.deliverable
        assert "auth flows" in task.success_criteria

    def test_with_parent_task(self, tmp_path):
        text = VALID_TASK.replace(
            "# CREATED_AT: 2026-02-17T10:00:00",
            "# CREATED_AT: 2026-02-17T10:00:00\n# PARENT_TASK: 2026-02-16-005",
        )
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        task = parse_task_file(f)
        assert task.header.parent_task == "2026-02-16-005"

    def test_missing_headers(self, tmp_path):
        text = textwrap.dedent("""\
            # TASK_ID: 2026-02-17-001

            ## CONTEXT

            Some context.

            ## CONSTRAINTS

            None.

            ## DELIVERABLE

            Something.

            ## SUCCESS CRITERIA

            It works.
        """)
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        with pytest.raises(ValueError, match="Missing required headers.*MODE"):
            parse_task_file(f)

    def test_missing_sections(self, tmp_path):
        text = textwrap.dedent("""\
            # TASK_ID: 2026-02-17-001
            # MODE: FAST
            # TASK_TYPE: REVIEW
            # PRIORITY: LOW
            # OUTPUT_FORMAT: TEXT
            # CREATED_AT: 2026-02-17T10:00:00

            ## CONTEXT

            Some context.
        """)
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        with pytest.raises(ValueError, match="Missing required sections"):
            parse_task_file(f)


class TestGenerateTaskId:
    def test_first_task_of_day(self, tmp_path):
        tid = generate_task_id(tmp_path)
        today = date.today().isoformat()
        assert tid == f"{today}-001"

    def test_increments_sequence(self, tmp_path):
        today = date.today().isoformat()
        (tmp_path / f"{today}-001.md").write_text("")
        (tmp_path / f"{today}-002.md").write_text("")

        tid = generate_task_id(tmp_path)
        assert tid == f"{today}-003"

    def test_ignores_other_dates(self, tmp_path):
        (tmp_path / "2025-01-01-005.md").write_text("")

        tid = generate_task_id(tmp_path)
        today = date.today().isoformat()
        assert tid == f"{today}-001"

    def test_nonexistent_dir(self, tmp_path):
        tid = generate_task_id(tmp_path / "does_not_exist")
        today = date.today().isoformat()
        assert tid == f"{today}-001"
