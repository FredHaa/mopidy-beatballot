import random

import pytest

from mopidy_beatballot.party import PartyController
from mopidy_beatballot.settings import Settings
from mopidy_beatballot.voting import VoteError

from .helpers import FakeClock, FakePlayer, track

SONG_MS = 200_000


@pytest.fixture
def player():
    return FakePlayer([track(f"t{i}", SONG_MS) for i in range(20)])


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def published():
    return []


def make_party(player, clock, published, **settings):
    s = Settings(playlists=["spotify:playlist:x"], **settings)
    party = PartyController(
        s, player, published.append, clock=clock, rng=random.Random(1)
    )
    party.start()
    return party


@pytest.fixture
def party(player, clock, published):
    return make_party(player, clock, published)


def at(party, player, position_ms):
    player.position = position_ms
    party.tick()


def uris(party):
    return set(party.election.candidates)


def test_start_plays_a_song_and_opens_a_round(party, player):
    assert player.state() == "playing"
    assert party.now is not None
    assert len(party.election.candidates) == 3
    assert party.now[1].uri not in uris(party)


def test_vote_locks_20_seconds_before_end(party, player):
    first = party.now[1]
    choice = sorted(uris(party))[0]
    party.vote("u1", "Ann", choice)

    at(party, player, SONG_MS - 21_000)
    assert player.tracklist_length() == 1  # only the current song

    at(party, player, SONG_MS - 20_000)
    assert [t.uri for _, t in player.tracklist] == [first.uri, choice]
    assert party.up_next.uri == choice
    assert choice not in uris(party)
    assert len(uris(party)) == 3  # a fresh round is open

    player.finish()
    party.tick()
    assert party.now[1].uri == choice
    assert party.up_next is None
    assert party.history[0].uri == first.uri


def test_locks_only_once_per_song(party, player):
    at(party, player, SONG_MS - 20_000)
    round_id = party.election.round_id
    at(party, player, SONG_MS - 10_000)
    assert party.election.round_id == round_id
    assert player.tracklist_length() == 2


def test_losers_with_two_votes_carry_over(party, player):
    a, b, c = sorted(uris(party))
    for u in ("u1", "u2", "u3"):
        party.vote(u, u, a)
    party.vote("u4", "u4", b)
    party.vote("u5", "u5", b)
    party.vote("u6", "u6", c)
    at(party, player, SONG_MS - 20_000)

    assert party.up_next.uri == a
    assert b in uris(party)
    assert c not in uris(party)
    assert party.election.tally()[b] == 2

    party.vote("u4", "u4", next(u for u in uris(party) if u != b))
    assert party.election.tally()[b] == 1


def test_test_mode_locks_at_15s_and_skips_at_30s(player, clock, published):
    party = make_party(player, clock, published, test_mode=True)
    first = party.now[1]

    at(party, player, 14_000)
    assert player.tracklist_length() == 1
    at(party, player, 15_000)
    assert player.tracklist_length() == 2
    winner = party.up_next

    at(party, player, 29_000)
    assert party.now[1] == first
    at(party, player, 30_000)
    assert party.now[1].uri == winner.uri
    assert player.position == 0


def test_toggling_test_mode_changes_timing(party, player):
    party.set_test_mode(True)
    at(party, player, 15_000)
    assert player.tracklist_length() == 2


def test_short_song_locks_immediately(player, clock, published):
    player.playlist[:] = [track("short", 10_000)]
    player.library["short"] = player.playlist[0]
    party = make_party(player, clock, published)
    # The only track was played at start; the round is empty, so nothing queues.
    assert party.now[1].uri == "short"


def test_locks_in_countdown(party, player):
    at(party, player, 100_000)
    assert party.locks_in_ms(100_000) == SONG_MS - 20_000 - 100_000
    at(party, player, SONG_MS - 20_000)
    # Next round locks 20s before the end of the queued winner.
    assert party.locks_in_ms(SONG_MS - 20_000) == 20_000 + SONG_MS - 20_000


def test_stopped_with_nothing_queued_plays_the_leader(party, player, clock):
    choice = sorted(uris(party))[1]
    party.vote("u1", "Ann", choice)
    player.tracklist.clear()
    player.finish()
    assert player.state() == "stopped"
    clock.advance(5)
    party.tick()
    assert party.now[1].uri == choice


