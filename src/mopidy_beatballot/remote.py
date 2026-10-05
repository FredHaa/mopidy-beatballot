"""The hub's side of a remote player.

``RemotePlayer`` implements the ``Player`` protocol for ``PartyController``
by sending commands to a paired player over its WebSocket and mirroring the
status the player reports. The player never gets account credentials: the
hub resolves each song to a short-lived stream URL (or DASH manifest) with
its own logins, and that is all it sends.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .tracks import TrackInfo

logger = logging.getLogger(__name__)

PLAYING = "playing"
STOPPED = "stopped"
MAX_TRACKS_KEPT = 64

type Send = Callable[[dict[str, Any]], None]
type Resolve = Callable[[str], dict[str, str]]


class NotRemotelyPlayable(Exception):
    """The song's service can't give a stream URL (e.g. Spotify)."""


class RemotePlayer:
    def __init__(
        self,
        library: Any,
        resolve: Resolve,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.library = library  # Hub-side library: playlists, images.
        self._resolve = resolve
        self._clock = clock
        self._send: Send | None = None
        self.player_name: str | None = None
        self.connected_at: float | None = None
        self._seq = 0  # Commands sent on the current connection.
        # Random start, so ids from before a hub restart never collide.
        self._next_id = secrets.randbelow(1 << 30) << 16
        self._tracks: dict[int, TrackInfo] = {}
        self._state = STOPPED
        self._position = 0
        self._position_at = clock()
        self._current: int | None = None
        self._queue: list[int] = []

    # --- connection ------------------------------------------------------

    @property
    def online(self) -> bool:
        return self._send is not None

    def attach(self, send: Send, name: str | None = None) -> None:
        """A player connected. Music it is already playing keeps playing."""
        self._send = send
        self.player_name = name
        self.connected_at = self._clock()
        self._seq = 0

    def detach(self, send: Send | None = None) -> None:
        if send is None or send == self._send:
            self._send = None
            self._state = STOPPED

    def update(self, status: dict[str, Any]) -> None:
        """A status report from the player."""
        self._state = str(status.get("state", STOPPED))
        self._position = int(status.get("position_ms") or 0)
        self._position_at = self._clock()
        # Reports sent before our latest command don't know about it yet, so
        # keep the optimistic queue until the player has caught up.
        if int(status.get("ack", -1)) >= self._seq:
            current = status.get("current")
            self._current = current if current in self._tracks else None
            self._queue = [i for i in status.get("queue", []) if i in self._tracks]
            self._forget_old()

    def _command(self, cmd: str, **fields: Any) -> None:
        if self._send is None:
            raise ConnectionError("The player is offline")
        self._seq += 1
        self._send({"cmd": cmd, "seq": self._seq, **fields})

    def _forget_old(self) -> None:
        if len(self._tracks) <= MAX_TRACKS_KEPT:
            return
        keep = set(self._queue) | ({self._current} if self._current else set())
        for track_id in sorted(self._tracks)[: len(self._tracks) - MAX_TRACKS_KEPT]:
            if track_id not in keep:
                del self._tracks[track_id]

    # --- Player protocol ---------------------------------------------------

    def state(self) -> str:
        return self._state if self.online else STOPPED

    def position_ms(self) -> int:
        if self._state != PLAYING:
            return self._position
        return self._position + int((self._clock() - self._position_at) * 1000)

    def current(self) -> tuple[int, TrackInfo] | None:
        if self._current is None or not self.online:
            return None
        return self._current, self._tracks[self._current]

    def tracklist_length(self) -> int:
        return len(self._queue)

    def queue(self) -> list[tuple[int, TrackInfo]]:
        return [(i, self._tracks[i]) for i in self._queue]

    def enqueue(self, uri: str, track: TrackInfo | None = None) -> None:
        if not self.online:
            raise ConnectionError("The player is offline")
        source = self._resolve(uri)  # Raises NotRemotelyPlayable.
        track = track or self.library.lookup(uri) or TrackInfo(uri, uri)
        self._next_id += 1
        track_id = self._next_id
        self._tracks[track_id] = track
        self._command(
            "enqueue",
            id=track_id,
            title=track.name,
            artist=", ".join(track.artists),
            length_ms=track.length_ms,
            **source,
        )
        self._queue.append(track_id)

    def remove(self, tlid: int) -> None:
        self._command("remove", id=tlid)
        self._queue = [i for i in self._queue if i != tlid]
        if self._current == tlid:
            self._current = None

    def play(self) -> None:
        self._command("play")

    def next(self) -> None:
        self._command("next")

    def pause(self) -> None:
        self._command("pause")
        self._state = "paused"

    def resume(self) -> None:
        self._command("resume")

    def load_playlist(self, uri: str) -> list[TrackInfo]:
        return self.library.load_playlist(uri)

    def images(self, uris: Iterable[str]) -> dict[str, str]:
        return self.library.images(uris)


def backend_resolver(timeout: float = 30) -> Resolve:
    """Resolve a song URI to a stream with the hub's own Mopidy backends.

    Uses each backend's ``translate_uri``, the same call Mopidy makes before
    playing: Tidal returns a signed CDN URL valid for about an hour (or a DASH
    manifest at hi-res quality), SoundCloud a stream URL. Spotify streams
    through the account itself, so it can't play remotely.
    """
    import pykka  # noqa: PLC0415
    from mopidy.backend import Backend  # noqa: PLC0415

    backends: dict[str, Any] = {}

    def find(scheme: str) -> Any:
        if scheme not in backends:
            for ref in pykka.ActorRegistry.get_all():
                if issubclass(ref.actor_class, Backend):
                    proxy = ref.proxy()
                    for s in proxy.uri_schemes.get(timeout=timeout):
                        backends.setdefault(s, proxy)
        return backends.get(scheme)

    def resolve(uri: str) -> dict[str, str]:
        scheme = uri.split(":", 1)[0]
        if scheme == "spotify":
            raise NotRemotelyPlayable("Spotify songs can only play on the hub itself")
        backend = find(scheme)
        if backend is None:
            raise NotRemotelyPlayable(f"No backend for {scheme} songs")
        url = backend.playback.translate_uri(uri).get(timeout=timeout)
        if not url:
            raise NotRemotelyPlayable("The service has no stream for this song")
        if url.startswith(("http://", "https://")):
            return {"url": url}
        if url.startswith("file://") and url.endswith(".mpd"):
            # Hi-res Tidal: the manifest lists signed segment URLs.
            return {"manifest": Path(url.removeprefix("file://")).read_text()}
        raise NotRemotelyPlayable(f"Can't stream {scheme} songs to a remote player")

    return resolve
