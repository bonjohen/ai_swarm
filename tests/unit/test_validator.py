"""Tests for automation task and result file validation."""

import textwrap

import pytest

from automation.validator import ValidationError, validate_result, validate_task

# ---------------------------------------------------------------------------
# Fixtures — valid file contents
# ---------------------------------------------------------------------------

VALID_TASK = textwrap.dedent("""\
    # TASK_ID: 2026-02-17-001
    # MODE: PREMIUM
    # TASK_TYPE: ARCHITECTURE
    # PRIORITY: HIGH
    # OUTPUT_FORMAT: MARKDOWN
    # CREATED_AT: 2026-02-17T10:00:00

    ## CONTEXT

    Redesign the auth module.

    ## CONSTRAINTS

    Standard library only.

    ## DELIVERABLE

    Architecture doc.

    ## SUCCESS CRITERIA

    All flows covered.
""")

VALID_RESULT_COMPLETE = textwrap.dedent("""\
    # RESULT_FOR: 2026-02-17-001
    # STATUS: COMPLETE
    # QUALITY_LEVEL: HIGH
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## OUTPUT

    Here is the architecture document.

    ## META

    ### Assumptions

    Single-tenant deployment.

    ### Risks

    May need caching later.

    ### Suggested_Followups

    Implement the auth module.
""")

VALID_RESULT_FAILED = textwrap.dedent("""\
    # RESULT_FOR: 2026-02-17-001
    # STATUS: FAILED
    # QUALITY_LEVEL: LOW
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## ERROR

    Could not process: insufficient context provided.

    ## META

    ### Assumptions

    None.

    ### Risks

    Task may need to be re-submitted.

    ### Suggested_Followups

    Provide more context and retry.
""")


# ---------------------------------------------------------------------------
# Task validation
# ---------------------------------------------------------------------------


class TestValidateTask:
    def test_valid_task_no_errors(self, tmp_path):
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(VALID_TASK)

        errors = validate_task(f)
        assert errors == []

    def test_task_id_filename_mismatch(self, tmp_path):
        f = tmp_path / "wrong-name.md"
        f.write_text(VALID_TASK)

        errors = validate_task(f)
        fields = {e.field for e in errors}
        assert "TASK_ID" in fields

    def test_invalid_mode(self, tmp_path):
        text = VALID_TASK.replace("MODE: PREMIUM", "MODE: TURBO")
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        errors = validate_task(f)
        msgs = [e.message for e in errors if e.field == "MODE"]
        assert any("TURBO" in m for m in msgs)

    def test_invalid_task_type(self, tmp_path):
        text = VALID_TASK.replace("TASK_TYPE: ARCHITECTURE", "TASK_TYPE: BUILD")
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        errors = validate_task(f)
        fields = {e.field for e in errors}
        assert "TASK_TYPE" in fields

    def test_invalid_priority(self, tmp_path):
        text = VALID_TASK.replace("PRIORITY: HIGH", "PRIORITY: URGENT")
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        errors = validate_task(f)
        fields = {e.field for e in errors}
        assert "PRIORITY" in fields

    def test_invalid_output_format(self, tmp_path):
        text = VALID_TASK.replace("OUTPUT_FORMAT: MARKDOWN", "OUTPUT_FORMAT: HTML")
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        errors = validate_task(f)
        fields = {e.field for e in errors}
        assert "OUTPUT_FORMAT" in fields

    def test_invalid_created_at(self, tmp_path):
        text = VALID_TASK.replace("CREATED_AT: 2026-02-17T10:00:00", "CREATED_AT: not-a-date")
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        errors = validate_task(f)
        fields = {e.field for e in errors}
        assert "CREATED_AT" in fields

    def test_missing_section(self, tmp_path):
        # Remove the CONSTRAINTS section
        text = VALID_TASK.replace(
            "## CONSTRAINTS\n\nStandard library only.\n\n",
            "",
        )
        f = tmp_path / "2026-02-17-001.md"
        f.write_text(text)

        errors = validate_task(f)
        fields = {e.field for e in errors}
        assert "CONSTRAINTS" in fields


# ---------------------------------------------------------------------------
# Result validation
# ---------------------------------------------------------------------------


class TestValidateResult:
    def test_valid_complete_result(self, tmp_path):
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(VALID_RESULT_COMPLETE)

        errors = validate_result(f)
        assert errors == []

    def test_valid_failed_result(self, tmp_path):
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(VALID_RESULT_FAILED)

        errors = validate_result(f)
        assert errors == []

    def test_missing_output_section_on_complete(self, tmp_path):
        text = VALID_RESULT_COMPLETE.replace(
            "## OUTPUT\n\nHere is the architecture document.\n\n",
            "",
        )
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "OUTPUT" in fields

    def test_empty_output_section_on_complete(self, tmp_path):
        text = VALID_RESULT_COMPLETE.replace(
            "Here is the architecture document.",
            "",
        )
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "OUTPUT" in fields

    def test_missing_error_section_on_failed(self, tmp_path):
        text = VALID_RESULT_FAILED.replace(
            "## ERROR\n\nCould not process: insufficient context provided.\n\n",
            "",
        )
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "ERROR" in fields

    def test_missing_meta_subsection(self, tmp_path):
        # Remove the Risks subsection
        text = VALID_RESULT_COMPLETE.replace(
            "### Risks\n\nMay need caching later.\n\n",
            "",
        )
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "META.Risks" in fields

    def test_missing_required_header(self, tmp_path):
        text = VALID_RESULT_COMPLETE.replace("# STATUS: COMPLETE\n", "")
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "STATUS" in fields

    def test_invalid_status(self, tmp_path):
        text = VALID_RESULT_COMPLETE.replace("STATUS: COMPLETE", "STATUS: PARTIAL")
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "STATUS" in fields

    def test_invalid_quality_level(self, tmp_path):
        text = VALID_RESULT_COMPLETE.replace("QUALITY_LEVEL: HIGH", "QUALITY_LEVEL: EXCELLENT")
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "QUALITY_LEVEL" in fields

    def test_invalid_completed_at(self, tmp_path):
        text = VALID_RESULT_COMPLETE.replace(
            "COMPLETED_AT: 2026-02-17T12:00:00",
            "COMPLETED_AT: yesterday",
        )
        f = tmp_path / "2026-02-17-001.result.md"
        f.write_text(text)

        errors = validate_result(f)
        fields = {e.field for e in errors}
        assert "COMPLETED_AT" in fields
