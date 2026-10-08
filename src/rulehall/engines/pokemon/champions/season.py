from random import Random
from typing import Literal

from pydantic import Field

from rulehall.core.validation import Frozen, Mutable, Refusal, Slug
from rulehall.engines.pokemon.battle.models import BattleBackground
from rulehall.engines.pokemon.champions.data import CompetitiveSet, Pool
from rulehall.engines.sheet import PLAYER_ID

type Tier = Literal["locals", "regionals", "internationals", "worlds"]
type Stage = Literal["open", "swiss", "cut", "done"]

BEST_FINISHES_COUNTED = 4
OWP_FLOOR = 0.25
STANDINGS_SHOWN = 8
STRENGTH = {"archetype": 2, "top8": 3, "top4": 4, "finalist": 5, "key_trainer": 5, "rival": 5}


class TierRule(Frozen):
    name: str = Field(min_length=1)
    swiss_rounds: int = Field(gt=0)
    cut_size: int = Field(gt=0)
    pools: tuple[Pool | Literal["archetype"], ...] = Field(min_length=1)
    cp: dict[int, int]
    unlock_cp: int = Field(ge=0)

    @property
    def field_size(self) -> int:
        return 2**self.swiss_rounds

    def placing_cp(self, placing: int) -> int:
        ceilings = [ceiling for ceiling in self.cp if placing <= ceiling]
        return self.cp[min(ceilings)] if ceilings else 0


TIERS: dict[Tier, TierRule] = {
    "locals": TierRule(
        name="Locals",
        swiss_rounds=3,
        cut_size=4,
        pools=("archetype", "top8"),
        cp={1: 50, 2: 40, 4: 25},
        unlock_cp=0,
    ),
    "regionals": TierRule(
        name="Regionals",
        swiss_rounds=4,
        cut_size=8,
        pools=("top8",),
        cp={1: 200, 2: 160, 4: 130, 8: 100},
        unlock_cp=50,
    ),
    "internationals": TierRule(
        name="Internationals",
        swiss_rounds=5,
        cut_size=8,
        pools=("top4", "top8"),
        cp={1: 500, 2: 400, 4: 320, 8: 250},
        unlock_cp=250,
    ),
    "worlds": TierRule(
        name="Worlds",
        swiss_rounds=6,
        cut_size=8,
        pools=("finalist", "top4"),
        cp={},
        unlock_cp=600,
    ),
}


class Entrant(Mutable):
    entrant_id: Slug
    name: str = Field(min_length=1)
    avatar_id: Slug
    style: str
    sets: tuple[CompetitiveSet, ...] = Field(min_length=1)
    strength: int = Field(gt=0)
    npc_id: Slug | None = None
    wins: int = Field(default=0, ge=0)
    losses: int = Field(default=0, ge=0)
    opponent_ids: list[Slug] = Field(default_factory=list)

    def win_rate(self) -> float:
        games = self.wins + self.losses
        return max(self.wins / games, OWP_FLOOR) if games else OWP_FLOOR


class Finish(Frozen):
    event_name: str = Field(min_length=1)
    tier: Tier
    placing: int = Field(gt=0)
    record: str = Field(min_length=1)
    cp: int = Field(ge=0)


