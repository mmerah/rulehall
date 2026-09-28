from collections.abc import Collection
from random import Random
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.game import Game
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, refuse
from rulehall.core.views import Rows
from rulehall.engines.pokemon.battle.models import (
    LEVEL_MAX,
    MOVES_MAX,
    TEAM_MAX,
    Ball,
    Battle,
    Battler,
    BattleResult,
    BattleSetup,
)
from rulehall.engines.pokemon.dex import ITEMS, dex
from rulehall.engines.pokemon.rules import (
    ACE_BELOW_TABLE,
    BELOW_ACE,
    BOSS_RISE,
    LEVEL_FLOOR,
    PRIZE_PER_LEVEL,
    RANK_MAX,
    SEED_LIMIT,
    SPECIES_ID,
    STARTER_LEVEL,
    TM_PREFIX,
    ItemId,
    RosterSlot,
    Skill,
    TmId,
    check_species,
    counter_pick,
    evolved,
    item_of,
    rescaled,
)
from rulehall.engines.pokemon.scheme import SCHEME_STAGES, EvilTeam, Operation, Scheme, held_line
from rulehall.engines.pokemon.sheet import Evolving, Learning, Mon, Trainer, built_team
from rulehall.engines.rooms.world import MapProposal, RegionProposal, RoomWorld

WILD = "The wild table of each new place, keyed by place id. A town or a building has no table."
RIVAL_WAITS = (
    "Your rival {name} waits here to battle. Voice them; call `start_battle` when the player "
    "agrees."
)
CENTER_PLACE_IDS = (
    "Ids of the places of this map that are a Pokemon Center, where the team heals. One in every "
    "town."
)
OPERATION = (
    "The evil team's operation in this map. Write it only when the request asks for it; else null."
)
BOSS_ID = (
    "Exact id of the evil team's boss, a person of this map. Write it only when the request asks "
    "for the lair; else null."
)
SCHEME_TRIGGER = (
    "It succeeds when the player earns a badge or loses to its leader; it is foiled when the "
    "player beats its leader."
)
RUMOUR = "RUMOUR, to tell: the team is at {place}: {goal}"
CENTER_SPARED = "The team tried to close a Pokemon Center"
CENTER_CLOSED = "{center} has closed"
FOILED = "The team's operation at {place} is foiled."
SUCCEEDED = "The team's operation at {place} succeeded: {change}."


class WildSlot(Frozen):
    species_id: Slug = Field(description=SPECIES_ID)
    lowest: int = Field(ge=1, le=LEVEL_MAX, description="The lowest level it has here.")
    highest: int = Field(ge=1, le=LEVEL_MAX, description="The highest level it has here.")
    weight: int = Field(ge=1, description="How often it shows up, against the other rows.")

    @model_validator(mode="after")
    def _a_species_in_a_level_range(self) -> Self:
        check_species(self.species_id)
        if self.lowest > self.highest:
            raise ValueError(f"lowest {self.lowest} is above highest {self.highest}")
        return self


class PokemonMap(MapProposal[Trainer]):
    wild: dict[Slug, tuple[WildSlot, ...]] = Field(default_factory=dict, description=WILD)
    center_place_ids: tuple[Slug, ...] = Field(default=(), description=CENTER_PLACE_IDS)


class PokemonOpeningProposal(PokemonMap):
    scheme: Scheme = Field(description="The evil team's scheme, written once for the journey.")
    operation: Operation = Field(description="The evil team's first operation, in this map.")


class PokemonRegionProposal(PokemonMap, RegionProposal[Trainer]):
    operation: Operation | None = Field(default=None, description=OPERATION)
    boss_id: Slug | None = Field(default=None, description=BOSS_ID)


