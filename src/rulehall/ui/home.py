import logging
from functools import partial

from nicegui import ui
from nicegui.events import ValueChangeEventArguments

from rulehall.app.catalog import LauncherCatalog, SavedGameKey, SaveOption
from rulehall.app.runtime import Runtime
from rulehall.core.validation import Slug, content_id
from rulehall.ui import theme
from rulehall.ui.routes import CHARACTER, PACK, PACKS, SCENARIO, SETTINGS, game_path
from rulehall.ui.widgets import (
    Confirm,
    action_tile,
    attempt,
    empty_state,
    entry_card,
    heading,
    icon_button,
    nav_button,
    page_body,
    page_header,
    page_intro,
    section,
)

LOGGER = logging.getLogger(__name__)
PLAY_ICON = "sym_r_play_arrow"
DELETE_ICON = "sym_r_delete"
DELETE_FAILED = "Something went wrong. The save was not deleted. Look in the server log."
CREATE_TILES: tuple[tuple[str, str, str, str], ...] = (
    ("sym_r_person_add", "New character", "Someone to play, built to the rules", CHARACTER),
    ("sym_r_auto_stories", "New scenario", "An adventure the worldsmith opens", SCENARIO),
    ("sym_r_auto_fix_high", "New pack", "Tables and seeds for a genre", PACK),
)


class LaunchForm:
    def __init__(self, catalog: LauncherCatalog) -> None:
        self.catalog = catalog
        self.scenario_id: Slug = catalog.scenarios[0].id
        self.character_id: Slug | None = None
        self.draw()

    def choose_scenario(self, event: ValueChangeEventArguments[str]) -> None:
        self.scenario_id = content_id(event.value)
        self.draw.refresh()

    def choose_character(self, event: ValueChangeEventArguments[str]) -> None:
        self.character_id = content_id(event.value)
        self.draw_start_button.refresh()

    @ui.refreshable_method
    def draw(self) -> None:
        catalog = self.catalog
        scenario = catalog.require_scenario(self.scenario_id)
        theme.set_look(scenario.look)
        ui.select(
            options={
                entry.id: f"{entry.name} · {entry.engine_title}" for entry in catalog.scenarios
            },
            value=self.scenario_id,
            label="Scenario",
            on_change=self.choose_scenario,
        )
        ui.label(scenario.brief).classes("game-hint").style("font-size: .85rem; line-height: 1.5")
        characters = {
            entry.id: f"{entry.name} — {entry.brief}"
            for entry in catalog.characters_for(scenario.engine_id)
        }
        if self.character_id not in characters:
            self.character_id = next(iter(characters), None)
        ui.select(
            options=characters,
            value=self.character_id,
            label="Character",
            on_change=self.choose_character,
        )
        self.draw_start_button()

    @ui.refreshable_method
    def draw_start_button(self) -> None:
        catalog = self.catalog
        if self.character_id is None:
            ui.label("No character is written for these rules.").classes("text-negative")
            return
        key = catalog.key_for(self.scenario_id, self.character_id)
        if key.save_id in catalog.unresumable:
            ui.label(
                f"A save file exists at {key.save_id!r} and cannot be resumed. "
                "Nothing is deleted or migrated."
            ).classes("text-negative")
            return
        started = any(save.key.save_id == key.save_id for save in catalog.saves)
        ui.button(
            "Continue game" if started else "Start game",
            icon=PLAY_ICON,
            on_click=partial(_open_game, key),
        ).props("color=primary size=md").classes("q-mt-sm self-start")


def home_page(runtime: Runtime) -> None:
    catalog = runtime.catalog()
    with page_header("Rulehall", home=False):
        ui.space()
        nav_button("Packs", "sym_r_style", PACKS)
        nav_button("Settings", "sym_r_settings", SETTINGS)

    with page_body():
        page_intro(
            "Adventure",
            "Begin an adventure",
            "Choose a scenario, then a character written for its rules.",
        )
        with section("New or current game", classes="game-launch"):
            if catalog.scenarios:
                LaunchForm(catalog)
            else:
                ui.label("No playable scenario was found.").classes("text-negative")
        _saved_games(runtime, catalog)
        _new_content()


def _new_content() -> None:
    heading("Create")
    with ui.element("div").classes("game-tiles"):
        for icon, title, caption, route in CREATE_TILES:
            action_tile(icon, title, caption, partial(ui.navigate.to, route))


def _saved_games(runtime: Runtime, catalog: LauncherCatalog) -> None:
    heading("Saved games", len(catalog.saves))
    with ui.column().classes("w-full game-gap-xl"):
        for save_id in catalog.unresumable:
            entry_card(
                "sym_r_broken_image",
                save_id,
                "This save cannot be resumed. Nothing is deleted or migrated.",
                (),
                partial(_delete_button, runtime, save_id),
            )
        if not catalog.saves:
            empty_state("sym_r_bookmarks", "No saved games yet.")
        for saved in catalog.saves:
            _saved_card(runtime, saved)


def _saved_card(runtime: Runtime, saved: SaveOption) -> None:
    def actions() -> None:
        ui.button(
            "Resume",
            icon=PLAY_ICON,
            on_click=partial(_open_game, saved.key),
        ).props("color=primary")
        _delete_button(runtime, saved.key.save_id)

    where = f" · {saved.where}" if saved.where else ""
    entry_card(
        "sym_r_bookmark",
        saved.scenario_label,
        f"{saved.character_label} · turn {saved.turn}{where}",
        (saved.engine_title,),
        actions,
    )


def _delete_button(runtime: Runtime, save_id: str) -> None:
    icon_button(DELETE_ICON, "Delete", partial(_confirm_delete, runtime, save_id))


async def _confirm_delete(runtime: Runtime, save_id: str) -> None:
    dialog = Confirm(keep="Keep", confirm="Delete")
    confirmed = await dialog.ask(f"Delete the save {save_id!r}? It cannot be brought back.")
    dialog.delete()
    if confirmed and await attempt(partial(runtime.delete_save, save_id), failed=DELETE_FAILED):
        ui.navigate.reload()


def _open_game(key: SavedGameKey) -> None:
    LOGGER.info("launcher opening %r", key.save_id)
    ui.navigate.to(game_path(key))
