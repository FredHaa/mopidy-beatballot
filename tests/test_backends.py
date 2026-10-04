import pytest

from mopidy_beatballot.backends import normalize_playlist, source_of, split_list


@pytest.mark.parametrize(
    ("link", "uri"),
    [
        (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=1a2b",
            "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        ),
        (
            "https://open.spotify.com/intl-da/playlist/abc123",
            "spotify:playlist:abc123",
        ),
        (
            "https://tidal.com/browse/playlist/0B1C2D3E-4f5a-6b7c-8d9e-0f1a2b3c4d5e",
            "tidal:playlist:0b1c2d3e-4f5a-6b7c-8d9e-0f1a2b3c4d5e",
        ),
        (
            "https://listen.tidal.com/playlist/0b1c2d3e-4f5a-6b7c-8d9e-0f1a2b3c4d5e",
            "tidal:playlist:0b1c2d3e-4f5a-6b7c-8d9e-0f1a2b3c4d5e",
        ),
        (
            "https://soundcloud.com/some-dj/sets/summer-party/?si=x",
            "sc:https://soundcloud.com/some-dj/sets/summer-party",
        ),
        ("https://m.soundcloud.com/dj/sets/x", "sc:https://soundcloud.com/dj/sets/x"),
        ("  spotify:playlist:abc  ", "spotify:playlist:abc"),
        ("spotify:playlist:abc?si=068c99e4", "spotify:playlist:abc"),
        ("m3u:party.m3u", "m3u:party.m3u"),
    ],
)
def test_normalize_playlist(link, uri):
    assert normalize_playlist(link) == uri


def test_source_of():
    assert source_of("spotify:track:1") == "spotify"
    assert source_of("tidal:track:1") == "tidal"
    assert source_of("soundcloud:song/x.1") == "soundcloud"
    assert source_of("sc:https://soundcloud.com/x") == "soundcloud"


def test_split_list():
    assert split_list("a, b\nc,,") == ["a", "b", "c"]
    assert split_list(("a", " ")) == ["a"]
    assert split_list(None) == []
