"""Fetch web pages and return raw text/HTML."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
DEFAULT_HEADERS = {
    "User-Agent": "ai-swarm/0.1 (research bot)",
}


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str
    content_hash: str


def fetch(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> FetchResult:
    """Fetch a URL and return its content as text."""
    logger.info("Fetching %s", url)
    resp = httpx.get(url, headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    text = resp.text
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return FetchResult(
        url=url,
        status_code=resp.status_code,
        content_type=resp.headers.get("content-type", ""),
        text=text,
        content_hash=content_hash,
    )


async def fetch_async(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> FetchResult:
    """Async variant of fetch."""
    logger.info("Async fetching %s", url)
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=timeout) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        text = resp.text
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        return FetchResult(
            url=url,
            status_code=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            text=text,
            content_hash=content_hash,
        )
