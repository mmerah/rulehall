from collections.abc import Collection, Sequence
from random import Random
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact, roll
from rulehall.core.game import Game
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug
from rulehall.core.views import Rows
from rulehall.engines.pokemon.battle.models import (
    DOUBLE_TEAM_MIN,
    LEVEL_MAX,
    TEAM_MAX,
    Ally,
    Ball,
    Battle,
    Battler,
    BattleResult,
    BattleSetup,
    Edge,
    Terrain,
    Throw,
    Weather,
)
from rulehall.engines.pokemon.dex import ITEMS, dex
from rulehall.engines.pokemon.rules import (
    ACE_BELOW_TABLE,
    BELOW_ACE,
    BOSS_RISE,
    PRIZE_PER_LEVEL,
    SEED_LIMIT,
    SPECIES_ID,
    STARTER_LEVEL,
    RosterSlot,
    catch_rate,
    check_species,
    evolved,
    item_of,
    rescaled,
)
from rulehall.engines.pokemon.scheme import SCHEME_STAGES, EvilTeam, Operation, Scheme
from rulehall.engines.pokemon.sheet import Mon, Trainer, TrainerSheet, built_team
from rulehall.engines.rooms.world import MapProposal, RegionProposal, RoomWorld
from rulehall.engines.world import OpeningProposal

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
    "It succeeds, and the boss grows stronger, when the player earns a badge or loses to its "
    "leader; it is foiled when the player beats its leader."
)
RUMOUR = "RUMOUR, to tell: the team is at {place}: {goal}"
FOILED = "The team's operation at {place} is foiled."
SUCCEEDED = "The team's operation at {place} succeeded; its boss grows stronger."


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

    def record_battle(
        self, place_name: str, badges: int, winner: str, highlights: Sequence[str]
    ) -> None:
        self.fought_at_badges = badges
        plural = "" if badges == 1 else "s"
        best = f". {highlights[0]}" if highlights else ""
        self.ledger.append(f"{place_name}, {badges} badge{plural}: {winner} won{best}")

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
    species_ids: tuple[Slug, ...] = Field(min_length=1)
    wild: dict[Slug, tuple[WildSlot, ...]] = Field(default_factory=dict)
    battle: Battle | None = None
    pending_edge: Edge | None = None
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
        return self

    @property
    def player_sheet(self) -> TrainerSheet:
        return self.player.require_sheet()

    def kill(self, entity_id: Slug) -> list[Fact]:
        self._refuse_key(entity_id)
        return super().kill(entity_id)

    def join(self, person: Trainer) -> list[Fact]:
        self._refuse_key(person.id)
        return super().join(person)

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
            "leaders: " + ", ".join(self.npcs[leader_id].ref for leader_id in evil_team.leader_ids),
        ]
        if (operation := evil_team.operation) is not None:
            place = self.places[operation.place_id]
            lines += [
                f"open operation at {place.ref}, led by {self.npcs[operation.leader_id].ref}: "
                f"{operation.goal}",
                SCHEME_TRIGGER,
            ]
            if not worldsmith and self.current.id in self.center_place_ids:
                lines.append(RUMOUR.format(place=place.name, goal=operation.goal))
        legendary_id = evil_team.joining_legendary_id()
        legendary = "" if legendary_id is None else f"; {dex().species_ref(legendary_id)} joins it"
        boss_id = evil_team.boss_id
        boss = "" if boss_id is None else f"; the boss is {self.npcs[boss_id].ref}"
        lines.append(
            f"final terms so far: the boss's ace is the next gym's level "
            f"+{BOSS_RISE * evil_team.succeeded}{legendary}{boss}"
        )
        return "\n".join(lines)

    def centers_line(self) -> str:
        here = self.current.id
        return ", ".join(
            self.places[place_id].ref + (" (here)" if place_id == here else "")
            for place_id in self.center_place_ids
            if self.places[place_id].known
        )

    def find_rival(self) -> Trainer | None:
        return next((npc for npc in self.npcs.values() if npc.rival), None)

    def sheet_rows(self) -> Rows:
        rows = super().sheet_rows()
        ledger = self.rival_record.ledger
        return (*rows, ("Rival", "; ".join(ledger))) if ledger else rows

    def apply_proposal_extras(self, proposal: OpeningProposal) -> None:
        assert isinstance(proposal, PokemonOpeningProposal | PokemonRegionProposal)
        self.wild.update(proposal.wild)
        self.center_place_ids.extend(proposal.center_place_ids)
        if isinstance(proposal, PokemonOpeningProposal):
            self.evil_team.scheme = proposal.scheme
        elif proposal.boss_id is not None:
            self.evil_team.boss_id = proposal.boss_id
        if proposal.operation is not None:
            self.open_operation(proposal.operation)

    def earn_edge(self, edge: Edge) -> None:
        self.pending_edge = edge

    def drop_edge(self) -> None:
        self.pending_edge = None

    def setup_battle(
        self,
        trainer: Trainer | None,
        foes: tuple[Battler, ...],
        rng: Random,
        *,
        weather: Weather | None,
        terrain: Terrain | None,
        companion: Trainer | None,
    ) -> None:
        player = self.player
        sheet = self.player_sheet
        able = sheet.able()
        if not able:
            raise Refusal("no team Pokemon can fight: heal the team first")
        if trainer is not None and companion is not None and len(foes) < DOUBLE_TEAM_MIN:
            raise Refusal(
                f"{trainer.name} has {len(foes)} Pokemon; a tag battle needs {DOUBLE_TEAM_MIN}"
            )
        alone = companion is None
        if trainer is not None and trainer.double and alone and len(able) < DOUBLE_TEAM_MIN:
            raise Refusal(
                f"{player.name} needs {DOUBLE_TEAM_MIN} Pokemon that can fight: "
                f"{trainer.name} battles two-on-two"
            )
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
        edge = self.pending_edge
        self.drop_edge()
        setup = BattleSetup(
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
            edge=None if trainer is not None and edge == "bait" else edge,
            weather=weather,
            terrain=terrain,
            double=trainer is not None and (trainer.double or companion is not None),
            ally=None
            if companion is None
            else Ally(
                name=companion.name,
                style=companion.style,
                avatar_id=companion.avatar_id,
                team=tuple(mon.battler() for mon in self.trainer_team(companion, rng)),
            ),
        )
        self.battle = Battle(setup=setup)

    def require_companion(self, foe: Trainer) -> Trainer:
        companion = next(
            (member for member in self.party_members() if member.roster and member.id != foe.id),
            None,
        )
        if companion is None:
            raise Refusal("no party member has a team to fight beside the player")
        return companion

    def throw_ball(self, ball_id: Slug, foe: Battler, rng: Random) -> Throw:
        battle = self.battle
        if battle is None or not battle.can_throw():
            raise Refusal("no ball can be thrown now: pick a move first")
        ball = ITEMS.get(ball_id)
        if ball is None or ball.kind != "ball":
            raise Refusal(f"{ball_id!r} is no ball")
        self.player_sheet.take(ball_id)
        rate = catch_rate(foe, ball.catch_bonus, baited=battle.setup.edge == "bait")
        rolled = roll((100,), f"{ball.name} at {foe.name}", rng, label="d100")
        success = rolled.face == 1 or rolled.face <= rate
        line = f"{ball.name} at {foe.name} — d100 {rolled.face} vs {rate} → " + (
            "caught" if success else "it breaks free"
        )
        throw = Throw(
            ball_id=ball_id,
            caught=success,
            fact=self.player.card_fact(line, (rolled.event,)),
            input_index=len(battle.inputs),
        )
        battle.throws.append(throw)
        return throw

    def wild_rows(self, species_id: Slug | None) -> tuple[WildSlot, ...]:
        here = self.current
        rows = self.wild.get(here.id, ())
        if not rows:
            raise Refusal(f"{here.name} has no wild Pokemon")
        sheet = self.player_sheet
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

    def heal_team(self) -> list[Fact]:
        if self.current.id not in self.center_place_ids:
            raise Refusal("no Pokemon Center here")
        self.player_sheet.heal_team()
        return [self.player.card_fact("Team healed")]

    def trainer_team(self, trainer: Trainer, rng: Random) -> list[Mon]:
        sheet = self.player_sheet
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
        sheet = self.player_sheet
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
        if not setup.wild and result.sent_out_foes:
            facts.append(player.fact(_sent_out_line(setup, result)))
        facts += [player.fact(highlight) for highlight in result.highlights]
        facts.append(player.card_fact(_outcome(setup, result, where)))
        cap = sheet.level_cap()
        shares = sheet.exp_shares(result, trainer=not setup.wild)
        for mon_id, exp in shares.items():
            mon = sheet.require_mon(mon_id)
            mon.train(result.fainted_foes())
            before = mon.exp
            reached, clipped = mon.gain(exp, cap)
            if gained := mon.exp - before:
                facts.append(player.card_fact(f"{mon.name} gains {gained} EXP"))
            if reached:
                facts.append(player.card_fact(f"{mon.name} grows to level {reached[-1]}"))
            if clipped:
                facts.append(player.card_fact(f"{mon.name} is at the level cap (L{cap})"))
            facts += player.grow(mon, reached, self.species_ids)
        notes: list[str] = []
        if setup.foe_id is not None:
            trainer = self.npcs[setup.foe_id]
            badges = len(sheet.badges)
            facts += self._settle_trainer(trainer, setup, result)
            moved, notes = self._move_scheme(trainer, result, badged=len(sheet.badges) > badges)
            facts += moved
        if sheet.challenge == "nuzlocke":
            facts += self._bury(setup)
        elif result.outcome != "won" and all(mon.fainted for mon in sheet.team):
            lost = sheet.money // 2
            sheet.money -= lost
            sheet.heal_team()
            facts.append(player.card_fact(f"You blacked out. -₽{lost}. Your team is healed."))
        self.battle = None
        return facts, notes

    def _settle_trainer(
        self, trainer: Trainer, setup: BattleSetup, result: BattleResult
    ) -> list[Fact]:
        player = self.player
        sheet = self.player_sheet
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
                    sheet.ranks_due += 1
        if key and (line := trainer.lose_line if won else trainer.win_line):
            facts.append(trainer.card_fact(f'{trainer.name}: "{line}"'))
        if trainer.rival:
            facts += self._rival_leaves(trainer, result.highlights, won=won)
        return facts

    def _move_scheme(
        self, trainer: Trainer, result: BattleResult, *, badged: bool
    ) -> tuple[list[Fact], list[str]]:
        operation = self.evil_team.operation
        if operation is None:
            return [], []
        leads = trainer.id == operation.leader_id
        if leads and result.outcome == "won":
            return self._end_operation(operation, foiled=True)
        if badged or (leads and result.outcome == "lost"):
            return self._end_operation(operation, foiled=False)
        return [], []

    def _end_operation(self, operation: Operation, *, foiled: bool) -> tuple[list[Fact], list[str]]:
        revealed_stage = self.evil_team.record_outcome(foiled=foiled)
        note = (FOILED if foiled else SUCCEEDED).format(place=self.places[operation.place_id].name)
        return [self.player.card_fact(revealed_stage)], [note]

    def _rival_leaves(self, rival: Trainer, highlights: Sequence[str], *, won: bool) -> list[Fact]:
        badges = len(self.player_sheet.badges)
        here = self.current
        winner = self.player.name if won else rival.name
        self.rival_record.record_battle(here.name, badges, winner, highlights)
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
        sheet = self.player_sheet
        fallen = [mon for mon in sheet.team if mon.fainted]
        foe = f"a wild {setup.foes[0].name}" if setup.wild else setup.foe_name
        if len(fallen) < len(sheet.team):
            for mon in fallen:
                sheet.team.remove(mon)
                sheet.memorial.append(mon.epitaph(foe))
        return [self.player.card_fact(f"{mon.name} has fallen") for mon in fallen]