def test_host_pause_is_respected(party, player, clock):
    party.pause()
    assert player.state() == "paused"
    clock.advance(10)
    party.tick()
    assert player.state() == "paused"
    party.resume()
    assert player.state() == "playing"


def test_skip_locks_first_when_round_is_open(party, player):
    choice = sorted(uris(party))[2]
    party.vote("u1", "Ann", choice)
    party.skip()
    party.tick()
    assert party.now[1].uri == choice


def test_suggest_adds_candidate(party, player):
    extra = track("x")
    player.library["x"] = extra
    party.suggest("u1", "Ann", extra)
    assert "x" in uris(party)
    with pytest.raises(VoteError):
        party.suggest("u1", "Ann", track("y"))


def test_cannot_suggest_now_playing(party):
    with pytest.raises(VoteError):
        party.suggest("u1", "Ann", party.now[1])


def test_snapshot_contents(party, player):
    choice = sorted(uris(party))[0]
    party.vote("u1", "Ann", choice)
    snap = party.snapshot()
    assert snap["type"] == "state"
    assert snap["now"]["track"]["uri"] == party.now[1].uri
    assert snap["now"]["lock_at_ms"] == SONG_MS - 20_000
    cand = next(c for c in snap["round"]["candidates"] if c["track"]["uri"] == choice)
    assert cand["votes"] == 1
    assert cand["voters"] == [{"id": "u1", "name": "Ann"}]
    assert cand["leading"] is True
    assert cand["track"]["image"] == f"https://img/{choice}"


def test_change_playlist_keeps_voted_picks(party, player):
    a, b, c = sorted(uris(party))
    party.vote("u1", "Ann", a)
    round_id = party.election.round_id
    party.set_playlists("https://open.spotify.com/playlist/other?si=abc")
    assert party.settings.playlists == ["spotify:playlist:other"]
    assert party.election.round_id == round_id
    assert a in uris(party)
    assert len(uris(party)) == 3


def test_empty_playlist_reports_error(clock, published):
    player = FakePlayer([])
    party = make_party(player, clock, published)
    assert party.error
    assert player.state() == "stopped"


def test_unplayable_track_is_skipped_not_retried_forever(party, player, clock):
    bad = sorted(uris(party))[0]
    player.unplayable.add(bad)
    party.vote("u1", "Ann", bad)
    at(party, player, SONG_MS - 20_000)  # bad wins and is queued
    good = sorted(uris(party))[0]
    party.vote("u2", "Bo", good)
    player.finish()  # bad starts, fails, stays current while stopped
    assert player.state() == "stopped"

    clock.advance(5)
    party.tick()  # first restart attempt
    assert player.state() == "stopped"
    clock.advance(5)
    party.tick()  # same track failed again: drop it, lock the next round, play
    assert player.state() == "playing"
    assert party.now[1].uri == good
    assert bad not in [t.uri for t in party.history]
    assert party.failures == 1
    assert "skipped" in party.snapshot()["playback_error"]

    at(party, player, 5_000)  # playing fine clears the error
    assert party.failures == 0
    assert party.snapshot()["playback_error"] is None


def test_backs_off_when_every_track_fails(party, player, clock):
    player.unplayable.update(t.uri for t in player.playlist)
    player.tracklist.clear()
    player.finish()
    for _ in range(40):
        clock.advance(3)
        party.tick()
    # Without backoff this would be ~40 attempts in 120 s.
    assert player.play_calls < 20
    assert party.failures >= 3
    assert "keeps failing" in party.playback_error


def mixed_player():
    tracks = [track(f"spotify:track:{i}", SONG_MS) for i in range(6)]
    tracks += [track(f"tidal:track:{i}", SONG_MS) for i in range(6)]
    player = FakePlayer(tracks)
    player.load_playlist = lambda uri: [
        t for t in tracks if t.uri.startswith(uri.split(":")[0])
    ]
    return player


