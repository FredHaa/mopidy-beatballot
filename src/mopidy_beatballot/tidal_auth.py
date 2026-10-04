"""Tidal device login, run by Beat Ballot instead of Mopidy-Tidal.

Mopidy-Tidal logs in on first use and blocks its backend, and with it all of
Mopidy's core, until someone approves the login. Instead, Beat Ballot runs the
login in a background thread, shows the link to the host, and writes the
session file Mopidy-Tidal loads lazily. Until then Beat Ballot keeps every
request away from the Tidal backend.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tracks import TrackInfo

logger = logging.getLogger(__name__)

RETRY_DELAY_S = 5.0

# The running login, for the web layer's host panel.
ACTIVE: TidalAuth | None = None


def _default_session(client_id: str | None, client_secret: str | None) -> Any:
    import tidalapi  # noqa: PLC0415

    config = tidalapi.Config()
    if client_id and client_secret:
        config.client_id = client_id
        config.client_secret = client_secret
    return tidalapi.Session(config)


class TidalAuth:
    def __init__(
        self,
        session_file: Path,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        session_factory: Callable[[], Any] | None = None,
        on_change: Callable[[], None] = lambda: None,
    ) -> None:
        self.session_file = session_file
        self._new_session = session_factory or (
            lambda: _default_session(client_id, client_secret)
        )
        self._on_change = on_change
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self.state = "checking"  # checking | logged_in | pending | error
        self.session: Any = None  # The logged-in session, reused for search.
        self._search_lock = threading.Lock()
        self.url: str | None = None
        self.code: str | None = None
        self.expires_at: float | None = None

    @property
    def pending(self) -> bool:
        """True until a valid session file exists."""
        return self.state != "logged_in"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "url": self.url,
                "code": self.code,
                "expires_in": (
                    max(0, int(self.expires_at - time.time()))
                    if self.expires_at
                    else None
                ),
            }

    def start(self) -> None:
        threading.Thread(target=self._run, name="TidalAuth", daemon=True).start()

    def stop(self) -> None:
        self._stopped.set()

    def search_tracks(self, query: str, limit: int) -> list[TrackInfo] | None:
        """Search Tidal for tracks directly: one API request.

        Mopidy-Tidal's search also fetches the top tracks of every matching
        artist and the tracks of every matching album (~100 requests, ~5 s).
        Returns None when not logged in, so the caller can fall back.
        """
        session = self.session
        if session is None:
            return None
        import tidalapi  # noqa: PLC0415

        with self._search_lock:  # One requests.Session, used from web threads.
            found = session.search(query, models=[tidalapi.Track], limit=limit)
        tracks = []
        for t in found.get("tracks", [])[:limit]:
            album = getattr(t, "album", None)
            artists = getattr(t, "artists", None) or [t.artist]
            image = None
            if album is not None and getattr(album, "cover", None):
                image = album.image(320)
            tracks.append(
                TrackInfo(
                    # Same URI format as Mopidy-Tidal, which plays them.
                    uri=f"tidal:track:{t.artist.id}:{album.id if album else 0}:{t.id}",
                    name=getattr(t, "full_name", None) or t.name,
                    artists=tuple(a.name for a in artists if a and a.name),
                    album=album.name if album else "",
                    length_ms=t.duration * 1000 if t.duration else None,
                    image=image,
                )
            )
        return tracks

    def _set(self, state: str, **fields: Any) -> None:
        with self._lock:
            self.state = state
            self.url = fields.get("url")
            self.code = fields.get("code")
            self.expires_at = fields.get("expires_at")
        self._on_change()

    def _run(self) -> None:
        try:
            session = self._new_session()
            if (
                session.load_session_from_file(self.session_file)
                and session.check_login()
            ):
                logger.info("Beat Ballot: Tidal session is valid")
                self.session = session
                self._set("logged_in")
                return
        except Exception:
            logger.exception("Beat Ballot: checking the Tidal session failed")
        while not self._stopped.is_set():
            try:
                session = self._new_session()
                link, future = session.login_oauth()
                url = link.verification_uri_complete
                url = url if url.startswith("http") else f"https://{url}"
                logger.warning("Beat Ballot: log in to Tidal at %s", url)
                self._set(
                    "pending",
                    url=url,
                    code=link.user_code,
                    expires_at=time.time() + link.expires_in,
                )
                future.result()  # Raises TimeoutError when the link expires.
                self.session_file.parent.mkdir(parents=True, exist_ok=True)
                session.save_session_to_file(self.session_file)
                logger.info("Beat Ballot: Tidal login OK")
                self.session = session
                self._set("logged_in")
                return
            except TimeoutError:
                logger.info("Beat Ballot: Tidal login link expired, making a new one")
            except Exception:
                logger.exception("Beat Ballot: Tidal login failed")
                self._set("error")
                self._stopped.wait(RETRY_DELAY_S * 6)
                continue
            self._stopped.wait(RETRY_DELAY_S)
