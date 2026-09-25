import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.io import read_model
from rulehall.core.play import DecisionOption
from rulehall.core.prompt import Sections, section_if, sections
from rulehall.core.validation import EngineId, Frozen, Refusal, Slug, content_id, slug

LOGGER = logging.getLogger(__name__)

DASH = " — "  # parts a name from its brief (`Named`, `Pack.sections`); inside neither
SEPARATOR = ", "  # parts one name from the next in the NAMES line; nowhere inside a name
SRD_PACK: Slug = "srd"
NPCS = "People a player could meet and deal with."


class Names(Frozen):
    female: tuple[str, ...] = ()
    male: tuple[str, ...] = ()
    neutral: tuple[str, ...] = ()
    surnames: tuple[str, ...] = ()
    nicknames: tuple[str, ...] = ()

    def listed(self) -> tuple[tuple[Slug, tuple[str, ...]], ...]:
        return (
            ("female", self.female),
            ("male", self.male),
            ("neutral", self.neutral),
            ("surnames", self.surnames),
            ("nicknames", self.nicknames),
        )

    @model_validator(mode="after")
    def _every_name_reads_in_a_list(self) -> Self:
        for kind, values in self.listed():
            check_items(kind, values)
        return self


class Named(Frozen):
    """One row of a creation table. Code makes the id from the name."""

    name: str = Field(min_length=1, max_length=60)
    brief: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _reads_as_one_table_line(self) -> Self:
        check_lines("a table entry", (self.name, self.brief))
        if DASH in self.name or DASH in self.brief:
            raise ValueError(f'a table entry holds "{DASH}", which parts a name from its brief')
        return self


class Location(Frozen):
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    encounters: str = ""  # the SRD's "Possible encounters" line, names the worldsmith may use

    @model_validator(mode="after")
    def _reads_in_a_block(self) -> Self:
        check_lines("a location", (self.name, self.brief, self.encounters))
        return self


class Pack(Frozen):
    name: str = Field(min_length=1)
    source: str
    license: str
    backdrop: str = ""
    names: Names = Field(default_factory=Names)
    rules: str = ""  # read by the master alone
    locations: tuple[Location, ...] = ()
    seeds: tuple[str, ...] = ()

    def sections(self, *, opening: bool) -> Sections:
        name_lines = "\n".join(
            f"{kind}: {SEPARATOR.join(values)}" for kind, values in self.names.listed() if values
        )
        location_lines: list[str] = []
        for location in self.locations:
            location_lines.append(f"- {location.name} — {location.brief}")
            if location.encounters:
                location_lines.append(f"  encounters: {location.encounters}")
        return (
            *section_if("BACKDROP", self.backdrop),
            *section_if("NAMES", name_lines),
            *section_if("LOCATIONS", "\n".join(location_lines)),
            *(bullets("ADVENTURE SEEDS", self.seeds) if opening else ()),
        )


class PackHead(Frozen):
    """The first ask: what the setting is, what a player picks from, and what people are called."""

    backdrop: str = Field(
        min_length=1,
        description="A few paragraphs on what this world is and what a story in it is about.",
    )
    names: Names = Field(
        description="Names that fit the setting. Write six to twelve names in each list. "
        "Leave a list empty where the setting has no such names.",
    )
    rules: str = Field(
        default="",
        description="The one special rule of the genre, as prose the game master reads. "
        "Leave it empty where the genre has no special rule.",
    )

    def pack_fields(self) -> dict[str, object]:
        return self.model_dump()


class PackBody(Frozen):
    """The second ask: who the player meets, where, and what a story can start from."""

    locations: tuple[Location, ...] = Field(
        min_length=3,
        max_length=6,
        description="Places in this setting. Each place says what is found there and who the "
        "player can meet there.",
    )
    seeds: tuple[str, ...] = Field(
        min_length=6,
        max_length=36,
        description="One-line adventure premises, such as 'A salt barge comes in with no crew "
        "aboard'.",
    )

    @model_validator(mode="after")
    def _every_seed_reads_on_one_line(self) -> Self:
        check_lines("a seed", self.seeds)
        return self


