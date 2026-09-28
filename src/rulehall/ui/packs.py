from nicegui import ui

from rulehall.app.runtime import Runtime
from rulehall.core.validation import EngineId
from rulehall.ui.create import NEW_PACK_ICON
from rulehall.ui.routes import NEW_PACK, engine_path, hall_path
from rulehall.ui.widgets import action_bar, entry_card, page_body, page_header, page_intro

PACK_ICON = "sym_r_style"


def packs_page(runtime: Runtime, engine_id: EngineId) -> None:
    engine = runtime.require_engine(engine_id)
    page_header("Packs", look=engine.look, back=hall_path(engine.id))
    with page_body():
        page_intro(engine.title, "Packs", "The tables these rules roll on.")
        with ui.column().classes("w-full game-gap-xl"):
            for pack in runtime.catalog().packs_for(engine.id):
                sub = f"Edit it in {runtime.packs.path(engine.id, pack.id)}" if pack.written else ""
                entry_card(PACK_ICON, pack.name, sub)
        with action_bar():
            ui.button(
                "New pack",
                icon=NEW_PACK_ICON,
                on_click=lambda: ui.navigate.to(engine_path(NEW_PACK, engine.id)),
            ).props("color=primary")
