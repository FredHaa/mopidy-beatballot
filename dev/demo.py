"""Run the Beat Ballot web app against a simulated player — no Mopidy or Spotify.

    uv run python dev/demo.py [--port 6680] [--real-time]

Then open http://localhost:6680/beatballot/ (PIN 1234, host PIN 9999).
Test mode is on by default so rounds take 30 seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time

import tornado.web
from tornado.ioloop import PeriodicCallback

from mopidy_beatballot import rooms
from mopidy_beatballot.hub import HUB
from mopidy_beatballot.parties import Parties
from mopidy_beatballot.rooms import Room, RoomStore, slugify
from mopidy_beatballot.settings import Settings
from mopidy_beatballot.tracks import TrackInfo
from mopidy_beatballot.web import Auth, Context, routes

SONGS = [
    ("Dancing Queen", "ABBA", 231),
    ("September", "Earth, Wind & Fire", 215),
    ("Mr. Brightside", "The Killers", 222),
    ("Uptown Funk", "Mark Ronson, Bruno Mars", 270),
    ("Hey Ya!", "Outkast", 235),
    ("Don't Stop Me Now", "Queen", 209),
    ("Get Lucky", "Daft Punk, Pharrell Williams", 248),
    ("Levitating", "Dua Lipa", 203),
    ("Shut Up and Dance", "WALK THE MOON", 199),
    ("I Wanna Dance with Somebody", "Whitney Houston", 291),
    ("Toxic", "Britney Spears", 199),
    ("Blinding Lights", "The Weeknd", 200),
    ("Crazy in Love", "Beyoncé, JAY-Z", 236),
    ("Wake Me Up Before You Go-Go", "Wham!", 231),
    ("Seven Nation Army", "The White Stripes", 232),
    ("Valerie", "Amy Winehouse, Mark Ronson", 219),
    ("Take On Me", "a-ha", 225),
    ("Murder On The Dancefloor", "Sophie Ellis-Bextor", 230),
]
COLORS = ["ff3d9a", "ff8a3d", "7c5cff", "3ddc97", "ffcc3d", "3dbdff"]


def library() -> list[TrackInfo]:
    return [
        TrackInfo(
            uri=f"{('spotify', 'tidal', 'soundcloud')[i % 3]}:track:{i}",
            name=name,
            artists=(artist,),
            album="Party Classics",
            length_ms=secs * 1000,
            image=f"https://placehold.co/300/{COLORS[i % 6]}/0d0a14?text={name[:1]}",
        )
        for i, (name, artist, secs) in enumerate(SONGS)
    ]


class SimPlayer:
    """Plays a consume-mode tracklist in (optionally accelerated) real time."""

    def __init__(self, tracks: list[TrackInfo], speed: float) -> None:
        self.tracks = {t.uri: t for t in tracks}
        self.speed = speed
        self.queue_: list[tuple[int, TrackInfo]] = []
        self.playing: tuple[int, TrackInfo] | None = None
        self._tlid = 0
        self._state = "stopped"
        self._offset = 0.0
        self._started = 0.0

    def _pos(self) -> int:
        if self._state != "playing":
            return int(self._offset)
        return int(
            self._offset + (time.monotonic() - self._started) * 1000 * self.speed
        )

    def state(self) -> str:
        self._auto_advance()
        return self._state

    def position_ms(self) -> int:
        return self._pos()

    def current(self):
        self._auto_advance()
        return self.playing

    def tracklist_length(self) -> int:
        return len(self.queue_)

    def queue(self):
        return list(self.queue_)

    def remove(self, tlid: int) -> None:
        self.queue_ = [t for t in self.queue_ if t[0] != tlid]

    def enqueue(self, uri: str, track=None) -> None:
        self._tlid += 1
        self.queue_.append((self._tlid, self.tracks[uri]))

    def play(self) -> None:
        if self._state == "paused":
            return self.resume()
        if self.playing is None:
            self._advance()

    def next(self) -> None:
        self._advance()

    def pause(self) -> None:
        self._offset = self._pos()
        self._state = "paused"

    def resume(self) -> None:
        self._started = time.monotonic()
        self._state = "playing"

    def load_playlist(self, uri: str) -> list[TrackInfo]:
        return list(self.tracks.values())

    def images(self, uris):
        return {u: self.tracks[u].image for u in uris if u in self.tracks}

    def search(self, q: str) -> list[TrackInfo]:
        q = q.lower()
        return [
            t
            for t in self.tracks.values()
            if q in t.name.lower() or q in " ".join(t.artists).lower()
        ]

    def lookup(self, uri: str) -> TrackInfo | None:
        return self.tracks.get(uri)

    def _auto_advance(self) -> None:
        if self.playing and self._pos() >= (self.playing[1].length_ms or 0):
            self._advance()

    def _advance(self) -> None:
        if self.playing in self.queue_:
            self.queue_.remove(self.playing)
        self.playing = self.queue_[0] if self.queue_ else None
        self._state = "playing" if self.playing else "stopped"
        self._offset = 0.0
        self._started = time.monotonic()


class DemoFrontend:
    """The party/hub API of BallotFrontend, minus Mopidy."""

    def __init__(self, parties: Parties) -> None:
        self.parties = parties

    def snapshot(self, room_id):
        return {
            **self.parties.party(room_id).snapshot(),
            "room": self.parties.store.get(room_id).public(),
        }

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


class DemoApi:
    """Same interface as web.FrontendApi, calling DemoFrontend directly."""

    def __init__(self, front: DemoFrontend, library: SimPlayer) -> None:
        self.front = front
        self.library = library

    async def call(self, method: str, *args):
        return getattr(self.front, method)(*args)

    def tell(self, method: str, *args) -> None:
        getattr(self.front, method)(*args)

    async def search(self, q: str):
        return self.library.search(q)

    async def lookup(self, uri: str):
        return self.library.lookup(uri)

    def available(self) -> bool:
        return True


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=6680)
    parser.add_argument("--real-time", action="store_true", help="disable test mode")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--bots", type=int, default=4, help="simulated voters")
    parser.add_argument(
        "--hub", action="store_true", help="hub mode: two parties, hub PIN 0000"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    settings = Settings(
        mode="hub" if args.hub else "standalone",
        hub_pin="0000" if args.hub else "",
        test_mode=not args.real_time,
    )
    store = RoomStore()
    names = ["Klubhuset", "Garden Party"] if args.hub else ["Beat Ballot"]
    for i, name in enumerate(names):
        store.add(
            Room(
                id=f"room{i}",
                slug="party" if not args.hub else slugify(name),
                name=name,
                pin="1234" if i == 0 else "4321",
                admin_pin="9999" if i == 0 else "8888",
                playlists=["demo:playlist"],
                test_mode=not args.real_time,
            )
        )
    rooms.STORE = store
    tracks = library()
    players: dict[str, SimPlayer] = {}

    def make_player(room: Room) -> SimPlayer:
        players[room.id] = SimPlayer(tracks, args.speed)
        return players[room.id]

    parties = Parties(settings, store, make_player, HUB.broadcast, forget=HUB.forget)
    parties.start()
    api = DemoApi(DemoFrontend(parties), SimPlayer(tracks, args.speed))

    rng = random.Random()
    bots = [
        (f"bot{i}", name)
        for i, name in enumerate(
            ["Maja", "Oskar", "Freja", "Lars", "Ida", "Emil"][: args.bots]
        )
    ]

    def bot_vote() -> None:
        for party in parties.parties.values():
            candidates = list(party.election.candidates)
            if candidates and rng.random() < 0.5:
                uid, name = rng.choice(bots)
                party.vote(uid, name, rng.choice(candidates))

    PeriodicCallback(parties.tick, 250).start()
    if bots:
        PeriodicCallback(bot_vote, 2500).start()

    ctx = Context(Auth(b"demo" * 8), api, settings, HUB)
    app = tornado.web.Application(
        [
            (r"/", tornado.web.RedirectHandler, {"url": "/beatballot/"}),
            (r"/beatballot", tornado.web.RedirectHandler, {"url": "/beatballot/"}),
            *[(f"/beatballot{rule[0]}", *rule[1:]) for rule in routes(ctx)],
        ]
    )
    app.listen(args.port)
    print(f"Beat Ballot: http://localhost:{args.port}/beatballot/ PIN 1234, host 9999")
    if args.hub:
        print("  hub page: #/hub with hub PIN 0000; 2nd party PIN 4321, host 8888")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
