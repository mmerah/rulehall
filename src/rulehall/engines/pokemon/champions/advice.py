from collections import Counter
from collections.abc import Collection, Sequence
from functools import cache

from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Slug
from rulehall.engines.pokemon.champions.args import PickEdit
from rulehall.engines.pokemon.champions.data import Archetype, Role, champions_data, move_shares
from rulehall.engines.pokemon.champions.panels import preset_option, team_option
from rulehall.engines.pokemon.champions.rules import PRESET_LETTERS
from rulehall.engines.pokemon.champions.unsaved import MOVES, UnsavedSet, UnsavedTeam
from rulehall.engines.pokemon.champions.views import Advice
from rulehall.engines.pokemon.dex import Species, dex, species_name
from rulehall.engines.pokemon.rules import effectiveness

ABILITY_IMMUNITIES: dict[Slug, str] = {
    "levitate": "Ground",
    "eartheater": "Ground",
    "flashfire": "Fire",
    "wellbakedbody": "Fire",
    "waterabsorb": "Water",
    "stormdrain": "Water",
    "dryskin": "Water",
    "voltabsorb": "Electric",
    "lightningrod": "Electric",
    "motordrive": "Electric",
    "sapsipper": "Grass",
}
WEAK_SHARE = 0.02
WEAK_MEMBERS = 3
THREATS_SHOWN = 5
ROLE_TIPS = {
    "speed-control": (
        "Nothing on your team controls speed. Tailwind or Icy Wind helps your slower Pokemon "
        "move first."
    ),
    "fake-out": (
        "No one knows Fake Out. It makes a foe flinch on the first turn, so its partner acts "
        "in peace."
    ),
    "intimidate": (
        "No one has Intimidate. It lowers both foes' Attack when its holder comes in, which "
        "blunts physical attackers."
    ),
}


def team_advice(team: UnsavedTeam) -> tuple[Advice, ...]:
    members = [(number, each) for number, each in enumerate(team.slots, 1) if each is not None]
    if not members:
        return (_empty_slots_advice(team),)
    errors = team.team_errors()
    return tuple(
        advice
        for advice in (
            *(
                Advice(advice_id=f"team-error-{number}", severity="error", text=error)
                for number, error in enumerate(errors, 1)
            ),
            *(_role_advice(role_id, members) for role_id in ROLE_TIPS),
            _archetype_advice(members),
            _megas_advice(members),
            *_weakness_advice(members),
            _threats_advice(members),
            *_weak_slot_advice(team, members),
            _empty_slots_advice(team) if len(members) < len(team.slots) else None,
        )
        if advice is not None
    )


def suggested_species(
    team: UnsavedTeam, count: int, *, avoid_ids: Collection[Slug] = ()
) -> tuple[Slug, ...]:
    data = champions_data()
    legal = data.legal
    members = [each.species_id for each in team.slots if each is not None]
    taken = {legal.species[species_id].base_species_id for species_id in (*members, *avoid_ids)}

    def score(candidate_id: Slug) -> tuple[float, float, Slug]:
        together = sum(data.teammates.get(member, {}).get(candidate_id, 0.0) for member in members)
        return (-together, -data.usage[candidate_id].usage_percent, candidate_id)

    suggested: list[Slug] = []
    for candidate_id in sorted((each for each in data.presets if each in data.usage), key=score):
        if len(suggested) == count:
            break
        base_id = legal.species[candidate_id].base_species_id
        if base_id in taken or not team.allows(candidate_id):
            continue
        taken.add(base_id)
        suggested.append(candidate_id)
    return tuple(suggested)


def battle_species(unsaved_set: UnsavedSet) -> Species:
    return dex().species[
        champions_data().legal.find_mega_forme_id(unsaved_set.item_id, unsaved_set.species_id)
        or unsaved_set.species_id
    ]


def primary_archetype(sets: Sequence[UnsavedSet]) -> Archetype:
    archetypes = champions_data().archetypes
    scored = [
        (max(_centrality(holder, sets) for holder in holders), archetype)
        for archetype in archetypes
        if _has_mechanic(archetype) and (holders := _holders(archetype, sets))
    ]
    if not scored:
        return next(each for each in archetypes if not _has_mechanic(each))
    return max(scored, key=lambda each: each[0])[1]


