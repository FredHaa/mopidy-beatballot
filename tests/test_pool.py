import random

from mopidy_beatballot.pool import Pool
from mopidy_beatballot.tracks import TrackInfo

from .helpers import track


def test_pick_excludes_played_and_given_uris():
    pool = Pool(random.Random(0))
    pool.load([track(u) for u in "abcde"])
    pool.mark_played("a")
    picks = {t.uri for t in pool.pick(3, exclude={"b"})}
    assert picks == {"c", "d", "e"}


def test_reshuffles_when_exhausted():
    pool = Pool(random.Random(0))
    pool.load([track(u) for u in "abc"])
    for u in "abc":
        pool.mark_played(u)
    picks = {t.uri for t in pool.pick(2, exclude={"a"})}
    assert picks == {"b", "c"}
    assert pool.played == {"a"}  # still on the table, so not reset


def test_load_dedupes():
    pool = Pool(random.Random(0))
    pool.load([track("a"), track("a"), track("b")])
    assert len(pool) == 2


def test_pick_more_than_available():
    pool = Pool(random.Random(0))
    pool.load([track("a")])
    assert [t.uri for t in pool.pick(3)] == ["a"]


def test_picks_randomly_from_all_playlists():
    pool = Pool(random.Random(3))
    tracks = [track(f"spotify:track:{i}") for i in range(10)]
    tracks += [track(f"tidal:track:{i}") for i in range(10)]
    pool.load(tracks)
    picked = set()
    for _ in range(30):
        picked.update(t.uri for t in pool.pick(3))
        pool.played.clear()
    # Every song can come up, and no service gets a guaranteed slot.
    assert picked == {t.uri for t in tracks}


def test_same_song_on_two_services_counts_once():
    pool = Pool(random.Random(0))
    a = TrackInfo("spotify:track:1", "Dancing Queen", ("ABBA",))
    b = TrackInfo("tidal:track:9", "dancing queen ", ("abba",))
    pool.load([a, b])
    assert pool.tracks == [a]


def test_skip_sources():
    pool = Pool(random.Random(0))
    pool.load([track("spotify:track:1"), track("tidal:track:1")])
    assert [t.uri for t in pool.pick(2, skip_sources={"spotify"})] == ["tidal:track:1"]
