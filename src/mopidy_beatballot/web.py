"""Tornado handlers: PIN join, party WebSocket, health and the Svelte app."""

from __future__ import annotations

import base64
import hashlib
import hmac
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

from . import tidal_auth
from .hub import HUB, Hub
from .settings import Settings
from .tracks import TrackInfo
from .voting import VoteError

logger = logging.getLogger(__name__)

STATIC_DIR = pathlib.Path(__file__).parent / "static"
MAX_NAME_LENGTH = 24
JOIN_ATTEMPTS_PER_MINUTE = 10
CALL_TIMEOUT_S = 30


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
    """Stateless signed tokens. Changing either PIN invalidates all tokens."""

    def __init__(self, secret: bytes, pin: str, admin_pin: str = "") -> None:
        self.pin = pin
        self.admin_pin = admin_pin
        self._key = hashlib.sha256(
            secret + b"\0" + pin.encode() + b"\0" + admin_pin.encode()
        ).digest()

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())

    def join(self, pin: str, name: str) -> tuple[str, User] | None:
        admin = bool(self.admin_pin) and hmac.compare_digest(pin, self.admin_pin)
        if not admin and not hmac.compare_digest(pin, self.pin):
            return None
        user = User(uuid.uuid4().hex, name, admin)
        payload = _b64(json.dumps({"id": user.id, "n": name, "a": admin}).encode())
        return f"{payload}.{self._sign(payload)}", user

    def verify(self, token: str) -> User | None:
        try:
            payload, signature = token.split(".", 1)
            if not hmac.compare_digest(signature, self._sign(payload)):
                return None
            data = json.loads(_unb64(payload))
            return User(data["id"], data["n"], bool(data["a"]))
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


# --- handlers --------------------------------------------------------------


class BaseHandler(tornado.web.RequestHandler):
    def initialize(
        self, auth: Auth, api: FrontendApi, settings: Settings, hub: Hub
    ) -> None:
        self.auth = auth
        self.api = api
        self.party_settings = settings
        self.hub = hub

    def set_default_headers(self) -> None:
        self.set_header("Cache-Control", "no-store")

    def write_json(self, data: Any, status: int = 200) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(data))


class FailedJoins:
    """Wrong-PIN attempts per IP over the last minute."""

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


class JoinHandler(BaseHandler):
    def initialize(self, failed: FailedJoins, **kwargs: Any) -> None:
        super().initialize(**kwargs)
        self.failed = failed

    def post(self) -> None:
        ip = self.request.remote_ip or ""
        if self.failed.blocked(ip):
            return self.write_json({"error": "Too many attempts, wait a minute"}, 429)
        try:
            body = json.loads(self.request.body or b"{}")
        except ValueError:
            return self.write_json({"error": "Bad request"}, 400)
        name = clean_name(body.get("name"))
        if name is None:
            return self.write_json({"error": "Pick a nickname"}, 400)
        joined = self.auth.join(str(body.get("pin", "")), name)
        if joined is None:
            self.failed.add(ip)
            return self.write_json({"error": "Wrong PIN"}, 403)
        token, user = joined
        self.write_json(
            {"token": token, "user": {"id": user.id, "name": name, "admin": user.admin}}
        )


class InfoHandler(BaseHandler):
    def get(self) -> None:
        self.write_json(
            {
                "public_url": self.party_settings.public_url,
                "admin_enabled": bool(self.party_settings.admin_pin),
            }
        )


class LoginsHandler(BaseHandler):
    """Backend logins waiting for the host. Host only: whoever opens the link
    connects their account to the party."""

    def get(self) -> None:
        user = self.auth.verify(self.get_argument("token", ""))
        if user is None or not user.admin:
            return self.write_json({"error": "Host only"}, 403)
        tidal = tidal_auth.ACTIVE
        self.write_json({"tidal": tidal.status() if tidal else None})


class HealthHandler(BaseHandler):
    def get(self) -> None:
        ok = self.api.available()
        self.write_json({"ok": ok}, 200 if ok else 503)


