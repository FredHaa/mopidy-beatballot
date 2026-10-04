"""The vote engine. Pure Python so the rules can be tested without Mopidy.

Rules:
- Each user has one vote. Voting for another candidate moves the vote.
- When a round closes, the candidate with the most votes wins. Ties go to the
  candidate that reached its count first; with no votes at all a random
  playlist pick wins.
- Losing candidates with at least ``carry_min_votes`` votes carry over to the
  next round, and their voters' votes stay on them until those users vote for
  something else. All other candidates and votes are dropped.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from .tracks import TrackInfo

PLAYLIST = "playlist"
SUGGESTED = "suggested"


class VoteError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    track: TrackInfo
    origin: str
    added_by: str | None
    added_at: float
    carried: int = 0


@dataclass(frozen=True)
class Ballot:
    uri: str
    at: float


class Election:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.round_id = 0
        self.candidates: dict[str, Candidate] = {}
        self.ballots: dict[str, Ballot] = {}

    def start_round(self, fresh: Iterable[TrackInfo]) -> None:
        self.round_id += 1
        self.add(fresh)

    def add(self, fresh: Iterable[TrackInfo]) -> None:
        """Add playlist picks to the current round."""
        for track in fresh:
            if track.uri not in self.candidates:
                self.candidates[track.uri] = Candidate(
                    track, PLAYLIST, None, self._clock()
                )

    def vote(self, user_id: str, uri: str) -> None:
        if uri not in self.candidates:
            raise VoteError("That song is not in this round")
        current = self.ballots.get(user_id)
        if current is not None and current.uri == uri:
            return  # Keep the original timestamp so tie-breaks stay fair.
        self.ballots[user_id] = Ballot(uri, self._clock())

    def retract(self, user_id: str) -> None:
        self.ballots.pop(user_id, None)

    def suggest(self, user_id: str, track: TrackInfo, limit: int) -> Candidate:
        if track.uri in self.candidates:
            return self.candidates[track.uri]
        used = sum(
            1
            for c in self.candidates.values()
            if c.origin == SUGGESTED and c.added_by == user_id and c.carried == 0
        )
        if used >= limit:
            raise VoteError(
                f"You can add {limit} song{'s' if limit != 1 else ''} per round"
            )
        candidate = Candidate(track, SUGGESTED, user_id, self._clock())
        self.candidates[track.uri] = candidate
        return candidate

    def remove(self, uri: str) -> None:
        self.candidates.pop(uri, None)
        self.ballots = {u: b for u, b in self.ballots.items() if b.uri != uri}

    def update_track(self, track: TrackInfo) -> None:
        if track.uri in self.candidates:
            self.candidates[track.uri] = replace(
                self.candidates[track.uri], track=track
            )

    def voters(self, uri: str) -> list[str]:
        """User ids voting for ``uri``, in the order they voted."""
        return [
            user
            for user, ballot in sorted(self.ballots.items(), key=lambda i: i[1].at)
            if ballot.uri == uri
        ]

    def tally(self) -> dict[str, int]:
        counts = dict.fromkeys(self.candidates, 0)
        for ballot in self.ballots.values():
            counts[ballot.uri] += 1
        return counts

    def leader(self, rng: random.Random | None = None) -> Candidate | None:
        """The candidate that would win if the round closed now.

        Without ``rng`` a round with no votes has no leader.
        """
        if not self.candidates:
            return None
        counts = self.tally()
        if any(counts.values()):
            reached_at: dict[str, float] = {}
            for ballot in self.ballots.values():
                reached_at[ballot.uri] = max(reached_at.get(ballot.uri, 0.0), ballot.at)
            uri = min(
                (u for u in self.candidates if counts[u] > 0),
                key=lambda u: (-counts[u], reached_at[u], self.candidates[u].added_at),
            )
            return self.candidates[uri]
        if rng is None:
            return None
        pool = [c for c in self.candidates.values() if c.origin == PLAYLIST]
        return rng.choice(pool or list(self.candidates.values()))

    def close(
        self, rng: random.Random, carry_min_votes: int | None
    ) -> Candidate | None:
        """Pick the winner and keep only the carried-over candidates and votes.

        ``carry_min_votes=None`` turns carry-over off: every round starts fresh.

        Call ``start_round`` afterwards to add the next round's fresh picks.
        """
        winner = self.leader(rng)
        counts = self.tally()
        carried = {
            uri: replace(c, carried=c.carried + 1)
            for uri, c in self.candidates.items()
            if (winner is None or uri != winner.track.uri)
            and carry_min_votes is not None
            and counts[uri] >= carry_min_votes
        }
        self.candidates = carried
        self.ballots = {u: b for u, b in self.ballots.items() if b.uri in carried}
        return winner
