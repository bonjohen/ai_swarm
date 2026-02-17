"""Tests for automation queue state management."""

import json

import pytest

from automation.queue import (
    QueueState,
    add_pending,
    link_parent,
    load_queue,
    move_to_completed,
    move_to_failed,
    move_to_processing,
    save_queue,
)


class TestQueueRoundtrip:
    def test_load_save_roundtrip(self, tmp_path):
        state = QueueState(
            pending=["t1", "t2"],
            processing=["t3"],
            completed=["t4"],
            failed=["t5"],
            parents={"t3": "t1"},
        )
        path = tmp_path / "queue.json"
        save_queue(path, state)
        loaded = load_queue(path)

        assert loaded.pending == ["t1", "t2"]
        assert loaded.processing == ["t3"]
        assert loaded.completed == ["t4"]
        assert loaded.failed == ["t5"]
        assert loaded.parents == {"t3": "t1"}


class TestAddPending:
    def test_add_pending(self):
        state = QueueState()
        add_pending(state, "task-1")
        assert "task-1" in state.pending

    def test_add_pending_duplicate(self):
        state = QueueState(pending=["task-1"])
        with pytest.raises(ValueError, match="already exists"):
            add_pending(state, "task-1")

    def test_add_pending_duplicate_in_other_list(self):
        state = QueueState(completed=["task-1"])
        with pytest.raises(ValueError, match="already exists"):
            add_pending(state, "task-1")


class TestMoveToProcessing:
    def test_move_to_processing(self):
        state = QueueState(pending=["task-1"])
        move_to_processing(state, "task-1")
        assert "task-1" not in state.pending
        assert "task-1" in state.processing

    def test_move_to_processing_not_found(self):
        state = QueueState()
        with pytest.raises(ValueError, match="not found in pending"):
            move_to_processing(state, "task-1")


class TestMoveToCompleted:
    def test_move_to_completed(self):
        state = QueueState(processing=["task-1"])
        move_to_completed(state, "task-1")
        assert "task-1" not in state.processing
        assert "task-1" in state.completed

    def test_move_to_completed_not_in_processing(self):
        state = QueueState(pending=["task-1"])
        with pytest.raises(ValueError, match="not found in processing"):
            move_to_completed(state, "task-1")


class TestMoveToFailed:
    def test_move_to_failed(self):
        state = QueueState(processing=["task-1"])
        move_to_failed(state, "task-1")
        assert "task-1" not in state.processing
        assert "task-1" in state.failed

    def test_move_to_failed_not_in_processing(self):
        state = QueueState()
        with pytest.raises(ValueError, match="not found in processing"):
            move_to_failed(state, "task-1")


class TestLinkParent:
    def test_link_parent(self):
        state = QueueState(pending=["task-1", "task-2"])
        link_parent(state, "task-2", "task-1")
        assert state.parents["task-2"] == "task-1"


class TestAtomicWrite:
    def test_atomic_write(self, tmp_path):
        """save_queue uses a .tmp file, and the final file is correct."""
        path = tmp_path / "queue.json"
        state = QueueState(pending=["t1"])
        save_queue(path, state)

        # .tmp should not linger
        assert not (tmp_path / "queue.tmp").exists()
        # Final file has correct content
        data = json.loads(path.read_text())
        assert data["pending"] == ["t1"]
