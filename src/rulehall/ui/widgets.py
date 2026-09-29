import string
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from hashlib import sha1
from pathlib import Path
from typing import Literal

from nicegui import app, ui

from rulehall.app.game_session import Busy
from rulehall.core.validation import Refusal
from rulehall.core.views import Look
from rulehall.ui import theme
from rulehall.ui.routes import HOME, SOUNDS

type ClipName = Literal["roll"]

BRAND_ICON = "sym_r_casino"
HOME_ICON = "sym_r_home"
BACK_ICON = "sym_r_arrow_back"
REFUSED_ICON = "sym_r_explore_off"
DANGER_ICON = "sym_r_warning"
HELP_ICON = "sym_r_info"
PLAY_ICON = "sym_r_play_arrow"
BROKEN_ICON = "sym_r_broken_image"
PACK_ICON = "sym_r_style"
NEW_CHARACTER_ICON = "sym_r_person_add"
NEW_ADVENTURE_ICON = "sym_r_auto_stories"
NEW_PACK_ICON = "sym_r_auto_fix_high"
ON_TOUCH = "matchMedia('(hover: none)').matches"
PASS_THROUGH = "display: contents"
SOUNDS_DIR = Path(__file__).parent / "sounds"
DICE_CLIP: ClipName = "roll"
BLANK = string.whitespace + (
    "\xa0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
    "\u200b\u200c\u200d\u2060\ufeff"
)
_media_routes: dict[Path, str] = {}


class Sounds(ui.element, component="sounds.js"):
    def __init__(self) -> None:
        super().__init__()
        self._props["base"] = SOUNDS
        self._props["clips"] = [DICE_CLIP]
        self._props["reeled"] = DICE_CLIP

    def play(self, clip: ClipName) -> None:
        self.run_method("play", clip)


class Confirm(ui.dialog):
    def __init__(self, *, keep: str, confirm: str) -> None:
        super().__init__()
        with self, ui.card().classes("game-confirm game-gap-2xl"):
            with ui.row().classes("items-start no-wrap game-gap-xl"):
                ui.icon(DANGER_ICON).classes("game-confirm-icon")
                self.message = ui.label().classes("game-confirm-text")
            with ui.row().classes("w-full justify-end game-gap-lg"):
                ui.button(keep, on_click=self.close).props("flat")
                ui.button(confirm, on_click=lambda: self.submit(result=True)).props(
                    "color=negative"
                )

    async def ask(self, message: str) -> bool:
        self.message.set_text(message)
        return await self is True


class Banner(ui.column):
    def __init__(
        self, icon: str, label: str, text: str = "", *, kind: str = "game-decision"
    ) -> None:
        super().__init__()
        self.classes(f"game-card {kind} game-banner w-full game-gap-lg")
        with self, ui.row().classes("w-full items-center no-wrap game-banner-head game-gap-xl"):
            ui.icon(icon).classes("game-card-icon")
            with ui.column().classes("game-banner-text game-gap-3xs"):
                ui.label(label).classes("game-banner-label")
                self.text = ui.label(text).classes("game-banner-body")
            self.actions = ui.row().classes("items-center no-wrap game-banner-actions game-gap-md")


def help_tip(text: str, anchor: ui.element | None = None) -> None:
    """Hover shows a tooltip; a touch screen, where a tooltip shows only while pressed, taps."""
    if not text:
        return
    target = (
        ui.icon(HELP_ICON)
        .classes("game-help-icon")
        .props('tabindex=0 role=button aria-hidden=false aria-label="What this means"')
        if anchor is None
        else anchor.classes("game-help")
    )
    # Children, not `.tooltip()`: its `#id` target is missing when a hidden tab redraws.
    with target:
        ui.tooltip(text).classes("game-help-tip")
        with ui.menu().props("no-parent-event").classes("game-help-pop") as pop:
            ui.label(text)
    show = f"runMethod({pop.id}, 'show', [])"
    if anchor is not None:
        target.on(
            "click", js_handler=f"(e) => {{ if ({ON_TOUCH}) {{ e.stopPropagation(); {show} }} }}"
        )
        return
    target.on("click.stop", js_handler=f"() => {{ if ({ON_TOUCH}) {show} }}")
    for key in ("enter", "space"):
        target.on(f"keydown.{key}.stop.prevent", js_handler=f"() => {show}")


def media_url(path: Path) -> str:
    """One mount per directory: deleting one element must not break another's shared image."""
    directory = path.parent
    if (route := _media_routes.get(directory)) is None:
        route = f"/media/{sha1(str(directory).encode(), usedforsecurity=False).hexdigest()[:12]}/"
        app.add_static_files(route, directory)
        _media_routes[directory] = route
    return route + path.name