class SocketHandler(tornado.websocket.WebSocketHandler):
    def initialize(
        self, auth: Auth, api: FrontendApi, settings: Settings, hub: Hub
    ) -> None:
        self.auth = auth
        self.api = api
        self.party_settings = settings
        self.hub = hub
        self.user: User | None = None

    async def open(self) -> None:
        self.user = self.auth.verify(self.get_argument("token", ""))
        if self.user is None:
            self.close(4001, "Please join again")
            return
        self.hub.attach(self)
        self.write_message(
            {
                "type": "hello",
                "user": {
                    "id": self.user.id,
                    "name": self.user.name,
                    "admin": self.user.admin,
                },
                # Hosts get the guest PIN so the big screen can display it.
                "pin": self.party_settings.pin if self.user.admin else None,
            }
        )
        if self.hub.latest is not None:
            self.send(self.hub.latest)
        else:
            try:
                self.write_message(await self.api.call("snapshot"))
            except Exception as e:
                self._error(e)

    def on_close(self) -> None:
        self.hub.detach(self)

    def send(self, message: str) -> None:
        self.write_message(message)

    async def on_message(self, message: str | bytes) -> None:
        if self.user is None:
            return
        try:
            data = json.loads(message)
            await self._dispatch(self.user, data)
        except Exception as e:
            self._error(e)

    async def _dispatch(self, user: User, data: dict[str, Any]) -> None:
        match data.get("type"):
            case "vote":
                await self.api.call("vote", user.id, user.name, str(data["uri"]))
            case "retract":
                await self.api.call("retract", user.id)
            case "suggest":
                track = await self.api.lookup(str(data["uri"]))
                if track is None:
                    raise VoteError("Could not find that song")
                await self.api.call("suggest", user.id, user.name, track)
            case "search":
                query = str(data.get("q", "")).strip()[:100]
                results = await self.api.search(query) if query else []
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
                await self.api.call("admin", str(data["action"]), data.get("value"))
            case "ping":
                self.write_message({"type": "pong"})
            case other:
                raise VoteError(f"Unknown message {other!r}")

    def _error(self, e: Exception) -> None:
        if isinstance(e, VoteError | Unavailable):
            message = str(e)
        else:
            logger.exception("Beat Ballot request failed")
            message = "Something went wrong"
        if self.ws_connection is not None:
            self.write_message({"type": "error", "message": message})


class AppHandler(tornado.web.StaticFileHandler):
    """Serves the built Svelte app. Hashed assets are cached forever."""

    def set_extra_headers(self, path: str) -> None:
        if path.startswith("assets/"):
            self.set_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.set_header("Cache-Control", "no-cache")


def make_app(config: Any, core: Any) -> list[tuple[Any, ...]]:
    from . import Extension  # noqa: PLC0415
    from .player import MopidyPlayer  # noqa: PLC0415

    settings = Settings.from_config(config["beatballot"])
    auth = Auth(
        load_secret(Extension.get_data_dir(config)), settings.pin, settings.admin_pin
    )

    def login_pending(source: str) -> bool:
        tidal = tidal_auth.ACTIVE
        return source == "tidal" and tidal is not None and tidal.pending

    api = FrontendApi(MopidyPlayer(core, settings.search_schemes, login_pending))
    return routes(auth, api, settings, HUB)


def routes(
    auth: Auth, api: FrontendApi, settings: Settings, hub: Hub
) -> list[tuple[Any, ...]]:
    ctx = {"auth": auth, "api": api, "settings": settings, "hub": hub}
    return [
        (r"/api/join", JoinHandler, {**ctx, "failed": FailedJoins()}),
        (r"/api/info", InfoHandler, ctx),
        (r"/api/health", HealthHandler, ctx),
        (r"/api/logins", LoginsHandler, ctx),
        (r"/ws", SocketHandler, ctx),
        (
            r"/(.*)",
            AppHandler,
            {"path": str(STATIC_DIR), "default_filename": "index.html"},
        ),
    ]
