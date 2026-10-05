"""Tornado handlers: parties, the hub owner's API, remote players, the app."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import pathlib
import secrets
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import tornado.web
import tornado.websocket
from tornado.ioloop import IOLoop

from . import rooms, tidal_auth
from .hub import HUB, Hub
from .rooms import Room, RoomError, RoomStore
from .settings import Settings
from .tracks import TrackInfo
from .voting import VoteError

logger = logging.getLogger(__name__)

STATIC_DIR = pathlib.Path(__file__).parent / "static"
MAX_NAME_LENGTH = 24
JOIN_ATTEMPTS_PER_MINUTE = 10
CALL_TIMEOUT_S = 30
HUB_ROOM = "_hub"  # Pseudo-room of the hub owner's tokens.


class Unavailable(Exception):
    pass


# --- auth ------------------------------------------------------------------


@dataclass(frozen=True)
class User:
    id: str
    name: str
    admin: bool = False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class Auth:
    """Stateless signed tokens, scoped to one party.

    A token is signed with a key derived from the party's PINs, so changing
    a party's PINs signs everyone out of that party (and only that party).
    """

    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    def _key(self, room_id: str, pin: str, admin_pin: str) -> bytes:
        material = b"\0".join(
            [self._secret, room_id.encode(), pin.encode(), admin_pin.encode()]
        )
        return hashlib.sha256(material).digest()

    def _sign(self, key: bytes, payload: str) -> str:
        return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())

    def join(
        self, room_id: str, pin: str, admin_pin: str, entered: str, name: str
    ) -> tuple[str, User] | None:
        admin = bool(admin_pin) and hmac.compare_digest(entered, admin_pin)
        if not admin and not (pin and hmac.compare_digest(entered, pin)):
            return None
        user = User(uuid.uuid4().hex, name, admin)
        data = {"r": room_id, "id": user.id, "n": name, "a": admin}
        payload = _b64(json.dumps(data).encode())
        return (
            f"{payload}.{self._sign(self._key(room_id, pin, admin_pin), payload)}",
            user,
        )

    def verify(self, token: str, pins: Any) -> tuple[str, User] | None:
        """``pins(room_id)`` returns (pin, admin_pin), or None if unknown."""
        try:
            payload, signature = token.split(".", 1)
            data = json.loads(_unb64(payload))
            room_id = data["r"]
            found = pins(room_id)
            if found is None:
                return None
            key = self._key(room_id, *found)
            if not hmac.compare_digest(signature, self._sign(key, payload)):
                return None
            return room_id, User(data["id"], data["n"], bool(data["a"]))
        except (ValueError, KeyError, TypeError):
            return None


def load_secret(data_dir: pathlib.Path) -> bytes:
    """A per-install secret, kept so tokens survive restarts."""
    path = data_dir / "secret"
    try:
        return path.read_bytes()
    except FileNotFoundError:
        secret = secrets.token_bytes(32)
        path.write_bytes(secret)
        path.chmod(0o600)
        return secret


def clean_name(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    name = " ".join(name.split())[:MAX_NAME_LENGTH]
    return name or None


# --- bridge to the frontend actor -------------------------------------------


class FrontendApi:
    """Runs blocking actor/core calls off the IOLoop thread."""

    def __init__(self, player: Any) -> None:
        self.player = player

    def _proxy(self) -> Any:
        import pykka  # noqa: PLC0415

        from .frontend import BallotFrontend  # noqa: PLC0415

        refs = pykka.ActorRegistry.get_by_class(BallotFrontend)
        if not refs:
            raise Unavailable("Beat Ballot is starting up")
        return refs[0].proxy()

    async def _run(self, fn: Any, *args: Any) -> Any:
        return await IOLoop.current().run_in_executor(None, fn, *args)

    async def call(self, method: str, *args: Any) -> Any:
        def run() -> Any:
            return getattr(self._proxy(), method)(*args).get(timeout=CALL_TIMEOUT_S)

        return await self._run(run)

    def tell(self, method: str, *args: Any) -> None:
        """Fire and forget; calls arrive in order."""
        getattr(self._proxy(), method)(*args)

    async def search(self, query: str) -> list[TrackInfo]:
        return await self._run(self.player.search, query)

    async def lookup(self, uri: str) -> TrackInfo | None:
        return await self._run(self.player.lookup, uri)

    def available(self) -> bool:
        try:
            self._proxy()
        except Unavailable:
            return False
        return True


# --- shared helpers ----------------------------------------------------------


def _in_networks(
    ip: str, networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network]
) -> bool:
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    return any(address in net for net in networks)


def client_ip(
    remote_ip: str, forwarded_for: str | None, trusted_proxies: list[str]
) -> str:
    """The guest's IP. Behind trusted proxies, take the right-most address in
    X-Forwarded-For that isn't a proxy: entries further left can be forged by
    the client, but each trusted proxy appends the peer it saw."""
    networks = []
    for entry in trusted_proxies:
        try:
            networks.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            logger.warning("Ignoring invalid trusted proxy %r", entry)
    if not networks or not _in_networks(remote_ip, networks) or not forwarded_for:
        return remote_ip
    for hop in reversed(forwarded_for.split(",")):
        hop = hop.strip()
        if hop and not _in_networks(hop, networks):
            return hop
    return remote_ip


class FailedJoins:
    """Wrong-PIN/code attempts per IP over the last minute."""

    def __init__(self) -> None:
        self._attempts: defaultdict[str, deque[float]] = defaultdict(deque)

    def blocked(self, ip: str) -> bool:
        attempts = self._attempts[ip]
        now = time.monotonic()
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        return len(attempts) >= JOIN_ATTEMPTS_PER_MINUTE

    def add(self, ip: str) -> None:
        self._attempts[ip].append(time.monotonic())


class Context:
    """What every handler needs."""

    def __init__(
        self,
        auth: Auth,
        api: FrontendApi,
        settings: Settings,
        hub: Hub,
        store: Any = None,
    ) -> None:
        self.auth = auth
        self.api = api
        self.settings = settings
        self.hub = hub
        self._store = store
        self.failed = FailedJoins()
        self.player_sockets: dict[str, PlayerSocketHandler] = {}

    @property
    def store(self) -> RoomStore:
        store = self._store or rooms.STORE
        if store is None:
            raise Unavailable("Beat Ballot is starting up")
        return store

    def pins(self, room_id: str) -> tuple[str, str] | None:
        if room_id == HUB_ROOM:
            return (
                (self.settings.hub_pin, self.settings.hub_pin)
                if self.settings.hub_pin
                else None
            )
        room = self.store.get(room_id)
        return (room.pin, room.admin_pin) if room else None

    def verify(self, token: str) -> tuple[str, User] | None:
        return self.auth.verify(token, self.pins)

    def join_url(self, room: Room) -> str | None:
        base = self.settings.public_url
        if not base:
            return None
        return f"{base.rstrip('/')}/r/{room.slug}/"

    def base_url(self) -> str:
        base = self.settings.public_url
        return f"{base.rstrip('/')}/" if base else ""


class BaseHandler(tornado.web.RequestHandler):
    def initialize(self, ctx: Context) -> None:
        self.ctx = ctx

    def set_default_headers(self) -> None:
        self.set_header("Cache-Control", "no-store")

    def write_json(self, data: Any, status: int = 200) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(data))

    def body(self) -> dict[str, Any]:
        try:
            data = json.loads(self.request.body or b"{}")
        except ValueError as e:
            raise tornado.web.HTTPError(400, "Bad request") from e
        if not isinstance(data, dict):
            raise tornado.web.HTTPError(400, "Bad request")
        return data

    def ip(self) -> str:
        return client_ip(
            self.request.remote_ip or "",
            self.request.headers.get("X-Forwarded-For"),
            self.ctx.settings.trusted_proxies,
        )

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        # HTTPError's message is meant for people; anything else is a bug.
        exc = kwargs.get("exc_info", (None, None))[1]
        if isinstance(exc, tornado.web.HTTPError) and exc.log_message:
            message = exc.log_message
        elif status_code < 500:
            message = self._reason
        else:
            message = "Something went wrong"
        self.write_json({"error": message}, status_code)

    def room(self, slug: str) -> Room:
        room = self.ctx.store.by_slug(slug)
        if room is None:
            raise tornado.web.HTTPError(404, "No such party")
        return room


# --- guests ------------------------------------------------------------------


class ModeHandler(BaseHandler):
    """What the landing page needs: the mode and the listed parties."""

    def get(self) -> None:
        listed = [r.public() for r in self.ctx.store.list() if r.listed]
        self.write_json(
            {
                "mode": self.ctx.settings.mode,
                "rooms": listed,
                "hub_admin": bool(self.ctx.settings.hub_pin),
            }
        )


class RoomInfoHandler(BaseHandler):
    def get(self, slug: str) -> None:
        room = self.room(slug)
        self.write_json(
            {
                "room": room.public(),
                "public_url": self.ctx.join_url(room),
                "admin_enabled": bool(room.admin_pin),
                "mode": self.ctx.settings.mode,
            }
        )


class JoinHandler(BaseHandler):
    def post(self, slug: str) -> None:
        ip = self.ip()
        if self.ctx.failed.blocked(ip):
            return self.write_json({"error": "Too many attempts, wait a minute"}, 429)
        room = self.room(slug)
        body = self.body()
        name = clean_name(body.get("name"))
        if name is None:
            return self.write_json({"error": "Pick a nickname"}, 400)
        joined = self.ctx.auth.join(
            room.id, room.pin, room.admin_pin, str(body.get("pin", "")), name
        )
        if joined is None:
            self.ctx.failed.add(ip)
            return self.write_json({"error": "Wrong PIN"}, 403)
        token, user = joined
        self.write_json(
            {
                "token": token,
                "user": {"id": user.id, "name": name, "admin": user.admin},
                "room": room.public(),
            }
        )


class LoginsHandler(BaseHandler):
    """Backend logins waiting (Tidal). Whoever opens the link connects their
    account, so only the hub owner sees it (or the host, when standalone)."""

    def get(self) -> None:
        found = self.ctx.verify(self.get_argument("token", ""))
        owner = found is not None and found[0] == HUB_ROOM
        standalone_host = (
            found is not None
            and found[1].admin
            and self.ctx.settings.mode == "standalone"
        )
        if not (owner or standalone_host):
            return self.write_json({"error": "Hub owner only"}, 403)
        tidal = tidal_auth.ACTIVE
        self.write_json({"tidal": tidal.status() if tidal else None})


class HealthHandler(BaseHandler):
    def get(self) -> None:
        ok = self.ctx.api.available()
        self.write_json({"ok": ok}, 200 if ok else 503)


class SocketHandler(tornado.websocket.WebSocketHandler):
    """A guest's or host's live connection to one party."""

    def initialize(self, ctx: Context) -> None:
        self.ctx = ctx
        self.user: User | None = None
        self.room_id: str | None = None

    async def open(self) -> None:
        found = self.ctx.verify(self.get_argument("token", ""))
        if found is None or found[0] == HUB_ROOM:
            self.close(4001, "Please join again")
            return
        self.room_id, self.user = found
        room = self.ctx.store.get(self.room_id)
        self.ctx.hub.attach(self.room_id, self)
        self.write_message(
            {
                "type": "hello",
                "user": {
                    "id": self.user.id,
                    "name": self.user.name,
                    "admin": self.user.admin,
                },
                "room": room.public() if room else None,
                # Hosts get the guest PIN so the big screen can display it.
                "pin": room.pin if room and self.user.admin else None,
            }
        )
        latest = self.ctx.hub.latest.get(self.room_id)
        if latest is not None:
            self.send(latest)
        else:
            try:
                self.write_message(await self.ctx.api.call("snapshot", self.room_id))
            except Exception as e:
                self._error(e)

    def on_close(self) -> None:
        if self.room_id is not None:
            self.ctx.hub.detach(self.room_id, self)

    def send(self, message: str) -> None:
        self.write_message(message)

    async def on_message(self, message: str | bytes) -> None:
        if self.user is None or self.room_id is None:
            return
        # PINs changed or party deleted since this socket opened?
        if self.ctx.pins(self.room_id) is None:
            self.close(4001, "This party no longer exists")
            return
        try:
            data = json.loads(message)
            await self._dispatch(self.room_id, self.user, data)
        except Exception as e:
            self._error(e)

    async def _dispatch(self, room_id: str, user: User, data: dict[str, Any]) -> None:
        api = self.ctx.api
        match data.get("type"):
            case "vote":
                await api.call("vote", room_id, user.id, user.name, str(data["uri"]))
            case "retract":
                await api.call("retract", room_id, user.id)
            case "suggest":
                track = await api.lookup(str(data["uri"]))
                if track is None:
                    raise VoteError("Could not find that song")
                await api.call("suggest", room_id, user.id, user.name, track)
            case "search":
                query = str(data.get("q", "")).strip()[:100]
                results = await api.search(query) if query else []
                if self.ctx.settings.mode == "hub":
                    # Remote players can't stream Spotify.
                    results = [t for t in results if not t.uri.startswith("spotify:")]
                self.write_message(
                    {
                        "type": "search_results",
                        "id": data.get("id"),
                        "results": [t.to_dict() for t in results],
                    }
                )
            case "admin":
                if not user.admin:
                    raise VoteError("Host only")
                await api.call("admin", room_id, str(data["action"]), data.get("value"))
            case "ping":
                self.write_message({"type": "pong"})
            case other:
                raise VoteError(f"Unknown message {other!r}")

    def _error(self, e: Exception) -> None:
        if isinstance(e, VoteError | Unavailable | RoomError):
            message = str(e)
        else:
            logger.exception("Beat Ballot request failed")
            message = "Something went wrong"
        if self.ws_connection is not None:
            self.write_message({"type": "error", "message": message})


# --- hub owner -----------------------------------------------------------------


class HubLoginHandler(BaseHandler):
    def post(self) -> None:
        ip = self.ip()
        if self.ctx.failed.blocked(ip):
            return self.write_json({"error": "Too many attempts, wait a minute"}, 429)
        if not self.ctx.settings.hub_pin:
            return self.write_json({"error": "Set a hub PIN to manage parties"}, 404)
        joined = self.ctx.auth.join(
            HUB_ROOM,
            self.ctx.settings.hub_pin,
            self.ctx.settings.hub_pin,
            str(self.body().get("pin", "")),
            "Owner",
        )
        if joined is None:
            self.ctx.failed.add(ip)
            return self.write_json({"error": "Wrong PIN"}, 403)
        self.write_json({"token": joined[0]})


class OwnerHandler(BaseHandler):
    """Hub owner endpoints: a Bearer token from HubLoginHandler."""

    def prepare(self) -> None:
        header = self.request.headers.get("Authorization", "")
        found = self.ctx.verify(header.removeprefix("Bearer ").strip())
        if found is None or found[0] != HUB_ROOM:
            raise tornado.web.HTTPError(401, "Log in as the hub owner")
        if self.ctx.settings.mode != "hub":
            raise tornado.web.HTTPError(404, "Only a hub hosts several parties")

    async def call(self, method: str, *args: Any) -> Any:
        try:
            return await self.ctx.api.call(method, *args)
        except (RoomError, VoteError) as e:
            raise tornado.web.HTTPError(400, str(e)) from e


class HubRoomsHandler(OwnerHandler):
    async def get(self) -> None:
        rows = await self.call("overview", self.ctx.base_url())
        for row in rows:
            row["player"]["connected"] = row["id"] in self.ctx.player_sockets
        self.write_json({"rooms": rows})

    async def post(self) -> None:
        body = self.body()
        fields = {
            k: body[k]
            for k in ("name", "slug", "pin", "admin_pin", "playlists")
            if body.get(k)
        }
        self.write_json({"room": await self.call("create_room", fields)}, 201)


class HubRoomHandler(OwnerHandler):
    async def patch(self, room_id: str) -> None:
        body = self.body()
        allowed = ("name", "slug", "pin", "admin_pin", "playlists", "listed")
        changes = {k: body[k] for k in allowed if k in body}
        self.write_json({"room": await self.call("update_room", room_id, changes)})

    async def delete(self, room_id: str) -> None:
        await self.call("delete_room", room_id)
        self._drop_player(room_id, "This party was deleted")
        self.write_json({"ok": True})

    def _drop_player(self, room_id: str, reason: str) -> None:
        socket = self.ctx.player_sockets.pop(room_id, None)
        if socket is not None:
            socket.close(4001, reason)


class HubPairHandler(HubRoomHandler):
    def post(self, room_id: str, action: str) -> None:
        try:
            if action == "pair":
                code, ttl = self.ctx.store.start_pairing(room_id)
                return self.write_json({"code": code, "expires_in": ttl})
            self.ctx.store.unpair(room_id)
        except RoomError as e:
            raise tornado.web.HTTPError(400, str(e)) from e
        self._drop_player(room_id, "This player was unpaired")
        self.write_json({"ok": True})


# --- remote players ----------------------------------------------------------------


class PlayerPairHandler(BaseHandler):
    def post(self) -> None:
        ip = self.ip()
        if self.ctx.failed.blocked(ip):
            return self.write_json({"error": "Too many attempts, wait a minute"}, 429)
        body = self.body()
        try:
            room, token = self.ctx.store.pair(
                str(body.get("code", "")), clean_name(body.get("name"))
            )
        except RoomError as e:
            self.ctx.failed.add(ip)
            return self.write_json({"error": str(e)}, 403)
        # A newly paired player replaces the old one.
        old = self.ctx.player_sockets.pop(room.id, None)
        if old is not None:
            old.close(4001, "Replaced by a newly paired player")
        self.write_json({"token": token, "room": room.public()})


class PlayerSocketHandler(tornado.websocket.WebSocketHandler):
    """A paired player's connection: commands out, status reports in."""

    def initialize(self, ctx: Context) -> None:
        self.ctx = ctx
        self.room_id: str | None = None
        self._send_fn: Any = None

    def open(self) -> None:
        header = self.request.headers.get("Authorization", "")
        room = self.ctx.store.verify_player(header.removeprefix("Bearer ").strip())
        if room is None:
            self.close(4001, "Unknown player; pair it again")
            return
        self.room_id = room.id
        old = self.ctx.player_sockets.get(room.id)
        if old is not None and old is not self:
            old.close(4000, "Another connection took over")
        self.ctx.player_sockets[room.id] = self
        loop = IOLoop.current()
        self.ctx.hub.set_loop(loop)

        def send(message: dict[str, Any]) -> None:  # Called from the actor thread.
            loop.add_callback(self._write, json.dumps(message))

        self._send_fn = send
        name = self.request.headers.get("X-Player-Name") or room.player_name
        self.write_message({"type": "hello", "room": room.public()})
        self.ctx.api.tell("player_connected", room.id, send, clean_name(name))
        logger.info("Beat Ballot: player connected to %r", room.slug)

    def _write(self, message: str) -> None:
        if self.ws_connection is not None:
            self.write_message(message)

    def on_message(self, message: str | bytes) -> None:
        if self.room_id is None:
            return
        try:
            data = json.loads(message)
        except ValueError:
            return
        if data.get("type") == "status":
            self.ctx.api.tell("player_status", self.room_id, data)

    def on_close(self) -> None:
        if self.room_id is None:
            return
        if self.ctx.player_sockets.get(self.room_id) is self:
            del self.ctx.player_sockets[self.room_id]
        with contextlib.suppress(Unavailable):
            self.ctx.api.tell("player_disconnected", self.room_id, self._send_fn)
        logger.info("Beat Ballot: player left party %s", self.room_id)


