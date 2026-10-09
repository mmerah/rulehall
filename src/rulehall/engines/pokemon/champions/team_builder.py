from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from functools import cache

from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import Surface
from rulehall.engines.pokemon.champions.advice import (
    battle_species,
    speed_hint,
    suggested_species,
    team_advice,
)
from rulehall.engines.pokemon.champions.args import ChoiceEdit, TemplateEdit
from rulehall.engines.pokemon.champions.data import (
    CompetitiveSet,
    Nature,
    UsageCard,
    champions_data,
    move_shares,
)
from rulehall.engines.pokemon.champions.panels import TEAM_TAB, preset_option, team_option
from rulehall.engines.pokemon.champions.paste import parse_paste
from rulehall.engines.pokemon.champions.pending import (
    ABILITY,
    ITEM,
    MOVES,
    NATURE,
    SP,
    SPECIES,
    PendingSet,
    PendingTeam,
    item_refusal,
    unowned_refusal,
)
from rulehall.engines.pokemon.champions.rules import PRESET_LETTERS, require_template
from rulehall.engines.pokemon.champions.views import (
    Catalog,
    CatalogOrder,
    Choice,
    Facet,
    ImportPreview,
    PickField,
    PointRow,
    PointsField,
    TeamBuilderField,
    TeamBuilderSlot,
    TeamBuilderView,
)
from rulehall.engines.pokemon.champions.world import ChampionsWorld
from rulehall.engines.pokemon.dex import NATURES, dex
from rulehall.engines.pokemon.rules import IV_MAX, STAT_NAMES, nature_effect, stats
from rulehall.engines.pokemon.sprites import (
    category_tag,
    mon_sprite,
    nature_tag,
    nature_text,
    type_tag,
)

TEAM_BUILDER_SURFACE_ID: Slug = "pokemon-team"
TITLE = "Team builder"
SPECIES_CATALOG = "species"
ITEMS_CATALOG = "items"
NATURES_CATALOG = "natures"
TEMPLATES_CATALOG = "templates"
SLOT_CATALOGS = frozenset((SPECIES_CATALOG, ITEMS_CATALOG))
ABILITIES_PREFIX = "abilities-"
MOVES_PREFIX = "moves-"
USAGE_PREFIX = "usage-"
CLEAR = "clear"
COMMON_SPECIES = 1.0
COMMON_MOVE = 5.0
PINNED = 3
SUGGESTED = 6
QUICK_USAGE = 5
SPREAD_TARGETS = frozenset(("allAdjacentFoes", "allAdjacent"))
SPREAD_SHAPES: dict[Slug, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "max-atk-spe": ("Max Atk + Spe", ("Atk", "Spe"), ("HP",)),
    "max-spa-spe": ("Max SpA + Spe", ("SpA", "Spe"), ("HP",)),
    "max-hp-atk": ("Max HP + Atk", ("HP", "Atk"), ("SpD",)),
    "bulky": ("Bulky (HP/Def/SpD)", ("HP",), ("Def", "SpD")),
    "trick-room": ("Trick Room (HP + Atk, 0 Spe)", ("HP", "Atk"), ("Def",)),
}


def team_builder_surface(world: ChampionsWorld, *, live: bool) -> Surface:
    view = team_builder_view(world) if live else None
    return Surface(surface_id=TEAM_BUILDER_SURFACE_ID, live=live, tab=TEAM_TAB, view=view)


def team_builder_view(world: ChampionsWorld) -> TeamBuilderView:
    shown = world.shown_team()
    saved = PendingTeam.of_team(world.player_sheet.team)
    allowed_species_ids = world.player_sheet.allowed_species_ids
    return TeamBuilderView(
        title=TITLE,
        slots=tuple(
            _roster_slot(shown, number, allowed_species_ids, edited=each != saved.slots[number - 1])
            for number, each in enumerate(shown.slots, 1)
        ),
        advice=team_advice(shown.slots, allowed_species_ids),
        dirty=world.pending_team_dirty(),
        locked_reason=world.pending_team_lock(),
        save_lock=world.team_lock(),
        copyable=not world.copy_lock(),
        pending_team_open=world.pending_team is not None and not world.season_over(),
    )