def _role_advice(role_id: Slug, members: Sequence[tuple[int, UnsavedSet]]) -> Advice | None:
    role = champions_data().roles[role_id]
    holders = [each for _, each in members if _fills(role, each)]
    if holders:
        names = ", ".join(species_name(each.species_id) for each in holders)
        return Advice(advice_id=role_id, severity="good", text=f"{role.name}: {names}.")
    return Advice(
        advice_id=f"no-{role_id}",
        severity="warning",
        text=ROLE_TIPS[role_id],
        fix=_teach_fix(role, members),
    )


def _teach_fix(role: Role, members: Sequence[tuple[int, UnsavedSet]]) -> ActionOption | None:
    data = champions_data()
    legal = data.legal
    best: tuple[float, int, UnsavedSet, Slug] | None = None
    for number, member in members:
        learnable = set(role.move_ids) & set(legal.species[member.species_id].move_ids)
        shares = move_shares(member.species_id)
        for move_id in sorted(learnable):
            share = shares.get(move_id, 0.0)
            if best is None or share > best[0]:
                best = (share, number, member, move_id)
    if best is None:
        return None
    _, number, member, move_id = best
    moves = dex().moves
    if len(member.move_ids) < legal.moves_max:
        move_ids = (*member.move_ids, move_id)
        name = f"Teach {moves[move_id].name} to {species_name(member.species_id)}"
    else:
        shares = move_shares(member.species_id)
        dropped_id = min(member.move_ids, key=lambda each: shares.get(each, 0.0))
        move_ids = tuple(move_id if each == dropped_id else each for each in member.move_ids)
        name = (
            f"Replace {moves[dropped_id].name} with {moves[move_id].name} "
            f"on {species_name(member.species_id)}"
        )
    edit = PickEdit(slot=number, field_id=MOVES, choice_ids=move_ids)
    return team_option("pick", edit, name=name)


def _archetype_advice(members: Sequence[tuple[int, UnsavedSet]]) -> Advice:
    sets = [each for _, each in members]
    archetype = primary_archetype(sets)
    if not _has_mechanic(archetype):
        text = f"{archetype.name}: strong Pokemon with no weather, terrain or speed mode."
    else:
        names = ", ".join(species_name(each.species_id) for each in _holders(archetype, sets))
        text = f"{archetype.name} team, set up by {names}."
    return Advice(advice_id="archetype", severity="info", text=text)


def _megas_advice(members: Sequence[tuple[int, UnsavedSet]]) -> Advice | None:
    mega_formes = champions_data().legal.mega_formes
    holders = [each for _, each in members if each.item_id in mega_formes]
    if len(holders) < 2:
        return None
    return Advice(
        advice_id="megas",
        severity="info",
        text=f"{len(holders)} Pokemon hold a Mega Stone. Only one can Mega Evolve in a battle, "
        "so you choose which one each game.",
    )


def _weakness_advice(members: Sequence[tuple[int, UnsavedSet]]) -> list[Advice]:
    advice: list[Advice] = []
    for attack in dex().type_chart:
        factors = [(each, _damage_factor(attack, each)) for _, each in members]
        weak = [each for each, factor in factors if factor > 1]
        if len(weak) < WEAK_MEMBERS or any(factor < 1 for _, factor in factors):
            continue
        names = ", ".join(species_name(each.species_id) for each in weak)
        advice.append(
            Advice(
                advice_id=f"weak-to-{attack.lower()}",
                severity="warning",
                text=f"{len(weak)} of your Pokemon ({names}) take extra damage from {attack} "
                f"moves, and none resists them. Add a Pokemon that resists {attack}.",
            )
        )
    return advice


def _threats_advice(members: Sequence[tuple[int, UnsavedSet]]) -> Advice | None:
    data = champions_data()
    species = data.legal.species
    on_team = {species[each.species_id].base_species_id for _, each in members}
    counts: Counter[Slug] = Counter()
    percents: dict[Slug, float] = {}
    for _, member in members:
        card = data.usage.get(member.species_id)
        for check in () if card is None else card.checks:
            if species[check.species_id].base_species_id in on_team:
                continue
            counts[check.species_id] += 1
            percents[check.species_id] = percents.get(check.species_id, 0.0) + check.percent
    if not counts:
        return None
    ranked = sorted(counts, key=lambda each: (-counts[each], -percents[each], each))
    names = ", ".join(species_name(each) for each in ranked[:THREATS_SHOWN])
    return Advice(
        advice_id="threats",
        severity="info",
        text=f"Pokemon that often beat yours: {names}. Plan an answer to each.",
    )


