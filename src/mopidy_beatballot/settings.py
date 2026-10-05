from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .backends import normalize_playlist, split_list

MODES = ("standalone", "hub", "player")


@dataclass
class Settings:
    # standalone: one party, music plays on this machine (the original mode).
    # hub: many parties, music plays on paired remote players.
    # player: a remote player that plays what its hub sends.
    mode: str = "standalone"
    party_name: str = "Beat Ballot"
    hub_pin: str = ""  # Hub owner: create parties, pair players, Tidal login.
    hub_url: str = ""  # Player: e.g. https://www.klubhuset.party
    pair_code: str = ""  # Player: one-time code from the hub page.
    player_name: str = ""
    playlists: list[str] = field(default_factory=list)
    pin: str = "1234"
    admin_pin: str = ""
    candidates: int = 3
    lock_before_end: int = 20
    carry_over: bool = True
    carry_min_votes: int = 2
    max_suggestions_per_user: int = 1
    # Mopidy URI schemes searched for suggestions; empty searches every backend.
    search_schemes: list[str] = field(default_factory=list)
    public_url: str = ""
    # Reverse proxies (IPs or CIDRs) whose X-Forwarded-For is trusted.
    trusted_proxies: list[str] = field(default_factory=list)
    test_mode: bool = False
    test_play_seconds: int = 30
    test_lock_at: int = 15

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> Settings:
        fields = cls.__dataclass_fields__
        settings = cls(
            **{k: v for k, v in section.items() if k in fields and v is not None}
        )
        settings.playlists = [
            normalize_playlist(p) for p in split_list(settings.playlists)
        ]
        settings.search_schemes = split_list(settings.search_schemes)
        settings.trusted_proxies = split_list(settings.trusted_proxies)
        return settings

    def play_limit_ms(self) -> int | None:
        """How much of each song is played, or None for the whole song."""
        return self.test_play_seconds * 1000 if self.test_mode else None

    def lock_window_ms(self) -> int:
        """How long before the (possibly truncated) end of a song voting locks."""
        if self.test_mode:
            return max(0, self.test_play_seconds - self.test_lock_at) * 1000
        return self.lock_before_end * 1000
