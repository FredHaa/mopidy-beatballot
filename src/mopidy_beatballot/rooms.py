"""Parties ("rooms") on a hub, their PINs, and pairing of remote players.

A hub hosts many parties. Each has its own guest/host PINs and join link,
and plays on one paired player. Players pair once with a short-lived code
and then authenticate with a long-lived token, of which only a hash is kept.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

PAIR_CODE_TTL_S = 15 * 60
# No 0/O/1/I/L, so codes survive being read out loud or typed on a TV remote.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")


class RoomError(Exception):
    pass


@dataclass
class Room:
    id: str
    slug: str
    name: str
    pin: str
    admin_pin: str
    playlists: list[str] = field(default_factory=list)
    test_mode: bool = False
    carry_over: bool = True
    listed: bool = True  # Shown on the hub's landing page.
    player_token_hash: str | None = None
    player_name: str | None = None
    created_at: float = 0.0

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "slug": self.slug, "name": self.name}

    def private(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("player_token_hash")
        data["paired"] = self.player_token_hash is not None
        return data


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return slug or "party"


def random_pin(digits: int) -> str:
    pin = ""
    while not pin or len(set(pin)) == 1 or pin in ("1234", "123456"):
        pin = "".join(secrets.choice("0123456789") for _ in range(digits))
    return pin


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RoomStore:
    """Thread-safe store of rooms, persisted to JSON when ``path`` is set."""

    def __init__(self, path: Path | None = None, clock=time.time) -> None:
        self.path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._rooms: dict[str, Room] = {}
        self._codes: dict[str, tuple[str, float]] = {}  # code -> (room id, expiry)
        if path is not None and path.exists():
            self._load()

    # --- persistence -----------------------------------------------------

    def _load(self) -> None:
        assert self.path is not None
        known = {f.name for f in fields(Room)}
        data = json.loads(self.path.read_text())
        for raw in data.get("rooms", []):
            room = Room(**{k: v for k, v in raw.items() if k in known})
            self._rooms[room.id] = room

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"rooms": [asdict(r) for r in self._rooms.values()]}
        tmp.write_text(json.dumps(payload, indent=2))
        os.chmod(tmp, 0o600)  # Holds PINs.
        tmp.replace(self.path)

    # --- rooms -----------------------------------------------------------

    def list(self) -> list[Room]:
        with self._lock:
            return sorted(self._rooms.values(), key=lambda r: r.created_at)

    def get(self, room_id: str) -> Room | None:
        with self._lock:
            return self._rooms.get(room_id)

    def by_slug(self, slug: str) -> Room | None:
        with self._lock:
            return next((r for r in self._rooms.values() if r.slug == slug), None)

    def add(self, room: Room) -> Room:
        """Add a room as-is (standalone mode's built-in room)."""
        with self._lock:
            self._rooms[room.id] = room
            return room

    def create(
        self,
        name: str,
        *,
        slug: str | None = None,
        pin: str | None = None,
        admin_pin: str | None = None,
        playlists: list[str] | None = None,
    ) -> Room:
        name = " ".join(name.split())[:60]
        if not name:
            raise RoomError("Give the party a name")
        with self._lock:
            slug = slug or self._free_slug(slugify(name))
            self._check_slug(slug)
            room = Room(
                id=uuid.uuid4().hex[:12],
                slug=slug,
                name=name,
                pin=pin or random_pin(4),
                admin_pin=admin_pin or random_pin(6),
                playlists=list(playlists or []),
                created_at=self._clock(),
            )
            self._check_pins(room.pin, room.admin_pin)
            self._rooms[room.id] = room
            self._save()
            return room

    def update(self, room_id: str, **changes: Any) -> Room:
        allowed = {
            "name",
            "slug",
            "pin",
            "admin_pin",
            "playlists",
            "test_mode",
            "carry_over",
            "listed",
        }
        with self._lock:
            room = self._require(room_id)
            for key, value in changes.items():
                if key not in allowed:
                    raise RoomError(f"Can't change {key}")
                if key == "slug" and value != room.slug:
                    self._check_slug(value)
                if key == "name":
                    value = " ".join(str(value).split())[:60]
                    if not value:
                        raise RoomError("Give the party a name")
                setattr(room, key, value)
            self._check_pins(room.pin, room.admin_pin)
            self._save()
            return room

    def delete(self, room_id: str) -> None:
        with self._lock:
            self._require(room_id)
            del self._rooms[room_id]
            self._codes = {c: v for c, v in self._codes.items() if v[0] != room_id}
            self._save()

    def _require(self, room_id: str) -> Room:
        room = self._rooms.get(room_id)
        if room is None:
            raise RoomError("No such party")
        return room

    def _free_slug(self, base: str) -> str:
        slug, n = base, 2
        while any(r.slug == slug for r in self._rooms.values()):
            slug = f"{base[:36]}-{n}"
            n += 1
        return slug

    def _check_slug(self, slug: str) -> None:
        if not SLUG_RE.match(slug):
            raise RoomError("Links can use a-z, 0-9 and dashes")
        if any(r.slug == slug for r in self._rooms.values()):
            raise RoomError("That link is already used by another party")

    @staticmethod
    def _check_pins(pin: str, admin_pin: str) -> None:
        if not (pin and pin.isalnum() and 4 <= len(pin) <= 12):
            raise RoomError("The guest PIN needs 4-12 letters or digits")
        if not (admin_pin and admin_pin.isalnum() and 4 <= len(admin_pin) <= 32):
            raise RoomError("The host PIN needs 4-32 letters or digits")
        if pin == admin_pin:
            raise RoomError("Guest and host PINs must differ")

    # --- player pairing ----------------------------------------------------

    def start_pairing(self, room_id: str) -> tuple[str, int]:
        """A one-time code a player uses to pair with this room."""
        with self._lock:
            self._require(room_id)
            now = self._clock()
            self._codes = {c: v for c, v in self._codes.items() if v[1] > now}
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            self._codes[code] = (room_id, now + PAIR_CODE_TTL_S)
            return f"{code[:4]}-{code[4:]}", PAIR_CODE_TTL_S

    def pair(self, code: str, player_name: str | None = None) -> tuple[Room, str]:
        """Exchange a pairing code for a player token. Replaces any old player."""
        code = re.sub(r"[^A-Z0-9]", "", code.upper())
        with self._lock:
            entry = self._codes.pop(code, None)
            if entry is None or entry[1] < self._clock():
                raise RoomError("Unknown or expired pairing code")
            room = self._require(entry[0])
            token = f"bbp_{room.id}_{secrets.token_urlsafe(32)}"
            room.player_token_hash = _hash_token(token)
            room.player_name = (player_name or "Player")[:40]
            self._save()
            return room, token

    def unpair(self, room_id: str) -> None:
        with self._lock:
            room = self._require(room_id)
            room.player_token_hash = None
            room.player_name = None
            self._save()

    def verify_player(self, token: str) -> Room | None:
        parts = token.split("_")
        if len(parts) < 3 or parts[0] != "bbp":
            return None
        with self._lock:
            room = self._rooms.get(parts[1])
            if room is None or room.player_token_hash is None:
                return None
            if not hmac.compare_digest(room.player_token_hash, _hash_token(token)):
                return None
            return room


# The running store, for the web layer.
STORE: RoomStore | None = None
