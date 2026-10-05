import json

import pytest

from mopidy_beatballot.rooms import RoomError, RoomStore, slugify

from .helpers import FakeClock


def test_create_persists_and_reloads(tmp_path):
    path = tmp_path / "rooms.json"
    store = RoomStore(path)
    room = store.create("Klubhuset Fredag!", pin="2468")
    assert room.slug == "klubhuset-fredag"
    assert room.pin == "2468"
    assert room.admin_pin.isdigit() and len(room.admin_pin) == 6
    assert path.stat().st_mode & 0o777 == 0o600  # holds PINs

    again = RoomStore(path)
    assert again.get(room.id) == room
    assert again.by_slug("klubhuset-fredag").id == room.id


def test_slugs_are_unique_and_validated():
    store = RoomStore()
    a = store.create("Party")
    b = store.create("Party")
    assert (a.slug, b.slug) == ("party", "party-2")
    with pytest.raises(RoomError):
        store.update(b.id, slug="party")
    with pytest.raises(RoomError):
        store.update(b.id, slug="Not OK!")
    assert slugify("  ") == "party"


def test_pin_rules():
    store = RoomStore()
    with pytest.raises(RoomError):
        store.create("x", pin="12")
    with pytest.raises(RoomError):
        store.create("x", pin="5555", admin_pin="5555")
    room = store.create("x")
    assert room.pin != room.admin_pin
    assert room.pin not in ("1234", "0000")


def test_update_and_delete():
    store = RoomStore()
    room = store.create("x")
    store.update(room.id, name="  New   name ", test_mode=True)
    assert store.get(room.id).name == "New name"
    with pytest.raises(RoomError):
        store.update(room.id, player_token_hash="sneaky")
    store.delete(room.id)
    assert store.list() == []


def test_pairing_flow_and_token_check():
    clock = FakeClock(1000)
    store = RoomStore(clock=clock)
    room = store.create("x")
    code, ttl = store.start_pairing(room.id)
    assert ttl == 900
    paired, token = store.pair(code.lower().replace("-", " "), "Pi")
    assert paired.id == room.id
    assert paired.player_name == "Pi"
    assert store.verify_player(token).id == room.id
    assert store.verify_player(token + "x") is None
    assert store.verify_player("garbage") is None
    with pytest.raises(RoomError):
        store.pair(code)  # single use

    # Pairing again replaces the old player.
    code2, _ = store.start_pairing(room.id)
    _, token2 = store.pair(code2)
    assert store.verify_player(token) is None
    assert store.verify_player(token2).id == room.id

    store.unpair(room.id)
    assert store.verify_player(token2) is None


def test_pairing_codes_expire():
    clock = FakeClock(1000)
    store = RoomStore(clock=clock)
    room = store.create("x")
    code, _ = store.start_pairing(room.id)
    clock.advance(901)
    with pytest.raises(RoomError):
        store.pair(code)


def test_tokens_are_stored_hashed(tmp_path):
    path = tmp_path / "rooms.json"
    store = RoomStore(path)
    room = store.create("x")
    code, _ = store.start_pairing(room.id)
    _, token = store.pair(code)
    assert token not in path.read_text()
    assert "player_token_hash" not in room.private()
    assert room.private()["paired"] is True
    assert json.loads(path.read_text())["rooms"][0]["player_token_hash"]
