import json

import tornado.web
import tornado.websocket
from tornado.testing import AsyncHTTPTestCase, gen_test

from mopidy_beatballot.hub import Hub
from mopidy_beatballot.settings import Settings
from mopidy_beatballot.voting import VoteError
from mopidy_beatballot.web import Auth, client_ip, routes

from .helpers import track


class FakeApi:
    def __init__(self, hub):
        self.hub = hub
        self.calls = []

    async def call(self, method, *args):
        self.calls.append((method, *args))
        if method == "vote" and args[2] == "bad":
            raise VoteError("That song is not in this round")
        if method == "snapshot":
            return {"type": "state", "round": {"id": 1}}
        self.hub.broadcast({"type": "state", "last": method})

    async def search(self, query):
        return [track("spotify:track:1")]

    async def lookup(self, uri):
        return track(uri)

    def available(self):
        return True


def test_auth_tokens_roundtrip_and_reject_tampering():
    auth = Auth(b"s" * 32, "1234", "9999")
    token, user = auth.join("1234", "Ann")
    assert auth.verify(token) == user
    assert not user.admin
    assert auth.join("0000", "Ann") is None
    assert auth.verify(token[:-2] + "xx") is None
    assert auth.verify("garbage") is None
    _, admin = auth.join("9999", "Host")
    assert admin.admin
    # Changing the PIN invalidates old tokens.
    assert Auth(b"s" * 32, "4321", "9999").verify(token) is None


def test_empty_admin_pin_disables_admin():
    auth = Auth(b"s" * 32, "1234", "")
    assert auth.join("", "x") is None


class WebTest(AsyncHTTPTestCase):
    def get_app(self):
        self.hub = Hub()
        self.api = FakeApi(self.hub)
        self.auth = Auth(b"k" * 32, "1234", "9999")
        settings = Settings(pin="1234", admin_pin="9999")
        return tornado.web.Application(routes(self.auth, self.api, settings, self.hub))

    def join(self, pin="1234", name="  Ann   B "):
        return self.fetch(
            "/api/join", method="POST", body=json.dumps({"pin": pin, "name": name})
        )

    def test_join(self):
        res = self.join()
        assert res.code == 200
        data = json.loads(res.body)
        assert data["user"]["name"] == "Ann B"
        assert self.auth.verify(data["token"]).name == "Ann B"

    def test_join_wrong_pin(self):
        assert self.join(pin="1").code == 403

    def test_join_requires_name(self):
        assert self.join(name="   ").code == 400

    def test_join_rate_limited(self):
        codes = [self.join(pin="1").code for _ in range(12)]
        assert codes[-1] == 429

    def test_logins_is_host_only(self):
        guest, _ = self.auth.join("1234", "Ann")
        host, _ = self.auth.join("9999", "Host")
        assert self.fetch(f"/api/logins?token={guest}").code == 403
        res = self.fetch(f"/api/logins?token={host}")
        assert res.code == 200
        assert json.loads(res.body) == {"tidal": None}

    def test_health(self):
        assert json.loads(self.fetch("/api/health").body) == {"ok": True}

    async def connect(self, token):
        url = f"ws://127.0.0.1:{self.get_http_port()}/ws?token={token}"
        return await tornado.websocket.websocket_connect(url)

    async def read(self, ws):
        return json.loads(await ws.read_message())

    @gen_test
    async def test_websocket_flow(self):
        token, _ = self.auth.join("1234", "Ann")
        ws = await self.connect(token)
        assert (await self.read(ws))["type"] == "hello"
        assert (await self.read(ws))["type"] == "state"

        ws.write_message(json.dumps({"type": "vote", "uri": "a"}))
        assert (await self.read(ws))["last"] == "vote"

        ws.write_message(json.dumps({"type": "vote", "uri": "bad"}))
        msg = await self.read(ws)
        assert msg == {"type": "error", "message": "That song is not in this round"}

        ws.write_message(json.dumps({"type": "search", "q": "abba", "id": 7}))
        msg = await self.read(ws)
        assert msg["type"] == "search_results" and msg["id"] == 7
        assert msg["results"][0]["uri"] == "spotify:track:1"

        ws.write_message(json.dumps({"type": "admin", "action": "skip"}))
        assert (await self.read(ws))["message"] == "Host only"
        ws.close()

    @gen_test
    async def test_admin_over_websocket(self):
        token, _ = self.auth.join("9999", "Host")
        ws = await self.connect(token)
        await self.read(ws)
        await self.read(ws)
        ws.write_message(json.dumps({"type": "admin", "action": "skip"}))
        assert (await self.read(ws))["last"] == "admin"
        assert self.api.calls[-1] == ("admin", "skip", None)
        ws.close()

    @gen_test
    async def test_websocket_rejects_bad_token(self):
        ws = await self.connect("nope")
        assert await ws.read_message() is None
        assert ws.close_code == 4001


def test_make_app_builds_routes(tmp_path, monkeypatch):
    from mopidy_beatballot import tidal_auth, web

    config = {
        "core": {"data_dir": str(tmp_path)},
        "beatballot": {"pin": "1", "playlists": ("a", "b"), "search_schemes": ()},
    }
    routes = web.make_app(config, core=object())
    api = routes[0][2]["api"]
    assert {r[0] for r in routes} >= {"/api/join", "/ws", "/api/logins"}
    assert (tmp_path / "beatballot" / "secret").exists()

    class Pending:
        pending = True

    monkeypatch.setattr(tidal_auth, "ACTIVE", Pending())
    assert api.player.login_pending("tidal")
    assert not api.player.login_pending("spotify")


def test_client_ip_without_trusted_proxies_ignores_header():
    assert client_ip("10.0.0.5", "6.6.6.6", []) == "10.0.0.5"


def test_client_ip_behind_traefik_and_cloudflare():
    trusted = ["192.168.10.254", "173.245.48.0/20"]
    # Forged left-most entry, real client, then the Cloudflare edge Traefik saw.
    xff = "1.2.3.4, 85.0.0.7, 173.245.48.9"
    assert client_ip("192.168.10.254", xff, trusted) == "85.0.0.7"
    # Direct to Traefik (no Cloudflare).
    assert client_ip("192.168.10.254", "85.0.0.7", trusted) == "85.0.0.7"
    # Not from a trusted proxy: header is ignored.
    assert client_ip("85.0.0.9", "1.2.3.4", trusted) == "85.0.0.9"
    assert client_ip("192.168.10.254", None, trusted) == "192.168.10.254"
