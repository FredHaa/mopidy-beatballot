from __future__ import annotations

import random
from collections.abc import Iterable

from .backends import source_of
from .tracks import TrackInfo


def song_key(track: TrackInfo) -> tuple[str, str]:
    """Identifies the same song on different services."""
    artist = track.artists[0] if track.artists else ""
    return track.name.casefold().strip(), artist.casefold().strip()


class Pool:
    """Tracks from all playlists that random candidates are drawn from,
    without repeats."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.tracks: list[TrackInfo] = []
        self.played: set[str] = set()

    def load(self, tracks: Iterable[TrackInfo]) -> None:
        by_uri: dict[str, TrackInfo] = {}
        songs: set[tuple[str, str]] = set()
        for track in tracks:
            key = song_key(track)
            if track.uri in by_uri or key in songs:
                continue  # Same song from another playlist or service.
            by_uri[track.uri] = track
            songs.add(key)
        self.tracks = list(by_uri.values())
        self.played &= set(by_uri)

    def __len__(self) -> int:
        return len(self.tracks)

    def sources(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for track in self.tracks:
            source = source_of(track.uri)
            counts[source] = counts.get(source, 0) + 1
        return counts

    def mark_played(self, uri: str) -> None:
        self.played.add(uri)

    def pick(
        self,
        n: int,
        exclude: Iterable[str] = (),
        skip_sources: Iterable[str] = (),
    ) -> list[TrackInfo]:
        excluded = set(exclude)
        skipped = set(skip_sources)
        usable = [
            t
            for t in self.tracks
            if t.uri not in excluded and source_of(t.uri) not in skipped
        ]
        available = [t for t in usable if t.uri not in self.played]
        if len(available) < n:
            # Everything has been played: start over, but don't repeat the
            # candidates already on the table.
            self.played -= {t.uri for t in usable}
            available = usable
        return self._rng.sample(available, min(n, len(available)))
