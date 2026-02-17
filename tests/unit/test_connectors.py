"""Tests for connectors — web_fetch, rss_fetch, file_loader."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from connectors.file_loader import load_file
from connectors.rss_fetch import FeedEntry, FeedResult, fetch_feed
from connectors.web_fetch import FetchResult, fetch


# --- file_loader tests ---

class TestFileLoader:
    def test_load_text_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            f.flush()
            result = load_file(f.name)
        Path(f.name).unlink()
        assert result.text == "hello world"
        assert result.extension == ".txt"
        assert result.content_hash  # non-empty

    def test_load_json_file(self):
        data = {"key": "value", "num": 42}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            result = load_file(f.name)
        Path(f.name).unlink()
        parsed = json.loads(result.text)
        assert parsed["key"] == "value"

    def test_load_markdown_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Title\n\nSome content")
            f.flush()
            result = load_file(f.name)
        Path(f.name).unlink()
        assert "# Title" in result.text
        assert result.extension == ".md"

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_file("/nonexistent/path/file.txt")

    def test_meta_contains_size(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("data")
            f.flush()
            result = load_file(f.name)
        Path(f.name).unlink()
        assert "size_bytes" in result.meta


# --- web_fetch tests (mocked HTTP) ---

class TestWebFetch:
    @patch("connectors.web_fetch.httpx.get")
    def test_fetch_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>content</html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch("https://example.com")
        assert isinstance(result, FetchResult)
        assert result.status_code == 200
        assert result.text == "<html>content</html>"
        assert result.content_hash  # non-empty

    @patch("connectors.web_fetch.httpx.get")
    def test_fetch_propagates_error(self, mock_get):
        mock_get.side_effect = Exception("connection failed")
        with pytest.raises(Exception, match="connection failed"):
            fetch("https://bad.example.com")


# --- rss_fetch tests (mocked feedparser) ---

class TestRSSFetch:
    @patch("connectors.rss_fetch.feedparser.parse")
    def test_fetch_feed(self, mock_parse):
        mock_parse.return_value = MagicMock(
            feed={"title": "Test Feed"},
            entries=[
                {
                    "title": "Entry 1",
                    "link": "https://example.com/1",
                    "summary": "Summary 1",
                    "published": "2026-01-01",
                },
                {
                    "title": "Entry 2",
                    "link": "https://example.com/2",
                    "summary": "Summary 2",
                    "published": "2026-01-02",
                },
            ],
        )
        result = fetch_feed("https://example.com/rss")
        assert isinstance(result, FeedResult)
        assert result.feed_title == "Test Feed"
        assert len(result.entries) == 2
        assert result.entries[0].title == "Entry 1"
        assert result.entries[1].content_hash  # non-empty