# --- the app ---------------------------------------------------------------------


class AppHandler(tornado.web.StaticFileHandler):
    """Serves the built Svelte app. Hashed assets are cached forever."""

    def set_extra_headers(self, path: str) -> None:
        if path.startswith("assets/"):
            self.set_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.set_header("Cache-Control", "no-cache")


class RoomPageHandler(tornado.web.RequestHandler):
    """/r/<slug>/ is the app too; it reads the party from the path."""

    def get(self, slug: str) -> None:
        self.set_header("Cache-Control", "no-cache")
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        try:
            self.finish((STATIC_DIR / "index.html").read_bytes())
        except FileNotFoundError:
            raise tornado.web.HTTPError(404) from None


class PlayerHealthHandler(tornado.web.RequestHandler):
    def get(self) -> None:
        from . import agent  # noqa: PLC0415

        health = agent.ACTIVE.health() if agent.ACTIVE else {"ok": False}
        self.set_status(200 if health.get("ok") else 503)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(health))


def make_app(config: Any, core: Any) -> list[tuple[Any, ...]]:
    from . import Extension  # noqa: PLC0415
    from .player import MopidyPlayer  # noqa: PLC0415

    settings = Settings.from_config(config["beatballot"])
    if settings.mode == "player":
        return [
            (r"/api/health", PlayerHealthHandler),
            (r"/", tornado.web.RedirectHandler, {"url": "api/health"}),
        ]

    def login_pending(source: str) -> bool:
        tidal = tidal_auth.ACTIVE
        return source == "tidal" and tidal is not None and tidal.pending

    def tidal_search(query: str, limit: int) -> list[TrackInfo] | None:
        tidal = tidal_auth.ACTIVE
        return tidal.search_tracks(query, limit) if tidal else None

    api = FrontendApi(
        MopidyPlayer(
            core,
            settings.search_schemes,
            login_pending,
            fast_search={"tidal": tidal_search},
        )
    )
    auth = Auth(load_secret(Extension.get_data_dir(config)))
    return routes(Context(auth, api, settings, HUB))


def routes(ctx: Context) -> list[tuple[Any, ...]]:
    c = {"ctx": ctx}
    slug = r"([a-z0-9-]+)"
    room_id = r"([a-zA-Z0-9_-]+)"
    return [
        (r"/api/mode", ModeHandler, c),
        (rf"/api/rooms/{slug}/info", RoomInfoHandler, c),
        (rf"/api/rooms/{slug}/join", JoinHandler, c),
        (r"/api/health", HealthHandler, c),
        (r"/api/logins", LoginsHandler, c),
        (r"/api/hub/login", HubLoginHandler, c),
        (r"/api/hub/rooms", HubRoomsHandler, c),
        (rf"/api/hub/rooms/{room_id}", HubRoomHandler, c),
        (rf"/api/hub/rooms/{room_id}/(pair|unpair)", HubPairHandler, c),
        (r"/api/player/pair", PlayerPairHandler, c),
        (r"/player/ws", PlayerSocketHandler, c),
        (r"/ws", SocketHandler, c),
        (rf"/r/{slug}/?.*", RoomPageHandler),
        (
            r"/(.*)",
            AppHandler,
            {"path": str(STATIC_DIR), "default_filename": "index.html"},
        ),
    ]
