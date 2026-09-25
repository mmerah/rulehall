from nicegui import ui

from rulehall.app.runtime import Runtime
from rulehall.ui.widgets import empty_state, entry_card, page_body, page_header, page_intro

PACKS_ROUTE = "/packs"


def packs_page(runtime: Runtime) -> None:
    packs = runtime.catalog().packs
    page_header("Packs")
    with page_body():
        page_intro("Packs", "Packs", "The tables each set of rules rolls on.")
        with ui.column().classes("w-full game-gap-xl"):
            if not packs:
                empty_state("sym_r_style", "No pack is installed.")
            for pack in packs:
                sub = (
                    f"Edit it in {runtime.packs.path(pack.engine_id, pack.id)}"
                    if pack.written
                    else ""
                )
                with entry_card("sym_r_style", pack.name, sub, (pack.rules,)):
                    pass
