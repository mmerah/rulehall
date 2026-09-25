import logging
from collections.abc import Callable
from functools import partial

from nicegui import app, ui
from nicegui.events import ValueChangeEventArguments

from rulehall.app.launch import LauncherCatalog, LaunchTarget, SaveOption
from rulehall.app.mcp import MOUNT_PATH, MountedLifespan, endpoint
from rulehall.app.runtime import Runtime
from rulehall.config import ENV_FILE, read_settings
from rulehall.core.validation import Refusal, Slug, content_id
from rulehall.ui import theme
from rulehall.ui.create import character_page, new_pack_page, scenario_page
from rulehall.ui.game import game_page
from rulehall.ui.packs import PACKS_ROUTE, packs_page
from rulehall.ui.settings import settings_page
from rulehall.ui.widgets import (
    GAME_ROUTE,
    HOME_ICON,
    SOUNDS_DIR,
    SOUNDS_ROUTE,
    Confirm,
    action_tile,
    alert,
    assets_route,
    empty_state,
    entry_card,
    game_path,
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
CREATE_TILES: tuple[tuple[str, str, str, str], ...] = (
    ("sym_r_person_add", "New character", "Someone to play, built to the rules", "/create"),
    ("sym_r_auto_stories", "New scenario", "An adventure the worldsmith opens", "/scenario"),
    ("sym_r_auto_fix_high", "New pack", "Tables and seeds for a genre", "/pack"),
)


class LaunchForm:
    def __init__(self, catalog: LauncherCatalog) -> None:
        self.catalog = catalog
        self.scenario_id: Slug = catalog.scenarios[0].id
        self.character_id: Slug | None = None

    def choose_scenario(self, event: ValueChangeEventArguments[str]) -> None:
        self.scenario_id = content_id(event.value)
        self.form.refresh()

    def choose_character(self, event: ValueChangeEventArguments[str]) -> None:
        self.character_id = content_id(event.value)
        self.start_button.refresh()

    @ui.refreshable_method
    def form(self) -> None:
        catalog = self.catalog
        scenario = catalog.scenario(self.scenario_id)
        theme.set_look(scenario.look)
        ui.select(
            options={entry.id: f"{entry.name} · {entry.rules}" for entry in catalog.scenarios},
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
        self.start_button()

    @ui.refreshable_method
    def start_button(self) -> None:
        catalog = self.catalog
        if self.character_id is None:
            ui.label("No character is written for these rules.").classes("text-negative")
            return
        target = catalog.target(self.scenario_id, self.character_id)
        if target.slug in catalog.unresumable:
            ui.label(
                f"A save file exists at {target.slug!r} and cannot be resumed. "
                "Nothing is deleted or migrated."
            ).classes("text-negative")
            return
        started = any(save.target.slug == target.slug for save in catalog.saves)
        ui.button(
            "Continue game" if started else "Start game",
            icon=PLAY_ICON,
            on_click=partial(_open_game, target),
        ).props("color=primary size=md").classes("q-mt-sm self-start")


def home_page(runtime: Runtime) -> None:
    catalog = runtime.catalog()
    with page_header("Rulehall", home=False):
        ui.space()
        nav_button("Packs", "sym_r_style", PACKS_ROUTE)
        nav_button("Settings", "sym_r_settings", "/settings")

    with page_body():
        page_intro(
            "Adventure",
            "Begin an adventure",
            "Choose a scenario, then a character written for its rules.",
        )
        with section("New or current game", classes="game-launch"):
            if catalog.scenarios:
                LaunchForm(catalog).form()
            else:
                ui.label("No playable scenario was found.").classes("text-negative")
        _saved_games(runtime, catalog)
        _new_content()


def mount(runtime: Runtime) -> None:
    plain_pages: tuple[tuple[str, Callable[[Runtime], None]], ...] = (
        ("/", home_page),
        ("/create", character_page),
        ("/scenario", scenario_page),
        ("/pack", new_pack_page),
        (PACKS_ROUTE, packs_page),
        ("/settings", settings_page),
    )
    asgi, manager = endpoint(runtime.gate)
    app.mount(MOUNT_PATH, asgi)
    app.get("/status")(runtime.gate.status)
    app.add_static_files(SOUNDS_ROUTE, SOUNDS_DIR)
    for engine in runtime.engines.values():
        if engine.assets is not None and engine.assets.is_dir():
            app.add_static_files(assets_route(engine.id), engine.assets)
    lifespan = MountedLifespan(manager)
    app.on_startup(lifespan.start)  # pyright: ignore[reportUnknownMemberType]
    app.on_shutdown(lifespan.stop)  # pyright: ignore[reportUnknownMemberType]
    app.on_shutdown(runtime.close)  # pyright: ignore[reportUnknownMemberType]
    for route, page in plain_pages:
        ui.page(route)(partial(page, runtime))
    ui.page(GAME_ROUTE)(partial(_game, runtime))


def start() -> None:
    # Without a handler the root logger drops every INFO record, spawns included.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = read_settings()
    except Refusal as broken:
        raise SystemExit(
            f"settings: {broken}. Fix the key in {ENV_FILE}, then start again."
        ) from None
    mount(Runtime(settings))
    theme.install()
    ui.run(  # pyright: ignore[reportUnknownMemberType]
        title="Rulehall",
        host=settings.server.host,
        port=settings.server.port,
        reload=False,
        show=False,
        viewport="width=device-width, initial-scale=1, interactive-widget=resizes-content",
    )


def _new_content() -> None:
    heading("Create")
    with ui.element("div").classes("game-tiles"):
        for icon, title, caption, route in CREATE_TILES:
            action_tile(icon, title, caption, partial(ui.navigate.to, route))


def _saved_games(runtime: Runtime, catalog: LauncherCatalog) -> None:
    heading("Saved games", len(catalog.saves))
    with ui.column().classes("w-full game-gap-xl"):
        for slug in catalog.unresumable:
            with entry_card(
                "sym_r_broken_image",
                slug,
                "This save cannot be resumed. Nothing is deleted or migrated.",
                (),
            ):
                _delete_button(runtime, slug)
        if not catalog.saves:
            empty_state("sym_r_bookmarks", "No saved games yet.")
        for saved in catalog.saves:
            _saved_card(runtime, saved)


def _saved_card(runtime: Runtime, saved: SaveOption) -> None:
    where = f" · {saved.where}" if saved.where else ""
    with entry_card(
        "sym_r_bookmark",
        saved.scenario_label,
        f"{saved.character_label} · turn {saved.turn}{where}",
        (saved.rules,),
    ):
        ui.button(
            "Resume",
            icon=PLAY_ICON,
            on_click=partial(_open_game, saved.target),
        ).props("color=primary")
        _delete_button(runtime, saved.target.slug)


def _delete_button(runtime: Runtime, slug: str) -> None:
    icon_button(DELETE_ICON, "Delete", partial(_confirm_delete, runtime, slug))


async def _confirm_delete(runtime: Runtime, slug: str) -> None:
    dialog = Confirm(keep="Keep", confirm="Delete")
    confirmed = await dialog.ask(f"Delete the save {slug!r}? It cannot be brought back.")
    dialog.delete()
    if not confirmed:
        return
    try:
        await runtime.delete_save(slug)
    except Refusal as refused:
        alert(str(refused))
        return
    ui.navigate.reload()


def _open_game(target: LaunchTarget) -> None:
    LOGGER.info("launcher opening %r", target.slug)
    ui.navigate.to(game_path(target))


def _refused_page(message: str) -> None:
    page_header("Rulehall")
    with (
        page_body(),
        ui.card().classes("w-full"),
        ui.column().classes("w-full items-center game-gap-2xl"),
    ):
        empty_state("sym_r_explore_off", message)
        ui.button("Home", icon=HOME_ICON, on_click=lambda: ui.navigate.to("/")).props(
            "color=primary"
        )


async def _game(runtime: Runtime, scenario: str, character: str) -> None:
    try:
        session = runtime.session(
            LaunchTarget(scenario_id=content_id(scenario), character_id=content_id(character))
        )
    except Refusal as refused:
        _refused_page(str(refused))
        return
    # Tab storage (the composer draft) is readable only after the handshake.
    await ui.context.client.connected()
    game_page(session)
