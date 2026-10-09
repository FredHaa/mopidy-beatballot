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
    """Songs random candidates are drawn from, without repeats: the playlists'
    songs plus songs that dropped off the ballot (e.g. guests' suggestions)."""

    def __init__(self, rng: random.Random, discarded_weight: float = 3) -> None:
        self._rng = rng
        # How much likelier a discarded song is to be drawn than a playlist song.
        self.discarded_weight = discarded_weight
        self._playlist_tracks: list[TrackInfo] = []
        self.discarded: dict[str, TrackInfo] = {}
        self.tracks: list[TrackInfo] = []
        self.played: set[str] = set()

    def load(self, tracks: Iterable[TrackInfo]) -> None:
        """Replace the playlists' songs. Discarded songs stay."""
        self._playlist_tracks = list(tracks)
        self._rebuild()

    def add_discarded(self, tracks: Iterable[TrackInfo]) -> None:
        """Songs that dropped off the ballot (e.g. guests' suggestions) become
        random picks too, drawn ``discarded_weight`` times as often as playlist
        songs. Playlist songs that lost just count as shown, so the rest of the
        playlist comes up first.
        """
        known_songs = {song_key(t) for t in self.tracks}
        for track in tracks:
            if track.uri in self.discarded:
                continue  # Lost again: stays in, as likely as before.
            if song_key(track) in known_songs:
                self.played.add(track.uri)  # A playlist song.
            else:
                self.discarded[track.uri] = track
        self._rebuild()

    def _rebuild(self) -> None:
        by_uri: dict[str, TrackInfo] = {}
        songs: set[tuple[str, str]] = set()
        for track in [*self._playlist_tracks, *self.discarded.values()]:
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
        *,
        guarantee_discarded: bool = True,
    ) -> list[TrackInfo]:
        """n random songs. With ``guarantee_discarded``, one of them is a
        discarded song whenever one is available; the rest are drawn with
        discarded songs weighted up."""
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
        picks: list[TrackInfo] = []
        if guarantee_discarded and n > 0:
            discarded = [t for t in available if t.uri in self.discarded]
            if discarded:
                picks.append(self._rng.choice(discarded))
                available = [t for t in available if t.uri != picks[0].uri]
        return picks + self._weighted_sample(available, n - len(picks))

    def _weighted_sample(self, tracks: list[TrackInfo], n: int) -> list[TrackInfo]:
        """n songs without replacement, discarded songs weighted up.

        Each song gets the key random() ** (1 / weight) and the highest keys
        win (Efraimidis-Spirakis), so a weight-3 song is drawn 3x as often.
        """

        def key(track: TrackInfo) -> float:
            weight = self.discarded_weight if track.uri in self.discarded else 1
            return self._rng.random() ** (1 / max(weight, 1e-9))

        return sorted(tracks, key=key, reverse=True)[: max(0, n)]
