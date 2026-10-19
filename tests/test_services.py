import io
import urllib.error

import pytest

from mopidy_beatballot import services
from mopidy_beatballot.services import ServiceError, SoundCloudAccount


def respond(body):
    def fetch(request):
        assert request.get_header("Authorization") == "OAuth tok"
        return io.BytesIO(body)

    return fetch


def fail(error):
    def fetch(request):
        raise error

    return fetch


def test_soundcloud_username():
    fetch = respond(b'{"username": "dj-ann", "permalink": "ann"}')
    assert services.soundcloud_username("tok", fetch) == "dj-ann"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("u", 401, "no", {}, None), "didn't accept"),
        (urllib.error.HTTPError("u", 500, "oops", {}, None), "HTTP 500"),
        (urllib.error.URLError("offline"), "Couldn't reach"),
    ],
)
def test_soundcloud_username_errors(error, message):
    with pytest.raises(ServiceError, match=message):
        services.soundcloud_username("tok", fail(error))


def test_saving_a_token(tmp_path):
    account = SoundCloudAccount(tmp_path, None, enabled=False)
    assert account.status()["connected"] is False
    assert account.save("tok", "dj-ann")  # Not running yet: restart.
    status = account.status()
    assert (status["connected"], status["source"], status["account"]) == (
        True,
        "web",
        "dj-ann",
    )
    # After the restart, the entrypoint passes the saved token as config.
    account = SoundCloudAccount(tmp_path, "tok", enabled=True)
    assert account.source == "web"
    assert not account.save("tok", "dj-ann")  # Same token, already running.
    assert account.save("new", "dj-ann")
    assert account.disconnect()
    assert account.source is None
    assert not (tmp_path / services.SOUNDCLOUD_TOKEN_FILE).exists()


def test_config_token(tmp_path):
    account = SoundCloudAccount(tmp_path, "cfg", enabled=True)
    assert account.source == "config"
    with pytest.raises(ServiceError):
        account.disconnect()
    # A token saved in the web app replaces it.
    account.save("tok", "dj-ann")
    assert account.source == "web"
    account.disconnect()
    assert account.source == "config"
