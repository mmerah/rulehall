import re
from collections.abc import Sequence

from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.pending import PendingSet
from rulehall.engines.pokemon.dex import NATURES, dex, showdown_id
from rulehall.engines.pokemon.rules import STAT_NAMES

GENDER = re.compile(r"\s*\([MF]\)$")
NICKNAMED = re.compile(r"\(([^()]+)\)$")
IVS_IGNORED = "IVs are ignored: every Pokemon has full IVs"
TERA_IGNORED = "Tera types are ignored: Champions has no Terastallization"


class ParsedRow(Frozen):
    pending_set: PendingSet | None
    errors: tuple[str, ...]
    notes: tuple[str, ...]


def export_paste(slots: Sequence[PendingSet | None]) -> str:
    return "\n\n".join(_export_set(each) for each in slots if each is not None) + "\n"


def parse_paste(text: str) -> tuple[ParsedRow, ...]:
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("==="):
            continue
        if stripped:
            blocks[-1].append(stripped)
        elif blocks[-1]:
            blocks.append([])
    sets = [block for block in blocks if block]
    team_size = champions_data().legal.team_size
    if not sets:
        raise Refusal("the paste holds no Pokemon")
    if len(sets) > team_size:
        raise Refusal(f"a team has at most {team_size} Pokemon; the paste has {len(sets)}")
    return tuple(_parse_set(block) for block in sets)


def _export_set(pending_set: PendingSet) -> str:
    pokedex = dex()
    name = pokedex.species[pending_set.species_id].name
    item = "" if pending_set.item_id is None else f" @ {pokedex.item_names[pending_set.item_id]}"
    points = " / ".join(
        f"{points} {STAT_NAMES[index]}" for index, points in enumerate(pending_set.sp) if points
    )
    lines = (
        f"{name}{item}",
        *(
            ()
            if pending_set.ability_id is None
            else (f"Ability: {pokedex.ability_names[pending_set.ability_id]}",)
        ),
        f"Level: {champions_data().legal.level}",
        *((f"EVs: {points}",) if points else ()),
        f"{pending_set.nature} Nature",
        *(f"- {pokedex.moves[move_id].name}" for move_id in pending_set.move_ids),
    )
    return "\n".join(lines)


def _parse_set(lines: Sequence[str]) -> ParsedRow:
    pokedex = dex()
    legal = champions_data().legal
    named, _, item_name = lines[0].partition(" @ ")
    named = GENDER.sub("", named.strip())
    nicknamed = NICKNAMED.search(named)
    species_name = nicknamed.group(1) if nicknamed else named
    species_id = showdown_id(species_name)
    if species_id not in legal.species:
        return ParsedRow(
            pending_set=None, errors=(f"{species_name} is not legal in the format",), notes=()
        )
    errors: list[str] = []
    notes: list[str] = []
    item_id = showdown_id(item_name) or None
    if item_id is not None and item_id not in pokedex.item_names:
        item_id = None
        errors.append(f"no item is named {item_name.strip()}")
    ability_id: Slug | None = None
    nature = "Serious"
    sp = [0] * len(STAT_NAMES)
    move_ids: list[Slug] = []
    for line in lines[1:]:
        label, _, value = line.partition(":")
        value = value.strip()
        if label == "Ability":
            ability_id = showdown_id(value)
            if ability_id not in pokedex.ability_names:
                ability_id = None
                errors.append(f"no ability is named {value}")
        elif label == "EVs":
            sp = _stat_points(value, errors)
        elif label == "IVs":
            notes.append(IVS_IGNORED)
        elif label == "Tera Type":
            notes.append(TERA_IGNORED)
        elif line.endswith(" Nature"):
            nature = line.removesuffix(" Nature").strip()
            if nature not in NATURES:
                errors.append(f"no nature is named {nature}")
                nature = "Serious"
        elif line.startswith("-"):
            _add_move(line.removeprefix("-").strip(), move_ids, errors)
    pending_set = PendingSet(
        species_id=species_id,
        ability_id=ability_id,
        item_id=item_id,
        move_ids=move_ids,
        nature=nature,
        sp=sp,
    )
    return ParsedRow(pending_set=pending_set, errors=tuple(errors), notes=tuple(notes))


def _add_move(name: str, move_ids: list[Slug], errors: list[str]) -> None:
    move_id = showdown_id(name)
    moves_max = champions_data().legal.moves_max
    if move_id not in dex().moves:
        errors.append(f"no move is named {name}")
    elif move_id in move_ids:
        errors.append(f"{name} is listed twice")
    elif len(move_ids) == moves_max:
        errors.append(f"a set has at most {moves_max} moves; {name} is left out")
    else:
        move_ids.append(move_id)


def _stat_points(value: str, errors: list[str]) -> list[int]:
    legal = champions_data().legal
    sp = [0] * len(STAT_NAMES)
    for part in value.split("/"):
        amount, _, stat = part.strip().partition(" ")
        if stat not in STAT_NAMES or not amount.isdecimal():
            errors.append(f"cannot read the stat points {part.strip()!r}")
            continue
        sp[STAT_NAMES.index(stat)] = int(amount)
    if max(sp) > legal.sp_max or sum(sp) > legal.sp_total:
        errors.append(
            f"these look like EVs; Champions uses Stat Points 0-{legal.sp_max}, "
            f"{legal.sp_total} in all"
        )
        return [0] * len(STAT_NAMES)
    return sp
