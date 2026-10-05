import json
import random

import tornado.gen
import tornado.web
import tornado.websocket
from tornado.httpclient import HTTPRequest
from tornado.testing import AsyncHTTPTestCase, gen_test

from mopidy_beatballot.hub import Hub
from mopidy_beatballot.parties import Parties
from mopidy_beatballot.rooms import Room, RoomStore
from mopidy_beatballot.settings import Settings
from mopidy_beatballot.web import Auth, Context, client_ip, routes

from .helpers import FakePlayer, track


class FakeFront:
    """BallotFrontend's API over real Parties with fake players."""

    def __init__(self, parties):
        self.parties = parties
        self.player_events = []
        self.send = None

    def snapshot(self, room_id):
        return self.parties.party(room_id).snapshot()

    def vote(self, room_id, user_id, name, uri):
        self.parties.party(room_id).vote(user_id, name, uri)

    def retract(self, room_id, user_id):
        self.parties.party(room_id).retract(user_id)

    def suggest(self, room_id, user_id, name, track):
        self.parties.party(room_id).suggest(user_id, name, track)

    def admin(self, room_id, action, value=None):
        self.parties.admin(room_id, action, value)

    def overview(self, base_url):
        return self.parties.overview(base_url)

    def create_room(self, fields):
        return self.parties.create_room(**fields)

    def update_room(self, room_id, changes):
        return self.parties.update_room(room_id, changes)

    def delete_room(self, room_id):
        self.parties.delete_room(room_id)

    def player_connected(self, room_id, send, name):
        self.player_events.append(("connected", room_id, name))
        self.send = send

    def player_status(self, room_id, status):
        self.player_events.append(("status", room_id, status["state"]))

    def player_disconnected(self, room_id, send):
        self.player_events.append(("disconnected", room_id))


class FakeApi:
    def __init__(self, front):
        self.front = front

    async def call(self, method, *args):
        return getattr(self.front, method)(*args)

    def tell(self, method, *args):
        getattr(self.front, method)(*args)

    async def search(self, query):
        return [track("spotify:track:1"), track("tidal:track:1:2:3")]

    async def lookup(self, uri):
        return track(uri)

    def available(self):
        return True


