from pathlib import Path

from nicegui import ui

from rulehall.core.views import Look
from rulehall.ui.widgets import media_url


def link_box(path: str, classes: str) -> ui.element:
    link = ui.element("a").classes(classes)
    link.props["href"] = path
    return link


def pattern_classes(look: Look) -> str:
    return f"game-pattern game-pattern-{look.pattern}"


def die_glyph(look: Look) -> None:
    with ui.column().classes("game-die game-glyph game-gap-0").props('aria-hidden="true"'):
        ui.label(f"d{look.die_faces}").classes("game-die-face")
        with ui.element("div").classes("game-die-window"):
            ui.label(str(look.die_faces)).classes("game-die-value")


def art(look: Look, cover: Path | None) -> None:
    with ui.element("div").classes(f"game-art {pattern_classes(look)}"):
        if cover is not None:
            image = ui.element("img").classes("game-art-image").props('alt="" loading="lazy"')
            image.props["src"] = media_url(cover)
