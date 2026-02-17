"""Tests for publisher versioning scheme."""

import shutil
from pathlib import Path

import pytest

from agents.publisher_agent import auto_version, _next_semver, _date_version, _suite_version

TMP_ROOT = Path("publish/out/_test_versioning")


@pytest.fixture(autouse=True)
def cleanup():
    yield
    if TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT)


class TestSemver:
    def test_first_publish(self):
        assert _next_semver(TMP_ROOT, "cert", "aws-101") == "1.0.0"

    def test_increments_minor(self):
        (TMP_ROOT / "cert" / "aws-101" / "1.0.0").mkdir(parents=True)
        assert _next_semver(TMP_ROOT, "cert", "aws-101") == "1.1.0"

    def test_picks_latest(self):
        for v in ("1.0.0", "1.1.0", "1.2.0"):
            (TMP_ROOT / "cert" / "aws-101" / v).mkdir(parents=True)
        assert _next_semver(TMP_ROOT, "cert", "aws-101") == "1.3.0"

    def test_ignores_non_semver_dirs(self):
        (TMP_ROOT / "cert" / "aws-101" / "draft").mkdir(parents=True)
        (TMP_ROOT / "cert" / "aws-101" / "1.0.0").mkdir(parents=True)
        assert _next_semver(TMP_ROOT, "cert", "aws-101") == "1.1.0"


class TestDateVersion:
    def test_returns_date_string(self):
        v = _date_version()
        # Should match YYYY-MM-DD pattern
        parts = v.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
        assert len(parts[1]) == 2
        assert len(parts[2]) == 2


class TestSuiteVersion:
    def test_uses_suite_id_and_snapshot(self):
        state = {
            "suite_config": {"suite_id": "bench-1"},
            "snapshot_id": "abcdef1234567890",
        }
        assert _suite_version(state) == "bench-1-abcdef12"

    def test_fallback_to_scope_id(self):
        state = {"scope_id": "my-suite", "snapshot_id": "xyz12345"}
        assert _suite_version(state) == "my-suite-xyz12345"


class TestAutoVersion:
    def test_cert_gets_semver(self):
        v = auto_version("cert", {"scope_id": "aws-101"}, publish_root=TMP_ROOT)
        assert v == "1.0.0"

    def test_topic_gets_date(self):
        v = auto_version("topic", {})
        parts = v.split("-")
        assert len(parts) == 3

    def test_lab_gets_suite_version(self):
        state = {"suite_config": {"suite_id": "bench-1"}, "snapshot_id": "abcdef12"}
        v = auto_version("lab", state)
        assert v.startswith("bench-1-")

    def test_unknown_scope_fallback(self):
        v = auto_version("other", {"snapshot_id": "abcdef1234567890"})
        assert v == "abcdef12"
