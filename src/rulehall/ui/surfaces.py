from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.validation import Slug
from rulehall.core.views import Surface
from rulehall.ui.widgets import Sounds

type ScreenFactory = Callable[[ScreenHost], Screen]
type ScreenFactories = Mapping[Slug, ScreenFactory]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreenHost:
    session: GameSession
    sounds: Sounds
    on_toggle: Callable[[], None]


class Screen(Protocol):
    opener_label: str
    opener_icon: str

    @property
    def shown(self) -> bool: ...
    def build_banner(self) -> None: ...
    def build(self, now: SessionSnapshot) -> None: ...
    def show(self) -> None: ...
    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None: ...


def require_screens(
    screen_factories: ScreenFactories, host: ScreenHost, surfaces: Sequence[Surface]
) -> dict[Slug, Screen]:
    if missing := sorted(
        surface.surface_id for surface in surfaces if surface.surface_id not in screen_factories
    ):
        raise ValueError(f"surfaces with no registered screen: {missing}")
    return {surface.surface_id: screen_factories[surface.surface_id](host) for surface in surfaces}


def check_surfaces(screens: Mapping[Slug, Screen], surfaces: Sequence[Surface]) -> None:
    if (listed := sorted(surface.surface_id for surface in surfaces)) != sorted(screens):
        raise ValueError(
            f"the engine lists the surfaces {listed}, not the {sorted(screens)} the page built"
        )
