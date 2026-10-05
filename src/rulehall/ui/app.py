import logging
from collections.abc import Callable
from functools import partial

from nicegui import app, ui

from rulehall.app.mcp import MOUNT_PATH, MountedLifespan, endpoint
from rulehall.app.runtime import Runtime
from rulehall.config import ENV_FILE, read_settings
from rulehall.core.validation import EngineId, Refusal
from rulehall.ui import theme
from rulehall.ui.create import CharacterForm, PackForm, ScenarioForm, packs_page
from rulehall.ui.game import game_page
from rulehall.ui.hall import hall_page
from rulehall.ui.home import home_page
from rulehall.ui.routes import (
    GAME,
    HALL,
    HOME,
    ICONS,
    NEW_CHARACTER,
    NEW_PACK,
    NEW_SCENARIO,
    PACKS,
    SETTINGS,
    SOUNDS,
    assets_route,
)
from rulehall.ui.settings import SettingsForm
from rulehall.ui.widgets import ICONS_DIR, SOUNDS_DIR, refused_page

type EnginePage = Callable[[Runtime, EngineId], object]


def mount(runtime: Runtime) -> None:
    plain_pages: tuple[tuple[str, Callable[[Runtime], object]], ...] = (
        (HOME, home_page),
        (SETTINGS, SettingsForm),
    )
    engine_pages: tuple[tuple[str, EnginePage], ...] = (
        (HALL, hall_page),
        (NEW_CHARACTER, CharacterForm),
        (NEW_SCENARIO, ScenarioForm),
        (NEW_PACK, PackForm),
        (PACKS, packs_page),
    )
    asgi, manager = endpoint(runtime.gate)
    app.mount(MOUNT_PATH, asgi)
    app.get("/status")(runtime.gate.status)
    app.add_static_files(SOUNDS, SOUNDS_DIR)
    app.add_static_files(ICONS, ICONS_DIR)
    for engine in runtime.engines.values():
        if engine.assets is not None and engine.assets.is_dir():
            app.add_static_files(assets_route(engine.id), engine.assets)
    lifespan = MountedLifespan(manager)
    app.on_startup(lifespan.start)  # pyright: ignore[reportUnknownMemberType]
    app.on_shutdown(lifespan.stop)  # pyright: ignore[reportUnknownMemberType]
    app.on_shutdown(runtime.close)  # pyright: ignore[reportUnknownMemberType]
    for route, page in plain_pages:
        ui.page(route)(partial(page, runtime))
    for route, page in engine_pages:
        ui.page(route)(partial(_engine_page, runtime, page))
    ui.page(GAME)(partial(game_page, runtime))


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
        favicon=ICONS_DIR / "favicon.svg",
        host=settings.server.host,
        port=settings.server.port,
        reload=False,
        show=False,
        viewport="width=device-width, initial-scale=1, interactive-widget=resizes-content",
    )


def _engine_page(runtime: Runtime, page: EnginePage, engine_id: str) -> None:
    try:
        found = runtime.require_engine(EngineId(engine_id))
    except Refusal as refused:
        refused_page(str(refused))
        return
    page(runtime, found.id)
