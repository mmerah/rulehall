import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from random import Random
from typing import Self

from rulehall.core.facts import Fact, Resolution
from rulehall.core.game import RoleAnswer
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.battles import BattleServices
from rulehall.engines.lite5e.battle import views
from rulehall.engines.lite5e.battle.actions import take_action
from rulehall.engines.lite5e.battle.aftermath import fight_over, require_fight, settle_battle
from rulehall.engines.lite5e.battle.foes import bonus_plans_of, plans_of, scripted_plan
from rulehall.engines.lite5e.battle.opponent import (
    FoeOffer,
    OpponentAnswer,
    check_commands,
    render_opponent,
)
from rulehall.engines.lite5e.battle.state import Battle, Fight, FoeCombatant
from rulehall.engines.lite5e.battle.turns import (
    BattleEnd,
    battle_end,
    end_turn,
    move,
    plan,
    play_next,
    surrender,
    toggle_auto,
)
from rulehall.engines.lite5e.battle.views import (
    Lite5eBattleView,
    battle_view,
    require_aim,
)
from rulehall.engines.lite5e.world import Lite5eGame

LOGGER = logging.getLogger(__name__)
BATTLE_SCREEN_ID: Slug = "lite5e-battle"


@dataclass(slots=True, kw_only=True)
class Lite5eRun:
    opponent: RoleAnswer | None = None
    resolution: Resolution | None = None
    thinking: bool = False
    picks: list[str] = field(default_factory=list)
    aiming: str = ""
    settled: Battle | None = None

    @classmethod
    def start(cls, draft: Lite5eGame, opponent: RoleAnswer | None) -> Self:
        run = cls(opponent=opponent)
        fight = require_fight(draft.world, Random())
        end = battle_end(fight)
        if end is not None:
            run._settle(draft, fight, end, ())
        return run

    def view(self, state: Lite5eGame, /) -> Lite5eBattleView:
        live = state.world.battle is not None
        return battle_view(
            self._reading_fight(state),
            live=live,
            thinking=self.thinking,
            aiming=self.aiming if live else "",
            picks=self.picks,
        )

    def log(self, state: Lite5eGame, /) -> Sequence[str]:
        return self._battle(state).log()

    def facts(self, state: Lite5eGame, /) -> Sequence[Fact]:
        return self._battle(state).facts

    def require_command(self, state: Lite5eGame, command: str, /) -> None:
        if not self.view(state).offers(command):
            raise Refusal(f"{command!r} is not a choice now")

    async def choose(self, draft: Lite5eGame, command: str, rng: Random) -> None:
        fight = require_fight(draft.world, rng)
        seen = len(fight.battle.facts)
        word, _, rest = command.partition(" ")
        end: BattleEnd | None = None
        match word:
            case views.MOVE:
                _ = move(fight)
            case views.ACT | views.BONUS:
                self.aiming, self.picks = command, []
                self._fire_when_aimed(fight)
            case views.TARGET | views.DONE | views.SLOT:
                self.picks.append(command)
                self._fire_when_aimed(fight)
            case views.BACK:
                if self.picks:
                    _ = self.picks.pop()
                else:
                    self.aiming = ""
            case views.PLAN:
                _ = plan(fight, rest)
            case views.END:
                _ = end_turn(fight)
            case views.NEXT:
                _ = await play_next(fight, self._plan_foes)
            case views.AUTO:
                _ = toggle_auto(fight, rest)
            case views.SURRENDER:
                end = surrender(fight)
            case _:
                raise ValueError(f"unknown battle command {command!r}")
        end = end or battle_end(fight)
        if end is not None:
            self._settle(draft, fight, end, fight.battle.facts[seen:])

    async def close(self) -> None:
        self.thinking = False

    def _fire_when_aimed(self, fight: Fight) -> None:
        aim = require_aim(fight, self.aiming)
        if not aim.is_ready(self.picks):
            return
        picks, self.aiming, self.picks = self.picks, "", []
        _ = take_action(fight, aim, picks)

    async def _plan_foes(self, fight: Fight, foes: Sequence[FoeCombatant]) -> dict[Slug, str]:
        role = self.opponent
        offers = tuple(
            FoeOffer(
                combatant_id=foe.combatant_id,
                name=foe.name,
                plans=tuple(plan.text for plan in plans_of(fight, foe)),
                bonus_plans=tuple(plan.text for plan in bonus_plans_of(fight, foe)),
            )
            for foe in foes
        )
        if role is None or all(len(o.plans) == 1 and not o.bonus_plans for o in offers):
            return _scripted_plans(fight, foes)
        self.thinking = True
        try:
            answer = await role(
                render_opponent(fight, offers), OpponentAnswer, partial(check_commands, offers)
            )
        except Refusal as refused:
            LOGGER.warning("the foes play the scripted plans: %s", refused)
            return _scripted_plans(fight, foes)
        finally:
            self.thinking = False
        if answer.line:
            speaker = offers[0].name
            said = Fact(trace=f"{speaker} says: {answer.line}", card=f'{speaker}: "{answer.line}"')
            fight.battle.facts.append(said)
        return {
            offer.combatant_id: command
            for offer, command in zip(offers, answer.commands, strict=True)
        }

    def _settle(
        self, draft: Lite5eGame, fight: Fight, end: BattleEnd, unseen: Sequence[Fact]
    ) -> None:
        self.settled = fight.battle
        self.aiming, self.picks = "", []
        settled, notes = settle_battle(draft.world, end, fight.rng)
        for note in notes:
            draft.note(note)
        self.resolution = Resolution((*unseen, *settled.facts), settled.narrator_cue)

    def _battle(self, state: Lite5eGame) -> Battle:
        battle = state.world.battle or self.settled
        if battle is None:
            raise ValueError("the run has no battle")
        return battle

    def _reading_fight(self, state: Lite5eGame) -> Fight:
        return fight_over(state.world, self._battle(state), Random())


class Lite5eBattles:
    def in_battle(self, state: Lite5eGame, /) -> bool:
        return state.world.battle is not None

    async def open_battle(self, draft: Lite5eGame, services: BattleServices, /) -> Lite5eRun:
        return Lite5eRun.start(draft, services.opponent)


def _scripted_plans(fight: Fight, foes: Sequence[FoeCombatant]) -> dict[Slug, str]:
    return {foe.combatant_id: scripted_plan(fight, foe).text for foe in foes}