class Event(Mutable):
    name: str = Field(min_length=1)
    tier: Tier
    venue_id: Slug
    battle_background: BattleBackground
    stage: Stage = "open"
    seed: int = 0
    round: int = Field(default=0, ge=0)
    entrants: list[Entrant] = Field(default_factory=list)
    pairings: list[tuple[Slug, Slug]] = Field(default_factory=list)
    bracket: list[Slug] = Field(default_factory=list)
    cut_wins: dict[Slug, int] = Field(default_factory=dict)
    placing: int | None = None
    winner_id: Slug | None = None

    def register(self, entrants: list[Entrant], seed: int) -> None:
        field_size = TIERS[self.tier].field_size
        if len(entrants) != field_size:
            raise ValueError(f"{self.name} needs {field_size} entrants, not {len(entrants)}")
        if sum(each.entrant_id == PLAYER_ID for each in entrants) != 1:
            raise ValueError(f"{self.name} needs the player once")
        self.seed = seed
        self.entrants = list(entrants)
        shuffled = [each.entrant_id for each in entrants]
        Random(f"{seed}").shuffle(shuffled)
        self.pairings = list(zip(shuffled[::2], shuffled[1::2], strict=True))
        self.stage = "swiss"
        self.round = 1

    def require_entrant(self, entrant_id: Slug) -> Entrant:
        for each in self.entrants:
            if each.entrant_id == entrant_id:
                return each
        raise Refusal(f"{entrant_id!r} is no entrant of {self.name}")

    def require_player_opponent(self) -> Entrant:
        for first, second in self.pairings:
            if PLAYER_ID in (first, second):
                return self.require_entrant(second if first == PLAYER_ID else first)
        raise Refusal(f"the player has no match to play in {self.name}")

    def standings(self) -> list[Entrant]:
        ranked = _ranked(self.entrants)
        return sorted(ranked, key=lambda each: -self.cut_wins.get(each.entrant_id, 0))

    def shown_standings(self) -> list[tuple[int, Entrant]]:
        return [
            (rank, each)
            for rank, each in enumerate(self.standings(), 1)
            if rank <= STANDINGS_SHOWN or each.entrant_id == PLAYER_ID
        ]

    def finish(self) -> Finish:
        if self.stage != "done" or self.placing is None:
            raise Refusal(f"{self.name} is not over")
        player = self.require_entrant(PLAYER_ID)
        return Finish(
            event_name=self.name,
            tier=self.tier,
            placing=self.placing,
            record=f"{player.wins}-{player.losses}",
            cp=TIERS[self.tier].placing_cp(self.placing),
        )

    def record_player(self, *, won: bool) -> list[str]:
        opponent = self.require_player_opponent()
        player = self.require_entrant(PLAYER_ID)
        rng = Random(f"{self.seed} {self.stage} {self.round}")
        lines = [f"{player.name} {'beat' if won else 'lost to'} {opponent.name}"]
        winners: list[Slug] = []
        for first, second in self.pairings:
            if PLAYER_ID in (first, second):
                winner_id = PLAYER_ID if won else opponent.entrant_id
            else:
                winner_id = self._roll(first, second, rng)
                lines.append(self._table_line(winner_id, first, second))
            winners.append(winner_id)
            if self.stage == "swiss":
                self._record_swiss(winner_id, first, second)
            else:
                self._record_cut(winner_id)
        if self.stage == "swiss":
            self._finish_swiss_round()
        else:
            self._finish_cut_round(winners, rng)
        return lines

    def _roll(self, first: Slug, second: Slug, rng: Random) -> Slug:
        strength_first = self.require_entrant(first).strength
        strength_second = self.require_entrant(second).strength
        chance = strength_first / (strength_first + strength_second)
        return first if rng.random() < chance else second

    def _table_line(self, winner_id: Slug, first: Slug, second: Slug) -> str:
        loser_id = second if winner_id == first else first
        return f"{self.require_entrant(winner_id).name} beat {self.require_entrant(loser_id).name}"

    def _record_swiss(self, winner_id: Slug, first: Slug, second: Slug) -> None:
        for entrant_id, other_id in ((first, second), (second, first)):
            entrant = self.require_entrant(entrant_id)
            entrant.opponent_ids.append(other_id)
            if entrant_id == winner_id:
                entrant.wins += 1
            else:
                entrant.losses += 1

    def _record_cut(self, winner_id: Slug) -> None:
        self.cut_wins[winner_id] = self.cut_wins.get(winner_id, 0) + 1

    def _finish_swiss_round(self) -> None:
        rule = TIERS[self.tier]
        if self.round < rule.swiss_rounds:
            self.round += 1
            self.pairings = swiss_pairings(self.entrants)
            return
        ranked = self.standings()
        qualifiers = [each.entrant_id for each in ranked[: rule.cut_size]]
        self.bracket = [qualifiers[seed - 1] for seed in _seed_order(rule.cut_size)]
        self.round = 1
        if PLAYER_ID in qualifiers:
            self.stage = "cut"
            self.pairings = _adjacent_pairs(self.bracket)
            return
        self.placing = [each.entrant_id for each in ranked].index(PLAYER_ID) + 1
        self._finish_event(Random(f"{self.seed} rolled out"))

    def _finish_cut_round(self, winners: list[Slug], rng: Random) -> None:
        if PLAYER_ID not in winners:
            self.placing = len(self.bracket)
            self.bracket = winners
            self._finish_event(rng)
            return
        self.bracket = winners
        self.round += 1
        if len(winners) == 1:
            self.placing = 1
            self._finish_event(rng)
            return
        self.pairings = _adjacent_pairs(winners)

    def _finish_event(self, rng: Random) -> None:
        while len(self.bracket) > 1:
            self.bracket = [
                self._roll(first, second, rng) for first, second in _adjacent_pairs(self.bracket)
            ]
            for winner_id in self.bracket:
                self._record_cut(winner_id)
        self.winner_id = self.bracket[0]
        self.stage = "done"
        self.pairings = []


def swiss_pairings(entrants: list[Entrant]) -> list[tuple[Slug, Slug]]:
    by_id = {each.entrant_id: each for each in entrants}
    waiting = [each.entrant_id for each in _ranked(entrants)]
    pairs: list[tuple[Slug, Slug]] = []
    while waiting:
        first = waiting.pop(0)
        met = by_id[first].opponent_ids
        index = next((at for at, other in enumerate(waiting) if other not in met), 0)
        pairs.append((first, waiting.pop(index)))
    return pairs


def total_cp(finishes: list[Finish]) -> int:
    total = 0
    for tier in TIERS:
        earned = sorted((each.cp for each in finishes if each.tier == tier), reverse=True)
        total += sum(earned[:BEST_FINISHES_COUNTED])
    return total


def unlocked_tiers(finishes: list[Finish]) -> tuple[Tier, ...]:
    cp = total_cp(finishes)
    played_worlds = any(each.tier == "worlds" for each in finishes)
    return tuple(
        tier
        for tier, rule in TIERS.items()
        if cp >= rule.unlock_cp and not (tier == "worlds" and played_worlds)
    )


def _ranked(entrants: list[Entrant]) -> list[Entrant]:
    by_id = {each.entrant_id: each for each in entrants}

    def owp(entrant: Entrant) -> float:
        if not entrant.opponent_ids:
            return OWP_FLOOR
        rates = [by_id[each].win_rate() for each in entrant.opponent_ids]
        return sum(rates) / len(rates)

    order = {each.entrant_id: at for at, each in enumerate(entrants)}
    return sorted(entrants, key=lambda each: (-each.wins, -owp(each), order[each.entrant_id]))


def _seed_order(size: int) -> list[int]:
    seeds = [1]
    while len(seeds) < size:
        seeds = [pick for seed in seeds for pick in (seed, 2 * len(seeds) + 1 - seed)]
    return seeds


def _adjacent_pairs(ids: list[Slug]) -> list[tuple[Slug, Slug]]:
    return list(zip(ids[::2], ids[1::2], strict=True))
