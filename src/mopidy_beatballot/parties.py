"""Runs one PartyController per room. Mopidy-independent, like party.py.

All methods must be called from one thread (the frontend actor).
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .backends import normalize_playlist, split_list
from .party import PartyController, Player
from .rooms import Room, RoomStore
from .settings import Settings
from .voting import VoteError

logger = logging.getLogger(__name__)


def room_settings(base: Settings, room: Room) -> Settings:
    return replace(
        base,
        party_name=room.name,
        pin=room.pin,
        admin_pin=room.admin_pin,
        playlists=list(room.playlists),
        test_mode=room.test_mode,
        carry_over=room.carry_over,
        search_schemes=list(base.search_schemes),
        trusted_proxies=list(base.trusted_proxies),
    )


class Parties:
    def __init__(
        self,
        base: Settings,
        store: RoomStore,
        make_player: Callable[[Room], Player],
        publish: Callable[[str, dict[str, Any]], None],
        *,
        login_pending: Callable[[str], bool] = lambda source: False,
        forget: Callable[[str], None] = lambda room_id: None,
        rng: random.Random | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.base = base
        self.store = store
        self._make_player = make_player
        self._publish = publish
        self._forget = forget
        self._login_pending = login_pending
        self._rng = rng
        self._clock = clock
        self.parties: dict[str, PartyController] = {}

    def start(self) -> None:
        for room in self.store.list():
            self._start(room)

    def _start(self, room: Room) -> PartyController:
        kwargs: dict[str, Any] = {"login_pending": self._login_pending}
        if self._rng is not None:
            kwargs["rng"] = self._rng
        if self._clock is not None:
            kwargs["clock"] = self._clock
        party = PartyController(
            room_settings(self.base, room),
            self._make_player(room),
            lambda state, room_id=room.id: self._publish(
                room_id, {**state, "room": self.store.get(room_id).public()}
            ),
            **kwargs,
        )
        self.parties[room.id] = party
        try:
            party.start()
        except Exception:
            logger.exception("Starting party %s failed", room.slug)
        return party

    def party(self, room_id: str) -> PartyController:
        party = self.parties.get(room_id)
        if party is None:
            raise VoteError("This party no longer exists")
        return party

    def tick(self) -> None:
        for room_id, party in list(self.parties.items()):
            try:
                party.tick()
            except Exception:
                logger.exception("Tick failed for party %s", room_id)

    def login_changed(self) -> None:
        for party in self.parties.values():
            party.login_changed()

    # --- host actions inside a party ---------------------------------------

    def admin(self, room_id: str, action: str, value: Any = None) -> None:
        party = self.party(room_id)
        match action:
            case "skip":
                party.skip()
            case "pause":
                party.pause()
            case "resume":
                party.resume()
            case "test_mode":
                party.set_test_mode(bool(value))
                self.store.update(room_id, test_mode=bool(value))
            case "carry_over":
                party.set_carry_over(bool(value))
                self.store.update(room_id, carry_over=bool(value))
            case "remove":
                party.remove_candidate(str(value))
            case "playlists":
                party.set_playlists(str(value))
                self.store.update(room_id, playlists=party.settings.playlists)
            case _:
                raise ValueError(f"Unknown admin action {action!r}")

    # --- hub owner actions -------------------------------------------------

    def create_room(self, **fields: Any) -> dict[str, Any]:
        if "playlists" in fields:
            fields["playlists"] = [
                normalize_playlist(p) for p in split_list(fields["playlists"])
            ]
        room = self.store.create(**fields)
        self._start(room)
        return room.private()

    def update_room(self, room_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if "playlists" in changes:
            changes["playlists"] = [
                normalize_playlist(p) for p in split_list(changes["playlists"])
            ]
        room = self.store.update(room_id, **changes)
        party = self.party(room_id)
        old_playlists = party.settings.playlists
        party.settings = room_settings(self.base, room)
        if room.playlists != old_playlists:
            party.set_playlists(room.playlists)
        party.publish()
        return room.private()

    def delete_room(self, room_id: str) -> None:
        self.store.delete(room_id)
        party = self.parties.pop(room_id, None)
        if party is not None:
            player = party.player
            if getattr(player, "online", False):
                try:
                    player.pause()
                except Exception:
                    logger.debug("Pausing removed party's player failed", exc_info=True)
        self._forget(room_id)

    def overview(self, base_url: str) -> list[dict[str, Any]]:
        """Every room with its player and what's playing, for the hub page."""
        rows = []
        for room in self.store.list():
            party = self.parties.get(room.id)
            snap = party.snapshot() if party else {}
            now = snap.get("now")
            rows.append(
                {
                    **room.private(),
                    # Without a public URL the page builds it from its own address.
                    "join_url": f"{base_url}r/{room.slug}/" if base_url else None,
                    "player": snap.get("player", {"online": False}),
                    "now_playing": now["track"] if now else None,
                    "round": snap.get("round", {}).get("id"),
                    "error": snap.get("error") or snap.get("playback_error"),
                }
            )
        return rows
