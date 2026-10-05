import random

from mopidy_beatballot.parties import Parties
from mopidy_beatballot.remote import RemotePlayer
from mopidy_beatballot.rooms import RoomStore
from mopidy_beatballot.settings import Settings

from .helpers import FakeClock, FakePlayer, track

SONG = 200_000


def setup(remote=False):
    tracks = [track(f"t{i}", SONG) for i in range(12)]
    published = []
    store = RoomStore()
    clock = FakeClock()

    class Library:
        def lookup(self, uri):
            return next(t for t in tracks if t.uri == uri)

        def load_playlist(self, uri):
            return tracks

        def images(self, uris):
            return {}

    def make_player(room):
        if remote:
            return RemotePlayer(
                Library(), lambda uri: {"url": f"https://cdn/{uri}"}, clock
            )
        return FakePlayer(tracks)

    parties = Parties(
        Settings(mode="hub" if remote else "standalone"),
        store,
        make_player,
        lambda room_id, state: published.append((room_id, state)),
        rng=random.Random(1),
        clock=clock,
    )
    return parties, store, published, clock


def test_each_room_runs_its_own_party():
    parties, store, published, _ = setup()
    a = store.create("A", playlists=["x:p"])
    b = store.create("B", playlists=["x:p"])
    parties.start()
    assert set(parties.parties) == {a.id, b.id}
    pa, pb = parties.party(a.id), parties.party(b.id)
    assert pa.player is not pb.player
    uri = next(iter(pa.election.candidates))
    pa.vote("u1", "Ann", uri)
    assert pa.election.tally()[uri] == 1
    assert pb.election.tally().get(uri, 0) == 0
    # Published state is tagged with its room.
    room_ids = {rid for rid, _ in published}
    assert room_ids == {a.id, b.id}
    assert published[-1][1]["room"]["id"] in room_ids


def test_create_update_delete_rooms_live():
    parties, store, _, _ = setup()
    parties.start()
    room = parties.create_room(
        name="Garden", playlists="https://open.spotify.com/playlist/abc"
    )
    assert room["playlists"] == ["spotify:playlist:abc"]
    party = parties.party(room["id"])
    parties.update_room(room["id"], {"pin": "8642", "name": "Garden 2"})
    assert party.settings.pin == "8642"
    assert party.settings.party_name == "Garden 2"
    parties.delete_room(room["id"])
    assert room["id"] not in parties.parties


def test_host_settings_persist_to_the_room():
    parties, store, _, _ = setup()
    room = store.create("A", playlists=["x:p"])
    parties.start()
    parties.admin(room.id, "test_mode", True)
    parties.admin(room.id, "carry_over", False)
    parties.admin(room.id, "playlists", "x:a\nx:b")
    saved = store.get(room.id)
    assert saved.test_mode is True
    assert saved.carry_over is False
    assert saved.playlists == ["x:a", "x:b"]


def test_remote_party_waits_for_its_player_then_plays():
    parties, store, published, clock = setup(remote=True)
    room = store.create("A", playlists=["x:p"])
    parties.start()
    party = parties.party(room.id)
    player = party.player
    parties.tick()
    assert party.snapshot()["player"] == {"online": False, "name": None, "remote": True}
    assert party.now is None

    sent = []
    player.attach(sent.append, "Pi")
    clock.advance(5)
    parties.tick()
    # The leader is locked in, sent to the player, and play is requested.
    cmds = [c["cmd"] for c in sent]
    assert cmds[:2] == ["enqueue", "play"]
    song = sent[0]["id"]
    assert sent[0]["url"].startswith("https://cdn/")

    player.update(
        {
            "state": "playing",
            "position_ms": 0,
            "current": song,
            "queue": [song],
            "ack": 2,
        }
    )
    parties.tick()
    assert party.now[1].uri == sent[0]["url"].removeprefix("https://cdn/")
    assert party.snapshot()["player"]["online"] is True

    # 20 s before the end the next winner is queued on the player.
    player.update(
        {
            "state": "playing",
            "position_ms": SONG - 20_000,
            "current": song,
            "queue": [song],
            "ack": 2,
        }
    )
    parties.tick()
    assert sent[-1]["cmd"] == "enqueue"
    assert party.up_next is not None

    # The player drops out: nothing is lost, voting continues.
    player.detach(sent.append)
    parties.tick()
    assert party.now is None
    assert party.snapshot()["player"]["online"] is False


def test_overview_lists_rooms_and_players():
    parties, store, _, _ = setup(remote=True)
    room = store.create("A", playlists=["x:p"])
    parties.start()
    [row] = parties.overview("https://www.klubhuset.party/beatballot/")
    assert row["join_url"] == f"https://www.klubhuset.party/beatballot/r/{room.slug}/"
    assert row["player"]["online"] is False
    assert row["pin"] == room.pin
    assert "player_token_hash" not in row
    assert parties.overview("")[0]["join_url"] is None
