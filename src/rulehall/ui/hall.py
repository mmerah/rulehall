import logging
from datetime import UTC, datetime
from functools import partial

from nicegui import ui

from rulehall.app.catalog import CatalogEntry, SavedGameKey, SaveOption
from rulehall.app.runtime import Runtime
from rulehall.core.validation import EngineId, Slug
from rulehall.ui.routes import (
    CHOSEN_CHARACTER,
    NEW_CHARACTER,
    NEW_PACK,
    NEW_SCENARIO,
    PACKS,
    engine_path,
    game_path,
)
from rulehall.ui.widgets import (
    BROKEN_ICON,
    NEW_ADVENTURE_ICON,
    NEW_CHARACTER_ICON,
    NEW_PACK_ICON,
    PACK_ICON,
    PLAY_ICON,
    Confirm,
    art,
    attempt,
    die_glyph,
    failure_notice,
    icon_button,
    link_box,
    media_url,
    page_body,
    page_header,
    pattern_classes,
    section_title,
)

LOGGER = logging.getLogger(__name__)
DELETE_ICON = "sym_r_delete"
DELETE_FAILED = failure_notice("The save was not deleted.")
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
WEEK = 7 * DAY


class Hall:
    def __init__(self, runtime: Runtime, engine_id: EngineId, chosen_id: str | None) -> None:
        self.runtime = runtime
        self.engine = runtime.require_engine(engine_id)
        self.catalog = runtime.catalog()
        self.characters = self.catalog.characters_for(engine_id)
        written = [character.id for character in self.characters]
        self.character_id: Slug | None = (
            chosen_id if chosen_id in written else next(iter(written), None)
        )
        self.now = datetime.now(UTC)

    def build(self) -> None:
        engine = self.engine
        page_header(engine.title, look=engine.look)
        with page_body(classes="game-wide"):
            with ui.element("div").classes(f"game-band {pattern_classes(engine.look)}"):
                with ui.column().classes("game-gap-md"):
                    ui.label(engine.title).classes("game-title game-hero-title").props(
                        'role="heading" aria-level="1"'
                    )
                    ui.label(engine.look.tagline).classes("game-lead")
                die_glyph(engine.look)
            self.draw()
            with ui.row().classes("game-hall-foot items-center game-gap-md"):
                packs = len(self.catalog.packs_for(engine.id))
                _small_link(f"Packs · {packs}", PACK_ICON, engine_path(PACKS, engine.id))
                _small_link("New pack", NEW_PACK_ICON, engine_path(NEW_PACK, engine.id))

    def choose(self, character_id: Slug) -> None:
        self.character_id = character_id
        self.draw.refresh()

    @ui.refreshable_method
    def draw(self) -> None:
        if self.character_id is None:
            self.draw_first_character()
            return
        section_title("Play as")
        with ui.element("div").classes("game-chips"):
            for character in self.characters:
                self.draw_chip(character)
            with (
                ui.button(on_click=self.new_character)
                .props('flat aria-label="New character"')
                .classes("game-chip game-chip-new")
            ):
                ui.icon(NEW_CHARACTER_ICON).classes("game-chip-face")
                ui.label("New")
        section_title("Adventures")
        with ui.element("div").classes("game-adventures"):
            for scenario in self.catalog.scenarios_for(self.engine.id):
                self.draw_adventure(scenario, self.character_id)
            new_adventure = engine_path(NEW_SCENARIO, self.engine.id)
            with link_box(new_adventure, "game-adventure game-adventure-new"):
                ui.icon(NEW_ADVENTURE_ICON).classes("game-adventure-new-icon")
                ui.label("Write an adventure").classes("game-title game-adventure-title")
                ui.label("Describe it, or upload one, and the worldsmith writes the opening.")

    def draw_chip(self, character: CatalogEntry) -> None:
        chosen = character.id == self.character_id
        with (
            ui.button(on_click=partial(self.choose, character.id))
            .props(f'flat aria-pressed="{str(chosen).lower()}"')
            .classes("game-chip game-chip-on" if chosen else "game-chip")
            .tooltip(character.brief)
        ):
            if character.portrait is None:
                ui.label(character.name[:1]).classes("game-chip-face game-chip-initial")
            else:
                portrait = ui.element("img").classes("game-chip-face").props('alt=""')
                portrait.props["src"] = media_url(character.portrait)
            ui.label(character.name)

    def draw_adventure(self, scenario: CatalogEntry, character_id: Slug) -> None:
        key = SavedGameKey(scenario_id=scenario.id, character_id=character_id)
        save = self.catalog.find_save(key)
        with ui.element("div").classes("game-adventure"):
            with ui.element("div").classes("game-adventure-head"):
                art(self.engine.look, None if save is None else save.cover)
                ui.label(scenario.name).classes("game-title game-adventure-title")
            with ui.column().classes("game-adventure-body game-gap-md"):
                ui.label(scenario.brief).classes("game-adventure-premise")
                with ui.row().classes("game-adventure-foot items-center no-wrap game-gap-md"):
                    if key.save_id in self.catalog.unresumable:
                        ui.icon(BROKEN_ICON).classes("game-adventure-broken")
                        ui.label("This save cannot be resumed.").classes("game-hint col")
                        delete_button(self.runtime, key.save_id)
                        return
                    if save is None:
                        ui.space()
                        label = "Start"
                    else:
                        ui.label(ago(save.saved_at, self.now)).classes("game-hint col text-no-wrap")
                        delete_button(self.runtime, key.save_id)
                        label = f"Continue · turn {save.turn}"
                    ui.button(label, icon=PLAY_ICON, on_click=partial(open_game, key)).props(
                        "color=primary"
                    )

    def draw_first_character(self) -> None:
        with ui.column().classes("game-first game-gap-lg"):
            section_title("Make a character first")
            ui.label("An adventure here is played by someone written to these rules.").classes(
                "game-lead"
            )
            ui.button(
                "New character",
                icon=NEW_CHARACTER_ICON,
                on_click=self.new_character,
            ).props("color=primary")

    def new_character(self) -> None:
        ui.navigate.to(engine_path(NEW_CHARACTER, self.engine.id))


