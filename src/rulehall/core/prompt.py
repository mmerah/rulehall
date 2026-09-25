from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rulehall.core.play import Chapter, Exchange

type Sections = tuple[tuple[str, str], ...]

SCENE_EXCHANGES = 20
WHOLE_SCENES = 2
TAIL_EXCHANGES = 3


@dataclass(frozen=True, slots=True)
class Prompt:
    system: str
    user: str

    @property
    def text(self) -> str:
        return "\n\n".join(part for part in (self.system, self.user) if part)


def sections(parts: Sections) -> str:
    return "\n\n".join(f"# {name}\n{body.strip()}" for name, body in parts)


def section_if(title: str, body: str) -> Sections:
    return ((title, body),) if body else ()


def lines_of(parts: Iterable[str]) -> str:
    return "\n".join(parts) or "- (none)"


def sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def render_history(log: Sequence[Chapter]) -> str:
    if not any(chapter.exchanges for chapter in log):
        return "(the game has not started yet)"
    total = len(log)
    return "\n\n".join(_block(chapter, index, total) for index, chapter in enumerate(log))


def _block(chapter: Chapter, index: int, total: int) -> str:
    if index >= total - WHOLE_SCENES:
        return _whole(chapter)
    body = f"what happened: {chapter.recap}" if chapter.recap else _told(chapter, TAIL_EXCHANGES)
    return f"{_heading(chapter)}\n\n{body}"


def _whole(chapter: Chapter) -> str:
    return f"{_heading(chapter)}\n\n{_told(chapter, SCENE_EXCHANGES)}"


def _heading(chapter: Chapter) -> str:
    return "\n".join(part for part in (f"## Scene: {chapter.title}", chapter.context) if part)


def _told(chapter: Chapter, last: int) -> str:
    exchanges = chapter.exchanges
    start = max(len(exchanges) - last, 0)
    before = [chapter.context, *(exchange.context for exchange in exchanges)]
    entries = (
        _entry(exchange, before[index]) for index, exchange in enumerate(exchanges[start:], start)
    )
    return "\n\n".join(entries) or "(nothing yet)"


def _entry(exchange: Exchange, before: str) -> str:
    if exchange.cause is not None:
        told = exchange.transcript()
    else:
        told = f"> {exchange.words}\n{exchange.transcript()}"
    kept = set(before.splitlines())
    changed = (f"→ {line}" for line in exchange.context.splitlines() if line not in kept)
    return "\n".join((told, *changed))
