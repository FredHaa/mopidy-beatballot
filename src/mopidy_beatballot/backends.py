"""Music services: names and playlist links."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse

SOURCE_NAMES = {
    "spotify": "Spotify",
    "tidal": "Tidal",
    "soundcloud": "SoundCloud",
    "file": "Local",
    "local": "Local",
}
# Search scope (Mopidy URI scheme) for each backend name used in config.
SEARCH_SCHEMES = {"spotify": "spotify", "tidal": "tidal", "soundcloud": "soundcloud"}


def source_of(uri: str) -> str:
    """The service a track URI belongs to, e.g. ``spotify`` or ``tidal``."""
    scheme = uri.split(":", 1)[0]
    return "soundcloud" if scheme == "sc" else scheme


def source_name(source: str) -> str:
    return SOURCE_NAMES.get(source, source.capitalize())


_SPOTIFY = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?playlist/([A-Za-z0-9]+)")
_TIDAL = re.compile(r"tidal\.com/(?:browse/)?playlist/([0-9a-fA-F-]{36})")


def normalize_playlist(value: str) -> str:
    """Turn a share link into a Mopidy URI; URIs pass through unchanged."""
    value = value.strip()
    if m := _SPOTIFY.search(value):
        return f"spotify:playlist:{m.group(1)}"
    if m := _TIDAL.search(value):
        return f"tidal:playlist:{m.group(1).lower()}"
    url = urlparse(value)
    if url.scheme in ("http", "https") and url.netloc.endswith("soundcloud.com"):
        # Mopidy-SoundCloud looks up sets via the page URL.
        return f"sc:https://soundcloud.com{url.path.rstrip('/')}"
    if url.scheme in ("spotify", "tidal"):
        return value.split("?", 1)[0]  # A pasted URI can keep the "?si=" suffix.
    return value


def split_list(value: str | Iterable[str] | None) -> list[str]:
    """Comma/newline separated text (or a list) to a clean list."""
    if value is None:
        return []
    items = re.split(r"[,\n]", value) if isinstance(value, str) else value
    return [i.strip() for i in items if i and i.strip()]