PokemonGame = Game[PokemonWorld]


def challenge_line(trainer_name: str, foes: Sequence[Battler]) -> str:
    team = _listed([f"{foe.species_name} (L{foe.level})" for foe in foes])
    # The foe side always picks `team 1` at team preview, so the first foe leads.
    return f"{trainer_name} challenges you to a battle with {team}; {foes[0].species_name} leads"


def unknown_wild_places(wild: Collection[Slug], places: Collection[Slug]) -> list[Slug]:
    return sorted(place_id for place_id in wild if place_id not in places)


def _sent_out_line(setup: BattleSetup, result: BattleResult) -> str:
    sent = _listed([foe.species_name for foe in result.sent_out_foes])
    fainted = [foe.species_name for foe in result.fainted_foes()]
    return f"{setup.foe_name} sent out {sent}; {_listed(fainted) if fainted else 'none'} fainted"


def _listed(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _outcome(setup: BattleSetup, result: BattleResult, where: Literal["team", "box"] | None) -> str:
    match result.outcome:
        case "won" if setup.wild:
            return f"The wild {setup.foes[0].name} fainted"
        case "won":
            return f"You beat {setup.foe_name}"
        case "lost":
            return "You lost the battle"
        case "fled":
            return "You got away"
        case "caught":
            assert result.caught is not None
            joins = "It joins your team." if where == "team" else "It goes to your box."
            return f"You caught {result.caught.name}. {joins}"
