"""Simple metrics dashboard — serves JSON metrics over HTTP.

Usage: python -m scripts.dashboard [--port 8080] [--db ai_swarm.db]

Endpoints:
    GET /metrics       — current MetricsCollector snapshot (JSON)
    GET /runs          — recent runs summary (JSON)
    GET /health        — health check
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from core.logging import get_metrics_collector
from data.db import get_initialized_connection
from data.dao_runs import list_runs

logger = logging.getLogger(__name__)

_DB_PATH = "ai_swarm.db"


class DashboardHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for metrics dashboard."""

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path == "/metrics":
            self._json_response(get_metrics_collector().to_dict())
        elif path == "/runs":
            self._json_response(self._recent_runs())
        elif path == "/health":
            self._json_response({"status": "ok"})
        else:
            self.send_error(404, "Not found")

    def _json_response(self, data: Any) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            conn = get_initialized_connection(_DB_PATH)
            runs = list_runs(conn, limit=limit)
            conn.close()
            return runs
        except Exception as exc:
            logger.error("Failed to fetch runs: %s", exc)
            return []

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug(fmt, *args)


def get_initialized_connection(db_path: str):
    """Import here to avoid circular imports at module level."""
    from data.db import get_initialized_connection as _get_conn
    return _get_conn(db_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Metrics dashboard server")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    parser.add_argument("--db", default="ai_swarm.db", help="SQLite database path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    global _DB_PATH
    _DB_PATH = args.db

    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    logger.info("Dashboard running on http://0.0.0.0:%d", args.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Dashboard shutting down")
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
