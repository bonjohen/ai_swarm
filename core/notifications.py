"""Notification hooks — email (stub) and webhook dispatching.

Provides a simple NotificationHook protocol and concrete implementations
for email (SMTP stub) and webhook (HTTP POST) notifications.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class NotificationHook(Protocol):
    """Protocol for notification hooks."""

    name: str

    def send(self, subject: str, body: str, metadata: dict[str, Any] | None = None) -> bool:
        """Send a notification. Returns True on success."""
        ...


@dataclass
class WebhookHook:
    """Sends notifications via HTTP POST to a configured URL."""

    name: str = "webhook"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: int = 10

    def send(self, subject: str, body: str, metadata: dict[str, Any] | None = None) -> bool:
        if not self.url:
            logger.warning("WebhookHook has no URL configured, skipping")
            return False

        payload = json.dumps({
            "subject": subject,
            "body": body,
            "metadata": metadata or {},
        }).encode("utf-8")

        headers = {"Content-Type": "application/json", **self.headers}
        req = urllib.request.Request(self.url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                logger.info("Webhook sent to %s: %d", self.url, resp.status)
                return resp.status < 400
        except urllib.error.URLError as exc:
            logger.error("Webhook to %s failed: %s", self.url, exc)
            return False


@dataclass
class EmailHook:
    """Sends notifications via SMTP (stub — logs instead of actually sending).

    In production, wire this to smtplib or a transactional email service.
    """

    name: str = "email"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    from_addr: str = "swarm@localhost"
    to_addrs: list[str] = field(default_factory=list)

    def send(self, subject: str, body: str, metadata: dict[str, Any] | None = None) -> bool:
        if not self.to_addrs:
            logger.warning("EmailHook has no recipients configured, skipping")
            return False

        # Stub: log instead of sending
        logger.info(
            "EMAIL [stub] to=%s subject='%s' body_len=%d",
            ", ".join(self.to_addrs), subject, len(body),
        )
        return True


@dataclass
class LogHook:
    """Simple hook that logs notifications (useful for testing/dev)."""

    name: str = "log"

    def send(self, subject: str, body: str, metadata: dict[str, Any] | None = None) -> bool:
        logger.info("NOTIFICATION: %s — %s", subject, body)
        return True


# ---------------------------------------------------------------------------
# Hook registry and dispatch
# ---------------------------------------------------------------------------

_HOOK_REGISTRY: dict[str, NotificationHook] = {}


def register_hook(hook: NotificationHook) -> None:
    """Register a notification hook by name."""
    _HOOK_REGISTRY[hook.name] = hook


def get_hook(name: str) -> NotificationHook | None:
    """Get a registered hook by name."""
    return _HOOK_REGISTRY.get(name)


def load_hooks(names: list[str]) -> list[NotificationHook]:
    """Load hooks by name, returning only those that are registered."""
    hooks = []
    for name in names:
        hook = _HOOK_REGISTRY.get(name)
        if hook:
            hooks.append(hook)
        else:
            logger.debug("Notification hook '%s' not registered, skipping", name)
    return hooks


def dispatch_notifications(
    hooks: list[NotificationHook],
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Send a notification through all provided hooks.

    Returns dict mapping hook name → success boolean.
    """
    results: dict[str, bool] = {}
    for hook in hooks:
        try:
            results[hook.name] = hook.send(subject, body, metadata)
        except Exception as exc:
            logger.error("Hook '%s' raised: %s", hook.name, exc)
            results[hook.name] = False
    return results


def reset_hook_registry() -> None:
    """Clear all registered hooks (for testing)."""
    _HOOK_REGISTRY.clear()
