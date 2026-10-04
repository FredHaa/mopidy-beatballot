import concurrent.futures
import threading

from mopidy_beatballot.tidal_auth import TidalAuth


class Link:
    verification_uri_complete = "link.tidal.com/ABCDE"
    user_code = "ABCDE"
    expires_in = 300.0


class FakeSession:
    def __init__(self, valid_file=False, futures=None):
        self.valid_file = valid_file
        self.futures = futures or []
        self.saved = None

    def load_session_from_file(self, path):
        return self.valid_file

    def check_login(self):
        return self.valid_file

    def login_oauth(self):
        return Link(), self.futures.pop(0)

    def save_session_to_file(self, path):
        self.saved = path


def run(auth, until):
    changed = threading.Event()
    auth._on_change = lambda: changed.set() if until() else None
    auth.start()
    assert changed.wait(2)


def test_existing_session_is_used(tmp_path):
    auth = TidalAuth(tmp_path / "s.json", session_factory=lambda: FakeSession(True))
    assert auth.pending
    run(auth, lambda: auth.state == "logged_in")
    assert not auth.pending


def test_device_login_shows_link_then_saves_session(tmp_path):
    future = concurrent.futures.Future()
    session = FakeSession(futures=[future])
    path = tmp_path / "tidal" / "tidal-oauth.json"
    auth = TidalAuth(path, session_factory=lambda: session)
    run(auth, lambda: auth.state == "pending")
    status = auth.status()
    assert status["url"] == "https://link.tidal.com/ABCDE"
    assert status["code"] == "ABCDE"
    assert 290 <= status["expires_in"] <= 300

    done = threading.Event()
    auth._on_change = done.set
    future.set_result(True)
    assert done.wait(2)
    assert auth.state == "logged_in"
    assert session.saved == path
    assert path.parent.is_dir()


def test_expired_link_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr("mopidy_beatballot.tidal_auth.RETRY_DELAY_S", 0.01)
    expired = concurrent.futures.Future()
    expired.set_exception(TimeoutError())
    fresh = concurrent.futures.Future()
    sessions = iter(
        [FakeSession(), FakeSession(futures=[expired]), FakeSession(futures=[fresh])]
    )
    auth = TidalAuth(tmp_path / "s.json", session_factory=lambda: next(sessions))
    seen = []
    done = threading.Event()

    def changed():
        seen.append(auth.state)
        if len(seen) == 2:
            done.set()

    auth._on_change = changed
    auth.start()
    assert done.wait(2)
    assert seen == ["pending", "pending"]
    auth.stop()
