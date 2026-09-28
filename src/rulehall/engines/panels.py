from collections.abc import Callable, Iterable, Sequence

from rulehall.core.decisions import ActionOption
from rulehall.core.views import Panel, PanelRow, Rows, Subject
from rulehall.engines.sheet import Entity


def character_panel(player: Subject, rows: Rows, *extra: PanelRow) -> Panel:
    return Panel(
        title="Character",
        rows=(
            player.row(),
            *(PanelRow(name=name, brief=brief) for name, brief in rows),
            *extra,
        ),
    )


def here_panel(
    others: Iterable[Subject],
    options_for: Callable[[Subject], tuple[ActionOption, ...]] = lambda _other: (),
) -> Panel:
    return Panel(title="Also here", rows=tuple(other.row(options_for(other)) for other in others))


def party_panel[T: Entity](
    members: Sequence[T], more: Callable[[T], Iterable[PanelRow]] = lambda _member: ()
) -> tuple[Panel, ...]:
    if not members:
        return ()
    rows = tuple(
        row
        for member in members
        for row in (
            member.subject().row(),
            *(PanelRow(name=name, brief=brief) for name, brief in member.rows()),
            *more(member),
        )
    )
    return (Panel(title="Party", rows=rows),)
