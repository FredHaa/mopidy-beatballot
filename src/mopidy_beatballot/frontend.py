from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import pykka
from mopidy.core import CoreListener

from . import hub, tidal_auth
from .party import PartyController
from .player import MopidyPlayer
from .settings import Settings
from .tracks import TrackInfo

logger = logging.getLogger(__name__)

TICK_INTERVAL_S = 0.25


class BallotFrontend(pykka.ThreadingActor, CoreListener):
    def __init__(self, config: Any, core: Any) -> None:
        super().__init__()
        self.config = config
        self.core = core
        self.settings = Settings.from_config(config["beatballot"])
        self.tidal: tidal_auth.TidalAuth | None = None
        self.player = MopidyPlayer(
            core, self.settings.search_schemes, login_pending=self.login_pending
        )
        self.party = PartyController(
            self.settings,
            self.player,
            hub.HUB.broadcast,
            login_pending=self.login_pending,
        )
        self._stopped = threading.Event()
        self._ticker: threading.Thread | None = None

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
        self.party.login_changed()

    def on_start(self) -> None:
        self._start_tidal_login()
        self.player.prepare()
        self.party.start()
        self._ticker = threading.Thread(
            target=self._run_ticker, name="BeatBallotTicker", daemon=True
        )
        self._ticker.start()

    def on_stop(self) -> None:
        self._stopped.set()
        if self.tidal is not None:
            self.tidal.stop()

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
        self.party.tick()

    # Mopidy events: react straight away instead of waiting for the next tick.

    def track_playback_started(self, tl_track: Any) -> None:
        self.party.tick()

    def playback_state_changed(self, old_state: Any, new_state: Any) -> None:
        self.party.publish()

    def seeked(self, time_position: int) -> None:
        self.party.publish()

    # API used by the web layer through the actor proxy.

    def snapshot(self) -> dict[str, Any]:
        return self.party.snapshot()

    def vote(self, user_id: str, name: str, uri: str) -> None:
        self.party.vote(user_id, name, uri)

    def retract(self, user_id: str) -> None:
        self.party.retract(user_id)

    def suggest(self, user_id: str, name: str, track: TrackInfo) -> None:
        self.party.suggest(user_id, name, track)

    def admin(self, action: str, value: Any = None) -> None:
        match action:
            case "skip":
                self.party.skip()
            case "pause":
                self.party.pause()
            case "resume":
                self.party.resume()
            case "test_mode":
                self.party.set_test_mode(bool(value))
            case "carry_over":
                self.party.set_carry_over(bool(value))
            case "remove":
                self.party.remove_candidate(str(value))
            case "playlists":
                self.party.set_playlists(str(value))
            case _:
                raise ValueError(f"Unknown admin action {action!r}")
