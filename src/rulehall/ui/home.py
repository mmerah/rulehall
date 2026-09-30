from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from nicegui import ui

from rulehall.app.catalog import LauncherCatalog, SaveOption
from rulehall.app.runtime import Runtime
from rulehall.app.version import app_version
from rulehall.core.validation import EngineId
from rulehall.core.views import Look
from rulehall.ui.hall import delete_button, open_game, save_line
from rulehall.ui.routes import SETTINGS, game_path, hall_path
from rulehall.ui.theme import look_style
from rulehall.ui.widgets import (
    BROKEN_ICON,
    PLAY_ICON,
    art,
    die_glyph,
    entry_card,
    link_box,
    nav_button,
    page_body,
    page_header,
    pattern_classes,
    section_title,
)

SETTINGS_ICON = "sym_r_settings"
OPEN_ICON = "sym_r_chevron_right"
RECENT_SAVES = 3
WELCOME = (
    "Solo tabletop role-playing. You play one character; "
    "AI roles and a rules engine play the rest of the table."
)


def home_page(runtime: Runtime) -> None:
    catalog = runtime.catalog()
    now = datetime.now(UTC)
    with page_header("Rulehall", back=None):
        ui.space()
        nav_button("Settings", SETTINGS_ICON, SETTINGS)
    with page_body(classes="game-wide"):
        if catalog.saves:
            _continue(runtime, catalog.saves[:RECENT_SAVES], now)
        else:
            _welcome()
        section_title("Choose your rules")
        with ui.element("div").classes("game-doors"):
            for engine in runtime.engines.values():
                _door(catalog, engine.id, engine.title, engine.look)
        if catalog.unresumable:
            _unresumable(runtime, catalog.unresumable)


def _welcome() -> None:
    with ui.column().classes("game-welcome game-gap-md"):
        ui.label("Rulehall").classes("game-title game-hero-title").props(
            'role="heading" aria-level="1"'
        )
        ui.label(app_version()).classes("game-version")
        ui.label(WELCOME).classes("game-lead")


def _continue(runtime: Runtime, saves: tuple[SaveOption, ...], now: datetime) -> None:
    newest, *older = saves
    with ui.element("div").classes("game-continue"):
        _hero(runtime, newest, now)
        if older:
            with ui.element("div").classes("game-recent"):
                for save in older:
                    _recent(runtime, save, now)


def _hero(runtime: Runtime, save: SaveOption, now: datetime) -> None:
    engine = runtime.require_engine(save.engine_id)
    look = engine.look
    with ui.element("div").classes("game-look game-hero").style(look_style(look)):
        _cover(look, save.cover)
        with ui.column().classes("game-hero-text game-gap-lg"):
            ui.label(engine.title).classes("game-eyebrow")
            ui.label(save.scenario_label).classes("game-title game-hero-title").props(
                'role="heading" aria-level="1"'
            )
            ui.label(save_line(save, now)).classes("game-hero-meta")
            ui.button("Continue", icon=PLAY_ICON, on_click=partial(open_game, save.key)).props(
                "color=primary size=lg"
            ).classes("game-hero-play")


def _recent(runtime: Runtime, save: SaveOption, now: datetime) -> None:
    look = runtime.require_engine(save.engine_id).look
    with link_box(game_path(save.key), "game-look game-save").style(look_style(look)):
        _cover(look, save.cover)
        with ui.column().classes("game-save-text game-gap-2xs"):
            ui.label(save.scenario_label).classes("game-title game-save-title")
            ui.label(save_line(save, now)).classes("game-save-meta")
        ui.icon(OPEN_ICON).classes("game-save-open")


def _door(catalog: LauncherCatalog, engine_id: EngineId, title: str, look: Look) -> None:
    adventures = len(catalog.scenarios_for(engine_id))
    playing = len(catalog.saves_for(engine_id))
    count = _counted(adventures, "adventure") + (f" · {playing} in play" if playing else "")
    door = link_box(hall_path(engine_id), f"game-look game-door {pattern_classes(look)}")
    with door.style(look_style(look)):
        with ui.row().classes("w-full items-start no-wrap game-gap-md"):
            ui.label(title).classes("game-title game-door-title col")
            die_glyph(look)
        ui.label(look.tagline).classes("game-door-tagline")
        ui.label(count).classes("game-door-count")


def _unresumable(runtime: Runtime, save_ids: tuple[str, ...]) -> None:
    section_title("Saves that cannot resume")
    with ui.column().classes("w-full game-gap-xl"):
        for save_id in save_ids:
            entry_card(
                BROKEN_ICON,
                save_id,
                "Its rules, scenario or character changed. Nothing is deleted or migrated.",
                partial(delete_button, runtime, save_id),
            )


def _cover(look: Look, cover: Path | None) -> None:
    art(look, cover)
    if cover is None:
        die_glyph(look)


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")
