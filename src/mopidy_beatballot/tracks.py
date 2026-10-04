from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .backends import source_of


@dataclass(frozen=True)
class TrackInfo:
    """A Mopidy-independent snapshot of a track."""

    uri: str
    name: str
    artists: tuple[str, ...] = ()
    album: str = ""
    length_ms: int | None = None
    image: str | None = field(default=None, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "artists": list(self.artists),
            "album": self.album,
            "length_ms": self.length_ms,
            "image": self.image,
            "source": source_of(self.uri),
        }
