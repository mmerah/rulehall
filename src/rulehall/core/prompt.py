from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rulehall.core.log import Chapter, LogEntry

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


def render_log(chapters: Sequence[Chapter]) -> str:
    if not any(chapter.entries for chapter in chapters):
        return "(the game has not started yet)"
    total = len(chapters)
    return "\n\n".join(_block(chapter, index, total) for index, chapter in enumerate(chapters))


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
    log_entries = chapter.entries
    start = max(len(log_entries) - last, 0)
    before = [chapter.context, *(entry.context for entry in log_entries)]
    entries = (
        _entry(entry, before[index]) for index, entry in enumerate(log_entries[start:], start)
    )
    return "\n\n".join(entries) or "(nothing yet)"


def _entry(entry: LogEntry, before: str) -> str:
    if entry.cause is not None:
        told = entry.transcript()
    else:
        told = f"> {entry.words}\n{entry.transcript()}"
    kept = set(before.splitlines())
    changed = (f"→ {line}" for line in entry.context.splitlines() if line not in kept)
    return "\n".join((told, *changed))
