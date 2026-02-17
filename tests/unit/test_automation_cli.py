"""Tests for the automation CLI (create, list, validate, archive, status)."""

import json
import textwrap

import pytest

from automation.automation_cli import main
from automation.queue import load_queue, save_queue, QueueState, add_pending
from automation.task_schema import parse_task_file


def _bootstrap(tmp_path, extra_yaml=""):
    """Create minimal config + directory structure for CLI testing."""
    cfg_yaml = textwrap.dedent(f"""\
        paths:
          base: {tmp_path / "auto"}
          tasks: {tmp_path / "auto" / "tasks"}
          processing: {tmp_path / "auto" / "processing"}
          outputs: {tmp_path / "auto" / "outputs"}
          archive: {tmp_path / "auto" / "archive"}
          logs: {tmp_path / "auto" / "logs"}
          schemas: {tmp_path / "auto" / "schemas"}
        {extra_yaml}
    """)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(cfg_yaml)

    for d in ["auto", "auto/tasks", "auto/processing", "auto/outputs",
              "auto/archive", "auto/logs", "auto/schemas"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    # Initialise empty queue
    queue_path = tmp_path / "auto" / "queue.json"
    save_queue(queue_path, QueueState())

    return cfg_path


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_generates_valid_task(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        rc = main(["--config", str(cfg), "create",
                    "--type", "ARCHITECTURE", "--mode", "PREMIUM",
                    "--title", "Design auth module"])
        assert rc == 0

        # Find the created file
        tasks_dir = tmp_path / "auto" / "tasks"
        files = list(tasks_dir.glob("*.md"))
        assert len(files) == 1

        task = parse_task_file(files[0])
        assert task.header.mode == "PREMIUM"
        assert task.header.task_type == "ARCHITECTURE"
        assert task.header.priority == "MEDIUM"  # default
        assert task.header.output_format == "MARKDOWN"  # default
        assert "Design auth module" in task.context

    def test_create_updates_queue(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        main(["--config", str(cfg), "create",
              "--type", "REVIEW", "--mode", "FAST",
              "--title", "Quick review"])

        state = load_queue(tmp_path / "auto" / "queue.json")
        assert len(state.pending) == 1

    def test_create_with_parent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        main(["--config", str(cfg), "create",
              "--type", "ANALYSIS", "--mode", "BALANCED",
              "--title", "Follow-up analysis",
              "--parent", "2026-02-16-001"])

        state = load_queue(tmp_path / "auto" / "queue.json")
        child_id = state.pending[0]
        assert state.parents[child_id] == "2026-02-16-001"

        # Verify PARENT_TASK header in file
        task_file = tmp_path / "auto" / "tasks" / f"{child_id}.md"
        task = parse_task_file(task_file)
        assert task.header.parent_task == "2026-02-16-001"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    def test_list_grouped_by_status(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        # Create two tasks
        main(["--config", str(cfg), "create",
              "--type", "DESIGN", "--mode", "FAST", "--title", "Task A"])
        main(["--config", str(cfg), "create",
              "--type", "REFACTOR", "--mode", "BALANCED", "--title", "Task B"])

        rc = main(["--config", str(cfg), "list"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "PENDING" in out

    def test_list_filter_by_status(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        main(["--config", str(cfg), "create",
              "--type", "REVIEW", "--mode", "FAST", "--title", "Task C"])

        rc = main(["--config", str(cfg), "list", "--status", "completed"])
        assert rc == 0

        out = capsys.readouterr().out
        # No completed tasks, so no task IDs in output
        assert "No tasks found" in out or "COMPLETED" not in out


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

VALID_RESULT = textwrap.dedent("""\
    # RESULT_FOR: {task_id}
    # STATUS: COMPLETE
    # QUALITY_LEVEL: HIGH
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## OUTPUT

    Architecture document content here.

    ## META

    ### Assumptions

    Single-tenant deployment.

    ### Risks

    May need caching later.

    ### Suggested_Followups

    Implement the module.
""")

INVALID_RESULT = textwrap.dedent("""\
    # RESULT_FOR: {task_id}
    # STATUS: COMPLETE
    # QUALITY_LEVEL: HIGH
    # COMPLETED_AT: 2026-02-17T12:00:00

    ## META

    ### Assumptions

    None.

    ### Risks

    None.

    ### Suggested_Followups

    None.
""")


class TestValidate:
    def test_validate_passes_valid_result(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        task_id = "2026-02-17-001"
        result_path = tmp_path / "auto" / "outputs" / f"{task_id}.result.md"
        result_path.write_text(VALID_RESULT.format(task_id=task_id))

        rc = main(["--config", str(cfg), "validate", task_id])
        assert rc == 0

    def test_validate_fails_malformed_result(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        task_id = "2026-02-17-002"
        result_path = tmp_path / "auto" / "outputs" / f"{task_id}.result.md"
        result_path.write_text(INVALID_RESULT.format(task_id=task_id))

        rc = main(["--config", str(cfg), "validate", task_id])
        assert rc == 1

        out = capsys.readouterr().out
        assert "FAIL" in out


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------


class TestArchive:
    def test_archive_moves_and_updates_queue(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        # Create a task first
        main(["--config", str(cfg), "create",
              "--type", "ANALYSIS", "--mode", "PREMIUM", "--title", "To archive"])

        state = load_queue(tmp_path / "auto" / "queue.json")
        task_id = state.pending[0]

        # Archive it
        rc = main(["--config", str(cfg), "archive", task_id])
        assert rc == 0

        # File moved to archive
        assert (tmp_path / "auto" / "archive" / f"{task_id}.md").exists()
        assert not (tmp_path / "auto" / "tasks" / f"{task_id}.md").exists()

        # Queue updated
        state = load_queue(tmp_path / "auto" / "queue.json")
        assert task_id not in state.pending
        assert task_id in state.completed


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_shows_counts(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        cfg = _bootstrap(tmp_path)

        # Create two tasks
        main(["--config", str(cfg), "create",
              "--type", "DESIGN", "--mode", "FAST", "--title", "Task 1"])
        main(["--config", str(cfg), "create",
              "--type", "REVIEW", "--mode", "FAST", "--title", "Task 2"])

        rc = main(["--config", str(cfg), "status"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "Pending:    2" in out
        assert "Processing: 0" in out
        assert "Completed:  0" in out
        assert "Failed:     0" in out
