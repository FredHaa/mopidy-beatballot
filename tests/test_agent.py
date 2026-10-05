from mopidy.models import TlTrack

from mopidy_beatballot.agent import PlayerAgent, hub_base


class Future:
    def __init__(self, value=None):
        self.value = value

    def get(self, *, timeout=None):
        return self.value


class FakeCore:
    """Enough of Mopidy's core for the agent: a consume-mode tracklist."""

    def __init__(self):
        self.tl = []
        self.current = None
        self.state = "stopped"
        self.position = 0
        self._tlid = 0
        core = self

        class Tracklist:
            def add(self, tracks=None, uris=None):
                added = []
                for t in tracks:
                    core._tlid += 1
                    added.append(TlTrack(tlid=core._tlid, track=t))
                core.tl.extend(added)
                return Future(added)

            def remove(self, criteria):
                core.tl = [t for t in core.tl if t.tlid not in criteria["tlid"]]
                return Future()

            def get_tl_tracks(self):
                return Future(list(core.tl))

            def get_length(self):
                return Future(len(core.tl))

            def clear(self):
                core.tl = []
                return Future()

            def __getattr__(self, name):  # set_consume etc.
                return lambda *a, **k: Future()

        class Playback:
            def get_state(self):
                return Future(core.state)

            def get_time_position(self):
                return Future(core.position)

            def get_current_tl_track(self):
                return Future(core.current)

            def play(self, tlid=None):
                core.current = next(t for t in core.tl if t.tlid == tlid)
                core.state = "playing"
                return Future()

            def next(self):
                return Future()

            def pause(self):
                core.state = "paused"
                return Future()

            def resume(self):
                core.state = "playing"
                return Future()

        self.tracklist = Tracklist()
        self.playback = Playback()


def make_agent(tmp_path):
    config = {"beatballot": {"mode": "player", "hub_url": "www.klubhuset.party"}}
    core = FakeCore()
    return PlayerAgent(config, core, tmp_path), core


def test_hub_base():
    assert hub_base("www.klubhuset.party") == "https://www.klubhuset.party/beatballot"
    assert hub_base("http://hub:6680/") == "http://hub:6680/beatballot"
    assert hub_base("https://h/beatballot/") == "https://h/beatballot"


def test_enqueue_play_and_status(tmp_path):
    agent, core = make_agent(tmp_path)
    agent.handle(
        {
            "cmd": "enqueue",
            "seq": 1,
            "id": 77,
            "url": "https://cdn/a.mp4",
            "title": "Get Lucky",
            "artist": "Daft Punk",
            "length_ms": 248000,
        }
    )
    [tl] = core.tl
    assert tl.track.uri == "https://cdn/a.mp4"
    assert tl.track.name == "Get Lucky"
    assert tl.track.length == 248000
    agent.handle({"cmd": "play", "seq": 2})
    core.position = 1234
    status = agent.status()
    assert status == {
        "type": "status",
        "state": "playing",
        "position_ms": 1234,
        "current": 77,
        "queue": [77],
        "ack": 2,
    }


def test_manifest_is_written_and_played_as_file(tmp_path):
    agent, core = make_agent(tmp_path)
    agent.handle({"cmd": "enqueue", "seq": 1, "id": 5, "manifest": "<MPD/>"})
    path = tmp_path / "manifests" / "5.mpd"
    assert path.read_text() == "<MPD/>"
    assert core.tl[0].track.uri == path.as_uri()
    # Manifests of songs that are gone get cleaned up.
    agent.handle({"cmd": "remove", "seq": 2, "id": 5})
    agent.status()
    assert not path.exists()


def test_status_drops_consumed_songs_and_reconnect_resets_ack(tmp_path):
    agent, core = make_agent(tmp_path)
    agent.handle({"cmd": "enqueue", "seq": 4, "id": 1, "url": "https://x/1"})
    core.tl.clear()  # consumed
    status = agent.status()
    assert status["queue"] == [] and status["current"] is None
    assert agent.ids == {}
    agent.handle({"cmd": "_connected"})
    assert agent.ack == 0


def test_bad_command_does_not_crash(tmp_path):
    agent, _ = make_agent(tmp_path)
    agent.handle({"cmd": "enqueue", "seq": 3})  # missing fields
    agent.handle({"cmd": "dance", "seq": 4})
    assert agent.ack == 4


def test_player_identifies_itself(tmp_path):
    agent, _ = make_agent(tmp_path)
    assert agent.user_agent.startswith("BeatBallot-Player/")
    assert "Python" not in agent.user_agent
