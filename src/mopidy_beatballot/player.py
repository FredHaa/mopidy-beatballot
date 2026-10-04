"""Adapter from Mopidy's core API to the small ``Player`` protocol."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from .backends import source_of
from .tracks import TrackInfo

if TYPE_CHECKING:
    from mopidy.models import Track

logger = logging.getLogger(__name__)

TIMEOUT = 20


def track_info(track: Track) -> TrackInfo:
    return TrackInfo(
        uri=track.uri,
        name=track.name or track.uri,
        artists=tuple(sorted(a.name for a in track.artists if a.name)),
        album=(track.album.name or "") if track.album else "",
        length_ms=track.length,
    )


class MopidyPlayer:
    def __init__(
        self,
        core: Any,
        search_schemes: Iterable[str] = (),
        login_pending: Callable[[str], bool] = lambda source: False,
    ) -> None:
        self.core = core
        self.search_schemes = list(search_schemes)
        self.login_pending = login_pending

    def prepare(self) -> None:
        """Put the tracklist in the mode Beat Ballot expects: a play-once queue."""
        tracklist = self.core.tracklist
        tracklist.set_consume(True).get(timeout=TIMEOUT)
        tracklist.set_repeat(False).get(timeout=TIMEOUT)
        tracklist.set_random(False).get(timeout=TIMEOUT)
        tracklist.set_single(False).get(timeout=TIMEOUT)
        if self.state() == "stopped":
            tracklist.clear().get(timeout=TIMEOUT)

    def state(self) -> str:
        return str(self.core.playback.get_state().get(timeout=TIMEOUT))

    def position_ms(self) -> int:
        return self.core.playback.get_time_position().get(timeout=TIMEOUT) or 0

    def current(self) -> tuple[int, TrackInfo] | None:
        tl_track = self.core.playback.get_current_tl_track().get(timeout=TIMEOUT)
        if tl_track is None:
            return None
        return tl_track.tlid, track_info(tl_track.track)

    def tracklist_length(self) -> int:
        return self.core.tracklist.get_length().get(timeout=TIMEOUT)

    def queue(self) -> list[tuple[int, TrackInfo]]:
        tl_tracks = self.core.tracklist.get_tl_tracks().get(timeout=TIMEOUT)
        return [(t.tlid, track_info(t.track)) for t in tl_tracks]

    def enqueue(self, uri: str) -> None:
        self.core.tracklist.add(uris=[uri]).get(timeout=TIMEOUT)

    def remove(self, tlid: int) -> None:
        self.core.tracklist.remove({"tlid": [tlid]}).get(timeout=TIMEOUT)

    def play(self) -> None:
        """Start the current track, or the first queued one if there is none."""
        tl_tracks = self.core.tracklist.get_tl_tracks().get(timeout=TIMEOUT)
        if not tl_tracks:
            return
        current = self.core.playback.get_current_tl_track().get(timeout=TIMEOUT)
        tlids = [t.tlid for t in tl_tracks]
        tlid = current.tlid if current and current.tlid in tlids else tlids[0]
        self.core.playback.play(tlid=tlid).get(timeout=TIMEOUT)

    def next(self) -> None:
        self.core.playback.next().get(timeout=TIMEOUT)

    def pause(self) -> None:
        self.core.playback.pause().get(timeout=TIMEOUT)

    def resume(self) -> None:
        self.core.playback.resume().get(timeout=TIMEOUT)

    def load_playlist(self, uri: str) -> list[TrackInfo]:
        tracks = (
            self.core.library.lookup(uris=[uri]).get(timeout=TIMEOUT * 3).get(uri) or []
        )
        if not tracks:
            refs = self.core.playlists.get_items(uri).get(timeout=TIMEOUT * 3) or []
            uris = [ref.uri for ref in refs]
            found = (
                self.core.library.lookup(uris=uris).get(timeout=TIMEOUT * 3)
                if uris
                else {}
            )
            tracks = [t for u in uris for t in found.get(u, [])[:1]]
        return [track_info(t) for t in tracks]

    def lookup(self, uri: str) -> TrackInfo | None:
        tracks = (
            self.core.library.lookup(uris=[uri]).get(timeout=TIMEOUT).get(uri) or []
        )
        return track_info(tracks[0]) if tracks else None

    def images(self, uris: Iterable[str]) -> dict[str, str]:
        uris = list(uris)
        if not uris:
            return {}
        result = self.core.library.get_images(uris).get(timeout=TIMEOUT)
        images = {}
        for uri, found in result.items():
            if found:
                # Pick the smallest image that is at least 300px wide.
                ranked = sorted(found, key=lambda i: i.width or 0)
                big = [i for i in ranked if (i.width or 0) >= 300]
                images[uri] = big[0].uri if big else ranked[-1].uri
        return images

    def _search_uris(self) -> list[str]:
        schemes = self.search_schemes or self.core.get_uri_schemes().get(
            timeout=TIMEOUT
        )
        # A backend waiting for its login would block the whole search.
        return [f"{s}:" for s in schemes if not self.login_pending(source_of(s))]

    def search(self, query: str, limit: int = 12) -> list[TrackInfo]:
        uris = self._search_uris()
        if not uris:
            return []
        results = self.core.library.search(query={"any": [query]}, uris=uris).get(
            timeout=TIMEOUT
        )
        # Take turns between backends so every service shows up in the results.
        per_backend = [[track_info(t) for t in r.tracks] for r in results if r]
        seen: dict[str, TrackInfo] = {}
        for rank in range(max((len(b) for b in per_backend), default=0)):
            for tracks in per_backend:
                if rank < len(tracks) and len(seen) < limit:
                    seen.setdefault(tracks[rank].uri, tracks[rank])
        tracks = list(seen.values())
        images = self.images(t.uri for t in tracks)
        return [
            TrackInfo(t.uri, t.name, t.artists, t.album, t.length_ms, images.get(t.uri))
            for t in tracks
        ]
