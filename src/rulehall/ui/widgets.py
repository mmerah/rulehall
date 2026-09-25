import string
from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from functools import partial
from hashlib import sha1
from pathlib import Path
from typing import Literal

from nicegui import app, ui
from nicegui.events import EChartPointClickEventArguments

from rulehall.app.launch import LaunchTarget
from rulehall.core.play import Answer, DecisionOption
from rulehall.core.validation import EngineId, Slug
from rulehall.core.views import Look, MapNode, MapView, Meter, Sprite, Tag
from rulehall.ui import theme

type ClipName = Literal["roll"]

DM_ICON = "sym_r_auto_stories"
BRAND_ICON = "sym_r_casino"
HOME_ICON = "sym_r_home"
DANGER_ICON = "sym_r_warning"
ARROW_ICON = "sym_r_arrow_forward"
PASS_THROUGH = "display: contents"
TURN_FAILED = "Something went wrong. The turn did not complete. Look in the server log."
BATTLE_FAILED = "Something went wrong. The battle did not start. Look in the server log."
GAME_ROUTE = "/game/{scenario}/{character}"
SOUNDS_DIR = Path(__file__).parent / "sounds"
SOUNDS_ROUTE = "/sounds/"
ASSETS_ROUTE = "/assets"
DICE_CLIP: ClipName = "roll"
# The relative luminance above which dark text on the tag reads better than white.
LIGHT_TAG = 0.4
BLANK = string.whitespace + (
    "\xa0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
    "\u200b\u200c\u200d\u2060\ufeff"
)
_media_routes: dict[Path, str] = {}


class Sounds(ui.element, component="sounds.js"):
    def __init__(self) -> None:
        super().__init__()
        self._props["base"] = SOUNDS_ROUTE
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
    def __init__(self, icon: str, label: str, text: str = "") -> None:
        super().__init__()
        self.classes("game-card game-decision game-banner w-full game-gap-lg")
        with self, ui.row().classes("w-full items-center no-wrap game-banner-head game-gap-xl"):
            ui.icon(icon).classes("game-card-icon")
            with ui.column().classes("game-banner-text game-gap-3xs"):
                ui.label(label).classes("game-banner-label")
                self.text = ui.label(text).classes("game-banner-body")
            self.actions = ui.row().classes("items-center no-wrap game-banner-actions game-gap-md")


def game_path(target: LaunchTarget) -> str:
    return GAME_ROUTE.format(scenario=target.scenario_id, character=target.character_id)


def assets_route(engine_id: EngineId) -> str:
    return f"{ASSETS_ROUTE}/{engine_id}"


def media_url(path: Path) -> str:
    """One mount per directory: deleting one element must not break another's shared image."""
    directory = path.parent
    if (route := _media_routes.get(directory)) is None:
        route = f"/media/{sha1(str(directory).encode(), usedforsecurity=False).hexdigest()[:12]}/"
        app.add_static_files(route, directory)
        _media_routes[directory] = route
    return route + path.name


def alert(message: str) -> None:
    _notify(message, "negative")


def warn(message: str) -> None:
    _notify(message, "warning")


def note(message: str, *, good: bool = False) -> None:
    _notify(message, "positive" if good else "info")


def page_header(
    title: str, badge: str | None = None, *, home: bool = True, look: Look | None = None
) -> ui.header:
    ui.dark_mode(value=True)
    theme.set_look(look)
    with ui.header().classes("items-center no-wrap") as header:
        if home:
            icon_button(HOME_ICON, "Home", lambda: ui.navigate.to("/"))
        else:
            with ui.element("div").classes("game-brand"):
                ui.icon(BRAND_ICON)
        ui.label(title).classes("game-title ellipsis")
        if badge is not None:
            ui.badge(badge).classes("gt-xs")
    return header