@dataclass(frozen=True, slots=True)
class PackSet[K: Pack]:
    engine_id: EngineId
    shipped: Mapping[Slug, K]
    written: Mapping[Slug, K]  # the player's, from `packs/<engine>/`; never shadows a shipped id

    @property
    def installed(self) -> Mapping[Slug, K]:
        return {**self.shipped, **self.written}

    def srd(self) -> K:
        found = self.installed.get(SRD_PACK)
        if found is None:
            raise ValueError(f"the {self.engine_id!r} engine ships no {SRD_PACK!r} pack")
        return found

    def require(self, pack_id: Slug) -> K:
        found = self.installed.get(pack_id)
        if found is None:
            raise Refusal(f"pack {pack_id!r} is not installed for {self.engine_id!r}")
        return found

    def played(self, pack_id: Slug) -> tuple[K, ...]:
        srd = self.srd()
        return (srd,) if pack_id == SRD_PACK else (srd, self.require(pack_id))

    def options(self) -> tuple[DecisionOption, ...]:
        rest = tuple(
            DecisionOption(id=pack_id, name=pack.name)
            for pack_id, pack in self.installed.items()
            if pack_id != SRD_PACK
        )
        return (DecisionOption(id=SRD_PACK, name=self.srd().name), *rest)

    def guidance(self, pack_id: Slug, *, opening: bool) -> str:
        pack = self.require(pack_id)
        parts = pack.sections(opening=opening)
        return f"PACK: {pack.name}\n\n{sections(parts)}" if parts else ""

    def rules_section(self, pack_id: Slug) -> Sections:
        pack = self.require(pack_id)
        return ((f"SPECIAL RULES: {pack.name}", pack.rules),) if pack.rules else ()


def block_line(name: str, brief: str, *fields: tuple[str, str]) -> str:
    return "; ".join((f"{name} — {brief}", *(f"{key}: {value}" for key, value in fields if value)))


def with_ids(rows: Iterable[Named], taken: list[Slug]) -> tuple[DecisionOption, ...]:
    """`taken` grows, so the ids stay unique across a pack's tables."""
    made: list[DecisionOption] = []
    for entry in rows:
        made.append(DecisionOption(id=slug(entry.name, taken), name=entry.name, brief=entry.brief))
        taken.append(made[-1].id)
    return tuple(made)


def unique_options[T: DecisionOption](rows: Iterable[T]) -> tuple[T, ...]:
    """Packs play together, so a written row repeating an SRD id is dropped, not offered twice."""
    offered: dict[Slug, T] = {}
    for row in rows:
        offered.setdefault(row.id, row)
    return tuple(offered.values())


def bullets(title: str, lines: Iterable[str]) -> Sections:
    return section_if(title, "\n".join(f"- {line}" for line in lines))


def check_lines(what: str, values: Iterable[str]) -> None:
    for value in values:
        if "\n" in value:
            raise ValueError(f"{what} runs over one line")


def check_items(what: str, values: Iterable[str]) -> None:
    check_lines(what, values)
    for value in values:
        if SEPARATOR in value:
            raise ValueError(f'{what} holds "{SEPARATOR}", which parts one item from the next')


def read_packs[P: Pack](
    engine_id: EngineId, shipped: Path, written: Path, model: type[P]
) -> PackSet[P]:
    """A shipped file that fails to parse is a bug; a written one is logged and skipped."""
    shipped_packs = {
        content_id(path.stem): read_model(path, model) for path in sorted(shipped.glob("*.json"))
    }
    written_packs: dict[Slug, P] = {}
    for path in sorted(written.glob("*.json")):
        try:
            pack_id = content_id(path.stem)
            pack = read_model(path, model)
        except Refusal as unreadable:
            LOGGER.warning("skipping pack %s for %r: %s", path.name, engine_id, unreadable)
            continue
        if pack_id in shipped_packs:
            LOGGER.warning(
                "skipping pack %s for %r: %r is a shipped pack", path.name, engine_id, pack_id
            )
            continue
        written_packs[pack_id] = pack
    return PackSet(engine_id, shipped_packs, written_packs)