def _weak_slot_advice(team: UnsavedTeam, members: Sequence[tuple[int, UnsavedSet]]) -> list[Advice]:
    if len(members) < 2:
        return []
    roles = champions_data().roles.values()
    advice: list[Advice] = []
    sets = [each for _, each in members]
    for number, member in members:
        if _centrality(member, sets) >= WEAK_SHARE or any(_fills(role, member) for role in roles):
            continue
        others = team.model_copy(deep=True)
        others.clear_slot(number)
        suggested = suggested_species(others, 1, avoid_ids=(member.species_id,))
        name = species_name(member.species_id)
        fix = None
        if suggested:
            index = others.free_preset_index(number, suggested[0])
            if index is not None:
                fix = preset_option(
                    number,
                    f"{suggested[0]}-{PRESET_LETTERS[index]}",
                    f"Swap {name} for {species_name(suggested[0])}",
                )
        advice.append(
            Advice(
                advice_id=f"weak-slot-{number}",
                severity="info",
                text=f"{name} rarely plays beside the rest of this team and fills no support role.",
                fix=fix,
            )
        )
    return advice


def _empty_slots_advice(team: UnsavedTeam) -> Advice:
    empty = [number for number, each in enumerate(team.slots, 1) if each is None]
    suggested = suggested_species(team, len(empty))
    names = ", ".join(species_name(each) for each in suggested)
    numbers = ", ".join(str(number) for number in empty)
    return Advice(
        advice_id="empty-slots",
        severity="warning",
        text=f"Empty slots: {numbers}. An event needs {len(team.slots)} Pokemon."
        + (f" Common partners for this team: {names}." if names else ""),
        fix=team_option("fill_empty_slots") if suggested else None,
    )


def _damage_factor(attack: str, unsaved_set: UnsavedSet) -> float:
    forme_id = champions_data().legal.find_mega_forme_id(
        unsaved_set.item_id, unsaved_set.species_id
    )
    species = battle_species(unsaved_set)
    ability_ids = (unsaved_set.ability_id,) if forme_id is None else _ability_ids(species)
    if any(each is not None and ABILITY_IMMUNITIES.get(each) == attack for each in ability_ids):
        return 0.0
    return effectiveness(attack, species.types)


def _holders(archetype: Archetype, sets: Sequence[UnsavedSet]) -> list[UnsavedSet]:
    return [
        each
        for each in sets
        if set(archetype.move_ids) & set(each.move_ids)
        or set(archetype.ability_ids) & set(_battle_ability_ids(each))
    ]


def _fills(role: Role, unsaved_set: UnsavedSet) -> bool:
    return bool(
        set(role.move_ids) & set(unsaved_set.move_ids)
        or set(role.ability_ids) & set(_battle_ability_ids(unsaved_set))
    )


def _centrality(holder: UnsavedSet, sets: Sequence[UnsavedSet]) -> float:
    shares = champions_data().teammates.get(holder.species_id, {})
    mates = [each for each in sets if each is not holder]
    return sum(shares.get(each.species_id, 0.0) for each in mates) / len(mates) if mates else 0.0


def _has_mechanic(archetype: Archetype) -> bool:
    return bool(archetype.move_ids or archetype.ability_ids)


def _battle_ability_ids(unsaved_set: UnsavedSet) -> tuple[Slug, ...]:
    own = () if unsaved_set.ability_id is None else (unsaved_set.ability_id,)
    forme_id = champions_data().legal.find_mega_forme_id(
        unsaved_set.item_id, unsaved_set.species_id
    )
    return own if forme_id is None else (*own, *_ability_ids(dex().species[forme_id]))


def _ability_ids(species: Species) -> tuple[Slug, ...]:
    ids = _ability_ids_by_name()
    return tuple(ids[name] for name in species.abilities)


@cache
def _ability_ids_by_name() -> dict[str, Slug]:
    return {name: ability_id for ability_id, name in dex().ability_names.items()}
