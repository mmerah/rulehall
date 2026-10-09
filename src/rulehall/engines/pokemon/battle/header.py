from collections.abc import Mapping, Sequence

from rulehall.core.views import Tag
from rulehall.engines.pokemon.battle.models import (
    TERRAINS,
    WEATHERS,
    Battler,
    BattleSetup,
    DumpMon,
    FieldCondition,
    FormatSpec,
)
from rulehall.engines.pokemon.battle.views import BattleHeader, BattleMon, BattleSide
from rulehall.engines.pokemon.dex import dex, showdown_id
from rulehall.engines.pokemon.rules import max_hp
from rulehall.engines.pokemon.sprites import (
    MEGA_COLOUR,
    STATUS_COLOURS,
    TYPE_COLOURS,
    hp_meter,
    mon_sprite,
    status_tag,
    trainer_sprite,
)

BOOST_NAMES = {
    "atk": "Atk",
    "def": "Def",
    "spa": "SpA",
    "spd": "SpD",
    "spe": "Spe",
    "accuracy": "Acc",
    "evasion": "Eva",
}
BOOST_UP, BOOST_DOWN = "#3f9f5a", "#c0504a"


def battle_header(
    setup: BattleSetup,
    p1: Sequence[DumpMon],
    p2: Sequence[DumpMon],
    log: Sequence[str],
    deciding_slot: int | None,
) -> BattleHeader:
    weather, terrain = setup.weather, setup.terrain
    # A line shows through the turn after the one it was said in, then expires.
    said: dict[str, str] = {}
    said_before: dict[str, str] = {}
    # A Mega Evolution lasts the whole battle: each player-side name keeps its stone and forme.
    formes: dict[str, str] = {}
    megas: dict[str, tuple[str, str]] = {}
    for line in log:
        _, kind, *fields = line.split("|", 3)
        match kind:
            case "turn":
                said_before, said = said, {}
            case "c":
                said[fields[0]] = fields[1]
            case "detailschange" if fields[0].startswith("p1"):
                forme = fields[1].partition(",")[0]
                formes[fields[0].partition(": ")[2]] = showdown_id(forme)
            case "-mega" if fields[0].startswith("p1"):
                name = fields[0].partition(": ")[2]
                megas[name] = (fields[1].rpartition("|")[2], formes.get(name, ""))
            case "-weather":
                weather = _field_id(fields[0], WEATHERS)
            case "-fieldstart" | "-fieldend" if found := _field_id(fields[0], TERRAINS):
                terrain = found if kind == "-fieldstart" else None
            case _:
                pass
    said = said_before | said
    player_side = sorted(p1, key=lambda mon: mon.slot)
    allied = len(setup.team)
    ally = setup.ally
    return BattleHeader(
        player=BattleSide(
            name=setup.player_name,
            sprite=trainer_sprite(setup.player_avatar_id),
            pips=tuple(mon.pip for mon in player_side[:allied]),
        ),
        ally=None
        if ally is None
        else BattleSide(
            name=ally.name,
            sprite=trainer_sprite(ally.avatar_id),
            pips=tuple(mon.pip for mon in player_side[allied:]),
            said=said.get(ally.name, ""),
        ),
        foe=BattleSide(
            name=setup.foe_name,
            sprite=mon_sprite(dex().species[setup.foes[0].species_id])
            if setup.foe_avatar_id is None
            else trainer_sprite(setup.foe_avatar_id),
            pips=tuple(mon.pip for mon in sorted(p2, key=lambda mon: mon.slot)),
            said=said.get(setup.foe_name, ""),
        ),
        conditions=(
            *(() if weather is None else (_chip(weather, WEATHERS[weather]),)),
            *(() if terrain is None else (_chip(f"{terrain} terrain", TERRAINS[terrain]),)),
        ),
        fielded=tuple(
            _fielded(
                setup.player_side()[mon.slot],
                mon,
                setup.format_spec(),
                megas,
                deciding=position == deciding_slot,
            )
            for position, mon in enumerate(p1)
            if mon.active and mon.hp
        ),
    )


def _fielded(
    battler: Battler,
    dumped: DumpMon,
    spec: FormatSpec,
    megas: Mapping[str, tuple[str, str]],
    *,
    deciding: bool,
) -> BattleMon:
    species = dex().species
    stone, forme_id = megas.get(battler.name, ("", ""))
    return BattleMon(
        name=battler.name,
        sprite=mon_sprite(species.get(forme_id) or species[battler.species_id]),
        hp=hp_meter(dumped.hp, max_hp(battler, stat_points=spec.stat_points)),
        tags=(
            Tag(name=f"Lv{battler.level}"),
            *(
                (Tag(name="Mega", colour=MEGA_COLOUR, help=f"Mega Evolved with {stone}"),)
                if stone
                else ()
            ),
            *((status_tag(dumped.status),) if dumped.status in STATUS_COLOURS else ()),
            *(
                Tag(
                    name=f"{BOOST_NAMES[stat]} {stage:+}",
                    colour=BOOST_UP if stage > 0 else BOOST_DOWN,
                )
                for stat, stage in dumped.boosts.items()
                if stage and stat in BOOST_NAMES
            ),
        ),
        deciding=deciding,
    )


def _chip(name: str, condition: FieldCondition) -> Tag:
    return Tag(name=name, colour=TYPE_COLOURS[condition.colour_type], help=condition.text)


def _field_id[K: str](text: str, table: Mapping[K, FieldCondition]) -> K | None:
    shown = text.removeprefix("move: ").replace(" ", "").lower()
    return next((key for key, condition in table.items() if condition.showdown_id == shown), None)
