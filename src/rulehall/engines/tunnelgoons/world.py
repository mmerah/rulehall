from rulehall.core.facts import Fact
from rulehall.core.model import Game
from rulehall.core.views import Rows
from rulehall.engines.rooms.world import RoomWorld
from rulehall.engines.tunnelgoons.sheet import Goon


class TunnelGoonsWorld(RoomWorld[Goon]):
    meanwhile_every = 4

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
