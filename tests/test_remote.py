import pytest

from mopidy_beatballot.remote import NotRemotelyPlayable, RemotePlayer

from .helpers import FakeClock, track


class Library:
    def lookup(self, uri):
        return track(uri)

    def load_playlist(self, uri):
        return [track("a")]

    def images(self, uris):
        return {}


def make(resolve=None):
    clock = FakeClock()
    sent = []
    player = RemotePlayer(
        Library(), resolve or (lambda uri: {"url": f"https://cdn/{uri}"}), clock
    )
    player.attach(sent.append, "Pi")
    return player, sent, clock


def test_offline_until_attached():
    player = RemotePlayer(Library(), lambda uri: {"url": "x"})
    assert not player.online
    assert player.state() == "stopped"
    with pytest.raises(ConnectionError):
        player.enqueue("a")


def test_enqueue_sends_stream_url_and_is_queued_right_away():
    player, sent, _ = make()
    player.enqueue("tidal:track:1:2:3", track("tidal:track:1:2:3"))
    cmd = sent[-1]
    assert cmd["cmd"] == "enqueue"
    assert cmd["url"] == "https://cdn/tidal:track:1:2:3"
    assert cmd["title"] == "TIDAL:TRACK:1:2:3"
    assert cmd["seq"] == 1
    # Optimistic: the controller sees the queued song before the player replies.
    assert [t.uri for _, t in player.queue()] == ["tidal:track:1:2:3"]


def test_status_before_ack_keeps_optimistic_queue():
    player, sent, _ = make()
    player.enqueue("a")
    song = sent[-1]["id"]
    player.update({"state": "stopped", "queue": [], "ack": 0})  # sent earlier
    assert player.tracklist_length() == 1
    player.update({"state": "playing", "current": song, "queue": [song], "ack": 1})
    assert player.current()[0] == song
    assert player.state() == "playing"


def test_position_is_extrapolated_while_playing():
    player, sent, clock = make()
    player.enqueue("a")
    song = sent[-1]["id"]
    player.update(
        {
            "state": "playing",
            "position_ms": 1000,
            "current": song,
            "queue": [song],
            "ack": 1,
        }
    )
    clock.advance(2.5)
    assert player.position_ms() == 3500
    player.update({"state": "paused", "position_ms": 3600, "ack": 1})
    clock.advance(10)
    assert player.position_ms() == 3600


def test_unknown_song_ids_are_ignored():
    player, _, _ = make()
    player.update({"state": "playing", "current": 999, "queue": [999], "ack": 0})
    assert player.current() is None
    assert player.queue() == []


def test_commands_and_detach():
    player, sent, _ = make()
    player.play()
    player.next()
    player.pause()
    assert [c["cmd"] for c in sent] == ["play", "next", "pause"]
    assert player.state() == "paused"
    player.detach(sent.append)
    assert not player.online
    assert player.current() is None


def test_reconnect_restarts_sequence():
    player, sent, _ = make()
    player.play()
    sent2 = []
    player.attach(sent2.append, "Pi")
    player.play()
    assert sent2[-1]["seq"] == 1


def test_unplayable_songs_raise():
    def resolve(uri):
        raise NotRemotelyPlayable("Spotify songs can only play on the hub itself")

    player, sent, _ = make(resolve)
    with pytest.raises(NotRemotelyPlayable):
        player.enqueue("spotify:track:1")
    assert sent == []
    assert player.queue() == []


def test_manifest_is_passed_through():
    player, sent, _ = make(lambda uri: {"manifest": "<MPD/>"})
    player.enqueue("tidal:track:1:2:3")
    assert sent[-1]["manifest"] == "<MPD/>"
    assert "url" not in sent[-1]
