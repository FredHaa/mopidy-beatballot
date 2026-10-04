"""Fan-out of party state from the frontend actor to WebSocket clients."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Protocol

from tornado.ioloop import IOLoop

logger = logging.getLogger(__name__)


class Client(Protocol):
    def send(self, message: str) -> None: ...


class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: set[Client] = set()
        self._loop: IOLoop | None = None
        self.latest: str | None = None

    def attach(self, client: Client) -> None:
        """Register a client. Must be called on the Tornado IOLoop thread."""
        with self._lock:
            self._loop = IOLoop.current()
            self._clients.add(client)

    def detach(self, client: Client) -> None:
        with self._lock:
            self._clients.discard(client)

    def broadcast(self, state: dict[str, Any]) -> None:
        """Send state to every client. Safe to call from any thread."""
        message = json.dumps(state)
        with self._lock:
            self.latest = message
            loop = self._loop
        if loop is not None:
            loop.add_callback(self._send_all, message)

    def _send_all(self, message: str) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.send(message)
            except Exception:
                logger.debug("Dropping Beat Ballot client", exc_info=True)
                self.detach(client)


HUB = Hub()