async def attempt(
    action: Callable[[], Awaitable[object]], *, failed: str, loading: ui.button | None = None
) -> bool:
    if loading is not None:
        loading.props("loading")
    try:
        await action()
    except Busy as busy:
        # Silent when it is this game's own turn: a double-click guard, not a message.
        if busy.elsewhere:
            alert(str(busy))
        return False
    except Refusal as refused:
        alert(str(refused))
        return False
    except Exception:
        # Announced, not handled: the re-raise is what logs the detail kept off the screen.
        alert(failed)
        raise
    finally:
        if loading is not None:
            loading.props(remove="loading")
    return True


def alert(message: str) -> None:
    _notify(message, "negative")


def warn(message: str) -> None:
    _notify(message, "warning")


def inform(message: str) -> None:
    _notify(message, "info")


def done(message: str) -> None:
    _notify(message, "positive")


def page_header(
    title: str,
    badge: str | None = None,
    *,
    back: str | None = HOME,
    look: Look | None = None,
) -> ui.header:
    ui.dark_mode(value=True)
    theme.set_look(look)
    with ui.header().classes("items-center no-wrap") as header:
        if back is None:
            with ui.element("div").classes("game-brand"):
                ui.icon(BRAND_ICON)
        elif back == HOME:
            icon_button(HOME_ICON, "Home", lambda: ui.navigate.to(HOME))
        else:
            icon_button(BACK_ICON, "Back", lambda: ui.navigate.to(back))
        ui.label(title).classes("game-title ellipsis")
        if badge is not None:
            ui.badge(badge).classes("gt-xs")
    return header


def refused_page(message: str) -> None:
    page_header("Rulehall")
    with (
        page_body(),
        ui.card().classes("w-full"),
        ui.column().classes("w-full items-center game-gap-2xl"),
    ):
        empty_state(REFUSED_ICON, message)
        ui.button("Home", icon=HOME_ICON, on_click=lambda: ui.navigate.to(HOME)).props(
            "color=primary"
        )


@contextmanager
def page_body(*, classes: str = "") -> Generator[None]:
    with (
        ui.column().classes(f"w-full q-pa-lg items-center {classes}"),
        ui.column().classes("w-full game-gap-3xl").style("max-width: var(--game-measure)"),
    ):
        yield


def page_intro(eyebrow: str, title: str, lead: str) -> None:
    with ui.column().classes("game-intro game-gap-lg"):
        ui.label(eyebrow).classes("game-eyebrow")
        ui.label(title).classes("game-title game-hero-title")
        ui.label(lead).classes("text-body1 game-lead")


def icon_button(icon: str, label: str, on_click: Callable[[], object] | None = None) -> ui.button:
    return (
        ui.button(icon=icon, on_click=on_click)
        .props(f'flat round aria-label="{label}"')
        .tooltip(label)
    )


def nav_button(label: str, icon: str, route: str) -> ui.button:
    with (
        ui.button(icon=icon, on_click=lambda: ui.navigate.to(route))
        .props(f'flat aria-label="{label}"')
        .classes("game-nav") as button
    ):
        ui.label(label).classes("gt-xs q-ml-sm")
    return button


def entry_card(
    icon: str,
    title: str,
    sub: str,
    actions: Callable[[], object] | None = None,
) -> None:
    with (
        ui.card().classes("w-full game-entry"),
        ui.row().classes("w-full items-center no-wrap game-entry-row game-gap-2xl"),
    ):
        ui.icon(icon).classes("game-entry-icon")
        with ui.column().classes("col game-gap-xs").style("min-width: 0"):
            ui.label(title).classes("game-entry-title game-title")
            if sub:
                ui.label(sub).classes("game-entry-sub")
        if actions is not None:
            with ui.row().classes("items-center no-wrap game-entry-actions game-gap-md"):
                actions()


def empty_state(icon: str, message: str) -> None:
    with ui.column().classes("game-empty items-center game-gap-xs"):
        ui.icon(icon)
        ui.label(message).classes("text-body2")


@contextmanager
def action_bar() -> Generator[None]:
    with ui.row().classes("w-full items-center justify-end game-actions game-gap-xl"):
        yield


@contextmanager
def section(title: str, *, classes: str = "", help: str = "") -> Generator[None]:
    with ui.card().classes(f"w-full game-gap-lg {classes}"):
        heading(title, help=help)
        yield


def section_title(title: str) -> None:
    ui.label(title).classes("game-section-title").props('role="heading" aria-level="2"')


def heading(title: str, count: int | None = None, *, help: str = "") -> None:
    with ui.element("div").classes("game-section-head"):
        help_tip(help, ui.label(title).classes("game-eyebrow"))
        if count is not None:
            ui.label(str(count)).classes("game-count")


def entered_text(field: ui.input | ui.textarea) -> str:
    return (field.value or "").strip(BLANK)


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


def failure_notice(what_failed: str) -> str:
    return f"Something went wrong. {what_failed} Look in the server log."


def _notify(message: str, kind: Literal["negative", "warning", "positive", "info"]) -> None:
    ui.notify(message, type=kind, multi_line=True, position="top")
