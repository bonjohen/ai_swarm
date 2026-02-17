"""Fetch and parse RSS/Atom feeds."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

import feedparser

logger = logging.getLogger(__name__)


@dataclass
class FeedEntry:
    title: str
    link: str
    summary: str
    published: str
    content_hash: str


@dataclass
class FeedResult:
    url: str
    feed_title: str
    entries: list[FeedEntry] = field(default_factory=list)


def fetch_feed(url: str) -> FeedResult:
    """Parse an RSS/Atom feed and return structured entries."""
    logger.info("Fetching feed %s", url)
    parsed = feedparser.parse(url)
    entries = []
    for entry in parsed.entries:
        summary = entry.get("summary", "")
        content_hash = hashlib.sha256(summary.encode()).hexdigest()
        entries.append(FeedEntry(
            title=entry.get("title", ""),
            link=entry.get("link", ""),
            summary=summary,
            published=entry.get("published", ""),
            content_hash=content_hash,
        ))
    return FeedResult(
        url=url,
        feed_title=parsed.feed.get("title", ""),
        entries=entries,
    )
