"""Music service logins managed from the web app.

Tidal's device login lives in tidal_auth.py; this module holds SoundCloud's
token and the restart Mopidy needs to start or stop a music backend (it only
loads backends at startup). The Docker entrypoint enables a service whenever
a saved login exists, and Docker's restart policy brings the container back.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SOUNDCLOUD_TOKEN_FILE = "soundcloud-token"  # read by docker/entrypoint.sh
SOUNDCLOUD_ACCOUNT_FILE = "soundcloud-account"
SOUNDCLOUD_ME = "https://api.soundcloud.com/me"
# Where to get a token: SoundCloud no longer registers new API apps, so
# Mopidy-SoundCloud's own login page hands out tokens.
SOUNDCLOUD_TOKEN_PAGE = "https://mopidy.com/ext/soundcloud/#authentication"


class ServiceError(Exception):
    pass


# Set in the Docker image, whose restart policy starts Mopidy again. Elsewhere
# stopping Mopidy would just stop it, so the host restarts it instead.
CAN_RESTART = os.environ.get("BALLOT_SELF_RESTART") == "1"


def restart_soon(reason: str, delay: float = 1.5) -> bool:
    """Stop Mopidy cleanly so it restarts with the music backends that now
    have a login. False if it can't restart itself."""
    if not CAN_RESTART:
        logger.warning("Beat Ballot: restart Mopidy to %s", reason)
        return False
    logger.warning("Beat Ballot: restarting to %s", reason)
    timer = threading.Timer(delay, os.kill, args=(os.getpid(), signal.SIGTERM))
    timer.daemon = True
    timer.start()
    return True


def soundcloud_username(
    token: str, fetch: Callable[[urllib.request.Request], Any] | None = None
) -> str:
    """The SoundCloud account a token belongs to; raises ServiceError if the
    token doesn't work."""
    request = urllib.request.Request(
        SOUNDCLOUD_ME,
        headers={"Authorization": f"OAuth {token}", "User-Agent": "BeatBallot"},
    )
    opener = fetch or (lambda r: urllib.request.urlopen(r, timeout=15))
    try:
        with opener(request) as response:
            me = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ServiceError("SoundCloud didn't accept that token") from e
        raise ServiceError(f"SoundCloud answered HTTP {e.code}; try again") from e
    except (OSError, ValueError) as e:
        raise ServiceError("Couldn't reach SoundCloud; try again") from e
    return str(me.get("username") or me.get("permalink") or "your account")


class SoundCloudAccount:
    """The SoundCloud token: saved from the web app, or from the server config."""

    def __init__(self, data_dir: Path, config_token: str | None, enabled: bool) -> None:
        self.token_file = data_dir / SOUNDCLOUD_TOKEN_FILE
        self.account_file = data_dir / SOUNDCLOUD_ACCOUNT_FILE
        self.enabled = enabled  # Is Mopidy-SoundCloud running right now?
        # The Docker entrypoint puts a saved token into the config, so that one
        # isn't a separate server-settings token.
        saved = self._saved_token()
        self.config_token = (config_token or None) if config_token != saved else None

    def _saved_token(self) -> str | None:
        try:
            return self.token_file.read_text().strip() or None
        except FileNotFoundError:
            return None

    @property
    def source(self) -> str | None:
        """'web' (saved here), 'config' (server settings) or None."""
        if self._saved_token():
            return "web"
        return "config" if self.config_token else None

    def status(self) -> dict[str, Any]:
        try:
            account = self.account_file.read_text().strip() or None
        except FileNotFoundError:
            account = None
        return {
            "connected": self.source is not None,
            "source": self.source,
            "account": account,
            "enabled": self.enabled,
            "token_page": SOUNDCLOUD_TOKEN_PAGE,
        }

    def save(self, token: str, username: str) -> bool:
        """Save a checked token. True if Mopidy must restart to use it."""
        changed = token != (self._saved_token() or self.config_token)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(token)
        self.token_file.chmod(0o600)
        self.account_file.write_text(username)
        return changed or not self.enabled

    def disconnect(self) -> bool:
        """Forget the saved token. True if Mopidy must restart."""
        if self.source == "config":
            raise ServiceError(
                "This token is in the server settings (SOUNDCLOUD_AUTH_TOKEN); "
                "remove it there"
            )
        self.token_file.unlink(missing_ok=True)
        self.account_file.unlink(missing_ok=True)
        return self.enabled


# The running account, for the web layer (set by the frontend).
SOUNDCLOUD: SoundCloudAccount | None = None