def test_loads_several_playlists_and_retries_failed_ones(clock, published):
    player = mixed_player()
    real = player.load_playlist
    calls = []

    def flaky(uri):
        calls.append(uri)
        return [] if uri.startswith("tidal") and len(calls) < 3 else real(uri)

    player.load_playlist = flaky
    party = PartyController(
        Settings(playlists=["spotify:playlist:a", "tidal:playlist:b"]),
        player,
        published.append,
        clock=clock,
        rng=random.Random(1),
    )
    party.start()
    assert len(party.pool) == 6
    assert party.snapshot()["playlists"][1]["tracks"] is None

    clock.advance(31)
    party.tick()
    assert calls == ["spotify:playlist:a", "tidal:playlist:b", "tidal:playlist:b"]
    assert len(party.pool) == 12
    assert {s["id"] for s in party.snapshot()["sources"]} == {"spotify", "tidal"}


def test_playlists_wait_for_login(clock, published):
    player = mixed_player()
    pending = {"tidal"}
    party = PartyController(
        Settings(playlists=["tidal:playlist:b"]),
        player,
        published.append,
        clock=clock,
        rng=random.Random(1),
        login_pending=lambda source: source in pending,
    )
    party.start()
    assert len(party.pool) == 0
    assert party.error == "Waiting for the host to log in to Tidal"
    assert party.snapshot()["playlists"][0]["login_pending"] is True

    pending.clear()
    party.login_changed()
    assert len(party.pool) == 6
    assert party.error is None
    assert len(party.election.candidates) == 3


def test_failing_service_is_left_out_of_picks(clock, published):
    player = mixed_player()
    player.unplayable.update(t.uri for t in player.playlist if "spotify" in t.uri)
    party = PartyController(
        Settings(playlists=["spotify:playlist:a", "tidal:playlist:b"]),
        player,
        published.append,
        clock=clock,
        rng=random.Random(1),
    )
    party.start()

    def play_songs(n):
        for _ in range(n):
            clock.advance(10)
            if player.state() == "playing":
                at(party, player, SONG_MS - 20_000)  # lock the next winner
                at(party, player, 5_000)
                player.finish()
            party.tick()

    for _ in range(40):
        play_songs(1)
        if party.paused_sources:
            break
    assert "spotify" in party.active_paused_sources()
    assert "Spotify playback keeps failing" in party.playback_error
    # Fresh picks now come from Tidal only (carried songs may remain).
    fresh = [c for c in party.election.candidates.values() if c.origin == "playlist"]
    assert fresh and all(c.track.uri.startswith("tidal") for c in fresh)
    # The party carries on with Tidal.
    play_songs(10)
    assert player.state() == "playing"
    assert party.now[1].uri.startswith("tidal")
    snap = party.snapshot()
    assert next(s for s in snap["sources"] if s["id"] == "spotify")["paused"]


def test_without_playlists_only_suggestions_are_voted_on(clock, published):
    player = FakePlayer([])
    extra = {u: track(u) for u in ("s1", "s2", "s3")}
    player.library.update(extra)
    party = PartyController(
        Settings(playlists=[]),
        player,
        published.append,
        clock=clock,
        rng=random.Random(1),
    )
    party.start()
    snap = party.snapshot()
    assert snap["error"] is None
    assert snap["suggestions_only"] is True
    assert party.election.candidates == {}
    assert player.state() == "stopped"

    # The first suggestion gets the music going.
    party.suggest("u1", "Ann", extra["s1"])
    clock.advance(5)
    party.tick()
    assert party.now[1].uri == "s1"

    # Later rounds hold only what guests add; votes pick the winner.
    party.suggest("u1", "Ann", extra["s2"])
    party.suggest("u2", "Bo", extra["s3"])
    assert set(party.election.candidates) == {"s2", "s3"}
    party.vote("u1", "Ann", "s3")
    at(party, player, extra["s1"].length_ms - 20_000)
    assert party.up_next.uri == "s3"
    assert party.election.candidates == {}  # no random picks get added


def test_empty_ballot_at_lock_time_waits_for_suggestions(clock, published):
    player = FakePlayer([])
    s1 = track("s1")
    player.library["s1"] = s1
    party = PartyController(
        Settings(playlists=[]),
        player,
        published.append,
        clock=clock,
        rng=random.Random(1),
    )
    party.start()
    party.suggest("u1", "Ann", s1)
    clock.advance(5)
    party.tick()
    at(party, player, s1.length_ms - 20_000)  # lock with nothing on the ballot
    assert party.up_next is None
    player.finish()
    clock.advance(5)
    party.tick()
    assert player.state() == "stopped"

    s2 = track("s2")
    player.library["s2"] = s2
    party.suggest("u2", "Bo", s2)
    clock.advance(5)
    party.tick()
    assert party.now[1].uri == "s2"


