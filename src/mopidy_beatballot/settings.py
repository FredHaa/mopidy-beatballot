from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .backends import normalize_playlist, split_list


@dataclass
class Settings:
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
        return settings

    def play_limit_ms(self) -> int | None:
        """How much of each song is played, or None for the whole song."""
        return self.test_play_seconds * 1000 if self.test_mode else None

    def lock_window_ms(self) -> int:
        """How long before the (possibly truncated) end of a song voting locks."""
        if self.test_mode:
            return max(0, self.test_play_seconds - self.test_lock_at) * 1000
        return self.lock_before_end * 1000