@contextmanager
def page_body() -> Generator[None]:
    with (
        ui.column().classes("w-full q-pa-lg items-center"),
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


def action_tile(icon: str, title: str, caption: str, on_click: Callable[[], object]) -> None:
    with ui.button(on_click=on_click).props("outline").classes("game-tile"):
        ui.icon(icon).classes("game-tile-icon")
        with ui.column().classes("game-gap-3xs"):
            ui.label(title).classes("game-tile-title")
            ui.label(caption).classes("game-tile-caption")
        ui.icon(ARROW_ICON).classes("game-tile-arrow")


@contextmanager
def entry_card(icon: str, title: str, sub: str, badges: Sequence[str]) -> Generator[None]:
    with (
        ui.card().classes("w-full game-entry"),
        ui.row().classes("w-full items-center no-wrap game-entry-row game-gap-2xl"),
    ):
        ui.icon(icon).classes("game-entry-icon")
        with ui.column().classes("col game-gap-xs").style("min-width: 0"):
            ui.label(title).classes("game-entry-title game-title")
            if sub:
                ui.label(sub).classes("game-entry-sub")
            if badges:
                with ui.row().classes("game-gap-md"):
                    for badge in badges:
                        ui.badge(badge)
        with ui.row().classes("items-center no-wrap game-entry-actions game-gap-md"):
            yield


def empty_state(icon: str, message: str) -> None:
    with ui.column().classes("game-empty items-center game-gap-xs"):
        ui.icon(icon)
        ui.label(message).classes("text-body2")


@contextmanager
def action_bar() -> Generator[None]:
    with ui.row().classes("w-full items-center justify-end game-actions game-gap-xl"):
        yield


@contextmanager
def section(title: str, *, classes: str = "") -> Generator[None]:
    with ui.card().classes(f"w-full game-gap-lg {classes}"):
        heading(title)
        yield


def heading(title: str, count: int | None = None) -> None:
    with ui.element("div").classes("game-section-head"):
        ui.label(title).classes("game-eyebrow")
        if count is not None:
            ui.label(str(count)).classes("game-count")


def entity_row(
    icon: Sprite | Path | None,
    name: str,
    sub: str,
    *,
    alive: bool = True,
    tags: Sequence[Tag] = (),
    meters: Sequence[Meter] = (),
) -> ui.element:
    classes = "game-entity" + ("" if alive else " game-entity-dead")
    with ui.element("div").classes(classes) as row:
        avatar(icon, name)
        with ui.column().classes("game-gap-0 game-entity-body"):
            with ui.row().classes("items-center no-wrap game-gap-sm"):
                ui.label(name).classes("game-entity-name game-title")
                if not alive:
                    ui.badge("dead").props("outline color=negative").classes("game-entity-badge")
            if tags:
                tag_row(tags)
            if meters:
                meter_grid(meters)
            if sub:
                ui.label(sub).classes("game-entity-sub")
    return row


def tag_row(tags: Sequence[Tag]) -> None:
    with ui.element("div").classes("game-tags"):
        for tag in tags:
            chip = ui.label(tag.name).classes("game-tag")
            if tag.hint:
                chip.tooltip(tag.hint)
            if tag.colour:
                chip.style(f"--game-tag: {tag.colour}").classes("game-tag-coloured")
                if _light(tag.colour):
                    chip.classes("game-tag-light")


def meter_grid(meters: Sequence[Meter]) -> None:
    lead = meters[0]
    with ui.element("div").classes("game-meters"):
        for meter in meters:
            share = min(meter.current, meter.maximum) / meter.maximum
            colour = meter.colour or "var(--game-accent)"
            with ui.element("div").classes("game-meter").style(f"--game-meter: {colour}") as box:
                if meter.hint:
                    box.tooltip(meter.hint)
                ui.label(meter.name).classes("game-meter-label")
                with ui.element("div").classes("game-meter-track"):
                    ui.element("div").classes("game-meter-fill").style(f"width: {share:.1%}")
                value = f"{meter.current}/{meter.maximum}" if meter is lead else str(meter.current)
                ui.label(value).classes("game-meter-value")


def avatar(icon: Sprite | Path | None, name: str | None) -> None:
    if isinstance(icon, Sprite) and icon.width:
        ui.element("div").classes("game-sprite-frame").style(
            f"width: {icon.width}px; height: {icon.height}px; "
            f"background-image: url({media_url(icon.path)}); "
            f"background-position: -{icon.x}px -{icon.y}px"
        )
        return
    with ui.avatar(size="42px", color=None).classes(
        "game-avatar" + (" game-avatar-dm" if name is None else "")
    ):
        if isinstance(icon, Sprite):
            ui.image(media_url(icon.path)).classes("game-pixelated")
        elif icon is not None:
            ui.image(media_url(icon))
        elif name is None:
            ui.icon(DM_ICON)
        else:
            ui.label(name[:1].upper()).classes("text-subtitle1")


def labeled_value(
    label: str, value: str, *, tags: Sequence[Tag] = (), meters: Sequence[Meter] = ()
) -> ui.element:
    stacked = len(value) > 28 or bool(tags or meters)
    with ui.element("div").classes("game-stat" + (" game-stat-long" if stacked else "")) as row:
        with ui.element("div").classes("game-stat-head"):
            ui.label(label).classes("game-stat-label")
            if tags:
                tag_row(tags)
        if value or not (tags or meters):
            ui.label(value or "—").classes("game-stat-value")
        if meters:
            meter_grid(meters)
    return row


def typed(box: ui.input | ui.textarea) -> str:
    return (box.value or "").strip(BLANK)


def decision_options(
    options: Sequence[DecisionOption],
    play: Callable[[Answer], Awaitable[object]],
    *,
    enabled: bool,
) -> None:
    with ui.row().classes("w-full items-start game-choices game-gap-md"):
        for option in options:
            chosen = partial(play, Answer(option_id=option.id))
            choice_button(option.name, option.brief, chosen, enabled=enabled)


def choice_button(
    name: str,
    brief: str,
    on_click: Callable[[], Awaitable[object]],
    *,
    enabled: bool,
    tags: Sequence[Tag] = (),
) -> None:
    button = ui.button(on_click=on_click).props("outline").classes("game-choice")
    if tint := next((tag.colour for tag in tags if tag.colour), ""):
        button.style(f"--game-tag: {tint}").classes("game-choice-tinted")
    # A label in the button's own slot sits beside the brief, not above it.
    with button.set_enabled(enabled), ui.column().classes("w-full game-gap-0"):
        with ui.row().classes("items-center w-full game-gap-sm game-choice-head"):
            ui.label(name)
            if tags:
                tag_row(tags)
        if brief:
            ui.label(brief).classes("text-xs opacity-70")


def map_chart(view: MapView, look: Look | None, pick: Callable[[int], None]) -> ui.echart:
    def clicked(event: EChartPointClickEventArguments) -> None:
        if event.data_type == "node":
            pick(event.data_index)

    # Inline, not a class: a hidden tab's chart falls back to its inline size, and a zero throws.
    return ui.echart(map_options(view, look), on_point_click=clicked).style(
        "width: 100%; height: 16rem"
    )


def map_options(view: MapView, look: Look | None) -> dict[str, object]:
    colours = theme.palette(look)
    index = {node.id: at for at, node in enumerate(view.nodes)}
    # NiceGUI's point click reads args['value'] unguarded; every node and link must carry one.
    nodes = [
        {
            "name": node.name,
            "value": node.id,
            "symbolSize": 18 if node.id == view.here_id else 12,
            "itemStyle": _map_style(node, view.here_id, colours),
            "label": _map_style(node, view.here_id, colours),
        }
        for node in view.nodes
    ]
    links = [
        {
            "source": index[edge.from_id],
            "target": index[edge.to_id],
            "value": 0,
            "lineStyle": {"type": "dashed" if edge.locked else "solid"},
        }
        for edge in view.edges
    ]
    series = {
        "type": "graph",
        "layout": "force",
        "roam": "move",
        "force": {
            "initLayout": "circular",
            "repulsion": 300,
            "edgeLength": 100,
            "layoutAnimation": False,
        },
        "label": {"show": True, "position": "right", "fontFamily": colours["game-body"]},
        "lineStyle": {"color": colours["game-muted"], "opacity": 0.6, "width": 2},
        "data": nodes,
        "links": links,
    }
    return {"animation": False, "series": [series]}


def _map_style(node: MapNode, here_id: Slug, colours: dict[str, str]) -> dict[str, str | float]:
    fill = "game-accent" if node.id == here_id else "game-text" if node.visited else "game-muted"
    return {"color": colours[fill], "opacity": 1 if node.visited else 0.5}


def _light(colour: str) -> bool:
    red, green, blue = (int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5))
    return 0.2126 * red**2.2 + 0.7152 * green**2.2 + 0.0722 * blue**2.2 > LIGHT_TAG


def _notify(message: str, kind: Literal["negative", "warning", "positive", "info"]) -> None:
    ui.notify(message, type=kind, multi_line=True, position="top")
