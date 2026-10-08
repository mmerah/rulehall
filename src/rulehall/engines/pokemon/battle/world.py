from random import Random
from typing import Protocol

from rulehall.core.facts import Fact
from rulehall.core.validation import Slug
from rulehall.engines.engine import Resolution
from rulehall.engines.pokemon.battle.models import Battle, Battler, BattleResult, Throw

BATTLE_OVER = (
    "The battle is over. Tell how it ended from WHAT HAPPENED, in a few sentences. The player "
    "watched every move, so do not tell the fight again; you may give one short nod to a "
    "highlight. Settle nothing else."
)


class BattleWorld(Protocol):
    battle: Battle | None

    def player_card_fact(self, line: str, /) -> Fact: ...
    def throw_ball(self, ball_id: Slug, foe: Battler, rng: Random, /) -> Throw: ...
    def settle_battle(self, result: BattleResult, /) -> tuple[Resolution, list[str]]: ...


class BattleGame(Protocol):
    @property
    def world(self) -> BattleWorld: ...
    def note(self, text: str, /) -> None: ...
