from mopidy_beatballot.tracks import TrackInfo


def track(uri: str, length_ms: int | None = 200_000) -> TrackInfo:
    return TrackInfo(
        uri=uri, name=uri.upper(), artists=("Artist",), length_ms=length_ms
    )


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakePlayer:
    """A minimal Mopidy stand-in: a consume-mode tracklist and a play head."""

    def __init__(self, playlist: list[TrackInfo]) -> None:
        self.playlist = playlist
        self.library = {t.uri: t for t in playlist}
        self.tracklist: list[tuple[int, TrackInfo]] = []
        self._next_tlid = 1
        self.playing: tuple[int, TrackInfo] | None = None
        self._state = "stopped"
        self.position = 0
        self.unplayable: set[str] = set()
        self.play_calls = 0

    # Player protocol

    def state(self) -> str:
        return self._state

    def position_ms(self) -> int:
        return self.position

    def current(self):
        return self.playing

    def tracklist_length(self) -> int:
        return len(self.tracklist)

    def queue(self):
        return list(self.tracklist)

    def enqueue(self, uri: str) -> None:
        self.tracklist.append((self._next_tlid, self.library[uri]))
        self._next_tlid += 1

    def remove(self, tlid: int) -> None:
        self.tracklist = [t for t in self.tracklist if t[0] != tlid]
        if self.playing is not None and self.playing[0] == tlid:
            self.playing = None
            self._state = "stopped"

    def play(self) -> None:
        self.play_calls += 1
        if self._state == "paused":
            self._state = "playing"
            return
        if self.playing not in self.tracklist:
            self.playing = self.tracklist[0] if self.tracklist else None
        self._start()

    def next(self) -> None:
        self._advance()

    def pause(self) -> None:
        self._state = "paused"

    def resume(self) -> None:
        self._state = "playing"

    def load_playlist(self, uri: str) -> list[TrackInfo]:
        return list(self.playlist)

    def images(self, uris):
        return {u: f"https://img/{u}" for u in uris}

    # Test helpers

    def _advance(self) -> None:
        if self.playing in self.tracklist:
            self.tracklist.remove(self.playing)  # consume
        self.playing = self.tracklist[0] if self.tracklist else None
        self._start()

    def _start(self) -> None:
        # Like Mopidy after a GStreamer error: playback stops, the current
        # track is cleared, but the failed track stays in the tracklist.
        ok = self.playing is not None and self.playing[1].uri not in self.unplayable
        if not ok:
            self.playing = None
        self._state = "playing" if ok else "stopped"
        self.position = 0

    def finish(self) -> None:
        """The current song reaches its natural end."""
        self._advance()
