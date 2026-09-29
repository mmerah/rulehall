from typing import Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.game import Game
from rulehall.core.validation import Frozen
from rulehall.core.views import Rows
from rulehall.engines.rooms.world import RoomWorld
from rulehall.engines.tunnelgoons.sheet import ABILITY_POINTS, AbilityScores, Goon


class AbilitiesProposal(Frozen):
    abilities: AbilityScores = Field(
        min_length=3,
        max_length=3,
        description=(
            f"Points in brute, skulker and erudite. The three share exactly "
            f"{ABILITY_POINTS} points."
        ),
    )

    @model_validator(mode="after")
    def _points_spent(self) -> Self:
        total = sum(self.abilities.values())
        if total != ABILITY_POINTS:
            raise ValueError(
                f"the three abilities must share exactly {ABILITY_POINTS} points, not {total}"
            )
        return self


class TunnelGoonsWorld(RoomWorld[Goon]):
    def sheet_rows(self) -> Rows:
        return self.player.rows(carried=len(list(self.carried(self.player.id))))

    def rest(self) -> list[Fact]:
        player = self.player
        members = self.party_members()
        facts = player.change(player.hp, player.hp.shortfall, "Health", "resting")
        for member in members:
            facts.extend(member.change(member.hp, member.hp.shortfall, "Health", "resting"))
        trace = f"{'the party' if members else 'the player'} rests at {self.current.mention}"
        facts.append(player.fact(trace, card=f"Rested — Health {player.hp}"))
        return facts

    def next_to_level(self, actor: Goon) -> Goon | None:
        members = self.hired_party_members()
        order = [self.player.id, *(member.id for member in members)]
        index = order.index(actor.id)
        return next(
            (member for member in members[index:] if member.require_sheet().level == 1), None
        )


TunnelGoonsGame = Game[TunnelGoonsWorld]
