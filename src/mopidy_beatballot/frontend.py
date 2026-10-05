from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import pykka
from mopidy.core import CoreListener

from . import hub, rooms, tidal_auth
from .parties import Parties
from .player import MopidyPlayer
from .rooms import Room, RoomStore
from .settings import Settings
from .tracks import TrackInfo

logger = logging.getLogger(__name__)

TICK_INTERVAL_S = 0.25
STANDALONE_ROOM = "party"


class BallotFrontend(pykka.ThreadingActor, CoreListener):
    """Runs the parties (standalone/hub) or the remote player (player mode)."""

    def __init__(self, config: Any, core: Any) -> None:
        super().__init__()
        self.config = config
        self.core = core
        self.settings = Settings.from_config(config["beatballot"])
        self.mode = self.settings.mode
        self.tidal: tidal_auth.TidalAuth | None = None
        self.agent: Any = None
        self.parties: Parties | None = None
        self.local_player: MopidyPlayer | None = None
        self._stopped = threading.Event()
        self._ticker: threading.Thread | None = None

        if self.mode == "player":
            from .agent import PlayerAgent  # noqa: PLC0415

            self.agent = PlayerAgent(config, core, self._data_dir())
            return

        library = MopidyPlayer(
            core, self.settings.search_schemes, login_pending=self.login_pending
        )
        if self.mode == "standalone":
            store = RoomStore()
            store.add(
                Room(
                    id=STANDALONE_ROOM,
                    slug=STANDALONE_ROOM,
                    name=self.settings.party_name or "Beat Ballot",
                    pin=self.settings.pin,
                    admin_pin=self.settings.admin_pin,
                    playlists=self.settings.playlists,
                    test_mode=self.settings.test_mode,
                    carry_over=self.settings.carry_over,
                )
            )
            self.local_player = library

            def make_player(room: Room) -> Any:
                return library

        else:
            from .remote import RemotePlayer, backend_resolver  # noqa: PLC0415

            store = RoomStore(self._data_dir() / "rooms.json")
            self._bootstrap_room(store)
            resolve = backend_resolver()

            def make_player(room: Room) -> Any:
                return RemotePlayer(library, resolve)

        rooms.STORE = store
        self.parties = Parties(
            self.settings,
            store,
            make_player,
            hub.HUB.broadcast,
            login_pending=self.login_pending,
            forget=hub.HUB.forget,
        )

    def _data_dir(self) -> Path:
        from . import Extension  # noqa: PLC0415

        return Path(Extension.get_data_dir(self.config))

    def _bootstrap_room(self, store: RoomStore) -> None:
        """A new hub starts with one party from the config's PINs, if given."""
        if store.list() or not (self.settings.pin and self.settings.admin_pin):
            return
        room = store.create(
            self.settings.party_name or "Beat Ballot",
            pin=self.settings.pin,
            admin_pin=self.settings.admin_pin,
            playlists=self.settings.playlists,
        )
        logger.info("Beat Ballot hub: created party %r from config", room.slug)

    # --- lifecycle -------------------------------------------------------

    def login_pending(self, source: str) -> bool:
        return source == "tidal" and self.tidal is not None and self.tidal.pending

    def _start_tidal_login(self) -> None:
        if "tidal" not in self.core.get_uri_schemes().get(timeout=20):
            return
        from mopidy._lib import paths  # noqa: PLC0415

        data_dir = paths.expand_path(self.config["core"]["data_dir"])
        tidal = self.config.get("tidal", {})
        proxy = self.actor_ref.proxy()
        self.tidal = tidal_auth.TidalAuth(
            Path(data_dir) / "tidal" / "tidal-oauth.json",
            tidal.get("client_id"),
            tidal.get("client_secret"),
            on_change=lambda: proxy.login_changed(),
        )
        tidal_auth.ACTIVE = self.tidal
        self.tidal.start()

    def login_changed(self) -> None:
        if self.parties is not None:
            self.parties.login_changed()

    def on_start(self) -> None:
        if self.agent is not None:
            self.agent.start(self.actor_ref.proxy())
        else:
            self._start_tidal_login()
            if self.local_player is not None:
                self.local_player.prepare()
            assert self.parties is not None
            self.parties.start()
        self._ticker = threading.Thread(
            target=self._run_ticker, name="BeatBallotTicker", daemon=True
        )
        self._ticker.start()

    def on_stop(self) -> None:
        self._stopped.set()
        if self.tidal is not None:
            self.tidal.stop()
        if self.agent is not None:
            self.agent.stop()

    def _run_ticker(self) -> None:
        proxy = self.actor_ref.proxy()
        while not self._stopped.wait(TICK_INTERVAL_S):
            try:
                proxy.tick().get(timeout=30)
            except pykka.ActorDeadError:
                return
            except Exception:
                logger.exception("Beat Ballot tick failed")

    def tick(self) -> None:
        if self.agent is not None:
            self.agent.tick()
        elif self.parties is not None:
            self.parties.tick()

    # Mopidy events: react straight away instead of waiting for the next tick.

    def _local_party(self) -> Any:
        if self.mode == "standalone" and self.parties is not None:
            return self.parties.parties.get(STANDALONE_ROOM)
        return None

    def track_playback_started(self, tl_track: Any) -> None:
        if self.agent is not None:
            self.agent.report()
        elif party := self._local_party():
            party.tick()

    def playback_state_changed(self, old_state: Any, new_state: Any) -> None:
        if self.agent is not None:
            self.agent.report()
        elif party := self._local_party():
            party.publish()

    def seeked(self, time_position: int) -> None:
        if self.agent is not None:
            self.agent.report()
        elif party := self._local_party():
            party.publish()

    # --- player mode: commands from the hub --------------------------------

    def agent_command(self, command: dict[str, Any]) -> None:
        self.agent.handle(command)

    # --- party API, used by the web layer ---------------------------------

    def _party(self, room_id: str) -> Any:
        assert self.parties is not None
        return self.parties.party(room_id)

    def snapshot(self, room_id: str) -> dict[str, Any]:
        party = self._party(room_id)
        room = rooms.STORE.get(room_id) if rooms.STORE else None
        return {**party.snapshot(), "room": room.public() if room else None}

    def vote(self, room_id: str, user_id: str, name: str, uri: str) -> None:
        self._party(room_id).vote(user_id, name, uri)

    def retract(self, room_id: str, user_id: str) -> None:
        self._party(room_id).retract(user_id)

    def suggest(self, room_id: str, user_id: str, name: str, track: TrackInfo) -> None:
        self._party(room_id).suggest(user_id, name, track)

    def admin(self, room_id: str, action: str, value: Any = None) -> None:
        assert self.parties is not None
        self.parties.admin(room_id, action, value)

    # --- hub owner API -----------------------------------------------------

    def overview(self, base_url: str) -> list[dict[str, Any]]:
        assert self.parties is not None
        return self.parties.overview(base_url)

    def create_room(self, fields: dict[str, Any]) -> dict[str, Any]:
        assert self.parties is not None
        return self.parties.create_room(**fields)

    def update_room(self, room_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        assert self.parties is not None
        return self.parties.update_room(room_id, changes)

    def delete_room(self, room_id: str) -> None:
        assert self.parties is not None
        self.parties.delete_room(room_id)

    # --- remote players (hub mode) ------------------------------------------

    def player_connected(self, room_id: str, send: Any, name: str | None) -> None:
        self._party(room_id).player.attach(send, name)
        self._party(room_id).publish()

    def player_status(self, room_id: str, status: dict[str, Any]) -> None:
        party = self.parties.parties.get(room_id) if self.parties else None
        if party is not None:
            party.player.update(status)

    def player_disconnected(self, room_id: str, send: Any) -> None:
        party = self.parties.parties.get(room_id) if self.parties else None
        if party is not None:
            party.player.detach(send)
            party.publish()
