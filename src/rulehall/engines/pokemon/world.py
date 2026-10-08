from collections.abc import Collection, Iterable, Sequence
from random import Random
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact, roll
from rulehall.core.game import Game
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, check_unique, refuse
from rulehall.core.views import Rows
from rulehall.engines.pokemon.battle.models import (
    DOUBLE_TEAM_MIN,
    LEVEL_MAX,
    TEAM_MAX,
    Ally,
    Ball,
    Battle,
    BattleBackground,
    BattleMusic,
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
    RIVAL_IV,
    SEED_LIMIT,
    SPECIES_ID,
    STARTER_LEVEL,
    RosterSlot,
    built_ev,
    built_iv,
    catch_rate,
    check_species,
    evolved,
    is_legendary,
    item_of,
    rescaled,
    rival_ev,
)
from rulehall.engines.pokemon.scheme import (
    SCHEME_STAGES,
    EvilTeam,
    Operation,
    Outcome,
    Scheme,
    SchemeDue,
)
from rulehall.engines.pokemon.sheet import Mon, Trainer, TrainerSheet, built_team
from rulehall.engines.rooms.world import OFF_MAP_ID, MapProposal, RegionProposal, RoomWorld

WILD = "The wild table of each new place, keyed by place id. A town or a building has no table."
RIVAL_WAITS = (
    "Your rival {name} waits here to battle. They block the road: until they battle, the player "
    "can only go back the way they came, and before the first move every way is blocked. Voice "
    "them; call `start_battle` when the player agrees."
)
TOWN_BATTLE_BACKGROUND: BattleBackground = "gen6-city"
ROUTE_BATTLE_BACKGROUND: BattleBackground = "gen5-route"
BATTLE_BACKGROUND_IDS = (
    "The battle background of each new place, keyed by place id: the image a battle there is "
    f"fought on. A place left out shows {TOWN_BATTLE_BACKGROUND!r} if it is a town, else "
    f"{ROUTE_BATTLE_BACKGROUND!r}."
)
TOWN_PLACE_IDS = (
    "Ids of the towns of this map. A town holds a Pokemon Center, where the team heals, and a "
    "mart, where the player buys; neither is a place of its own. List every town."
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
        species = dex().species[self.species_id]
        if is_legendary(species):
            raise ValueError(
                f"{species.name} is legendary and never in a wild table: write it as a person of "
                "the map with `legendary_id`"
            )
        if self.lowest > self.highest:
            raise ValueError(f"lowest {self.lowest} is above highest {self.highest}")
        return self


class PokemonMapProposal(MapProposal[Trainer]):
    wild: dict[Slug, tuple[WildSlot, ...]] = Field(default_factory=dict, description=WILD)
    town_place_ids: tuple[Slug, ...] = Field(default=(), description=TOWN_PLACE_IDS)
    battle_background_ids: dict[Slug, BattleBackground] = Field(
        default_factory=dict, description=BATTLE_BACKGROUND_IDS
    )


class PokemonOpeningProposal(PokemonMapProposal):
    scheme: Scheme = Field(description="The evil team's scheme, written once for the journey.")
    operation: Operation = Field(description="The evil team's first operation, in this map.")


class PokemonRegionProposal(PokemonMapProposal, RegionProposal[Trainer]):
    operation: Operation | None = Field(default=None, description=OPERATION)
    boss_id: Slug | None = Field(default=None, description=BOSS_ID)


class RivalRecord(Mutable):
    starter_id: Slug | None = None
    due: bool = False
    ledger: list[str] = Field(default_factory=list)

    def record_battle(
        self, place_name: str, badges: int, winner: str, highlights: Sequence[str]
    ) -> None:
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
        member_level = ace_level - BELOW_ACE
        candidates = {
            evolved(species_id, member_level, species_ids) for species_id in seen_species_ids
        }
        candidates -= {ace_id, evolved(self.starter_id, member_level, species_ids)}
        others = sorted(
            candidates, key=lambda species_id: (-sum(species[species_id].base_stats), species_id)
        )
        count = min(badges, TEAM_MAX - 1)
        taken_types = set(species[ace_id].types)
        picked: list[Slug] = []
        for species_id in others:
            if len(picked) == count:
                break
            if taken_types.isdisjoint(species[species_id].types):
                picked.append(species_id)
                taken_types.update(species[species_id].types)
        picked.extend(
            [species_id for species_id in others if species_id not in picked][: count - len(picked)]
        )
        return (
            *(
                RosterSlot(species_id=species_id, level=ace_level - BELOW_ACE)
                for species_id in picked
            ),
            RosterSlot(species_id=ace_id, level=ace_level),
        )


class PokemonWorld(RoomWorld[Trainer]):
    species_ids: tuple[Slug, ...] = Field(min_length=1)
    wild: dict[Slug, tuple[WildSlot, ...]] = Field(default_factory=dict)
    battle: Battle | None = None
    pending_edge: Edge | None = None
    town_place_ids: list[Slug] = Field(default_factory=list)
    battle_background_ids: dict[Slug, BattleBackground] = Field(default_factory=dict)
    encountered_place_ids: list[Slug] = Field(default_factory=list)
    rival_record: RivalRecord = Field(default_factory=RivalRecord)
    evil_team: EvilTeam = Field(default_factory=EvilTeam)

    @model_validator(mode="after")
    def _a_trainer_on_a_map(self) -> Self:
        if self.player.roster:
            raise ValueError("the player's team is `sheet.team`; `roster` is for npc trainers")
        if strays := unknown_place_ids(self.wild, self.places):
            raise ValueError(f"wild tables for places that do not exist: {strays}")
        wild_species_ids = {slot.species_id for rows in self.wild.values() for slot in rows}
        if strays := sorted(wild_species_ids - set(self.species_ids)):
            raise ValueError(f"wild species outside `species_ids`: {strays}")
        if strays := unknown_place_ids(self.town_place_ids, self.places):
            raise ValueError(f"towns that are no place: {strays}")
        if strays := unknown_place_ids(self.battle_background_ids, self.places):
            raise ValueError(f"battle backgrounds for places that do not exist: {strays}")
        if len([npc for npc in self.npcs.values() if npc.rival]) > 1:
            raise ValueError("a world has one rival at most")
        if strays := sorted(set(self.evil_team.key_ids()) - set(self.npcs)):
            raise ValueError(f"leaders or a boss who are no npc: {strays}")
        operation = self.evil_team.operation
        if operation is not None and operation.place_id not in self.places:
            raise ValueError(f"the operation is at no place: {operation.place_id!r}")
        found_legendary_ids = legendary_ids(self.npcs.values())
        check_unique("legendary ids", found_legendary_ids)
        if strays := sorted(set(found_legendary_ids) - set(self.species_ids)):
            raise ValueError(f"legendaries outside `species_ids`: {strays}")
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
        self.evil_team.open_operation(operation, len(self.player_sheet.badges))
        leader = self.npcs[operation.leader_id]
        leader.place_id = operation.place_id
        leader.beaten = False

    def scheme_lines(self, *, worldsmith: bool) -> str:
        evil_team = self.evil_team
        scheme = evil_team.scheme
        if scheme is None:
            return ""
        done = evil_team.stage()
        lines = [
            f"{scheme.name}. Goal: {scheme.goal}",
            f"stage {done}/{SCHEME_STAGES}, foiled {evil_team.foiled()}, "
            f"succeeded {evil_team.succeeded()}",
            *(
                f"- stage {number}, {outcome}: {stage.text_for(outcome)}"
                for number, (stage, outcome) in enumerate(
                    zip(scheme.stages, evil_team.outcomes, strict=False), 1
                )
            ),
        ]
        if worldsmith and done < SCHEME_STAGES:
            upcoming = scheme.stages[done]
            lines.append(
                f"- stage {done + 1}, if foiled: {upcoming.foiled} / "
                f"if it succeeds: {upcoming.succeeded}"
            )
        lines.append(
            "leaders: " + ", ".join(self.npcs[leader_id].ref for leader_id in evil_team.leader_ids)
        )
        if (operation := evil_team.operation) is not None:
            place = self.places[operation.place_id]
            lines += [
                f"open operation at {place.ref}, led by {self.npcs[operation.leader_id].ref}: "
                f"{operation.goal}",
                SCHEME_TRIGGER,
            ]
            if not worldsmith and self.current.id in self.town_place_ids:
                lines.append(RUMOUR.format(place=place.name, goal=operation.goal))
        elif worldsmith and done < SCHEME_STAGES:
            lines.append(
                f"next operation: once the player holds {evil_team.next_operation_badges()} badges"
            )
        legendary_id = evil_team.joining_legendary_id()
        legendary = "" if legendary_id is None else f"; {dex().species_ref(legendary_id)} joins it"
        boss_id = evil_team.boss_id
        boss = "" if boss_id is None else f"; the boss is {self.npcs[boss_id].ref}"
        lines.append(
            f"final terms so far: the boss's ace is the next gym's level "
            f"+{BOSS_RISE * evil_team.succeeded()}{legendary}{boss}"
        )
        return "\n".join(lines)

    def scheme_due(self) -> SchemeDue | None:
        return self.evil_team.due(len(self.player_sheet.badges))

    def towns_line(self) -> str:
        here = self.current.id
        return ", ".join(
            self.places[place_id].ref + (" (here)" if place_id == here else "")
            for place_id in self.town_place_ids
            if self.places[place_id].known
        )

    def battle_background_of(self, place_id: Slug) -> BattleBackground:
        return self.battle_background_ids.get(
            place_id,
            TOWN_BATTLE_BACKGROUND if place_id in self.town_place_ids else ROUTE_BATTLE_BACKGROUND,
        )

    def find_rival(self) -> Trainer | None:
        return next((npc for npc in self.npcs.values() if npc.rival), None)

    def sheet_rows(self) -> Rows:
        rows = super().sheet_rows()
        ledger = self.rival_record.ledger
        return (*rows, ("Rival", "; ".join(ledger))) if ledger else rows

    def apply_opening_extras(self, opening: PokemonOpeningProposal) -> None:
        self._add_map_extras(opening)
        self.evil_team.scheme = opening.scheme
        self.open_operation(opening.operation)

    def apply_region_extras(self, region: PokemonRegionProposal) -> None:
        self._add_map_extras(region)
        if region.boss_id is not None:
            self.evil_team.boss_id = region.boss_id
        if region.operation is not None:
            self.open_operation(region.operation)

    def _add_map_extras(self, proposal: PokemonMapProposal) -> None:
        self.wild.update(proposal.wild)
        self.town_place_ids.extend(proposal.town_place_ids)
        self.battle_background_ids.update(proposal.battle_background_ids)

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
        legendary_id: Slug | None,
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
        legendary = legendary_id is not None
        catchable = trainer is None and (legendary or first_here or sheet.challenge != "nuzlocke")
        balls = (
            tuple(
                Ball(item_id=item_id, name=item_of(item_id).name, count=count)
                for item_id, count in sheet.bag.items()
                if item_of(item_id).kind == "ball"
            )
            if catchable
            else ()
        )
        if trainer is None and first_here and not legendary:
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
            battle_background=self.battle_background_of(here),
            battle_music=self._battle_music_of(trainer),
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
        self.battle = Battle(setup=setup, legendary_id=legendary_id)

    def _battle_music_of(self, trainer: Trainer | None) -> BattleMusic:
        if trainer is None:
            return "bw-trainer"
        if trainer.rival:
            return "bw-rival"
        if trainer.badge:
            return "bw2-kanto-gym-leader"
        if trainer.id in self.evil_team.key_ids():
            return "spl-elite4"
        return "bw-trainer"

    def start_wild_battle(
        self,
        species_id: Slug | None,
        rng: Random,
        *,
        weather: Weather | None,
        terrain: Terrain | None,
    ) -> list[Fact]:
        rows = self.wild_rows(species_id)
        row = rng.choices(rows, weights=[row.weight for row in rows])[0]
        level = rng.randint(row.lowest, row.highest)
        foe = Mon.new(row.species_id, level, rng, self.player_sheet.mon_ids())
        self.setup_battle(
            None,
            (foe.battler(),),
            rng,
            weather=weather,
            terrain=terrain,
            companion=None,
            legendary_id=None,
        )
        return [self.player.card_fact(f"A wild {foe.species_name} appears")]

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

    def wild_pick_refusal(self, species_id: Slug | None) -> str:
        if species_id is None or self.player_sheet.challenge != "nuzlocke":
            return ""
        return "in a Nuzlocke the wild table decides: search the grass, with no species picked"

    def wild_rows(self, species_id: Slug | None) -> tuple[WildSlot, ...]:
        here = self.current
        rows = self.wild.get(here.id, ())
        if not rows:
            raise Refusal(f"{here.name} has no wild Pokemon")
        refuse(self.wild_pick_refusal(species_id))
        sheet = self.player_sheet
        if sheet.challenge == "nuzlocke":
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

    def require_road_open(self, to_id: Slug) -> None:
        rival = self.find_rival()
        if rival is None or not rival.known or rival.place_id != self.current.id:
            return
        visited = self.visited_place_ids
        back_id = visited[-2] if len(visited) > 1 else None
        if to_id == back_id:
            return
        way_back = (
            "there is no way back yet"
            if back_id is None
            else f"only the way back to {self.places[back_id].name} is open"
        )
        raise Refusal(f"{rival.name} blocks the road until you battle: {way_back}")

    def require_town(self) -> None:
        if self.current.id not in self.town_place_ids:
            raise Refusal("no town here: a Pokemon Center and a mart are only in a town")

    def heal_team(self) -> list[Fact]:
        self.require_town()
        self.player_sheet.heal_team()
        return [self.player.card_fact("Team healed")]

    def trainer_team(self, trainer: Trainer, rng: Random) -> list[Mon]:
        sheet = self.player_sheet
        badges = len(sheet.badges)
        ace_level = sheet.table_level() - ACE_BELOW_TABLE
        if trainer.rival:
            seen_species_ids = {
                slot.species_id
                for place_id in set(self.visited_place_ids)
                for slot in self.wild.get(place_id, ())
            }
            return built_team(
                self.rival_record.roster(badges, ace_level, seen_species_ids, self.species_ids),
                badges,
                iv=RIVAL_IV,
                ev=rival_ev(badges),
            )
        iv, ev = built_iv(badges), built_ev(badges)
        if trainer.id == self.evil_team.boss_id:
            return built_team(
                self.evil_team.boss_roster(trainer, sheet.table_level(), self.species_ids),
                badges,
                iv=iv,
                ev=ev,
            )
        if trainer.id in self.evil_team.leader_ids:
            return built_team(
                rescaled(trainer.roster, ace_level, self.species_ids), badges, iv=iv, ev=ev
            )
        if trainer.badge:
            return built_team(trainer.roster, badges, iv=iv, ev=ev)
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
            mon.train(result.defeated_foes())
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
        if battle.legendary_id is not None:
            facts += self._settle_legendary(self.npcs[battle.legendary_id], result)
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

    def _settle_legendary(self, legendary: Trainer, result: BattleResult) -> list[Fact]:
        if result.outcome not in ("won", "caught"):
            legendary.last_battle_visit = len(self.visited_place_ids)
            return []
        legendary.place_id = OFF_MAP_ID
        legendary.beaten = True
        if result.outcome == "caught":
            return []
        return [legendary.card_fact(f"{legendary.name} is gone")]

    def _move_scheme(
        self, trainer: Trainer, result: BattleResult, *, badged: bool
    ) -> tuple[list[Fact], list[str]]:
        operation = self.evil_team.operation
        if operation is None:
            return [], []
        leads = trainer.id == operation.leader_id
        if leads and result.outcome == "won":
            return self._end_operation(operation, "foiled")
        if badged or (leads and result.outcome == "lost"):
            return self._end_operation(operation, "succeeded")
        return [], []

    def _end_operation(
        self, operation: Operation, outcome: Outcome
    ) -> tuple[list[Fact], list[str]]:
        stage_text = self.evil_team.record_outcome(outcome)
        headline = (FOILED if outcome == "foiled" else SUCCEEDED).format(
            place=self.places[operation.place_id].name
        )
        facts = [self.player.card_fact(f"{headline}\n{stage_text}")]
        leader = self.npcs[operation.leader_id]
        if leader.place_id == self.current.id:
            facts.append(leader.card_fact(f"{leader.name} leaves"))
        leader.place_id = OFF_MAP_ID
        return facts, [headline]

    def _rival_leaves(self, rival: Trainer, highlights: Sequence[str], *, won: bool) -> list[Fact]:
        badges = len(self.player_sheet.badges)
        here = self.current
        winner = self.player.name if won else rival.name
        self.rival_record.record_battle(here.name, badges, winner, highlights)
        rival.place_id = OFF_MAP_ID
        return [rival.card_fact(f"{rival.name} leaves")]

    def _refuse_key(self, entity_id: Slug) -> None:
        person = self.find_person(entity_id)
        if person is None:
            return
        if person.legendary_id is not None:
            raise Refusal(f"{person.name} is a legendary Pokemon; it does not die or join you")
        if person.is_key(self.evil_team.key_ids()):
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


def legendary_ids(npcs: Iterable[Trainer]) -> list[Slug]:
    return [npc.legendary_id for npc in npcs if npc.legendary_id]


def unknown_place_ids(place_ids: Collection[Slug], known_place_ids: Collection[Slug]) -> list[Slug]:
    return sorted(place_id for place_id in place_ids if place_id not in known_place_ids)


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
