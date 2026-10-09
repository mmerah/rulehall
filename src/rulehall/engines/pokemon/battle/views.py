from typing import Literal

from rulehall.core.validation import Frozen
from rulehall.core.views import Meter, Sprite, Tag

type Pip = Literal["able", "fainted", "reserve"]
type BattleChoiceKind = Literal["move", "mega", "switch", "item", "next", "back", "leave"]


class BattleChoice(Frozen):
    command: str
    kind: BattleChoiceKind
    name: str
    brief: str = ""
    help: str = ""
    group: str = ""
    refusal: str = ""
    tags: tuple[Tag, ...] = ()
    meters: tuple[Meter, ...] = ()
    sprite: Sprite | None = None


class BattleSide(Frozen):
    name: str
    sprite: Sprite
    pips: tuple[Pip, ...]
    said: str = ""


class BattleMon(Frozen):
    name: str
    sprite: Sprite
    hp: Meter
    tags: tuple[Tag, ...] = ()
    deciding: bool = False


class BattleHeader(Frozen):
    player: BattleSide
    ally: BattleSide | None
    foe: BattleSide
    conditions: tuple[Tag, ...]
    fielded: tuple[BattleMon, ...]


class BattleView(Frozen):
    header: BattleHeader
    choices: tuple[BattleChoice, ...]
    background: str
    music: str
