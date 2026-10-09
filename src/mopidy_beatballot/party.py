"""Party orchestration: rounds, lock-in timing, queueing and test mode.

Talks to Mopidy only through the small ``Player`` protocol so it can be
driven by a fake player in tests. All methods must be called from one thread
(the frontend actor).
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any, Protocol

from .backends import normalize_playlist, source_name, source_of, split_list
from .pool import Pool
from .settings import Settings
from .tracks import TrackInfo
from .voting import PLAYLIST, Candidate, Election, VoteError

logger = logging.getLogger(__name__)

PLAYING = "playing"
PAUSED = "paused"
STOPPED = "stopped"

POOL_RETRY_S = 30.0
RESTART_COOLDOWN_S = 3.0
MAX_RESTART_COOLDOWN_S = 60.0
FAILURES_BEFORE_BACKOFF = 3
PLAYING_OK_MS = 2000
# A service whose songs fail this many times in a row is left out of the
# random picks for a while, so a broken service doesn't stall the party.
SOURCE_FAILURE_LIMIT = 3
SOURCE_PAUSE_S = 600.0
SYNC_EVERY_S = 5.0


class Player(Protocol):
    def state(self) -> str: ...
    def position_ms(self) -> int: ...
    def current(self) -> tuple[int, TrackInfo] | None: ...
    def tracklist_length(self) -> int: ...
    def queue(self) -> list[tuple[int, TrackInfo]]: ...
    def enqueue(self, uri: str, track: TrackInfo | None = None) -> None: ...
    def remove(self, tlid: int) -> None: ...
    def play(self) -> None: ...
    def next(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def load_playlist(self, uri: str) -> list[TrackInfo]: ...
    def images(self, uris: Iterable[str]) -> dict[str, str]: ...


class PartyController:
    def __init__(
        self,
        settings: Settings,
        player: Player,
        publish: Callable[[dict[str, Any]], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
        login_pending: Callable[[str], bool] = lambda source: False,
    ) -> None:
        self.settings = settings
        self.player = player
        self._publish = publish
        self._clock = clock
        self._wall_clock = wall_clock
        self._rng = rng or random.Random()
        self._login_pending = login_pending
        self.election = Election(clock)
        self.pool = Pool(self._rng)
        self.users: dict[str, str] = {}
        self.images: dict[str, str] = {}
        self.history: deque[TrackInfo] = deque(maxlen=12)
        self.now: tuple[int, TrackInfo] | None = None
        self.up_next: TrackInfo | None = None
        self.last_winner: dict[str, Any] | None = None
        self.locked_tlid: int | None = None
        self.skipped_tlid: int | None = None
        self.paused_by_host = False
        self.error: str | None = None
        self.playback_error: str | None = None
        self.failures = 0
        self.source_failures: dict[str, int] = {}
        self.paused_sources: dict[str, float] = {}
        # Tracks per playlist URI, or None if loading it failed.
        self.playlist_tracks: dict[str, list[TrackInfo] | None] = {}
        self._attempt: tuple[int, TrackInfo] | None = None
        self._last_pool_attempt = -POOL_RETRY_S
        self._last_restart = -RESTART_COOLDOWN_S
        self._last_sync = 0.0

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self.reload_pool()
        self._open_round()
        self.tick()

    def reload_pool(self, *, retry_only: bool = False) -> None:
        """Load the playlists. With ``retry_only``, only the ones that failed."""
        self._last_pool_attempt = self._clock()
        playlists = self.settings.playlists
        self.playlist_tracks = {
            uri: self.playlist_tracks.get(uri) if retry_only else None
            for uri in playlists
        }
        for uri in playlists:
            if self.playlist_tracks[uri] is not None:
                continue
            if self._login_pending(source_of(uri)):
                continue  # Its backend is blocked waiting for the host to log in.
            try:
                tracks = self.player.load_playlist(uri)
            except Exception:
                logger.exception("Loading playlist %s failed", uri)
                tracks = []
            if tracks:
                self.playlist_tracks[uri] = tracks
                logger.info("Beat Ballot loaded %d tracks from %s", len(tracks), uri)
            else:
                logger.warning("Beat Ballot could not load playlist %s", uri)
        self.pool.load(t for ts in self.playlist_tracks.values() for t in ts or [])
        self.error = self._pool_error()

    def _pool_error(self) -> str | None:
        if len(self.pool):
            return None
        if not self.settings.playlists:
            return None  # Suggestions-only party: guests fill the ballot.
        waiting = {
            source_of(uri)
            for uri in self.settings.playlists
            if self._login_pending(source_of(uri))
        }
        if waiting:
            names = " and ".join(source_name(s) for s in sorted(waiting))
            return f"Waiting for the host to log in to {names}"
        return (
            "Could not load the playlists. Check the links, and use playlists "
            "you own: Spotify blocks access to its own editorial playlists."
        )

    def tick(self) -> None:
        """Called a few times per second by the frontend's ticker thread."""
        now = self._clock()
        failed = any(t is None for t in self.playlist_tracks.values())
        if failed and now - self._last_pool_attempt >= POOL_RETRY_S:
            had_tracks = len(self.pool)
            self.reload_pool(retry_only=True)
            if len(self.pool) != had_tracks:
                if len(self.election.candidates) < self.settings.candidates:
                    self._open_round(new_round=False)
                self.publish()
        elif self.error and self.error != self._pool_error():
            self.error = self._pool_error()  # e.g. the login finished
            self.publish()

        if not self.player_online():
            # A remote player that went away: voting goes on, nothing plays.
            self._track_changed(None)
            if now - self._last_sync >= SYNC_EVERY_S:
                self.publish()
            return

        state = self.player.state()
        current = self.player.current()
        self._track_changed(current)

        if state == STOPPED or current is None:
            self._recover_stopped()
        elif state == PLAYING:
            tlid, track = current
            position = self.player.position_ms()
            if position >= PLAYING_OK_MS:
                self._playing_ok(track)
            lock_at = self.lock_point_ms(track)
            if self.locked_tlid != tlid and lock_at is not None and position >= lock_at:
                self.locked_tlid = tlid
                self.lock()
            limit = self.settings.play_limit_ms()
            if limit is not None and position >= limit and self.skipped_tlid != tlid:
                self.skipped_tlid = tlid
                self.player.next()
                self._track_changed(self.player.current())

        if now - self._last_sync >= SYNC_EVERY_S:
            self.publish()

    def _track_changed(self, current: tuple[int, TrackInfo] | None) -> None:
        old_tlid = self.now[0] if self.now else None
        new_tlid = current[0] if current else None
        if old_tlid == new_tlid:
            return
        if self.now is not None:
            self.history.appendleft(self.now[1])
        self.now = current
        if current is not None:
            track = current[1]
            self.pool.mark_played(track.uri)
            if self.up_next is not None and self.up_next.uri == track.uri:
                self.up_next = None
            self._fetch_images([track.uri])
        self.publish()

    def _recover_stopped(self) -> None:
        """Keep the party going if playback stopped without the host pausing."""
        if self.paused_by_host:
            return
        now = self._clock()
        if now - self._last_restart < self._restart_cooldown():
            return
        # Mopidy clears the current track after a stream error but leaves it
        # queued, so a track we started that is still queued never played.
        queue = self.player.queue()
        if self._attempt is not None and self._attempt[0] in {t for t, _ in queue}:
            self._drop_unplayable(*self._attempt)
            queue = self.player.queue()
        self._attempt = None
        if not queue:
            if not self.election.candidates:
                return  # Nothing to play yet; a suggestion will get us going.
            self.lock()
            queue = self.player.queue()
        self._last_restart = now
        # Stopped playback starts the first queued track. Remember it, since
        # Mopidy forgets the current track if it fails to start.
        self._attempt = queue[0] if queue else None
        self.player.play()
        self._track_changed(self.player.current())

    def _playing_ok(self, track: TrackInfo) -> None:
        source = source_of(track.uri)
        if self.failures or self.playback_error or self.source_failures.get(source):
            self.failures = 0
            self.playback_error = None
            self.source_failures.pop(source, None)
            self.paused_sources.pop(source, None)
            self.publish()

    def active_paused_sources(self) -> set[str]:
        now = self._clock()
        return {s for s, until in self.paused_sources.items() if until > now}

    def _restart_cooldown(self) -> float:
        """Back off when every track fails, e.g. while Spotify streaming is down."""
        if self.failures < FAILURES_BEFORE_BACKOFF:
            return RESTART_COOLDOWN_S
        extra = self.failures - FAILURES_BEFORE_BACKOFF + 1
        return min(MAX_RESTART_COOLDOWN_S, RESTART_COOLDOWN_S * 2**extra)

    def _drop_unplayable(self, tlid: int, track: TrackInfo) -> None:
        """We restarted this track and it stopped again: skip it."""
        logger.warning("Beat Ballot: could not play %s, skipping it", track.uri)
        self.player.remove(tlid)
        self.failures += 1
        source = source_of(track.uri)
        self.source_failures[source] = self.source_failures.get(source, 0) + 1
        paused_now = (
            self.source_failures[source] >= SOURCE_FAILURE_LIMIT
            and source not in self.active_paused_sources()
        )
        if paused_now:
            self.paused_sources[source] = self._clock() + SOURCE_PAUSE_S
            logger.warning(
                "Beat Ballot: pausing %s picks, playback keeps failing", source
            )
        if self.up_next is not None and self.up_next.uri == track.uri:
            self.up_next = None
        if self.now is not None and self.now[0] == tlid:
            self.now = None  # It never played, so keep it out of the history.
        service = source_name(source)
        if paused_now and len(self.pool.sources()) > 1:
            self.playback_error = (
                f"{service} playback keeps failing, so its songs are left out "
                f"for {int(SOURCE_PAUSE_S // 60)} minutes."
            )
        elif self.failures >= FAILURES_BEFORE_BACKOFF:
            self.playback_error = (
                f"Playback keeps failing ({self.failures} songs in a row). "
                f"Check the {service} connection in the server logs."
            )
        else:
            self.playback_error = (
                f"Couldn't play “{track.name}” on {service}, skipped it"
            )
        self.publish()

    # --- timing ----------------------------------------------------------

    def end_ms(self, track: TrackInfo) -> int | None:
        """Where playback of ``track`` ends, taking test mode into account."""
        limit = self.settings.play_limit_ms()
        if track.length_ms is None:
            return limit
        return track.length_ms if limit is None else min(track.length_ms, limit)

    def lock_point_ms(self, track: TrackInfo) -> int | None:
        end = self.end_ms(track)
        if end is None:
            return None
        return max(0, end - self.settings.lock_window_ms())

    def locks_in_ms(self, position: int) -> int | None:
        if self.now is None:
            return None
        tlid, track = self.now
        if self.locked_tlid != tlid:
            lock_at = self.lock_point_ms(track)
            return None if lock_at is None else max(0, lock_at - position)
        # Already locked for this song: the open round locks during the next one.
        end = self.end_ms(track)
        if self.up_next is None or end is None:
            return None
        next_lock = self.lock_point_ms(self.up_next)
        if next_lock is None:
            return None
        return max(0, end - position) + next_lock

    # --- rounds ----------------------------------------------------------

    def lock(self) -> Candidate | None:
        """Close the round, queue the winner and open the next round."""
        counts = self.election.tally()
        on_ballot = dict(self.election.candidates)
        carry = self.settings.carry_min_votes if self.settings.carry_over else None
        winner = self.election.close(self._rng, carry)
        # Songs that lost and weren't carried over join the random pool.
        dropped = [
            c.track
            for uri, c in on_ballot.items()
            if uri not in self.election.candidates
            and (winner is None or uri != winner.track.uri)
        ]
        self.pool.add_discarded(dropped)
        # ...but not straight back onto the next ballot.
        just_dropped = {t.uri for t in dropped}
        if winner is not None:
            uri = winner.track.uri
            try:
                self.player.enqueue(uri, winner.track)
            except Exception as e:
                # E.g. a Spotify song on a remote player, or the player left.
                logger.warning("Beat Ballot could not queue %s: %s", uri, e)
                self.playback_error = f"Couldn't play “{winner.track.name}”: {e}"
                self.pool.mark_played(uri)
                self._open_round(skip=just_dropped)
                self.publish()
                return None
            self.pool.mark_played(uri)
            self.up_next = winner.track
            self.last_winner = {
                "round": self.election.round_id,
                "track": self._track_dict(winner.track),
                "votes": counts.get(uri, 0),
            }
            logger.info("Beat Ballot round %d won by %s", self.election.round_id, uri)
        self._open_round(skip=just_dropped)
        self.publish()
        return winner

    def _open_round(self, *, new_round: bool = True, skip: Iterable[str] = ()) -> None:
        exclude = set(self.election.candidates) | set(skip)
        if self.now is not None:
            exclude.add(self.now[1].uri)
        if self.up_next is not None:
            exclude.add(self.up_next.uri)
        picks = sum(
            1
            for c in self.election.candidates.values()
            if c.origin == PLAYLIST and not c.carried
        )
        wanted = max(0, self.settings.candidates - picks)
        fresh = self.pool.pick(wanted, exclude, self.active_paused_sources())
        if not fresh and wanted:
            fresh = self.pool.pick(wanted, exclude)  # Better than an empty ballot.
        if new_round:
            self.election.start_round(fresh)
        else:
            self.election.add(fresh)
        self._fetch_images(self.election.candidates)

    def _fetch_images(self, uris: Iterable[str]) -> None:
        missing = [u for u in uris if u not in self.images]
        if not missing:
            return
        try:
            self.images.update(self.player.images(missing))
        except Exception:
            logger.debug("Image lookup failed", exc_info=True)

    # --- guest actions ---------------------------------------------------

    def join(self, user_id: str, name: str) -> None:
        self.users[user_id] = name

    def vote(self, user_id: str, name: str, uri: str) -> None:
        self.join(user_id, name)
        self.election.vote(user_id, uri)
        self.publish()

    def retract(self, user_id: str) -> None:
        self.election.retract(user_id)
        self.publish()

    def suggest(self, user_id: str, name: str, track: TrackInfo) -> None:
        self.join(user_id, name)
        blocked = {
            t.uri for t in (self.now[1] if self.now else None, self.up_next) if t
        }
        if track.uri in blocked:
            raise VoteError("That song is already playing or up next")
        if track.image:
            self.images.setdefault(track.uri, track.image)
        self.election.suggest(user_id, track, self.settings.max_suggestions_per_user)
        # A song you add starts with your vote (moving it from any other song).
        self.election.vote(user_id, track.uri)
        self._fetch_images([track.uri])
        self.publish()

    # --- host actions ----------------------------------------------------

    def skip(self) -> None:
        if self.now is not None and self.locked_tlid != self.now[0]:
            self.locked_tlid = self.now[0]
            self.lock()
        self.paused_by_host = False
        self.player.next()
        self._track_changed(self.player.current())

    def pause(self) -> None:
        self.paused_by_host = True
        self.player.pause()
        self.publish()

    def resume(self) -> None:
        self.paused_by_host = False
        if self.player.state() == PAUSED:
            self.player.resume()
        else:
            self.player.play()
        self.publish()

    def set_carry_over(self, enabled: bool) -> None:
        """Applies from the next lock; songs already carried stay this round."""
        self.settings.carry_over = enabled
        self.publish()

    def set_test_mode(self, enabled: bool) -> None:
        self.settings.test_mode = enabled
        self.publish()

    def remove_candidate(self, uri: str) -> None:
        self.election.remove(uri)
        self.publish()

    def login_changed(self) -> None:
        """A backend login started or finished: retry what was waiting on it."""
        if any(t is None for t in self.playlist_tracks.values()):
            had_tracks = len(self.pool)
            self.reload_pool(retry_only=True)
            if len(self.pool) != had_tracks and (
                len(self.election.candidates) < self.settings.candidates
            ):
                self._open_round(new_round=False)
        self.error = self._pool_error()
        self.publish()

    def set_playlists(self, value: str | list[str]) -> None:
        """Replace the playlists (links or URIs, comma/newline separated)."""
        self.settings.playlists = [normalize_playlist(p) for p in split_list(value)]
        self.reload_pool()
        # Replace the playlist picks that nobody has voted for yet.
        counts = self.election.tally()
        for c in list(self.election.candidates.values()):
            if c.origin == PLAYLIST and counts[c.track.uri] == 0:
                self.election.remove(c.track.uri)
        self._open_round(new_round=False)
        self.publish()

    # --- state -----------------------------------------------------------

    def _track_dict(self, track: TrackInfo) -> dict[str, Any]:
        image = self.images.get(track.uri) or track.image
        return replace(track, image=image).to_dict()

    def snapshot(self) -> dict[str, Any]:
        state = self.player.state()
        position = self.player.position_ms() if self.now else 0
        counts = self.election.tally()
        leader = self.election.leader()
        candidates = []
        for uri, c in self.election.candidates.items():
            candidates.append(
                {
                    "track": self._track_dict(c.track),
                    "origin": c.origin,
                    "added_by": self.users.get(c.added_by or "", None),
                    "carried": c.carried,
                    "votes": counts[uri],
                    "voters": [
                        {"id": u, "name": self.users.get(u, "?")}
                        for u in self.election.voters(uri)
                    ],
                    "leading": leader is not None and leader.track.uri == uri,
                }
            )
        now = None
        if self.now is not None:
            track = self.now[1]
            now = {
                "track": self._track_dict(track),
                "position_ms": position,
                "end_ms": self.end_ms(track),
                "lock_at_ms": self.lock_point_ms(track),
                "locked": self.locked_tlid == self.now[0],
            }
        return {
            "type": "state",
            "server_time": self._wall_clock(),
            "playback": state,
            "paused_by_host": self.paused_by_host,
            "test_mode": self.settings.test_mode,
            "settings": {
                "lock_before_end": self.settings.lock_before_end,
                "test_play_seconds": self.settings.test_play_seconds,
                "test_lock_at": self.settings.test_lock_at,
                "carry_over": self.settings.carry_over,
                "carry_min_votes": self.settings.carry_min_votes,
                "max_suggestions_per_user": self.settings.max_suggestions_per_user,
                "playlists": self.settings.playlists,
            },
            "now": now,
            "up_next": self._track_dict(self.up_next) if self.up_next else None,
            "locks_in_ms": self.locks_in_ms(position),
            "round": {"id": self.election.round_id, "candidates": candidates},
            "last_winner": self.last_winner,
            "history": [self._track_dict(t) for t in self.history],
            "pool_size": len(self.pool),
            "pool_discarded": len(self.pool.discarded),
            "player": {
                "online": self.player_online(),
                "name": getattr(self.player, "player_name", None),
                "remote": hasattr(self.player, "online"),
            },
            "suggestions_only": not self.settings.playlists,
            "playlists": [
                {
                    "uri": uri,
                    "source": source_of(uri),
                    "tracks": None if tracks is None else len(tracks),
                    "login_pending": self._login_pending(source_of(uri)),
                }
                for uri, tracks in self.playlist_tracks.items()
            ],
            "sources": [
                {
                    "id": source,
                    "name": source_name(source),
                    "tracks": count,
                    "paused": source in self.active_paused_sources(),
                }
                for source, count in sorted(self.pool.sources().items())
            ],
            "error": self.error,
            "playback_error": self.playback_error,
        }

    def player_online(self) -> bool:
        return getattr(self.player, "online", True)

    def publish(self) -> None:
        self._last_sync = self._clock()
        try:
            self._publish(self.snapshot())
        except Exception:
            logger.exception("Publishing Beat Ballot state failed")
