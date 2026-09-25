from collections.abc import Callable, Iterable, Sequence

from rulehall.core.views import Panel, PanelRow, Rows, Subject
from rulehall.engines.entities import Thing


def character_panel(rows: Rows, *extra: PanelRow) -> Panel:
    return Panel(
        title="Character",
        portrait=True,
        rows=(*(PanelRow(name=name, brief=brief) for name, brief in rows), *extra),
    )


def here_panel(others: Iterable[Subject]) -> Panel:
    """The player already has the sheet above, so a row for them would say it twice."""
    return Panel(title="Also here", rows=tuple(other.row() for other in others))


def party_panel[T: Thing](
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