def team_builder_catalog(world: ChampionsWorld, slot: int, catalog_id: Slug) -> Catalog:
    team = world.shown_team()
    allowed_species_ids = world.player_sheet.allowed_species_ids
    if catalog_id == SPECIES_CATALOG:
        return _species_catalog(
            _species_refusal(team, slot, allowed_species_ids), allowed_species_ids
        )
    if catalog_id == ITEMS_CATALOG:
        species_id = team.require_set(slot).species_id
        return _refused(_items_catalog(species_id), _item_refusal(team, slot, species_id))
    if catalog_id == NATURES_CATALOG:
        return _natures_catalog()
    if catalog_id == TEMPLATES_CATALOG:
        return _templates_catalog(allowed_species_ids)
    if catalog_id.startswith(ABILITIES_PREFIX):
        return _abilities_catalog(_catalog_species(catalog_id, ABILITIES_PREFIX))
    if catalog_id.startswith(MOVES_PREFIX):
        return _moves_catalog(_catalog_species(catalog_id, MOVES_PREFIX))
    raise Refusal(f"{catalog_id!r} is no catalog of the team builder")


def import_preview(world: ChampionsWorld, text: str) -> ImportPreview:
    rows = parse_paste(text)
    sets = [row.pending_set for row in rows]
    allowed_species_ids = world.player_sheet.allowed_species_ids
    size = champions_data().legal.team_size
    team = PendingTeam(slots=[*sets, *[None] * (size - len(sets))])
    unowned = unowned_refusal((each.species_id for each in sets if each), allowed_species_ids)
    previews = tuple(
        _roster_slot(team, number, allowed_species_ids, edited=False, parsed=row.errors)
        for number, row in enumerate(rows, 1)
    )
    notes = dict.fromkeys(note for row in rows for note in row.notes)
    return ImportPreview(
        rows=previews,
        notes=(*notes, *((unowned,) if unowned else ())),
        importable=not unowned and any(sets),
    )


def quick_spread(pending_set: PendingSet, choice_id: Slug) -> tuple[Nature, tuple[int, ...]]:
    if choice_id == CLEAR:
        return pending_set.nature, (0,) * len(STAT_NAMES)
    if choice_id in SPREAD_SHAPES:
        return pending_set.nature, _shape_points(choice_id)
    spreads = (
        _usage_card(pending_set.species_id).spreads if choice_id.startswith(USAGE_PREFIX) else ()
    )
    number = choice_id.removeprefix(USAGE_PREFIX)
    if not (number.isdecimal() and 1 <= int(number) <= min(len(spreads), QUICK_USAGE)):
        raise Refusal(f"{choice_id!r} is no quick spread of {pending_set.species_id}")
    spread = spreads[int(number) - 1]
    return spread.nature, spread.sp


def _roster_slot(
    team: PendingTeam,
    number: int,
    allowed_species_ids: Collection[Slug] | None,
    *,
    edited: bool,
    parsed: Sequence[str] = (),
) -> TeamBuilderSlot:
    pending_set = team.find_set(number)
    if pending_set is None:
        suggested = suggested_species(team.slots, SUGGESTED, allowed_species_ids)
        species = _species_choices()
        field = PickField(
            field_id=SPECIES,
            label="Pokemon",
            catalog_id=SPECIES_CATALOG,
            picked=(),
            pinned=_with_refusals(
                (species[species_id] for species_id in suggested),
                _species_refusal(team, number, allowed_species_ids),
            ),
        )
        return TeamBuilderSlot(
            name="Empty",
            sprite=None,
            tags=(),
            brief="",
            filled=False,
            edited=edited,
            error="; ".join(parsed),
            fields=(field,),
        )
    pokedex = dex()
    species = pokedex.species[pending_set.species_id]
    errors = team.field_errors(number)
    return TeamBuilderSlot(
        name=species.name,
        sprite=mon_sprite(species),
        tags=tuple(type_tag(kind) for kind in species.types),
        brief=" · ".join(pokedex.moves[move_id].name for move_id in pending_set.move_ids),
        filled=True,
        edited=edited,
        error="; ".join((*parsed, *errors.values())),
        fields=_fields(team, pending_set, number, errors),
        presets=tuple(
            choice.model_copy(
                update={"option": preset_option(number, choice.choice_id, choice.name)}
            )
            for choice in _preset_choices(pending_set.species_id)
        ),
    )


