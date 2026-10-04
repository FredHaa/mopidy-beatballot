import configparser

from mopidy_beatballot import Extension
from mopidy_beatballot.settings import Settings


def test_default_config_is_valid():
    ext = Extension()
    raw = ext.get_default_config()
    assert "[beatballot]" in raw
    parser = configparser.RawConfigParser()
    parser.read_string(raw)
    values, errors = ext.get_config_schema().deserialize(dict(parser["beatballot"]))
    # playlist and admin_pin are intentionally empty by default.
    assert not errors
    settings = Settings.from_config(values)
    assert settings.lock_before_end == 20
    assert settings.test_lock_at == 15


def test_schema_has_all_settings():
    schema = Extension().get_config_schema()
    for field in Settings.__dataclass_fields__:
        assert field in schema


def test_settings_lock_window():
    s = Settings()
    assert s.lock_window_ms() == 20_000
    assert s.play_limit_ms() is None
    s.test_mode = True
    assert s.lock_window_ms() == 15_000
    assert s.play_limit_ms() == 30_000
