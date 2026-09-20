"""Shared fixtures: a loopback fake gateway so no test touches a real API.

All identities / payloads are inert fixtures.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import pytest

from paratro import Config, MPCClient

Reply = Tuple[int, Any]


class FakeGateway:
    """Records every request; answers ``/api/v1/auth/token`` itself and pops
    everything else from ``queue`` (FIFO of ``(status, json_body)``)."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.queue: List[Reply] = []
        self.token_replies: List[Reply] = []
        self.token_issued = 0
        self.default_expires_in = 900
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ──

    def start(self) -> "FakeGateway":
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:  # silence
                pass

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                parts = urlsplit(self.path)
                status, body = gateway._dispatch(self.command, parts.path, parts.query, dict(self.headers), raw)
                if status in (301, 302, 303, 307, 308):
                    self.send_response(status)
                    self.send_header("Location", str(body))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                wire = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(wire)))
                self.end_headers()
                if wire:
                    self.wfile.write(wire)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    # ── request handling ──

    def _dispatch(self, method: str, path: str, query: str, headers: Dict[str, str], raw: bytes) -> Reply:
        body: Any = None
        if raw:
            try:
                body = json.loads(raw)
            except ValueError:
                body = raw.decode("utf-8", "replace")
        self.calls.append({
            "method": method,
            "path": path,
            "query": query,
            "headers": {k.lower(): v for k, v in headers.items()},
            "body": body,
            "raw": raw,
        })
        if path == "/api/v1/auth/token":
            if self.token_replies:
                return self.token_replies.pop(0)
            self.token_issued += 1
            return 200, {
                "token": f"tok-{self.token_issued}",
                "expires_in": self.default_expires_in,
                "token_type": "Bearer",
                "client": {"client_id": "client-fixture", "client_name": "fixture", "status": "ACTIVE",
                           "subscription_tier": "", "max_wallets": 10},
            }
        if self.queue:
            return self.queue.pop(0)
        return 500, {"code": "internal_error", "type": "api_error", "message": "unmocked request " + method + " " + path}

    # ── helpers for tests ──

    def api_calls(self) -> List[Dict[str, Any]]:
        """Calls other than the token exchange."""
        return [c for c in self.calls if c["path"] != "/api/v1/auth/token"]

    def token_calls(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["path"] == "/api/v1/auth/token"]


@pytest.fixture
def gateway():
    gw = FakeGateway().start()
    try:
        yield gw
    finally:
        gw.stop()


@pytest.fixture
def client(gateway: FakeGateway):
    c = MPCClient("fixture-key", "fixture-secret", Config(gateway.base_url))
    c._session.trust_env = False
    try:
        yield c
    finally:
        c._session.close()