class WebTest(AsyncHTTPTestCase):
    mode = "hub"

    def get_app(self):
        self.hub = Hub()
        self.store = RoomStore()
        self.store.add(
            Room(
                id="r1",
                slug="party",
                name="Party",
                pin="1234",
                admin_pin="9999",
                playlists=["x:playlist"],
            )
        )
        self.settings = Settings(mode=self.mode, hub_pin="0000")
        tracks = [track(f"t{i}") for i in range(10)]
        self.parties = Parties(
            self.settings,
            self.store,
            lambda room: FakePlayer(tracks),
            self.hub.broadcast,
            rng=random.Random(1),
        )
        self.parties.start()
        self.front = FakeFront(self.parties)
        self.auth = Auth(b"k" * 32)
        self.ctx = Context(
            self.auth, FakeApi(self.front), self.settings, self.hub, self.store
        )
        return tornado.web.Application(routes(self.ctx))

    # helpers

    def post(self, path, body, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.fetch(path, method="POST", body=json.dumps(body), headers=headers)

    def join(self, pin="1234", name="  Ann   B ", slug="party"):
        return self.post(f"/api/rooms/{slug}/join", {"pin": pin, "name": name})

    def owner(self):
        return json.loads(self.post("/api/hub/login", {"pin": "0000"}).body)["token"]

    async def apost(self, path, body, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        res = await self.http_client.fetch(
            self.get_url(path),
            method="POST",
            body=json.dumps(body),
            headers=headers,
            raise_error=False,
        )
        return json.loads(res.body)

    async def ajoin(self, pin="1234", name="Ann"):
        data = await self.apost("/api/rooms/party/join", {"pin": pin, "name": name})
        return data["token"]

    async def aowner(self):
        return (await self.apost("/api/hub/login", {"pin": "0000"}))["token"]

    async def connect(self, token):
        url = f"ws://127.0.0.1:{self.get_http_port()}/ws?token={token}"
        return await tornado.websocket.websocket_connect(url)

    async def read(self, ws):
        return json.loads(await ws.read_message())

    async def read_until(self, ws, pred):
        while not pred(msg := await self.read(ws)):
            pass
        return msg

    # guests

    def test_mode_lists_parties(self):
        data = json.loads(self.fetch("/api/mode").body)
        assert data == {
            "mode": self.mode,
            "rooms": [{"id": "r1", "slug": "party", "name": "Party"}],
            "hub_admin": True,
        }

    def test_room_info(self):
        data = json.loads(self.fetch("/api/rooms/party/info").body)
        assert data["room"]["name"] == "Party"
        assert self.fetch("/api/rooms/nope/info").code == 404

    def test_join(self):
        res = self.join()
        assert res.code == 200
        data = json.loads(res.body)
        assert data["user"]["name"] == "Ann B"
        assert data["room"]["slug"] == "party"
        room_id, user = self.ctx.verify(data["token"])
        assert room_id == "r1"
        assert user.name == "Ann B"
        assert not user.admin

    def test_join_wrong_pin_and_rate_limit(self):
        assert self.join(pin="1").code == 403
        codes = [self.join(pin="1").code for _ in range(12)]
        assert codes[-1] == 429

    def test_join_requires_name(self):
        assert self.join(name="   ").code == 400

    def test_token_is_scoped_to_its_party(self):
        token = json.loads(self.join().body)["token"]
        assert self.ctx.verify(token)[0] == "r1"
        # Changing the party's PINs signs everyone out of it.
        self.store.update("r1", pin="4321")
        assert self.ctx.verify(token) is None

    def test_room_page_serves_app(self):
        assert self.fetch("/r/party/").code in (200, 404)  # 404 if not built

    @gen_test
    async def test_host_gets_pin_and_admin(self):
        token = await self.ajoin(pin="9999", name="Host")
        ws = await self.connect(token)
        hello = await self.read(ws)
        assert hello["user"]["admin"]
        assert hello["pin"] == "1234"
        ws.write_message(
            json.dumps({"type": "admin", "action": "test_mode", "value": True})
        )
        await self.read_until(ws, lambda m: m.get("test_mode"))
        assert self.store.get("r1").test_mode is True  # persisted to the room
        ws.close()

    @gen_test
    async def test_websocket_rejects_bad_and_owner_tokens(self):
        ws = await self.connect("nope")
        assert await ws.read_message() is None
        assert ws.close_code == 4001
        ws = await self.connect(await self.aowner())
        assert await ws.read_message() is None

    def test_owner_login(self):
        assert self.post("/api/hub/login", {"pin": "1"}).code == 403
        assert self.owner()

    def test_owner_endpoints_need_owner_token(self):
        guest = json.loads(self.join(pin="9999").body)["token"]
        assert self.fetch("/api/hub/rooms").code == 401
        res = self.fetch("/api/hub/rooms", headers={"Authorization": f"Bearer {guest}"})
        assert res.code == 401

    def test_pairing_code_is_single_use(self):
        code, _ = self.store.start_pairing("r1")
        assert self.post("/api/player/pair", {"code": code}).code == 200
        assert self.post("/api/player/pair", {"code": code}).code == 403

    def test_health(self):
        assert json.loads(self.fetch("/api/health").body) == {"ok": True}


class HubWebTest(WebTest):
    @gen_test
    async def test_websocket_flow(self):
        token = await self.ajoin()
        ws = await self.connect(token)
        hello = await self.read(ws)
        assert hello["type"] == "hello"
        assert hello["room"]["slug"] == "party"
        assert hello["pin"] is None  # guests don't get the PIN
        state = await self.read_until(ws, lambda m: m["type"] == "state")
        uri = state["round"]["candidates"][0]["track"]["uri"]

        ws.write_message(json.dumps({"type": "vote", "uri": uri}))
        await self.read_until(
            ws,
            lambda m: (
                m["type"] == "state"
                and any(c["votes"] for c in m["round"]["candidates"])
            ),
        )

        ws.write_message(json.dumps({"type": "vote", "uri": "bad"}))
        msg = await self.read_until(ws, lambda m: m["type"] == "error")
        assert msg["message"] == "That song is not in this round"

        ws.write_message(json.dumps({"type": "search", "q": "abba", "id": 7}))
        msg = await self.read_until(ws, lambda m: m["type"] == "search_results")
        # Hub mode: remote players can't stream Spotify.
        assert [r["uri"] for r in msg["results"]] == ["tidal:track:1:2:3"]

        ws.write_message(json.dumps({"type": "admin", "action": "skip"}))
        msg = await self.read_until(ws, lambda m: m["type"] == "error")
        assert msg["message"] == "Host only"
        ws.close()

    def test_create_update_delete_room(self):
        owner = self.owner()
        auth = {"Authorization": f"Bearer {owner}"}
        res = self.post(
            "/api/hub/rooms", {"name": "Garden Party", "pin": "2468"}, owner
        )
        assert res.code == 201
        room = json.loads(res.body)["room"]
        assert room["slug"] == "garden-party"
        assert room["pin"] == "2468"
        assert len(room["admin_pin"]) == 6
        assert room["id"] in self.parties.parties

        res = self.fetch(
            f"/api/hub/rooms/{room['id']}",
            method="PATCH",
            headers=auth,
            body=json.dumps({"name": "Garden"}),
        )
        assert json.loads(res.body)["room"]["name"] == "Garden"
        bad = self.fetch(
            f"/api/hub/rooms/{room['id']}",
            method="PATCH",
            headers=auth,
            body=json.dumps({"slug": "party"}),
        )
        assert bad.code == 400
        assert "already used" in json.loads(bad.body)["error"]

        rows = json.loads(self.fetch("/api/hub/rooms", headers=auth).body)["rooms"]
        assert {r["slug"] for r in rows} == {"party", "garden-party"}

        res = self.fetch(f"/api/hub/rooms/{room['id']}", method="DELETE", headers=auth)
        assert res.code == 200
        assert room["id"] not in self.parties.parties
        assert self.store.get(room["id"]) is None

    @gen_test
    async def test_pair_and_connect_player(self):
        owner = {"Authorization": f"Bearer {await self.aowner()}"}
        res = await self.http_client.fetch(
            self.get_url("/api/hub/rooms/r1/pair"),
            method="POST",
            body="{}",
            headers=owner,
        )
        code = json.loads(res.body)["code"]
        assert len(code) == 9
        assert code[4] == "-"

        res = await self.http_client.fetch(
            self.get_url("/api/player/pair"),
            method="POST",
            body=json.dumps({"code": code.lower(), "name": "Pi"}),
        )
        paired = json.loads(res.body)
        assert paired["room"]["slug"] == "party"
        assert self.store.get("r1").player_name == "Pi"

        url = f"ws://127.0.0.1:{self.get_http_port()}/player/ws"
        ws = await tornado.websocket.websocket_connect(
            HTTPRequest(url, headers={"Authorization": f"Bearer {paired['token']}"})
        )
        hello = await self.read(ws)
        assert hello == {
            "type": "hello",
            "room": {"id": "r1", "slug": "party", "name": "Party"},
        }
        assert ("connected", "r1", "Pi") in self.front.player_events

        # Commands from the hub (actor thread) reach the player.
        self.front.send({"cmd": "play", "seq": 1})
        assert json.loads(await ws.read_message()) == {"cmd": "play", "seq": 1}

        ws.write_message(json.dumps({"type": "status", "state": "playing"}))
        while ("status", "r1", "playing") not in self.front.player_events:
            await tornado.gen.sleep(0.01)

        # Unpairing kicks the player off.
        await self.http_client.fetch(
            self.get_url("/api/hub/rooms/r1/unpair"),
            method="POST",
            body="{}",
            headers=owner,
        )
        assert await ws.read_message() is None
        assert ws.close_code == 4001

    @gen_test
    async def test_player_with_bad_token_is_rejected(self):
        url = f"ws://127.0.0.1:{self.get_http_port()}/player/ws"
        ws = await tornado.websocket.websocket_connect(
            HTTPRequest(url, headers={"Authorization": "Bearer bbp_r1_forged"})
        )
        assert await ws.read_message() is None
        assert ws.close_code == 4001


class StandaloneWebTest(WebTest):
    mode = "standalone"

    def test_owner_endpoints_only_in_hub_mode(self):
        auth = {"Authorization": f"Bearer {self.owner()}"}
        assert self.fetch("/api/hub/rooms", headers=auth).code == 404

    def test_logins_for_standalone_host(self):
        guest = json.loads(self.join().body)["token"]
        host = json.loads(self.join(pin="9999").body)["token"]
        assert self.fetch(f"/api/logins?token={guest}").code == 403
        res = self.fetch(f"/api/logins?token={host}")
        assert json.loads(res.body) == {"tidal": None}


# WebTest is a base class; only its subclasses run.
del WebTest


def test_client_ip_without_trusted_proxies_ignores_header():
    assert client_ip("10.0.0.5", "6.6.6.6", []) == "10.0.0.5"


def test_client_ip_behind_traefik_and_cloudflare():
    trusted = ["192.168.10.254", "173.245.48.0/20"]
    xff = "1.2.3.4, 85.0.0.7, 173.245.48.9"
    assert client_ip("192.168.10.254", xff, trusted) == "85.0.0.7"
    assert client_ip("192.168.10.254", "85.0.0.7", trusted) == "85.0.0.7"
    assert client_ip("85.0.0.9", "1.2.3.4", trusted) == "85.0.0.9"
    assert client_ip("192.168.10.254", None, trusted) == "192.168.10.254"


def test_make_app_builds_routes(tmp_path, monkeypatch):
    from mopidy_beatballot import tidal_auth, web

    config = {
        "core": {"data_dir": str(tmp_path)},
        "beatballot": {"pin": "1", "playlists": ("a", "b"), "search_schemes": ()},
    }
    built = web.make_app(config, core=object())
    ctx = built[0][2]["ctx"]
    assert {r[0] for r in built} >= {"/api/mode", "/ws", "/player/ws", "/api/logins"}
    assert (tmp_path / "beatballot" / "secret").exists()

    class Pending:
        pending = True

    monkeypatch.setattr(tidal_auth, "ACTIVE", Pending())
    assert ctx.api.player.login_pending("tidal")
    assert not ctx.api.player.login_pending("spotify")


def test_make_app_player_mode_is_just_health(tmp_path):
    from mopidy_beatballot import web

    config = {"core": {"data_dir": str(tmp_path)}, "beatballot": {"mode": "player"}}
    assert [r[0] for r in web.make_app(config, core=object())] == ["/api/health", "/"]