def _fields(
    team: PendingTeam, pending_set: PendingSet, number: int, errors: Mapping[Slug, str]
) -> tuple[TeamBuilderField, ...]:
    species_id = pending_set.species_id
    items = _item_choices(species_id)
    moves = _move_choices(species_id)
    card = champions_data().usage.get(species_id)
    common_items = () if card is None else card.items
    common_moves = () if card is None else card.moves
    return (
        PickField(
            field_id=SPECIES,
            label="Pokemon",
            catalog_id=SPECIES_CATALOG,
            picked=(_species_choices()[species_id],),
            error=errors.get(SPECIES, ""),
        ),
        PickField(
            field_id=ABILITY,
            label="Ability",
            catalog_id=f"{ABILITIES_PREFIX}{species_id}",
            picked=_picked(_ability_choices(species_id), (pending_set.ability_id,)),
            error=errors.get(ABILITY, ""),
        ),
        PickField(
            field_id=ITEM,
            label="Item",
            catalog_id=ITEMS_CATALOG,
            picked=_picked(items, (pending_set.item_id,)),
            pinned=_with_refusals(
                _picked(items, (each.item_id for each in common_items[:PINNED])),
                _item_refusal(team, number, species_id),
            ),
            error=errors.get(ITEM, ""),
        ),
        PickField(
            field_id=NATURE,
            label="Nature",
            catalog_id=NATURES_CATALOG,
            picked=(_nature_choices()[pending_set.nature.lower()],),
        ),
        PickField(
            field_id=MOVES,
            label="Moves",
            catalog_id=f"{MOVES_PREFIX}{species_id}",
            picked=_picked(moves, pending_set.move_ids),
            picks=champions_data().legal.moves_max,
            pinned=_picked(moves, (each.move_id for each in common_moves[:PINNED])),
            error=errors.get(MOVES, ""),
        ),
        _points_field(pending_set, number, errors.get(SP, "")),
    )


def _points_field(pending_set: PendingSet, number: int, error: str) -> PointsField:
    legal = champions_data().legal
    species = battle_species(pending_set)
    ivs = (IV_MAX,) * len(STAT_NAMES)
    finals = stats(
        species, legal.level, pending_set.nature, ivs, tuple(pending_set.sp), stat_points=True
    )
    raised, lowered = nature_effect(pending_set.nature) or (None, None)
    speed = STAT_NAMES.index("Spe")
    rows = tuple(
        PointRow(
            name=name,
            points=pending_set.sp[index],
            final=finals[index],
            mark="raised" if index == raised else "lowered" if index == lowered else None,
            hint=speed_hint(pending_set) if index == speed else "",
        )
        for index, name in enumerate(STAT_NAMES)
    )
    return PointsField(
        field_id=SP,
        label="Stat Points",
        rows=rows,
        row_max=legal.sp_max,
        budget=legal.sp_total,
        quick=tuple(
            choice.model_copy(
                update={
                    "option": team_option(
                        "apply_quick",
                        ChoiceEdit(slot=number, field_id=SP, choice_id=choice.choice_id),
                        name=choice.name,
                        option_id=f"apply-quick-{number}-{choice.choice_id}",
                    )
                }
            )
            for choice in _quick_choices(pending_set.species_id)
        ),
        error=error,
    )


def _picked(
    choices: Mapping[Slug, Choice], choice_ids: Iterable[Slug | None]
) -> tuple[Choice, ...]:
    return tuple(choices[each] for each in choice_ids if each is not None and each in choices)


def _refused(catalog: Catalog, refusal: Callable[[Slug], str]) -> Catalog:
    return catalog.model_copy(update={"choices": _with_refusals(catalog.choices, refusal)})


def _with_refusals(choices: Iterable[Choice], refusal: Callable[[Slug], str]) -> tuple[Choice, ...]:
    return tuple(
        choice.model_copy(update={"refusal": refusal(choice.choice_id)}) for choice in choices
    )


def _species_refusal(
    team: PendingTeam, slot: int, allowed_species_ids: Collection[Slug] | None
) -> Callable[[Slug], str]:
    return lambda species_id: team.species_refusal(slot, species_id, allowed_species_ids)


def _item_refusal(team: PendingTeam, slot: int, species_id: Slug) -> Callable[[Slug], str]:
    return lambda item_id: item_refusal(species_id, item_id) or team.item_clash(slot, item_id)


