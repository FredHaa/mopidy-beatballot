from types import SimpleNamespace

from mopidy.models import Album, Artist, Image, Ref, SearchResult, TlTrack, Track

from mopidy_beatballot.player import MopidyPlayer


class Future:
    """Mimics pykka 4: ``timeout`` is keyword-only."""

    def __init__(self, value):
        self.value = value

    def get(self, *, timeout=None):
        return self.value


def returns(value):
    return lambda *args, **kwargs: Future(value)


TRACK = Track(
    uri="spotify:track:1",
    name="Song",
    artists=frozenset({Artist(name="B"), Artist(name="A")}),
    album=Album(name="LP"),
    length=200_000,
)


def make_core(**library):
    calls = []

    def record(name, value=None):
        def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            return Future(value)

        return call

    core = SimpleNamespace(
        playback=SimpleNamespace(
            get_state=returns("playing"),
            get_time_position=returns(1234),
            get_current_tl_track=returns(TlTrack(tlid=3, track=TRACK)),
            play=record("play"),
            next=record("next"),
            pause=record("pause"),
            resume=record("resume"),
        ),
        tracklist=SimpleNamespace(
            set_consume=record("consume"),
            set_repeat=record("repeat"),
            set_random=record("random"),
            set_single=record("single"),
            clear=record("clear"),
            get_length=returns(2),
            get_tl_tracks=returns(
                [TlTrack(tlid=2, track=TRACK), TlTrack(tlid=3, track=TRACK)]
            ),
            add=record("add"),
            remove=record("remove"),
        ),
        library=SimpleNamespace(
            lookup=returns(library.get("lookup", {})),
            get_images=returns(library.get("images", {})),
            search=returns(library.get("search", [])),
        ),
        playlists=SimpleNamespace(get_items=returns(library.get("items"))),
    )
    return core, calls


def test_playback_calls():
    core, calls = make_core()
    player = MopidyPlayer(core)
    player.prepare()
    assert player.state() == "playing"
    assert player.position_ms() == 1234
    tlid, track = player.current()
    assert tlid == 3
    assert track.name == "Song"
    assert track.artists == ("A", "B")
    assert track.album == "LP"
    assert player.tracklist_length() == 2
    assert [tlid for tlid, _ in player.queue()] == [2, 3]
    player.enqueue("spotify:track:9")
    player.play()
    player.next()
    player.remove(5)
    assert ("add", (), {"uris": ["spotify:track:9"]}) in calls
    assert ("play", (), {"tlid": 3}) in calls  # the current track, not the first
    assert ("remove", ({"tlid": [5]},), {}) in calls
    assert [c[0] for c in calls][-3:] == ["play", "next", "remove"]


def test_load_playlist_falls_back_to_playlist_items():
    core, _ = make_core(
        lookup={"spotify:track:1": [TRACK]},
        items=[Ref.track(uri="spotify:track:1", name="Song")],
    )
    tracks = MopidyPlayer(core).load_playlist("m3u:party.m3u")
    assert [t.uri for t in tracks] == ["spotify:track:1"]


def test_images_prefers_smallest_at_least_300px():
    images = (
        Image(uri="small", width=64),
        Image(uri="big", width=640),
        Image(uri="mid", width=300),
    )
    core, _ = make_core(images={"spotify:track:1": images})
    assert MopidyPlayer(core).images(["spotify:track:1"]) == {"spotify:track:1": "mid"}


def test_search_takes_turns_between_backends_and_skips_pending_login():
    def track(uri, name):
        return Track(uri=uri, name=name, length=1000)

    results = [
        SearchResult(
            tracks=(track("spotify:track:1", "S1"), track("spotify:track:2", "S2"))
        ),
        SearchResult(tracks=(track("tidal:track:1", "T1"),)),
    ]
    core, _ = make_core(search=results)
    searched = []

    def search(query, uris=None, exact=False):
        searched.append(uris)
        return Future(results)

    core.library.search = search
    core.get_uri_schemes = returns(["spotify", "tidal", "m3u"])
    player = MopidyPlayer(core, login_pending=lambda s: s == "tidal")
    found = player.search("x")
    assert searched == [["spotify:"]]  # tidal pending, m3u not searchable
    assert [t.name for t in found] == ["S1", "T1", "S2"]


def _search_core(results_by_scheme):
    core, _ = make_core()
    searched = []

    def search(query, uris=None, exact=False):
        searched.append(uris)
        return Future([results_by_scheme[u] for u in uris])

    core.library.search = search
    core.get_uri_schemes = returns(["spotify", "tidal", "http"])
    return core, searched


def test_fast_search_replaces_mopidy_search_for_that_service():
    from mopidy_beatballot.tracks import TrackInfo

    core, searched = _search_core(
        {"spotify:": SearchResult(tracks=(Track(uri="spotify:track:1", name="S1"),))}
    )
    fast = TrackInfo("tidal:track:1:2:3", "T1", ("A",), image="https://img/t1")
    player = MopidyPlayer(core, fast_search={"tidal": lambda q, n: [fast]})
    found = player.search("x")
    assert searched == [["spotify:"]]  # tidal not sent to Mopidy, http skipped
    assert [t.name for t in found] == ["T1", "S1"]
    assert found[0].image == "https://img/t1"


def test_fast_search_falls_back_to_mopidy():
    tidal = SearchResult(tracks=(Track(uri="tidal:track:1:2:3", name="T1"),))
    core, searched = _search_core({"tidal:": tidal, "spotify:": SearchResult()})

    def broken(query, limit):
        raise ConnectionError("tidal down")

    player = MopidyPlayer(core, ["tidal"], fast_search={"tidal": broken})
    assert [t.name for t in player.search("x")] == ["T1"]
    assert searched == [["tidal:"]]
    # Not logged in yet (None) also falls back.
    player = MopidyPlayer(core, ["tidal"], fast_search={"tidal": lambda q, n: None})
    assert [t.name for t in player.search("x")] == ["T1"]
