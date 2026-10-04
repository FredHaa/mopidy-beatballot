import random

import pytest

from mopidy_beatballot.voting import PLAYLIST, SUGGESTED, Election, VoteError

from .helpers import FakeClock, track


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def election(clock):
    e = Election(clock)
    e.start_round([track("a"), track("b"), track("c")])
    return e


def close(e, carry=2):
    return e.close(random.Random(0), carry)


def test_most_votes_wins(election, clock):
    election.vote("u1", "a")
    clock.advance(1)
    election.vote("u2", "b")
    election.vote("u3", "b")
    assert close(election).track.uri == "b"


def test_voting_again_moves_the_vote(election):
    election.vote("u1", "a")
    election.vote("u1", "b")
    assert election.tally() == {"a": 0, "b": 1, "c": 0}


def test_vote_for_unknown_song_is_rejected(election):
    with pytest.raises(VoteError):
        election.vote("u1", "zzz")


def test_tie_goes_to_first_to_reach_the_count(election, clock):
    election.vote("u1", "b")
    clock.advance(1)
    election.vote("u2", "a")
    clock.advance(1)
    election.vote("u3", "a")
    clock.advance(1)
    election.vote("u4", "b")  # b reaches 2 votes after a did
    assert close(election).track.uri == "a"


def test_revoting_same_song_keeps_original_timestamp(election, clock):
    election.vote("u1", "a")
    clock.advance(1)
    election.vote("u2", "b")
    clock.advance(1)
    election.vote("u1", "a")
    assert close(election).track.uri == "a"


def test_no_votes_picks_a_random_playlist_song(election):
    election.suggest("u1", track("s"), limit=1)
    for seed in range(20):
        e = Election()
        e.start_round([track("a"), track("b")])
        e.suggest("u1", track("s"), limit=1)
        assert e.close(random.Random(seed), 2).origin == PLAYLIST


def test_empty_round_has_no_winner():
    e = Election()
    e.start_round([])
    assert e.close(random.Random(0), 2) is None


def test_losers_with_multiple_votes_carry_over_with_their_votes(election, clock):
    for u in ("u1", "u2", "u3"):
        election.vote(u, "a")
    election.vote("u4", "b")
    election.vote("u5", "b")
    election.vote("u6", "c")
    assert close(election).track.uri == "a"

    assert set(election.candidates) == {"b"}
    assert election.candidates["b"].carried == 1
    assert election.voters("b") == ["u4", "u5"]
    assert "u6" not in election.ballots  # single-vote loser dropped

    election.start_round([track("d"), track("e")])
    assert election.tally() == {"b": 2, "d": 0, "e": 0}


def test_carried_vote_moves_when_user_votes_elsewhere(election):
    for u in ("u1", "u2", "u3"):
        election.vote(u, "a")
    election.vote("u4", "b")
    election.vote("u5", "b")
    close(election)
    election.start_round([track("d")])

    election.vote("u4", "d")
    assert election.tally() == {"b": 1, "d": 1}


def test_carried_song_can_carry_again_and_win_later(election):
    for u in ("u1", "u2", "u3"):
        election.vote(u, "a")
    election.vote("u4", "b")
    election.vote("u5", "b")
    close(election)
    election.start_round([track("d")])
    election.vote("u6", "b")
    assert close(election).track.uri == "b"
    assert election.candidates == {}
    assert election.ballots == {}


def test_carry_threshold_is_configurable(election):
    election.vote("u1", "a")
    election.vote("u2", "a")
    election.vote("u3", "b")
    close(election, carry=1)
    assert set(election.candidates) == {"b"}


def test_suggestions_are_limited_per_user_per_round(election):
    election.suggest("u1", track("s1"), limit=1)
    with pytest.raises(VoteError):
        election.suggest("u1", track("s2"), limit=1)
    election.suggest("u2", track("s2"), limit=1)
    assert election.candidates["s1"].origin == SUGGESTED
    assert election.candidates["s1"].added_by == "u1"


def test_suggesting_an_existing_candidate_is_a_noop(election):
    c = election.suggest("u1", track("a"), limit=1)
    assert c.origin == PLAYLIST
    election.suggest("u1", track("s1"), limit=1)  # Limit not used up


def test_carried_suggestion_does_not_count_against_new_round(election):
    election.suggest("u1", track("s1"), limit=1)
    election.vote("u1", "s1")
    election.vote("u2", "s1")
    for u in ("u3", "u4", "u5"):
        election.vote(u, "a")
    close(election)
    election.start_round([])
    election.suggest("u1", track("s2"), limit=1)


def test_remove_drops_candidate_and_votes(election):
    election.vote("u1", "a")
    election.remove("a")
    assert "a" not in election.candidates
    assert election.ballots == {}


def test_leader_without_votes_is_none(election):
    assert election.leader() is None
    election.vote("u1", "c")
    assert election.leader().track.uri == "c"


def test_carry_over_off_drops_every_loser(election):
    for u in ("u1", "u2", "u3"):
        election.vote(u, "a")
    election.vote("u4", "b")
    election.vote("u5", "b")
    assert election.close(random.Random(0), None).track.uri == "a"
    assert election.candidates == {}
    assert election.ballots == {}
