from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from itertools import groupby
from pathlib import Path

from nicegui import ui

from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Slug
from rulehall.core.views import Meter, PanelRow, Sprite, Tag
from rulehall.ui.widgets import heading, help_tip, media_url

type IconOf = Callable[[Slug], Sprite | Path | None]
type PickOption = Callable[[ActionOption], Awaitable[object]]

DM_ICON = "sym_r_auto_stories"
CHOICES_ROW = "row w-full items-start game-choices game-gap-md"
ROW_OPTIONS = "row items-center game-row-options game-gap-md"
LIGHT_TAG_LUMINANCE = 0.4


def entity_row(
    icon: Sprite | Path | None,
    name: str,
    sub: str,
    *,
    alive: bool = True,
    tags: Sequence[Tag] = (),
    meters: Sequence[Meter] = (),
    help: str = "",
    opens: bool = False,
) -> ui.element:
    classes = "game-entity" + ("" if alive else " game-entity-dead")
    with ui.element("div").classes(classes) as row:
        avatar(icon, name)
        with ui.column().classes("game-gap-0 game-entity-body"):
            with ui.row().classes("items-center no-wrap game-gap-sm"):
                _help_label(name, "game-entity-name game-title", help, opens=opens)
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
            help_tip(tag.help, chip)
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
            with ui.element("div").classes("game-meter").style(f"--game-meter: {colour}"):
                help_tip(meter.help, ui.label(meter.name).classes("game-meter-label"))
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
    label: str,
    value: str,
    *,
    tags: Sequence[Tag] = (),
    meters: Sequence[Meter] = (),
    help: str = "",
    opens: bool = False,
) -> ui.element:
    stacked = len(value) > 28 or bool(tags or meters)
    with ui.element("div").classes("game-stat" + (" game-stat-long" if stacked else "")) as row:
        with ui.element("div").classes("game-stat-head"):
            _help_label(label, "game-stat-label", help, opens=opens)
            if tags:
                tag_row(tags)
        if value or not (tags or meters):
            ui.label(value or "—").classes("game-stat-value")
        if meters:
            meter_grid(meters)
    return row


def choice_groups(
    items: Sequence[ActionOption], pick: PickOption, *, enabled: bool, row_class: str
) -> list[tuple[ui.button, ActionOption]]:
    groups = [
        (group, tuple(members)) for group, members in groupby(items, key=lambda item: item.group)
    ]
    drawn: list[tuple[ui.button, ActionOption]] = []
    for group, members in groups:
        if len(groups) > 1 and group:
            heading(group)
        with ui.element("div").classes(row_class):
            drawn.extend(
                (
                    choice_button(
                        item.name,
                        item.refusal or item.brief,
                        partial(pick, item),
                        enabled=enabled and not item.refusal,
                        help=item.help,
                    ),
                    item,
                )
                for item in members
            )
    return drawn


def choice_button(
    name: str,
    brief: str,
    on_click: Callable[[], Awaitable[object]],
    *,
    enabled: bool,
    help: str = "",
    tags: Sequence[Tag] = (),
    meters: Sequence[Meter] = (),
    icon: Sprite | Path | None = None,
) -> ui.button:
    button = ui.button(on_click=on_click).props("outline").classes("game-choice")
    if tint := next((tag.colour for tag in tags if tag.colour), ""):
        button.style(f"--game-tag: {tint}").classes("game-choice-tinted")
    with button.set_enabled(enabled), ui.column().classes("w-full game-gap-0"):
        with ui.row().classes("items-center w-full game-gap-sm game-choice-head"):
            if icon is not None:
                avatar(icon, name)
            with ui.label(name).classes("game-choice-name"):
                help_tip(help)
            if tags:
                tag_row(tags)
        if meters:
            meter_grid(meters)
        if brief:
            ui.label(brief).classes("text-xs opacity-70")
    return button


def panel_row(
    row: PanelRow,
    icon_of: IconOf,
    open_row: Callable[[PanelRow], None] | None = None,
    pick: PickOption | None = None,
) -> list[tuple[ui.button, ActionOption]]:
    if pick is not None and row.options and not row.detail:
        with ui.element("div").classes("game-row-line"):
            _row_body(row, icon_of, opens=False)
            return choice_groups(row.options, pick, enabled=True, row_class=ROW_OPTIONS)
    opens = open_row is not None and bool(row.detail)
    drawn = _row_body(row, icon_of, opens=opens)
    if open_row is not None and opens:
        opened = partial(open_row, row)
        drawn.classes("game-opens").props("tabindex=0 role=button")
        drawn.on("click", opened).on("keydown.enter", opened)
        drawn.on("keydown.space.prevent", opened)
        with drawn:
            ui.icon("sym_r_chevron_right").classes("game-opens-cue")
    return []


def _row_body(row: PanelRow, icon_of: IconOf, *, opens: bool) -> ui.element:
    if row.icon_id is not None:
        return entity_row(
            icon_of(row.icon_id),
            row.name,
            row.brief,
            alive=row.alive,
            tags=row.tags,
            meters=row.meters,
            help=row.help,
            opens=opens,
        )
    if row.brief or row.tags or row.meters:
        return labeled_value(
            row.name, row.brief, tags=row.tags, meters=row.meters, help=row.help, opens=opens
        )
    return _help_label(row.name, "text-sm", row.help, opens=opens)


def _help_label(text: str, classes: str, help: str, *, opens: bool) -> ui.label:
    """A row that opens a dialog on a tap takes the icon, so a tap on its name still opens it."""
    label = ui.label(text).classes(classes)
    if opens:
        with label:
            help_tip(help)
    else:
        help_tip(help, label)
    return label


def _light(colour: str) -> bool:
    red, green, blue = (int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5))
    return 0.2126 * red**2.2 + 0.7152 * green**2.2 + 0.0722 * blue**2.2 > LIGHT_TAG_LUMINANCE
