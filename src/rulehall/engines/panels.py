import re
from collections.abc import Callable, Iterable, Sequence
from typing import Literal

from rulehall.core.decisions import ActionOption
from rulehall.core.views import Meter, Panel, PanelRow, PanelRows, Score, Subject, Tag
from rulehall.engines.sheet import Person

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def character_panel(player: Subject, rows: PanelRows) -> Panel:
    return Panel(title="Character", rows=(player.row(), *rows))


def here_panel(others: Iterable[Subject]) -> Panel:
    return Panel(title="Also here", rows=tuple(other.row() for other in others))


def party_panel[T: Person](
    members: Sequence[T], member_rows: Callable[[T], PanelRows]
) -> Panel | None:
    if not members:
        return None
    rows = tuple(
        row for member in members for row in (member.subject().row(), *member_rows(member))
    )
    return Panel(title="Party", rows=rows)


def text_rows(name: str, help: str, text: str) -> PanelRows:
    return (PanelRow(name=name, brief=text, help=help),) if text else ()


def tag_list(name: str, help: str, tags: Sequence[Tag]) -> PanelRows:
    return (PanelRow(name=name, brief="", help=help, tags=tuple(tags)),) if tags else ()


def score_block(name: str, help: str, scores: Sequence[Score]) -> PanelRows:
    return (PanelRow(name=name, brief="", help=help, scores=tuple(scores)),) if scores else ()


def gauge_row(
    name: str,
    help: str,
    current: int,
    maximum: int,
    *,
    look: Literal["bar", "pips"] = "bar",
    options: Sequence[ActionOption] = (),
) -> PanelRow:
    meter = Meter(name="", current=current, maximum=maximum, look=look)
    return PanelRow(name=name, brief="", help=help, meters=(meter,), options=tuple(options))


def described_tag(name: str, text: str, *, stat_line: str = "", colour: str = "") -> Tag:
    return Tag(
        name=name,
        colour=colour,
        help=". ".join(part for part in (stat_line, first_sentence(text)) if part),
        detail="\n".join(part for part in (stat_line, text) if part) if text else "",
    )


def first_sentence(text: str) -> str:
    first_line = text.strip().partition("\n")[0]
    return SENTENCE_END.split(first_line, maxsplit=1)[0]
