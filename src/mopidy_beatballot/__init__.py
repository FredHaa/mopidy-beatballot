from __future__ import annotations

import pathlib
from importlib.metadata import PackageNotFoundError, version
from typing import override

from mopidy import config, ext

try:
    __version__ = version("mopidy-beatballot")
except PackageNotFoundError:
    __version__ = "0.0.0+local"


class Extension(ext.Extension):
    dist_name = "mopidy-beatballot"
    ext_name = "beatballot"
    version = __version__

    @override
    def get_default_config(self) -> str:
        return config.read(pathlib.Path(__file__).parent / "ext.conf")

    @override
    def get_config_schema(self) -> config.ConfigSchema:
        schema = super().get_config_schema()
        schema["mode"] = config.String(choices=("standalone", "hub", "player"))
        schema["party_name"] = config.String(optional=True)
        schema["hub_pin"] = config.Secret(optional=True)
        schema["hub_url"] = config.String(optional=True)
        schema["pair_code"] = config.Secret(optional=True)
        schema["player_name"] = config.String(optional=True)
        schema["playlists"] = config.List(optional=True)
        schema["pin"] = config.Secret(optional=True)
        schema["admin_pin"] = config.Secret(optional=True)
        schema["candidates"] = config.Integer(minimum=1, maximum=10)
        schema["lock_before_end"] = config.Integer(minimum=1)
        schema["carry_over"] = config.Boolean()
        schema["carry_min_votes"] = config.Integer(minimum=1)
        schema["max_suggestions_per_user"] = config.Integer(minimum=0)
        schema["search_schemes"] = config.List(optional=True)
        schema["public_url"] = config.String(optional=True)
        schema["trusted_proxies"] = config.List(optional=True)
        schema["test_mode"] = config.Boolean()
        schema["test_play_seconds"] = config.Integer(minimum=5)
        schema["test_lock_at"] = config.Integer(minimum=1)
        return schema

    @override
    def setup(self, registry: ext.Registry) -> None:
        from .frontend import BallotFrontend  # noqa: PLC0415
        from .web import make_app  # noqa: PLC0415

        registry.add("frontend", BallotFrontend)
        registry.add("http:app", {"name": self.ext_name, "factory": make_app})
