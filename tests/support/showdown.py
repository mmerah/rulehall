import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.battle.models import BattleMove, Battler, BattleSetup
from rulehall.engines.pokemon.battle.simulator import DUMPED

FIXTURES = Path(__file__).parents[1] / "pokemon" / "fixtures"
RECORDED = FIXTURES / "battle.txt"
ASSESSED = FIXTURES / "assessment.txt"
type Block = tuple[str, ...]
PIKACHU = Battler(
    mon_id="pikachu",
    species_id="pikachu",
    name="Pikachu",
    level=7,
    nature="Hardy",
    ability="Static",
    gender="M",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    moves=(
        BattleMove(move_id="thundershock", name="Thunder Shock", type="Electric", pp=48),
        BattleMove(move_id="growl", name="Growl", type="Normal", pp=64),
    ),
    hp=24,
)
RATTATA = Battler(
    mon_id="rattata",
    species_id="rattata",
    name="Rattata",
    level=3,
    nature="Hardy",
    ability="Guts",
    gender="F",
    ivs=(31, 31, 31, 31, 31, 31),
    evs=(0, 0, 0, 0, 0, 0),
    friendship=70,
    moves=(BattleMove(move_id="tackle", name="Tackle", type="Normal", pp=56),),
    hp=15,
)
WILD_SETUP = BattleSetup(
    kind="wild",
    foe_id=None,
    player_name="Kael",
    foe_name="Wild Rattata",
    player_avatar_id="ethan",
    foe_avatar_id=None,
    seed=(1, 2, 3, 4),
    team=(PIKACHU,),
    foes=(RATTATA,),
)


@dataclass(slots=True)
class ScriptedSimulator:
    blocks: list[Block]
    sent: list[str] = field(default_factory=list)
    closed: bool = False

    async def send(self, lines: Sequence[str]) -> None:
        self.sent.extend(lines)

    async def receive(self) -> Block:
        if not self.blocks:
            raise Refusal("the scripted simulator has no block left")
        return self.blocks.pop(0)

    async def close(self) -> None:
        self.closed = True


def recorded() -> list[Block]:
    return [tuple(text.split("\n")) for text in RECORDED.read_text().strip().split("\n\n")]


def assessed() -> list[Block]:
    """One eval answer recorded from a 2v2 trainer battle after a turn of Ember and Leech Seed."""
    return [("update", ASSESSED.read_text().strip())]


def started(setup: BattleSetup) -> list[Block]:
    return [_update(setup), *_asks(setup, moving=False)]


def moving(setup: BattleSetup) -> list[Block]:
    return [_update(setup), *_asks(setup, moving=True)]


def ended(setup: BattleSetup, *, foe_hp: int) -> list[Block]:
    return [
        ("update", f"|win|{setup.player_name}", _dumped(setup, out=1, foe_hp=foe_hp)),
        ("end", "{}"),
    ]


def _update(setup: BattleSetup) -> Block:
    return ("update", _dumped(setup))


def _dumped(setup: BattleSetup, *, out: int = 0, foe_hp: int | None = None) -> str:
    team = [
        _dumped_mon(slot, battler, battler.hp, out=out if slot == 0 else 0)
        for slot, battler in enumerate(setup.team)
    ]
    foes = [
        _dumped_mon(slot, battler, battler.hp if foe_hp is None else foe_hp, out=0)
        for slot, battler in enumerate(setup.foes)
    ]
    return f'{DUMPED}{json.dumps({"p1": team, "p2": foes})}"'


def _dumped_mon(slot: int, battler: Battler, hp: int, *, out: int) -> dict[str, object]:
    pp = [move.pp for move in battler.moves]
    return {
        "slot": slot,
        "hp": hp,
        "status": battler.status,
        "pp": pp,
        "out": out,
        "held": True,
    }


def _asks(setup: BattleSetup, *, moving: bool) -> list[Block]:
    return [
        ("sideupdate", side, f"|request|{json.dumps(_request(battlers, moving=moving))}")
        for side, battlers in (("p1", setup.team), ("p2", setup.foes))
    ]


def _request(battlers: Sequence[Battler], *, moving: bool) -> dict[str, object]:
    pokemon = [
        {
            "details": f"{battler.name}, L{battler.level}",
            "condition": f"{battler.hp}/{battler.hp}",
            "active": slot == 0,
        }
        for slot, battler in enumerate(battlers)
    ]
    if not moving:
        return {"teamPreview": True, "side": {"pokemon": pokemon}}
    moves = [
        {"move": move.name, "id": move.move_id, "pp": move.pp, "maxpp": move.pp}
        for move in battlers[0].moves
    ]
    return {"active": [{"moves": moves}], "side": {"pokemon": pokemon}}