def save_line(save: SaveOption, now: datetime) -> str:
    return f"{save.character_label} · turn {save.turn} · {ago(save.saved_at, now)}"


def ago(moment: datetime, now: datetime) -> str:
    seconds = (now - moment).total_seconds()
    if seconds < MINUTE:
        return "just now"
    if seconds < HOUR:
        return f"{int(seconds // MINUTE)} min ago"
    if seconds < DAY:
        return f"{int(seconds // HOUR)}h ago"
    if seconds < 2 * DAY:
        return "yesterday"
    if seconds < WEEK:
        return f"{int(seconds // DAY)} days ago"
    local = moment.astimezone()
    return f"{local.day} {local:%b}"


def open_game(key: SavedGameKey) -> None:
    LOGGER.info("opening %r", key.save_id)
    ui.navigate.to(game_path(key))


def delete_button(runtime: Runtime, save_id: str) -> None:
    icon_button(DELETE_ICON, "Delete", partial(_confirm_delete, runtime, save_id))


def hall_page(runtime: Runtime, engine_id: EngineId) -> None:
    chosen_id = ui.context.client.request.query_params.get(CHOSEN_CHARACTER)
    Hall(runtime, engine_id, chosen_id).build()


def _small_link(label: str, icon: str, path: str) -> None:
    with link_box(path, "game-small-link"):
        ui.icon(icon)
        ui.label(label)


async def _confirm_delete(runtime: Runtime, save_id: str) -> None:
    dialog = Confirm(keep="Keep", confirm="Delete")
    confirmed = await dialog.ask(f"Delete the save {save_id!r}? It cannot be brought back.")
    dialog.delete()
    if confirmed and await attempt(partial(runtime.delete_save, save_id), failed=DELETE_FAILED):
        ui.navigate.reload()