def _species_catalog(
    refusal: Callable[[Slug], str], allowed_species_ids: Collection[Slug] | None
) -> Catalog:
    owned = () if allowed_species_ids is None else ("owned",)
    choices = tuple(
        choice.model_copy(
            update={
                "refusal": refusal(choice.choice_id),
                "facets": (
                    *choice.facets,
                    *(
                        (Facet(name="owned", value="yes"),)
                        if allowed_species_ids is not None
                        and choice.choice_id in allowed_species_ids
                        else ()
                    ),
                ),
            }
        )
        for choice in _species_choices().values()
    )
    return Catalog(
        catalog_id=SPECIES_CATALOG,
        title="Choose a Pokemon",
        choices=choices,
        facets=("type", "mega", "common", *owned),
        orders=_species_orders(),
    )


@cache
def _species_choices() -> Mapping[Slug, Choice]:
    data = champions_data()
    pokedex = dex()
    holders = {holder for formes in data.legal.mega_formes.values() for holder in formes}
    choices: dict[Slug, Choice] = {}
    for species_id, legal in data.legal.species.items():
        species = pokedex.species[species_id]
        usage = _usage_percent(species_id)
        abilities = " / ".join(pokedex.ability_names[each] for each in legal.ability_ids)
        stats_text = f"BST {sum(species.base_stats)} · Spe {species.base_stats[-1]}"
        choices[species_id] = Choice(
            choice_id=species_id,
            name=species.name,
            brief=f"{stats_text} · {abilities}",
            sprites=(mon_sprite(species),),
            tags=tuple(type_tag(kind) for kind in species.types),
            badge=f"{usage:g}%" if usage else "",
            search_text=" ".join((species.name, *species.types)),
            facets=(
                *(Facet(name="type", value=kind) for kind in species.types),
                *((Facet(name="mega", value="yes"),) if species_id in holders else ()),
                *((Facet(name="common", value="yes"),) if usage >= COMMON_SPECIES else ()),
            ),
        )
    return choices


@cache
def _species_orders() -> tuple[CatalogOrder, ...]:
    species = dex().species
    ids = tuple(_species_choices())
    return (
        CatalogOrder(name="Usage", choice_ids=_ordered(ids, lambda each: -_usage_percent(each))),
        CatalogOrder(name="Name", choice_ids=_ordered(ids, lambda each: species[each].name)),
        CatalogOrder(
            name="Spe", choice_ids=_ordered(ids, lambda each: -species[each].base_stats[-1])
        ),
        CatalogOrder(
            name="BST", choice_ids=_ordered(ids, lambda each: -sum(species[each].base_stats))
        ),
    )


@cache
def _items_catalog(species_id: Slug) -> Catalog:
    choices = _item_choices(species_id)
    ids = tuple(choices)
    shares = _item_shares(species_id)
    return Catalog(
        catalog_id=ITEMS_CATALOG,
        title="Choose an item",
        choices=tuple(choices.values()),
        facets=(),
        orders=(
            CatalogOrder(name="Usage", choice_ids=_ordered(ids, lambda each: -shares.get(each, 0))),
            CatalogOrder(name="Name", choice_ids=_ordered(ids, lambda each: choices[each].name)),
        ),
    )


@cache
def _item_choices(species_id: Slug) -> Mapping[Slug, Choice]:
    data = champions_data()
    pokedex = dex()
    shares = _item_shares(species_id)
    choices: dict[Slug, Choice] = {}
    for item_id in data.legal.item_ids:
        name = pokedex.item_names[item_id]
        choices[item_id] = Choice(
            choice_id=item_id,
            name=name,
            help=pokedex.item_text(item_id),
            badge=_badge(shares.get(item_id, 0)),
            group=_item_group(item_id, name),
            search_text=name,
        )
    return choices


@cache
def _abilities_catalog(species_id: Slug) -> Catalog:
    return Catalog(
        catalog_id=f"{ABILITIES_PREFIX}{species_id}",
        title="Choose an ability",
        choices=tuple(_ability_choices(species_id).values()),
        facets=(),
        orders=(),
    )


