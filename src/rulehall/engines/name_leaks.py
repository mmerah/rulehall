import re
from collections.abc import Iterable, Sequence

from rulehall.engines.sheet import Entity, Person

NAME_WORD_LETTERS = 4
ARTICLES = ("the", "a", "an")


def names_in(text: str, entities: Iterable[Entity]) -> list[str]:
    return [entity.name for entity in entities if _mentions(text, entity.name)]


def unmet_people_named[P: Person](text: str, people: Iterable[P]) -> list[P]:
    everyone = list(people)
    unmet = [person for person in everyone if not person.known]
    met = [person for person in everyone if person.known]
    named = {*names_in(text, unmet), *_named_by_distinctive_word(text, unmet, met)}
    return [person for person in unmet if person.name in named]


def leaked_names(read: str, entities: Iterable[Entity], hidden: Sequence[Entity]) -> set[str]:
    leaked = set(names_in(read, hidden))
    for entity in entities:
        text = "\n".join((entity.brief, *(value for _, value in entity.rows())))
        leaked.update(names_in(text, (other for other in hidden if other.id != entity.id)))
    return leaked


def _named_by_distinctive_word(
    text: str, people: Iterable[Person], met: Iterable[Person]
) -> list[str]:
    shared = {word for person in met for word in _capitalised(person.name)}
    return [
        person.name
        for person in people
        if any(
            re.search(rf"(?<!\w){word}(?!\w)", text) is not None
            for word in _name_words(person.name)
            if word not in shared
        )
    ]


def _mentions(text: str, name: str) -> bool:
    folded = name.strip().casefold()
    return (
        bool(folded)
        and re.search(rf"(?<!\w){re.escape(folded)}(?!\w)", text.casefold()) is not None
    )


def _words(name: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", name)


def _capitalised(name: str) -> list[str]:
    return [word for word in _words(name) if word[0].isupper() and len(word) >= NAME_WORD_LETTERS]


def _name_words(name: str) -> list[str]:
    words = _words(name)
    return [] if not words or words[0].casefold() in ARTICLES else _capitalised(name)