def test_host_can_turn_carry_over_off(party, player):
    a, b, c = sorted(uris(party))
    for u in ("u1", "u2", "u3"):
        party.vote(u, u, a)
    party.vote("u4", "u4", b)
    party.vote("u5", "u5", b)
    party.set_carry_over(False)
    assert party.snapshot()["settings"]["carry_over"] is False
    at(party, player, SONG_MS - 20_000)
    assert party.up_next.uri == a
    assert b not in uris(party)
    assert party.election.ballots == {}


def test_adding_a_song_votes_for_it(party, player):
    first = sorted(uris(party))[0]
    party.vote("u1", "Ann", first)
    extra = track("x")
    player.library["x"] = extra
    party.suggest("u1", "Ann", extra)
    # The suggester's one vote moved to the song they added.
    assert party.election.tally()["x"] == 1
    assert party.election.tally()[first] == 0
    snap = party.snapshot()
    added = next(c for c in snap["round"]["candidates"] if c["track"]["uri"] == "x")
    assert added["voters"] == [{"id": "u1", "name": "Ann"}]
    assert added["leading"] is True


def test_adding_a_song_already_on_the_ballot_votes_for_it(party):
    on_ballot = sorted(uris(party))[1]
    party.suggest("u2", "Bo", party.election.candidates[on_ballot].track)
    assert party.election.tally()[on_ballot] == 1


def test_songs_that_lose_join_the_random_pool(party, player):
    extra = track("x")
    player.library["x"] = extra
    party.suggest("u1", "Ann", extra)
    leader = next(u for u in uris(party) if u != "x")
    party.vote("u2", "Bo", leader)
    party.vote("u3", "Cy", leader)
    at(party, player, SONG_MS - 20_000)  # leader wins; x had 1 vote: dropped
    assert party.up_next.uri == leader
    assert "x" in party.pool.discarded
    assert "x" in {t.uri for t in party.pool.tracks}
    assert party.snapshot()["pool_discarded"] == 1


def test_host_removed_songs_do_not_join_the_pool(party, player):
    extra = track("x")
    player.library["x"] = extra
    party.suggest("u1", "Ann", extra)
    party.remove_candidate("x")
    at(party, player, SONG_MS - 20_000)
    assert "x" not in party.pool.discarded


def test_suggestions_only_party_reuses_earlier_suggestions(clock, published):
    player = FakePlayer([])
    songs = {u: track(u) for u in ("s1", "s2", "s3")}
    player.library.update(songs)
    party = PartyController(
        Settings(playlists=[], carry_over=False),
        player,
        published.append,
        clock=clock,
        rng=random.Random(1),
    )
    party.start()
    party.suggest("u1", "Ann", songs["s1"])
    clock.advance(5)
    party.tick()  # s1 plays
    party.suggest("u1", "Ann", songs["s2"])
    party.suggest("u2", "Bo", songs["s3"])
    party.vote("u3", "Cy", "s2")
    at(party, player, SONG_MS - 20_000)  # s2 wins, s3 is discarded
    assert party.up_next.uri == "s2"
    assert [t.uri for t in party.pool.tracks] == ["s3"]
    # Once the pool has cycled, earlier suggestions come back as random picks.
    party.pool.played.clear()
    party._open_round(new_round=False)
    assert "s3" in party.election.candidates


def test_a_dropped_song_skips_the_very_next_ballot(clock, published):
    player = FakePlayer([])
    songs = {u: track(u) for u in ("s1", "s2", "s3")}
    player.library.update(songs)
    party = PartyController(
        Settings(playlists=[]),
        player,
        published.append,
        clock=clock,
        rng=random.Random(1),
    )
    party.start()
    party.suggest("u1", "Ann", songs["s1"])
    clock.advance(5)
    party.tick()
    party.suggest("u1", "Ann", songs["s2"])
    party.suggest("u2", "Bo", songs["s3"])
    party.vote("u3", "Cy", "s2")
    at(party, player, SONG_MS - 20_000)  # s2 wins, s3 dropped
    assert "s3" in party.pool.discarded
    assert "s3" not in party.election.candidates  # not straight back