@cache
def _ability_choices(species_id: Slug) -> Mapping[Slug, Choice]:
    data = champions_data()
    pokedex = dex()
    card = data.usage.get(species_id)
    shares = {each.ability_id: each.percent for each in (() if card is None else card.abilities)}
    choices: dict[Slug, Choice] = {}
    for ability_id in data.legal.species[species_id].ability_ids:
        name = pokedex.ability_names[ability_id]
        choices[ability_id] = Choice(
            choice_id=ability_id,
            name=name,
            help=pokedex.abilities.get(name, ""),
            badge=_badge(shares.get(ability_id, 0)),
            search_text=name,
        )
    return choices


@cache
def _moves_catalog(species_id: Slug) -> Catalog:
    choices = _move_choices(species_id)
    moves = dex().moves
    ids = tuple(choices)
    shares = move_shares(species_id)
    return Catalog(
        catalog_id=f"{MOVES_PREFIX}{species_id}",
        title="Choose moves",
        choices=tuple(choices.values()),
        facets=("type", "category", "common", "spread"),
        orders=(
            CatalogOrder(name="Usage", choice_ids=_ordered(ids, lambda each: -shares.get(each, 0))),
            CatalogOrder(name="Power", choice_ids=_ordered(ids, lambda each: -moves[each].power)),
            CatalogOrder(name="Name", choice_ids=_ordered(ids, lambda each: moves[each].name)),
        ),
    )


@cache
def _move_choices(species_id: Slug) -> Mapping[Slug, Choice]:
    data = champions_data()
    moves = dex().moves
    shares = move_shares(species_id)
    choices: dict[Slug, Choice] = {}
    for move_id in data.legal.species[species_id].move_ids:
        move = moves[move_id]
        share = shares.get(move_id, 0)
        accuracy = "sure hit" if move.accuracy is None else f"{move.accuracy}%"
        power = (f"{move.power} BP",) if move.power else ()
        choices[move_id] = Choice(
            choice_id=move_id,
            name=move.name,
            brief=" · ".join((*power, accuracy, f"{move.pp} PP")),
            help=move.text,
            tags=(type_tag(move.type), category_tag(move.category)),
            badge=_badge(share),
            search_text=f"{move.name} {move.text}",
            facets=(
                Facet(name="type", value=move.type),
                Facet(name="category", value=move.category),
                *((Facet(name="common", value="yes"),) if share >= COMMON_MOVE else ()),
                *((Facet(name="spread", value="yes"),) if move.target in SPREAD_TARGETS else ()),
            ),
        )
    return choices


@cache
def _natures_catalog() -> Catalog:
    return Catalog(
        catalog_id=NATURES_CATALOG,
        title="Choose a nature",
        choices=tuple(_nature_choices().values()),
        facets=(),
        orders=(),
        columns=5,
    )


@cache
def _nature_choices() -> Mapping[Slug, Choice]:
    return {
        nature.lower(): Choice(
            choice_id=nature.lower(),
            name=nature,
            brief=nature_text(nature),
            tags=(nature_tag(nature),),
            search_text=nature,
        )
        for nature in NATURES
    }


def _templates_catalog(allowed_species_ids: Collection[Slug] | None) -> Catalog:
    choices = _template_choices()
    if allowed_species_ids is not None:
        choices = tuple(
            choice.model_copy(
                update={
                    "refusal": (
                        refusal := unowned_refusal(
                            (each.species_id for each in require_template(choice.choice_id)),
                            allowed_species_ids,
                        )
                    ),
                    "facets": (
                        *choice.facets,
                        *(() if refusal else (Facet(name="owned", value="yes"),)),
                    ),
                }
            )
            for choice in choices
        )
    return Catalog(
        catalog_id=TEMPLATES_CATALOG,
        title="Start from a team",
        choices=choices,
        facets=(
            "archetype",
            "pool",
            "species",
            *(() if allowed_species_ids is None else ("owned",)),
        ),
        orders=(CatalogOrder(name="Placing", choice_ids=tuple(c.choice_id for c in choices)),),
    )


@cache
def _template_choices() -> tuple[Choice, ...]:
    data = champions_data()
    names = {each.archetype_id: each.name for each in data.archetypes}
    archetypes = (
        _template_choice(
            each.archetype_id,
            each.name,
            "Archetype team",
            each.team.sets,
            (each.archetype_id,),
            "archetype",
            names,
        )
        for each in data.archetypes
    )
    teams = sorted(
        data.real_teams, key=lambda team: (team.placing, -int(team.date.replace("-", "")))
    )
    real_teams = (
        _template_choice(
            team.team_id,
            team.label,
            f"{team.placing}/{team.players} · {team.credit}",
            team.sets,
            team.archetype_ids,
            team.pool,
            names,
        )
        for team in teams
    )
    return (*archetypes, *real_teams)


