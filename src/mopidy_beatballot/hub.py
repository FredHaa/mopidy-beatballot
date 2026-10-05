"""Fan-out of party state from the frontend actor to WebSocket clients."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from typing import Any, Protocol

from tornado.ioloop import IOLoop

logger = logging.getLogger(__name__)


class Client(Protocol):
    def send(self, message: str) -> None: ...


class Hub:
    """Clients per room. Each room's latest state is kept for new clients."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: defaultdict[str, set[Client]] = defaultdict(set)
        self._loop: IOLoop | None = None
        self.latest: dict[str, str] = {}

    def attach(self, room_id: str, client: Client) -> None:
        """Register a client. Must be called on the Tornado IOLoop thread."""
        with self._lock:
            self._loop = IOLoop.current()
            self._clients[room_id].add(client)

    def detach(self, room_id: str, client: Client) -> None:
        with self._lock:
            self._clients[room_id].discard(client)

    def forget(self, room_id: str) -> None:
        with self._lock:
            self._clients.pop(room_id, None)
            self.latest.pop(room_id, None)

    def broadcast(self, room_id: str, state: dict[str, Any]) -> None:
        """Send a room's state to its clients. Safe to call from any thread."""
        message = json.dumps(state)
        with self._lock:
            self.latest[room_id] = message
            loop = self._loop
        if loop is not None:
            loop.add_callback(self._send_all, room_id, message)

    def call_soon(self, fn: Any, *args: Any) -> bool:
        """Run ``fn`` on the IOLoop thread. False if no loop is known yet."""
        with self._lock:
            loop = self._loop
        if loop is None:
            return False
        loop.add_callback(fn, *args)
        return True

    def set_loop(self, loop: IOLoop) -> None:
        with self._lock:
            self._loop = loop

    def _send_all(self, room_id: str, message: str) -> None:
        with self._lock:
            clients = list(self._clients.get(room_id, ()))
        for client in clients:
            try:
                client.send(message)
            except Exception:
                logger.debug("Dropping Beat Ballot client", exc_info=True)
                self.detach(room_id, client)


HUB = Hub()
