"""Player mode: play what a Beat Ballot hub sends, through local Mopidy.

The agent connects out to the hub (works behind any router), pairs once with
a code from the hub page, and keeps the token in its data dir. It only ever
receives stream URLs or DASH manifests for single songs, never logins.

``handle``, ``report`` and ``tick`` run on the frontend actor's thread; the
WebSocket runs on its own asyncio thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .player import TIMEOUT, MopidyPlayer
from .settings import Settings

logger = logging.getLogger(__name__)

REPORT_EVERY_S = 1.0
# Some proxies (e.g. Cloudflare's browser check) block Python's default agent.
USER_AGENT = "BeatBallot-Player/{} (+https://github.com/FredHaa/mopidy-beatballot)"
MAX_BACKOFF_S = 30.0

# The running agent, for the player-mode health endpoint.
ACTIVE: PlayerAgent | None = None


def hub_base(url: str) -> str:
    """https://host[/beatballot] -> https://host/beatballot"""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url if url.endswith("/beatballot") else f"{url}/beatballot"


class PairingError(Exception):
    pass


class PlayerAgent:
    def __init__(self, config: Any, core: Any, data_dir: Path) -> None:
        settings = Settings.from_config(config["beatballot"])
        if not settings.hub_url:
            raise ValueError("Player mode needs hub_url (BALLOT_HUB_URL)")
        self.base = hub_base(settings.hub_url)
        self.pair_code = settings.pair_code
        self.name = settings.player_name or socket.gethostname()
        from . import __version__  # noqa: PLC0415

        self.user_agent = USER_AGENT.format(__version__)
        self.core = core
        self.player = MopidyPlayer(core)
        self.token_file = data_dir / "player-token"
        self.manifest_dir = data_dir / "manifests"
        self.ids: dict[int, int] = {}  # hub song id -> local tlid
        self.ack = 0
        self.connected = False
        self.room: dict[str, Any] | None = None
        self.last_error: str | None = None
        self._last_report = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None
        self._stop = threading.Event()
        self._proxy: Any = None

    # --- lifecycle (actor thread) ------------------------------------------

    def start(self, proxy: Any) -> None:
        global ACTIVE
        ACTIVE = self
        self._proxy = proxy
        self.player.prepare()
        self.core.tracklist.clear().get(timeout=TIMEOUT)
        threading.Thread(target=self._run, name="BeatBallotAgent", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def tick(self) -> None:
        if time.monotonic() - self._last_report >= REPORT_EVERY_S:
            self.report()

    # --- commands from the hub (actor thread) --------------------------------

    def handle(self, command: dict[str, Any]) -> None:
        cmd = command.get("cmd")
        try:
            match cmd:
                case "_connected":
                    self.ack = 0
                case "enqueue":
                    self._enqueue(command)
                case "remove":
                    tlid = self.ids.pop(int(command["id"]), None)
                    if tlid is not None:
                        self.core.tracklist.remove({"tlid": [tlid]}).get(
                            timeout=TIMEOUT
                        )
                case "play":
                    self.player.play()
                case "next":
                    self.player.next()
                case "pause":
                    self.player.pause()
                case "resume":
                    self.player.resume()
                case _:
                    logger.warning("Beat Ballot player: unknown command %r", cmd)
        except Exception:
            logger.exception("Beat Ballot player: %s failed", cmd)
        if "seq" in command:
            self.ack = max(self.ack, int(command["seq"]))
        self.report()

    def _enqueue(self, command: dict[str, Any]) -> None:
        from mopidy.models import Artist, Track  # noqa: PLC0415

        song_id = int(command["id"])
        if command.get("manifest"):
            self.manifest_dir.mkdir(parents=True, exist_ok=True)
            path = self.manifest_dir / f"{song_id}.mpd"
            path.write_text(command["manifest"])
            uri = path.as_uri()
        else:
            uri = command["url"]
        artist = command.get("artist")
        track = Track(
            uri=uri,
            name=command.get("title") or None,
            artists=frozenset({Artist(name=artist)}) if artist else frozenset(),
            length=command.get("length_ms"),
        )
        # Passing a Track skips Mopidy's metadata scan of the stream.
        added = self.core.tracklist.add(tracks=[track]).get(timeout=TIMEOUT)
        if added:
            self.ids[song_id] = added[0].tlid

    # --- status to the hub (actor thread) ------------------------------------

    def status(self) -> dict[str, Any]:
        by_tlid = {tlid: song for song, tlid in self.ids.items()}
        queued = [tlid for tlid, _ in self.player.queue()]
        current = self.player.current()
        current_tlid = current[0] if current else None
        live = set(queued) | {current_tlid}
        self.ids = {s: t for s, t in self.ids.items() if t in live}
        for path in (
            self.manifest_dir.glob("*.mpd") if self.manifest_dir.exists() else []
        ):
            if path.stem.isdigit() and int(path.stem) not in self.ids:
                path.unlink(missing_ok=True)
        return {
            "type": "status",
            "state": self.player.state(),
            "position_ms": self.player.position_ms(),
            "current": by_tlid.get(current_tlid),
            "queue": [by_tlid[t] for t in queued if t in by_tlid],
            "ack": self.ack,
        }

    def report(self) -> None:
        self._last_report = time.monotonic()
        if not self.connected or self._loop is None:
            return
        try:
            message = json.dumps(self.status())
        except Exception:
            logger.exception("Beat Ballot player: status failed")
            return
        self._loop.call_soon_threadsafe(self._write, message)

    # --- connection (asyncio thread) ------------------------------------------

    def _write(self, message: str) -> None:
        if self._ws is not None:
            try:
                self._ws.write_message(message)
            except Exception:
                logger.debug("Beat Ballot player: write failed", exc_info=True)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._main())
        except RuntimeError:
            pass  # Loop stopped on shutdown.
        finally:
            loop.close()

    def _token(self) -> str:
        try:
            return self.token_file.read_text().strip()
        except FileNotFoundError:
            pass
        if not self.pair_code:
            raise PairingError(
                "Not paired yet: set BALLOT_PAIR_CODE to a code from the hub page"
            )
        request = urllib.request.Request(
            f"{self.base}/api/player/pair",
            data=json.dumps({"code": self.pair_code, "name": self.name}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": self.user_agent},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as res:
                data = json.load(res)
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                detail = json.loads(body).get("error", e.reason)
            except ValueError:
                detail = f"HTTP {e.code}: {body[:120].decode(errors='replace')}"
            raise PairingError(f"Pairing failed: {detail}") from e
        except ValueError as e:
            raise PairingError("Pairing failed: the hub didn't answer with JSON") from e
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(data["token"])
        os.chmod(self.token_file, 0o600)
        logger.info("Beat Ballot player: paired with %r", data["room"]["name"])
        return data["token"]

    async def _main(self) -> None:
        from tornado.httpclient import HTTPRequest  # noqa: PLC0415
        from tornado.websocket import websocket_connect  # noqa: PLC0415

        backoff = 1.0
        ws_url = self.base.replace("https://", "wss://").replace("http://", "ws://")
        while not self._stop.is_set():
            try:
                token = await asyncio.get_running_loop().run_in_executor(
                    None, self._token
                )
                request = HTTPRequest(
                    f"{ws_url}/player/ws",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Player-Name": self.name,
                        "User-Agent": self.user_agent,
                    },
                )
                ws = await websocket_connect(request, ping_interval=20, ping_timeout=15)
            except PairingError as e:
                self.last_error = str(e)
                logger.error("Beat Ballot player: %s", e)
                await asyncio.sleep(MAX_BACKOFF_S)
                continue
            except Exception as e:
                self.last_error = f"Can't reach the hub: {e}"
                if getattr(e, "code", None) == 401:
                    self.last_error = "The hub rejected this player; pair it again"
                    if self.token_file.exists() and self.pair_code:
                        self.token_file.unlink()  # Retry pairing with the code.
                logger.warning("Beat Ballot player: %s", self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(MAX_BACKOFF_S, backoff * 2)
                continue
            backoff = 1.0
            self._ws = ws
            self.connected = True
            self.last_error = None
            self._proxy.agent_command({"cmd": "_connected"})
            logger.info("Beat Ballot player: connected to %s", self.base)
            while True:
                message = await ws.read_message()
                if message is None:
                    break
                try:
                    data = json.loads(message)
                except ValueError:
                    continue
                if data.get("type") == "hello":
                    self.room = data.get("room")
                    logger.info("Beat Ballot player: playing party %r", self.room)
                elif "cmd" in data:
                    self._proxy.agent_command(data)  # FIFO, so order is kept.
            self.connected = False
            self._ws = None
            close = ws.close_code
            if close == 4001:
                self.last_error = "The hub unpaired this player"
                logger.error("Beat Ballot player: %s; pair it again", self.last_error)
                self.token_file.unlink(missing_ok=True)
            else:
                logger.warning("Beat Ballot player: lost the hub, reconnecting")
            await asyncio.sleep(1)

    def health(self) -> dict[str, Any]:
        return {
            "ok": self.connected,
            "hub": self.base,
            "room": self.room,
            "error": self.last_error,
        }
