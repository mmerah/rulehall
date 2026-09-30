from collections.abc import Callable, Iterable, Mapping, Sequence

from rulehall.core.views import Panel, PanelRow, Rows, Subject
from rulehall.engines.sheet import Entity


def character_panel(
    player: Subject, rows: Rows, *extra: PanelRow, sheet_help: Mapping[str, str]
) -> Panel:
    return Panel(
        title="Character",
        rows=(player.row(), *helped_rows(rows, sheet_help), *extra),
    )


def here_panel(others: Iterable[Subject]) -> Panel:
    return Panel(title="Also here", rows=tuple(other.row() for other in others))


def party_panel[T: Entity](
    members: Sequence[T],
    sheet_help: Mapping[str, str],
    more: Callable[[T], Iterable[PanelRow]] = lambda _member: (),
) -> Panel | None:
    if not members:
        return None
    rows = tuple(
        row
        for member in members
        for row in (member.subject().row(), *helped_rows(member.rows(), sheet_help), *more(member))
    )
    return Panel(title="Party", rows=rows)


def helped_rows(rows: Rows, sheet_help: Mapping[str, str]) -> tuple[PanelRow, ...]:
    return tuple(
        PanelRow(name=name, brief=brief, help=sheet_help.get(name, "")) for name, brief in rows
    )
