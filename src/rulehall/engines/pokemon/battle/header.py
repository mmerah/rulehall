from collections.abc import Mapping, Sequence

from rulehall.core.views import BattleHeader, BattleSide, Tag
from rulehall.engines.pokemon.battle.models import (
    TERRAINS,
    WEATHERS,
    BattleSetup,
    DumpMon,
    FieldCondition,
)
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.panels import TYPE_COLOURS, mon_sprite, trainer_sprite


def battle_header(
    setup: BattleSetup, p1: Sequence[DumpMon], p2: Sequence[DumpMon], log: Sequence[str]
) -> BattleHeader:
    weather, terrain = setup.weather, setup.terrain
    # A line shows through the turn after the one it was said in, then expires.
    said: dict[str, str] = {}
    said_before: dict[str, str] = {}
    for line in log:
        _, kind, *fields = line.split("|", 3)
        match kind:
            case "turn":
                said_before, said = said, {}
            case "c":
                said[fields[0]] = fields[1]
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
    )


def _chip(name: str, condition: FieldCondition) -> Tag:
    return Tag(name=name, colour=TYPE_COLOURS[condition.colour_type], help=condition.text)


def _field_id[K: str](text: str, table: Mapping[K, FieldCondition]) -> K | None:
    shown = text.removeprefix("move: ").replace(" ", "").lower()
    return next((key for key, condition in table.items() if condition.showdown_id == shown), None)
