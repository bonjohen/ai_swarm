"""Tests for the notification hooks system."""

import pytest

from core.notifications import (
    EmailHook,
    LogHook,
    WebhookHook,
    dispatch_notifications,
    get_hook,
    load_hooks,
    register_hook,
    reset_hook_registry,
)


class TestLogHook:
    def test_send(self, caplog):
        hook = LogHook()
        import logging
        with caplog.at_level(logging.INFO):
            result = hook.send("Test Subject", "Test Body", {"key": "val"})
        assert result is True
        assert any("Test Subject" in r.message for r in caplog.records)


class TestEmailHook:
    def test_send_stub(self, caplog):
        hook = EmailHook(to_addrs=["user@example.com"])
        import logging
        with caplog.at_level(logging.INFO):
            result = hook.send("Alert", "Something happened")
        assert result is True
        assert any("EMAIL" in r.message for r in caplog.records)

    def test_no_recipients(self, caplog):
        hook = EmailHook()
        import logging
        with caplog.at_level(logging.WARNING):
            result = hook.send("Alert", "No one to send to")
        assert result is False


class TestWebhookHook:
    def test_no_url_skips(self, caplog):
        hook = WebhookHook()
        import logging
        with caplog.at_level(logging.WARNING):
            result = hook.send("Alert", "No URL configured")
        assert result is False


class TestHookRegistry:
    def setup_method(self):
        reset_hook_registry()

    def test_register_and_get(self):
        hook = LogHook(name="test_log")
        register_hook(hook)
        assert get_hook("test_log") is hook

    def test_get_missing(self):
        assert get_hook("nonexistent") is None

    def test_load_hooks_filters(self):
        register_hook(LogHook(name="a"))
        register_hook(LogHook(name="b"))
        hooks = load_hooks(["a", "c", "b"])
        assert len(hooks) == 2
        assert hooks[0].name == "a"
        assert hooks[1].name == "b"

    def test_reset(self):
        register_hook(LogHook(name="x"))
        reset_hook_registry()
        assert get_hook("x") is None


class TestDispatchNotifications:
    def test_dispatch_multiple(self):
        hooks = [LogHook(name="h1"), LogHook(name="h2")]
        results = dispatch_notifications(hooks, "subj", "body")
        assert results == {"h1": True, "h2": True}

    def test_dispatch_with_failure(self):
        class FailHook:
            name = "fail"
            def send(self, subject, body, metadata=None):
                raise RuntimeError("broken")

        hooks = [LogHook(name="ok"), FailHook()]
        results = dispatch_notifications(hooks, "subj", "body")
        assert results["ok"] is True
        assert results["fail"] is False