def _template_choice(
    choice_id: Slug,
    name: str,
    brief: str,
    sets: Sequence[CompetitiveSet],
    archetype_ids: Sequence[Slug],
    pool: str,
    archetype_names: Mapping[Slug, str],
) -> Choice:
    species = dex().species
    members = [species[each.species_id] for each in sets]
    return Choice(
        choice_id=choice_id,
        name=name,
        brief=brief,
        option=team_option(
            "load_template",
            TemplateEdit(template_id=choice_id),
            name=f"Start from {name}",
            option_id=f"load-template-{choice_id}",
        ),
        sprites=tuple(mon_sprite(each) for each in members),
        search_text=" ".join((name, *(each.name for each in members))),
        facets=(
            *(Facet(name="archetype", value=archetype_names[each]) for each in archetype_ids),
            Facet(name="pool", value=pool),
            *(Facet(name="species", value=each.name) for each in members),
        ),
    )


@cache
def _preset_choices(species_id: Slug) -> tuple[Choice, ...]:
    pokedex = dex()
    return tuple(
        Choice(
            choice_id=f"{species_id}-{letter}",
            name=f"Preset {letter.upper()}",
            brief=" · ".join(
                (
                    pokedex.item_names[preset.item_id],
                    pokedex.ability_names[preset.ability_id],
                    preset.nature,
                )
            ),
            help=", ".join(pokedex.moves[move_id].name for move_id in preset.move_ids),
        )
        for letter, preset in zip(
            PRESET_LETTERS, champions_data().presets.get(species_id, ()), strict=False
        )
    )


@cache
def _quick_choices(species_id: Slug) -> tuple[Choice, ...]:
    card = champions_data().usage.get(species_id)
    spreads = () if card is None else card.spreads[:QUICK_USAGE]
    usage = (
        Choice(
            choice_id=f"{USAGE_PREFIX}{number}",
            name=f"{spread.percent:g}% · {spread.nature} {'/'.join(map(str, spread.sp))}",
        )
        for number, spread in enumerate(spreads, 1)
    )
    shapes = (
        Choice(choice_id=shape_id, name=name, brief="/".join(map(str, _shape_points(shape_id))))
        for shape_id, (name, _, _) in SPREAD_SHAPES.items()
    )
    return (*usage, *shapes, Choice(choice_id=CLEAR, name="Clear"))


def _shape_points(shape_id: Slug) -> tuple[int, ...]:
    legal = champions_data().legal
    _, maxed, leftover = SPREAD_SHAPES[shape_id]
    spare, extra = divmod(legal.sp_total - legal.sp_max * len(maxed), len(leftover))
    shares = {name: spare + (index < extra) for index, name in enumerate(leftover)}
    return tuple(legal.sp_max if name in maxed else shares.get(name, 0) for name in STAT_NAMES)


def _catalog_species(catalog_id: Slug, prefix: str) -> Slug:
    species_id = catalog_id.removeprefix(prefix)
    _ = champions_data().legal.require_species(species_id)
    return species_id


def _usage_card(species_id: Slug) -> UsageCard:
    return champions_data().usage[species_id]


def _usage_percent(species_id: Slug) -> float:
    card = champions_data().usage.get(species_id)
    return 0.0 if card is None else card.usage_percent


def _item_shares(species_id: Slug) -> dict[Slug, float]:
    card = champions_data().usage.get(species_id)
    return {} if card is None else {each.item_id: each.percent for each in card.items}


def _badge(percent: float) -> str:
    return f"{percent:g}%" if percent else ""


def _item_group(item_id: Slug, name: str) -> str:
    if item_id in champions_data().legal.mega_formes:
        return "Mega Stones"
    if name.endswith("Berry"):
        return "Berries"
    return "Choice" if name.startswith("Choice") else "Other"


def _ordered(ids: Sequence[Slug], key: Callable[[Slug], float | str]) -> tuple[Slug, ...]:
    return tuple(sorted(ids, key=key))
