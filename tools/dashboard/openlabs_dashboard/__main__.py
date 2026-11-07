"""OpenLabs researcher dashboard: read-only local web view of research, papers and submissions.

    python -m openlabs_dashboard serve [--port 8765] [--site-snapshot FILE | --site-api]
    python -m openlabs_dashboard build --output dashboard.html

``serve`` binds to 127.0.0.1 by default and recomputes state at most every ``--cache-seconds``.
``build`` writes one self-contained HTML file with the state embedded (no server needed).
Nothing in OpenLabs is modified; the factory SQLite file is opened read-only.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from openlabs_dashboard.collect import build_state, default_workspace

STATIC = Path(__file__).resolve().parent / "static" / "index.html"


class StateCache:
    def __init__(self, workspace: Path, snapshot: Path | None, use_api: bool, ttl: int) -> None:
        self.workspace, self.snapshot, self.use_api, self.ttl = workspace, snapshot, use_api, ttl
        self.lock = threading.Lock()
        self.value: bytes | None = None
        self.stamp = 0.0

    def get(self, refresh: bool = False) -> bytes:
        with self.lock:
            if refresh or self.value is None or time.monotonic() - self.stamp > self.ttl:
                site = None
                if self.use_api:
                    from paper_writing.journal_history import fetch_site_papers
                    site = fetch_site_papers()
                state = build_state(self.workspace, site_snapshot=self.snapshot, site_papers=site)
                self.value = json.dumps(state, ensure_ascii=False, default=str).encode("utf-8")
                self.stamp = time.monotonic()
            return self.value


def make_handler(cache: StateCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path, _, query = self.path.partition("?")
            if path in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, STATIC.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                try:
                    body = cache.get(refresh="refresh=1" in query)
                except Exception as exc:  # surface collection failures to the page
                    body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode()
                    self._send(HTTPStatus.INTERNAL_SERVER_ERROR, body, "application/json; charset=utf-8")
                    return
                self._send(HTTPStatus.OK, body, "application/json; charset=utf-8")
            else:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return Handler


def build_static(workspace: Path, snapshot: Path | None, output: Path) -> Path:
    state = build_state(workspace, site_snapshot=snapshot)
    payload = json.dumps(state, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = STATIC.read_text(encoding="utf-8").replace(
        "<script>window.OPENLABS_STATE = null;</script>",
        f"<script>window.OPENLABS_STATE = {payload};</script>", 1)
    output.write_text(html, encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openlabs-dashboard", description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", default=str(default_workspace()))
    parser.add_argument("--site-snapshot", help="Management-site paper-detail JSON (default: newest under maintenance/)")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--cache-seconds", type=int, default=120)
    serve.add_argument("--site-api", action="store_true", help="Read the management API live (GET only).")
    build = commands.add_parser("build")
    build.add_argument("--output", default="openlabs-dashboard.html")
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).resolve()
    snapshot = Path(args.site_snapshot).resolve() if args.site_snapshot else None
    if args.command == "build":
        print(build_static(workspace, snapshot, Path(args.output).resolve()))
        return 0
    cache = StateCache(workspace, snapshot, args.site_api, args.cache_seconds)
    cache.get()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(cache))
    print(f"OpenLabs dashboard: http://{args.host}:{args.port}/  (workspace {workspace})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
