from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from nicegui import ui

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.validation import Slug
from rulehall.core.views import ScreenSlot
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
    screen_factories: ScreenFactories, host: ScreenHost, screen_slots: Sequence[ScreenSlot]
) -> dict[Slug, Screen]:
    if missing := sorted(
        slot.screen_id for slot in screen_slots if slot.screen_id not in screen_factories
    ):
        raise ValueError(f"screen slots with no registered screen: {missing}")
    return {slot.screen_id: screen_factories[slot.screen_id](host) for slot in screen_slots}


def check_screen_slots(screens: Mapping[Slug, Screen], screen_slots: Sequence[ScreenSlot]) -> None:
    if (listed := sorted(slot.screen_id for slot in screen_slots)) != sorted(screens):
        raise ValueError(
            f"the engine lists the screen slots {listed}, not the {sorted(screens)} the page built"
        )


def screen_banner(screen: Screen, label: str, body: str) -> tuple[ui.column, ui.label]:
    with (
        ui.column().classes("game-card game-decision game-banner w-full game-gap-lg") as banner,
        ui.row().classes("w-full items-center no-wrap game-banner-head game-gap-xl"),
    ):
        ui.icon(screen.opener_icon).classes("game-card-icon")
        with ui.column().classes("game-banner-text game-gap-3xs"):
            ui.label(label).classes("game-banner-label")
            body_label = ui.label(body).classes("game-banner-body")
        with ui.row().classes("items-center no-wrap game-banner-actions game-gap-md"):
            ui.button(screen.opener_label, on_click=screen.show).props("outline")
    return banner, body_label