class RivalRecord(Mutable):
    starter_id: Slug | None = None
    fought_at_badges: int = Field(default=-1, ge=-1)
    due: bool = False
    ledger: list[str] = Field(default_factory=list)

    def record_battle(self, place_name: str, badges: int, winner: str) -> None:
        self.fought_at_badges = badges
        plural = "" if badges == 1 else "s"
        self.ledger.append(f"{place_name}, {badges} badge{plural}: {winner} won")

    def roster(
        self,
        badges: int,
        ace_level: int,
        seen_species_ids: Collection[Slug],
        species_ids: Collection[Slug],
    ) -> tuple[RosterSlot, ...]:
        assert self.starter_id is not None
        if not badges:
            return (RosterSlot(species_id=self.starter_id, level=STARTER_LEVEL),)
        ace_id = evolved(self.starter_id, ace_level, species_ids)
        species = dex().species
        strongest = sorted(
            seen_species_ids,
            key=lambda species_id: (-sum(species[species_id].base_stats), species_id),
        )
        others = dict.fromkeys(
            evolved(species_id, ace_level - BELOW_ACE, species_ids) for species_id in strongest
        )
        others.pop(ace_id, None)
        return (
            *(
                RosterSlot(species_id=species_id, level=ace_level - BELOW_ACE)
                for species_id in list(others)[: min(badges, TEAM_MAX - 1)]
            ),
            RosterSlot(species_id=ace_id, level=ace_level),
        )


class PokemonWorld(RoomWorld[Trainer]):
    meanwhile_every = 4
    species_ids: tuple[Slug, ...] = Field(min_length=1)
    wild: dict[Slug, tuple[WildSlot, ...]] = Field(default_factory=dict)
    learning: list[Learning] = Field(default_factory=list)
    evolving: list[Evolving] = Field(default_factory=list)
    ranks_due: int = Field(default=0, ge=0)
    battle: Battle | None = None
    center_place_ids: list[Slug] = Field(default_factory=list)
    encountered_place_ids: list[Slug] = Field(default_factory=list)
    rival_record: RivalRecord = Field(default_factory=RivalRecord)
    evil_team: EvilTeam = Field(default_factory=EvilTeam)

    @model_validator(mode="after")
    def _a_trainer_on_a_map(self) -> Self:
        if self.player.roster:
            raise ValueError("the player's team is `sheet.team`; `roster` is for npc trainers")
        if strays := unknown_wild_places(self.wild, self.places):
            raise ValueError(f"wild tables for places that do not exist: {strays}")
        wild_species_ids = {slot.species_id for rows in self.wild.values() for slot in rows}
        if strays := sorted(wild_species_ids - set(self.species_ids)):
            raise ValueError(f"wild species outside `species_ids`: {strays}")
        if strays := sorted(set(self.center_place_ids) - set(self.places)):
            raise ValueError(f"Pokemon Centers that are no place: {strays}")
        if len([npc for npc in self.npcs.values() if npc.rival]) > 1:
            raise ValueError("a world has one rival at most")
        if strays := sorted(set(self.evil_team.key_ids()) - set(self.npcs)):
            raise ValueError(f"leaders or a boss who are no npc: {strays}")
        operation = self.evil_team.operation
        if operation is not None and operation.place_id not in self.places:
            raise ValueError(f"the operation is at no place: {operation.place_id!r}")
        if strays := [pair for pair in self.evil_team.held_ways if self.find_way(*pair) is None]:
            raise ValueError(f"held ways that are no way: {strays}")
        return self

    def kill(self, entity_id: Slug) -> list[Fact]:
        self._refuse_key(entity_id)
        return super().kill(entity_id)

    def join(self, person: Trainer) -> list[Fact]:
        self._refuse_key(person.id)
        return super().join(person)

    def unlock_way(self, to_id: Slug) -> list[Fact]:
        if self.evil_team.holds_way(self.current.id, to_id):
            raise Refusal(f"the grunts of {self.evil_team.require_scheme().name} hold this way")
        return super().unlock_way(to_id)

    def open_operation(self, operation: Operation) -> None:
        self.evil_team.open_operation(operation)
        leader = self.npcs[operation.leader_id]
        leader.place_id = operation.place_id
        leader.beaten = False

    def scheme_lines(self, *, worldsmith: bool) -> str:
        evil_team = self.evil_team
        scheme = evil_team.scheme
        if scheme is None:
            return ""
        done = evil_team.stage()
        shown = scheme.stages[: done + 1] if worldsmith else scheme.stages[:done]
        lines = [
            f"{scheme.name}. Goal: {scheme.goal}",
            f"stage {done}/{SCHEME_STAGES}, foiled {evil_team.foiled}, "
            f"succeeded {evil_team.succeeded}",
            *(f"- stage {number}: {line}" for number, line in enumerate(shown, 1)),
            "leaders: " + ", ".join(self.npcs[leader_id].tag for leader_id in evil_team.leader_ids),
        ]
        if (operation := evil_team.operation) is not None:
            place = self.places[operation.place_id]
            lines += [
                f"open operation at {place.tag}, led by {self.npcs[operation.leader_id].tag}: "
                f"{operation.goal}",
                f"if it succeeds: {operation.stake(self)}. {SCHEME_TRIGGER}",
            ]
            if not worldsmith and self.current.id in self.center_place_ids:
                lines.append(RUMOUR.format(place=place.name, goal=operation.goal))
        legendary_id = evil_team.joining_legendary_id()
        legendary = "" if legendary_id is None else f"; {dex().tag(legendary_id)} joins it"
        boss_id = evil_team.boss_id
        boss = "" if boss_id is None else f"; the boss is {self.npcs[boss_id].tag}"
        lines.append(
            f"final terms so far: the boss's ace is the next gym's level "
            f"+{BOSS_RISE * evil_team.succeeded}{legendary}{boss}"
        )
        return "\n".join(lines)

    def centers_line(self) -> str:
        here = self.current.id
        return ", ".join(
            self.places[place_id].tag + (" (here)" if place_id == here else "")
            for place_id in self.center_place_ids
            if self.places[place_id].known
        )

    def find_rival(self) -> Trainer | None:
        return next((npc for npc in self.npcs.values() if npc.rival), None)

    def sheet_rows(self) -> Rows:
        rows = super().sheet_rows()
        ledger = self.rival_record.ledger
        return (*rows, ("Rival", "; ".join(ledger))) if ledger else rows

    def apply_proposal_extras(
        self, proposal: PokemonOpeningProposal | PokemonRegionProposal
    ) -> None:
        self.wild.update(proposal.wild)
        self.center_place_ids.extend(proposal.center_place_ids)
        if isinstance(proposal, PokemonOpeningProposal):
            self.evil_team.scheme = proposal.scheme
        elif proposal.boss_id is not None:
            self.evil_team.boss_id = proposal.boss_id
        if proposal.operation is not None:
            self.open_operation(proposal.operation)

    def setup_battle(self, trainer: Trainer | None, foes: tuple[Battler, ...], rng: Random) -> None:
        player = self.player
        sheet = player.require_sheet()
        able = sheet.able()
        if not able:
            raise Refusal("no team Pokemon can fight: heal the team first")
        here = self.current.id
        first_here = here not in self.encountered_place_ids
        catchable = trainer is None and (first_here or sheet.challenge != "nuzlocke")
        balls = (
            tuple(
                Ball(item_id=item_id, name=item_of(item_id).name, count=count)
                for item_id, count in sheet.bag.items()
                if item_of(item_id).kind == "ball"
            )
            if catchable
            else ()
        )
        if trainer is None and first_here:
            self.encountered_place_ids.append(here)
        setup = BattleSetup(
            kind="wild" if trainer is None else "trainer",
            policy="random"
            if trainer is None
            else "model"
            if trainer.is_key(self.evil_team.key_ids())
            else "scripted",
            foe_style="" if trainer is None else trainer.style,
            foe_id=None if trainer is None else trainer.id,
            player_name=player.name,
            foe_name=f"Wild {foes[0].name}" if trainer is None else trainer.name,
            player_avatar_id=player.avatar_id,
            foe_avatar_id=None if trainer is None else trainer.avatar_id,
            seed=(
                rng.randrange(SEED_LIMIT),
                rng.randrange(SEED_LIMIT),
                rng.randrange(SEED_LIMIT),
                rng.randrange(SEED_LIMIT),
            ),
            team=tuple(mon.battler() for mon in able),
            foes=foes,
            balls=balls,
        )
        self.battle = Battle(setup=setup)

    def wild_rows(self, species_id: Slug | None) -> tuple[WildSlot, ...]:
        here = self.current
        rows = self.wild.get(here.id, ())
        if not rows:
            raise Refusal(f"{here.name} has no wild Pokemon")
        sheet = self.player.require_sheet()
        if sheet.challenge == "nuzlocke":
            if species_id is not None:
                raise Refusal("in a Nuzlocke the wild table decides: leave species_id null")
            if here.id in self.encountered_place_ids:
                return rows
            return (
                tuple(row for row in rows if row.species_id not in sheet.caught_species_ids) or rows
            )
        if species_id is None:
            return rows
        chosen = tuple(row for row in rows if row.species_id == species_id)
        if not chosen:
            raise Refusal(f"{species_id!r} is not in WILD HERE")
        return chosen

    def nickname(self, mon_id: Slug, name: str) -> list[Fact]:
        sheet = self.player.require_sheet()
        mon = sheet.require_owned(mon_id)
        refuse(sheet.nickname_refusal(mon, name))
        before = mon.name
        mon.nickname = name
        return [self.player.card_fact(f"{before} is now called {name}")]

    def heal_team(self) -> list[Fact]:
        if self.current.id not in self.center_place_ids:
            raise Refusal("no open Pokemon Center here")
        self.player.require_sheet().heal_team()
        return [self.player.card_fact("Team healed")]

    def trainer_team(self, trainer: Trainer, rng: Random) -> list[Mon]:
        sheet = self.player.require_sheet()
        ace_level = sheet.table_level() - ACE_BELOW_TABLE
        if trainer.rival:
            seen_species_ids = {
                slot.species_id
                for place_id in set(self.visited_place_ids)
                for slot in self.wild.get(place_id, ())
            }
            return built_team(
                self.rival_record.roster(
                    len(sheet.badges), ace_level, seen_species_ids, self.species_ids
                )
            )
        if trainer.id == self.evil_team.boss_id:
            return built_team(
                self.evil_team.boss_roster(trainer, sheet.table_level(), self.species_ids)
            )
        if trainer.id in self.evil_team.leader_ids:
            return built_team(rescaled(trainer.roster, ace_level, self.species_ids))
        if trainer.badge:
            return built_team(trainer.roster)
        if not trainer.team:
            for slot in trainer.roster:
                trainer.team.append(
                    Mon.new(slot.species_id, slot.level, rng, [mon.mon_id for mon in trainer.team])
                )
        return trainer.team

    def place_rival(self) -> tuple[list[Fact], list[str]]:
        rival = self.find_rival()
        here = self.current.id
        operation = self.evil_team.operation
        operation_here = operation is not None and operation.place_id == here
        if (
            not self.rival_record.due
            or rival is None
            or operation_here
            or any(npc.badge for npc in self.at(here))
        ):
            return [], []
        rival.place_id = here
        rival.known = True
        self.rival_record.due = False
        return [rival.card_fact(f"{rival.name} is here")], [RIVAL_WAITS.format(name=rival.name)]

    def settle_battle(self, result: BattleResult) -> tuple[list[Fact], list[str]]:
        battle = self.battle
        assert battle is not None
        setup = battle.setup
        player = self.player
        sheet = player.require_sheet()
        facts = [throw.fact for throw in battle.throws]
        for battler in result.team:
            sheet.require_mon(battler.mon_id).apply(battler)
        caught = result.caught
        where = (
            None
            if caught is None
            else sheet.catch(
                Mon.from_battler(caught, f"caught at {self.current.name} at L{caught.level}")
            )
        )
        facts.append(player.card_fact(_outcome(setup, result, where)))
        cap = sheet.level_cap()
        shares = sheet.exp_shares(result, trainer=setup.kind == "trainer")
        for mon_id, exp in shares.items():
            mon = sheet.require_mon(mon_id)
            mon.train(result.fainted_foes)
            before = mon.exp
            reached, clipped = mon.gain(exp, cap)
            if gained := mon.exp - before:
                facts.append(player.card_fact(f"{mon.name} gains {gained} EXP"))
            if reached:
                facts.append(player.card_fact(f"{mon.name} grows to level {reached[-1]}"))
            if clipped:
                facts.append(player.card_fact(f"{mon.name} is at the level cap (L{cap})"))
            facts += self.grow(mon, reached)
        notes: list[str] = []
        if setup.foe_id is not None:
            trainer = self.npcs[setup.foe_id]
            badges = len(sheet.badges)
            facts += self._settle_trainer(trainer, setup, result)
            moved, notes = self._move_scheme(
                trainer, setup, result, badged=len(sheet.badges) > badges
            )
            facts += moved
        if sheet.challenge == "nuzlocke":
            facts += self._bury(setup)
        elif all(mon.fainted for mon in sheet.team):
            lost = sheet.money // 2
            sheet.money -= lost
            sheet.heal_team()
            facts.append(player.card_fact(f"You blacked out. -₽{lost}. Your team is healed."))
        self.battle = None
        return facts, notes

    def swap_mon(self, team_mon_id: Slug, box_mon_id: Slug) -> list[Fact]:
        leaving, joining = self.player.require_sheet().swap(team_mon_id, box_mon_id)
        line = f"{leaving.name} to the box, {joining.name} to the team"
        return [self.player.card_fact(line)]

    def store_mon(self, mon_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().store(mon_id)
        return [self.player.card_fact(f"{mon.name} to the box")]

    def withdraw_mon(self, mon_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().withdraw(mon_id)
        return [self.player.card_fact(f"{mon.name} to the team")]

    def lead_mon(self, mon_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().lead(mon_id)
        return [self.player.card_fact(f"{mon.name} leads the team")]

    def hold_item(self, mon_id: Slug, item_id: ItemId | None) -> list[Fact]:
        sheet = self.player.require_sheet()
        mon = sheet.require_mon(mon_id)
        name = mon.name
        if item_id is None:
            if mon.item_id is None:
                raise Refusal(f"{name} holds nothing")
            line = f"Took the {ITEMS[mon.item_id].name} from {name}"
        else:
            item = ITEMS[item_id]
            if item.kind != "held":
                raise Refusal(f"{item.name} is not an item to hold")
            refuse(mon.item_refusal(item_id, (), sheet.level_cap()))
            sheet.take(item_id)
            line = f"{name} holds the {item.name}"
        if mon.item_id is not None:
            sheet.add(mon.item_id, 1)
        mon.item_id = item_id
        return [self.player.card_fact(line)]

    def teach_move(self, mon_id: Slug, item_id: TmId) -> list[Fact]:
        sheet = self.player.require_sheet()
        if item_id not in sheet.bag:
            raise Refusal(f"the bag holds no {item_of(item_id).name}")
        mon = sheet.require_mon(mon_id)
        refuse(mon.item_refusal(item_id, (), sheet.level_cap()))
        return self._learn_or_ask(mon, item_id.removeprefix(TM_PREFIX))

    def relearn_move(self, mon_id: Slug, move_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().require_mon(mon_id)
        if move_id not in mon.relearnable():
            raise Refusal(f"{mon.name} cannot remember {move_id!r}")
        return self._learn_or_ask(mon, move_id)

    def learn_move(self, mon_id: Slug, move_id: Slug, forget_id: Slug | None) -> list[Fact]:
        if self.learning[:1] != [Learning(mon_id=mon_id, move_id=move_id)]:
            raise Refusal("no new move waits on this answer")
        mon = self.player.require_sheet().require_mon(mon_id)
        name = mon.name
        move = dex().moves[move_id].name
        if forget_id is None:
            line = f"{name} did not learn {move}"
        else:
            mon.learn(move_id, forget_id)
            line = f"{name} forgot {dex().moves[forget_id].name} and learned {move}"
        _ = self.learning.pop(0)
        return [self.player.card_fact(line)]

    def evolve(self, mon_id: Slug, species_id: Slug) -> list[Fact]:
        if not any(
            each.mon_id == mon_id and species_id in each.species_ids for each in self.evolving[:1]
        ):
            raise Refusal("no evolution waits on this answer")
        mon = self.player.require_sheet().require_mon(mon_id)
        name = mon.name
        mon.evolve(species_id)
        _ = self.evolving.pop(0)
        facts = [self.player.card_fact(f"{name} evolved into {mon.species_name}")]
        return facts + self.evolve_chain(mon)

    def raise_skill(self, skill: Skill) -> list[Fact]:
        if not self.ranks_due:
            raise Refusal("no skill rank waits")
        sheet = self.player.require_sheet()
        rank = sheet.skills.get(skill, 0)
        if rank >= RANK_MAX:
            raise Refusal(f"{skill.title()} is already at rank {RANK_MAX}")
        sheet.skills[skill] = rank + 1
        self.ranks_due -= 1
        return [self.player.card_fact(f"{skill.title()} rises to rank {rank + 1}")]

    def use_item(self, item_id: ItemId, mon_id: Slug) -> list[Fact]:
        sheet = self.player.require_sheet()
        mon = sheet.require_mon(mon_id)
        item = ITEMS[item_id]
        if item.kind in ("ball", "held", "tm"):
            raise Refusal(f"{item.name} is given or taught on the Team page, not used")
        refuse(mon.item_refusal(item_id, self.species_ids, sheet.level_cap()))
        name = mon.name
        level = mon.level
        sheet.take(item_id)
        match item.kind:
            case "potion":
                healed = mon.hp.adjust(item.heal)
                line = f"{item.name} on {name}: HP +{healed} → {mon.hp}"
            case "full-heal":
                cured, mon.status = mon.status, ""
                line = f"{item.name} on {name}: {cured} cured"
            case "revive":
                mon.hp.current = mon.hp.maximum // 2
                line = f"{item.name} on {name}: HP {mon.hp}"
            case "candy":
                _ = mon.gain((mon.level + 1) ** 3 - mon.exp, sheet.level_cap())
                line = f"{item.name} on {name}: level {mon.level}"
            case "evolution":
                evolved_id = mon.evolution_by_item(self.species_ids, item.name)
                assert evolved_id is not None
                mon.evolve(evolved_id)
                line = f"{item.name} on {name}: it evolved into {mon.species_name}"
        facts = [self.player.card_fact(line)]
        return facts + self.grow(mon, list(range(level + 1, mon.level + 1)))

    def grow(self, mon: Mon, reached: list[int]) -> list[Fact]:
        facts: list[Fact] = []
        for level in reached:
            for move_id in mon.moves_at(level):
                if not mon.knows(move_id):
                    facts += self._learn_or_ask(mon, move_id)
        if reached and mon.item_id != "everstone":
            facts += self.evolve_chain(mon)
        return facts

    def evolve_chain(self, mon: Mon) -> list[Fact]:
        facts: list[Fact] = []
        while len(found := mon.evolutions(self.species_ids)) == 1:
            name = mon.name
            mon.evolve(found[0])
            facts.append(self.player.card_fact(f"{name} evolved into {mon.species_name}"))
        if len(found) > 1:
            self.evolving.append(Evolving(mon_id=mon.mon_id, species_ids=found))
        return facts

    def _settle_trainer(
        self, trainer: Trainer, setup: BattleSetup, result: BattleResult
    ) -> list[Fact]:
        player = self.player
        sheet = player.require_sheet()
        facts: list[Fact] = []
        won = result.outcome == "won"
        key = trainer.is_key(self.evil_team.key_ids())
        trainer.last_battle_visit = len(self.visited_place_ids)
        if won and key:
            for mon_id in result.on_field_mon_ids:
                sheet.require_mon(mon_id).wins.append(trainer.name)
        if won and trainer.id == self.evil_team.boss_id:
            self.evil_team.boss_beaten = True
        if won and (trainer.rival or not trainer.beaten):
            if not trainer.rival:
                trainer.beaten = True
            prize = PRIZE_PER_LEVEL * max(foe.level for foe in setup.foes)
            sheet.money += prize
            facts.append(player.fact(f"{trainer.name} pays ₽{prize}", card=f"+₽{prize}"))
            if trainer.badge and trainer.badge not in sheet.badges:
                sheet.badges.append(trainer.badge)
                facts.append(player.card_fact(f"You earned the {trainer.badge}"))
                self.rival_record.due = True
                if sheet.rankable():
                    self.ranks_due += 1
        if key and (line := trainer.lose_line if won else trainer.win_line):
            facts.append(trainer.card_fact(f'{trainer.name}: "{line}"'))
        if trainer.rival:
            facts += self._rival_leaves(trainer, won=won)
        return facts

    def _move_scheme(
        self,
        trainer: Trainer,
        setup: BattleSetup,
        result: BattleResult,
        *,
        badged: bool,
    ) -> tuple[list[Fact], list[str]]:
        operation = self.evil_team.operation
        if operation is None:
            return [], []
        leads = trainer.id == operation.leader_id
        if leads and result.outcome == "won":
            self._learn_counter(trainer, max(foe.level for foe in setup.foes))
            return self._end_operation(operation, foiled=True)
        if badged or (leads and result.outcome == "lost"):
            return self._end_operation(operation, foiled=False)
        return [], []

    def _end_operation(self, operation: Operation, *, foiled: bool) -> tuple[list[Fact], list[str]]:
        revealed_stage = self.evil_team.record_outcome(foiled=foiled)
        place = self.places[operation.place_id].name
        facts = [self.player.card_fact(revealed_stage)]
        if foiled:
            return facts, [FOILED.format(place=place)]
        change = self._hold_way(operation) or self._close_center()
        facts.append(self.player.card_fact(change))
        return facts, [SUCCEEDED.format(place=place, change=change)]

    def _hold_way(self, operation: Operation) -> str:
        start_id, to_id = operation.place_id, operation.shut_to_id
        way = None if to_id is None else self.find_way(start_id, to_id)
        if to_id is None or way is None or way.locked:
            return ""
        here_id = self.current.id
        held_ways = self.evil_team.held_ways
        if self.reachable(
            here_id, past_locks=True, cut=[*held_ways, (start_id, to_id)]
        ) != self.reachable(here_id, past_locks=True, cut=held_ways):
            return ""
        way.locked = True
        if (back := self.find_way(to_id, start_id)) is not None:
            back.locked = True
        held_ways.append((start_id, to_id))
        return held_line(self, start_id, to_id)

    def _close_center(self) -> str:
        if len(self.center_place_ids) < 2:
            return CENTER_SPARED
        visited = (
            place_id
            for place_id in reversed(self.visited_place_ids)
            if place_id in self.center_place_ids
        )
        closed = next(visited, self.center_place_ids[0])
        self.center_place_ids.remove(closed)
        return CENTER_CLOSED.format(center=self.places[closed].name)

    def _learn_counter(self, leader: Trainer, fought_level: int) -> None:
        ace = max(slot.level for slot in leader.roster)
        lead = self.player.require_sheet().team[0]
        species_id = counter_pick(self.species_ids, lead.species.types, fought_level)
        roster = sorted(leader.roster, key=lambda slot: slot.level)
        if any(slot.species_id == species_id for slot in roster):
            return
        if len(roster) == TEAM_MAX:
            roster.pop(0)
        roster.insert(0, RosterSlot(species_id=species_id, level=max(ace - BELOW_ACE, LEVEL_FLOOR)))
        leader.roster = tuple(roster)

    def _rival_leaves(self, rival: Trainer, *, won: bool) -> list[Fact]:
        badges = len(self.player.require_sheet().badges)
        here = self.current
        self.rival_record.record_battle(here.name, badges, self.player.name if won else rival.name)
        away = [
            *(place_id for place_id in reversed(self.visited_place_ids) if place_id != here.id),
            *(way.to_id for way in self.ways.get(here.id, ()) if not way.locked),
        ]
        if not away:
            return []
        rival.place_id = away[0]
        return [rival.card_fact(f"{rival.name} leaves")]

    def _refuse_key(self, entity_id: Slug) -> None:
        person = self.find_person(entity_id)
        if person is not None and person.is_key(self.evil_team.key_ids()):
            raise Refusal(f"{person.name} has a part to play; they do not die or join you")

    def _bury(self, setup: BattleSetup) -> list[Fact]:
        sheet = self.player.require_sheet()
        fallen = [mon for mon in sheet.team if mon.fainted]
        foe = setup.foe_name if setup.kind == "trainer" else f"a wild {setup.foes[0].name}"
        if len(fallen) < len(sheet.team):
            for mon in fallen:
                sheet.team.remove(mon)
                sheet.memorial.append(mon.epitaph(foe))
        return [self.player.card_fact(f"{mon.name} has fallen") for mon in fallen]

    def _learn_or_ask(self, mon: Mon, move_id: Slug) -> list[Fact]:
        if len(mon.moves) < MOVES_MAX:
            mon.learn(move_id)
            learned = f"{mon.name} learned {dex().moves[move_id].name}"
            return [self.player.card_fact(learned)]
        self.learning.append(Learning(mon_id=mon.mon_id, move_id=move_id))
        return []


PokemonGame = Game[PokemonWorld]


def unknown_wild_places(wild: Collection[Slug], places: Collection[Slug]) -> list[Slug]:
    return sorted(place_id for place_id in wild if place_id not in places)


def _outcome(setup: BattleSetup, result: BattleResult, where: Literal["team", "box"] | None) -> str:
    match result.outcome:
        case "won" if setup.kind == "trainer":
            return f"You beat {setup.foe_name}"
        case "won":
            return f"The wild {setup.foes[0].name} fainted"
        case "lost":
            return "You lost the battle"
        case "fled":
            return "You got away"
        case "caught":
            assert result.caught is not None
            joins = "It joins your team." if where == "team" else "It goes to your box."
            return f"You caught {result.caught.name}. {joins}"
