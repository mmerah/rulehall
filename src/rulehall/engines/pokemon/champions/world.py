from collections.abc import Sequence
from random import Random
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.game import Game
from rulehall.core.validation import Frozen, Refusal, Slug, refuse
from rulehall.engines.engine import Resolution
from rulehall.engines.packs import Names
from rulehall.engines.pokemon.battle.models import (
    Battle,
    BattleBackground,
    BattleMusic,
    Battler,
    BattleResult,
    BattleSetup,
    Throw,
)
from rulehall.engines.pokemon.battle.world import BATTLE_OVER
from rulehall.engines.pokemon.champions.data import (
    Archetype,
    CompetitiveSet,
    RealTeam,
    champions_data,
)
from rulehall.engines.pokemon.champions.pending import (
    PendingSet,
    PendingTeam,
    unowned_refusal,
)
from rulehall.engines.pokemon.champions.rules import (
    RECRUITS_PER_EVENT,
    battler_of_set,
    build_key_team,
    draw_field,
    field_id,
    key_team_pools,
    require_archetype,
)
from rulehall.engines.pokemon.champions.season import (
    STRENGTH,
    TIERS,
    Entrant,
    Event,
    Tier,
)
from rulehall.engines.pokemon.champions.sheet import LOCKED, ChampionsSheet, ChampionsTrainer
from rulehall.engines.pokemon.dex import avatars, dex, species_name
from rulehall.engines.pokemon.rules import SEED_LIMIT, battle_seed
from rulehall.engines.pokemon.trainers import RivalLedger, check_one_rival, find_rival
from rulehall.engines.rooms.world import MapProposal, RegionProposal, RoomWorld
from rulehall.engines.sheet import PLAYER_ID

EVENT = (
    "The event this map hosts: its tier, its name, the venue where it is played and the "
    "battle background of its matches."
)
EVENT_OVER = (
    "The event is over. Tell how the last match ended from WHAT HAPPENED, in a few sentences, "
    "then the placing and what it earned. The player watched every move, so do not tell the "
    "fight again. The team is free to change again."
)
SEASON_OVER = (
    "Worlds is over, and with it the season. Tell how the last match ended from WHAT HAPPENED, "
    "then close the story in a short epilogue."
)
FIELD_ID_PREFIX = "field-"
TEAM_FINAL = "the season is over; the team is final"
MATCH_ON = "a match is on; edit the team after it"
NOT_LOCKED = "the team is not locked; edit it as it is"
PENDING_OPEN = "a pending team is already open"
NO_CHANGES = "the team has no unsaved changes"


class EventProposal(Frozen):
    tier: Tier = Field(description="The tier of the event; SEASON lists the tiers allowed.")
    name: str = Field(
        min_length=1,
        description="The event's name, carrying its tier, such as 'Lumiose Locals' or 'Kanto "
        "Regionals'.",
    )
    venue_id: Slug = Field(
        description="Exact id of the place of this map where the matches are played."
    )
    battle_background: BattleBackground = Field(
        description="The battle background of the venue's matches, such as 'gen3-arena'."
    )


class ChampionsMapProposal(MapProposal[ChampionsTrainer]):
    event: EventProposal = Field(description=EVENT)


class ChampionsOpeningProposal(ChampionsMapProposal):
    pass


class ChampionsRegionProposal(ChampionsMapProposal, RegionProposal[ChampionsTrainer]):
    pass


class ChampionsWorld(RoomWorld[ChampionsTrainer]):
    season_seed: int = Field(ge=0)
    event: Event | None = None
    key_trainer_ids: list[Slug] = Field(default_factory=list)
    key_team_ids: list[Slug] = Field(default_factory=list)
    rival_ledger: RivalLedger = Field(default_factory=RivalLedger)
    used_team_ids: list[Slug] = Field(default_factory=list)
    battle: Battle | None = None
    pending_team: PendingTeam | None = None

    @model_validator(mode="after")
    def _a_season_on_a_map(self) -> Self:
        check_one_rival(self.npcs.values())
        if self.event is not None and self.event.venue_id not in self.places:
            raise ValueError(f"the event is at no place: {self.event.venue_id!r}")
        if strays := sorted(set(self.key_trainer_ids) - set(self.npcs)):
            raise ValueError(f"key trainers who are no npc: {strays}")
        return self

    @property
    def player_sheet(self) -> ChampionsSheet:
        return self.player.require_sheet()

    def require_event(self) -> Event:
        if self.event is None:
            raise Refusal("no event is open")
        return self.event

    def find_rival(self) -> ChampionsTrainer | None:
        return find_rival(self.npcs.values())

    def kill(self, entity_id: Slug) -> list[Fact]:
        self._refuse_key(entity_id)
        return super().kill(entity_id)

    def join(self, person: ChampionsTrainer) -> list[Fact]:
        self._refuse_key(person.id)
        return super().join(person)

    def install_event(self, proposal: ChampionsMapProposal) -> None:
        planned = proposal.event
        pools = key_team_pools(planned.tier)
        self.key_trainer_ids = []
        self.key_team_ids = []
        for npc_id in proposal.npcs:
            npc = self.npcs[npc_id]
            if npc.archetype_id is None:
                continue
            real_team, npc.team = build_key_team(
                npc.archetype_id,
                npc.ace_species_id,
                pools,
                self.used_team_ids,
                Random(f"{self.season_seed} {npc_id}"),
            )
            if real_team is not None:
                self.used_team_ids.append(real_team.team_id)
            self.key_team_ids.append(npc.archetype_id if real_team is None else real_team.team_id)
            self.key_trainer_ids.append(npc_id)
        if (rival := self.find_rival()) is not None:
            rival.place_id = planned.venue_id
        self.event = Event(
            name=planned.name,
            tier=planned.tier,
            venue_id=planned.venue_id,
            battle_background=planned.battle_background,
        )

    def register_team(self, names: Names, rng: Random) -> list[Fact]:
        event = self.require_event()
        sheet = self.player_sheet
        player = self.player
        if self.current.id != event.venue_id:
            raise Refusal(f"registration is at {self.places[event.venue_id].name}, the venue")
        if event.stage == "done":
            raise Refusal(f"{event.name} is over; extend the map to the next event's city")
        if event.stage != "open":
            raise Refusal(f"{event.name} is already under way")
        if event.tier not in sheet.unlocked_tiers():
            raise Refusal(_locked_tier(event.tier))
        sheet.refuse_while_registered()
        registered = tuple(sheet.team)
        entrants = [
            Entrant(
                entrant_id=PLAYER_ID,
                name=player.name,
                avatar_id=player.avatar_id,
                style="",
                sets=registered,
                strength=STRENGTH["key_trainer"],
            ),
            *(self._npc_entrant(npc_id) for npc_id in self._entering_npc_ids()),
        ]
        field_size = TIERS[event.tier].field_size
        drawn = draw_field(
            event.tier, field_size - len(entrants), self.used_team_ids, self.key_team_ids, rng
        )
        self.used_team_ids.extend(field_id(each) for each in drawn)
        taken_names = {each.name for each in entrants}
        for number, each in enumerate(drawn, 1):
            name = _field_name(names, taken_names, rng)
            taken_names.add(name)
            entrants.append(
                _field_entrant(
                    each, f"{FIELD_ID_PREFIX}{number}", name, rng.choice(avatars().npc.classes).id
                )
            )
        event.register(entrants, rng.randrange(SEED_LIMIT))
        sheet.registered = registered
        opponent = event.require_player_opponent()
        line = (
            f"Registered for {event.name}: {field_size} players, "
            f"{TIERS[event.tier].swiss_rounds} Swiss rounds. The team is locked until the "
            f"event ends. Round 1: {opponent.name}"
        )
        return [player.card_fact(line)]

    def start_match(self, rng: Random) -> list[Fact]:
        if self.battle is not None:
            raise Refusal("a match is already on")
        event = self.require_event()
        if event.stage not in ("swiss", "cut"):
            raise Refusal(f"{event.name} has no match to play now")
        if self.current.id != event.venue_id:
            raise Refusal(f"the matches are played at {self.places[event.venue_id].name}")
        sheet = self.player_sheet
        registered = sheet.registered
        assert registered is not None
        player = self.player
        opponent = event.require_player_opponent()
        setup = BattleSetup(
            policy="model",
            foe_style=opponent.style,
            foe_id=opponent.entrant_id,
            player_name=player.name,
            foe_name=opponent.name,
            player_avatar_id=player.avatar_id,
            foe_avatar_id=opponent.avatar_id,
            seed=battle_seed(rng),
            battle_background=event.battle_background,
            battle_music=self._music_against(opponent, event),
            team=_battlers(registered),
            foes=_battlers(opponent.sets),
            format_id=champions_data().source.format_id,
        )
        self.battle = Battle(setup=setup)
        return [
            player.card_fact(f"{_round_name(event).capitalize()}: {player.name} vs {opponent.name}")
        ]

    def player_card_fact(self, line: str) -> Fact:
        return self.player.card_fact(line)

    def throw_ball(self, _ball_id: Slug, _foe: Battler, _rng: Random) -> Throw:
        raise Refusal("no ball is thrown in a tournament match")

    def settle_battle(self, result: BattleResult) -> tuple[Resolution, list[str]]:
        event = self.require_event()
        sheet = self.player_sheet
        player = self.player
        won = result.outcome == "won"
        opponent = event.require_player_opponent()
        round_name = _round_name(event)
        swiss = event.stage == "swiss"
        lines = event.record_player(won=won)
        facts = [
            player.card_fact(f"{round_name.capitalize()}: {lines[0]}"),
            *(player.fact(line) for line in result.highlights),
        ]
        if lines[1:]:
            facts.append(player.fact(f"Other tables: {'; '.join(lines[1:])}"))
        npc = None if opponent.npc_id is None else self.npcs[opponent.npc_id]
        if npc is not None and (line := npc.lose_line if won else npc.win_line):
            facts.append(npc.card_fact(f'{npc.name}: "{line}"'))
        if npc is not None and npc.rival:
            winner = player.name if won else npc.name
            self.rival_ledger.record_battle(
                f"{event.name}, {round_name}", winner, result.highlights
            )
        if swiss:
            record = event.require_entrant(PLAYER_ID)
            facts.append(player.card_fact(f"Record: {record.wins}-{record.losses}"))
        self.battle = None
        if event.stage != "done":
            facts.append(player.card_fact(self._next_match_line(event)))
            return Resolution(tuple(facts), BATTLE_OVER), []
        facts += self._finish_event(event, sheet)
        cue = SEASON_OVER if event.tier == "worlds" else EVENT_OVER
        return Resolution(tuple(facts), cue), []

    def require_event_idle(self) -> None:
        event = self.event
        if event is not None and event.stage in ("swiss", "cut"):
            raise Refusal(f"{event.name} is under way; the player leaves once it is over")

    def recruit(self, species_id: Slug, how: str) -> list[Fact]:
        sheet = self.player_sheet
        if sheet.roster != "story":
            raise Refusal("in an open roster every legal species is already the player's")
        sheet.refuse_while_registered()
        if not sheet.recruits_left:
            raise Refusal("the player has recruited since the last event; wait for the next")
        _ = champions_data().legal.require_species(species_id)
        if species_id in sheet.owned_species_ids:
            raise Refusal(f"the player already has {species_name(species_id)}")
        sheet.owned_species_ids.append(species_id)
        sheet.recruits_left -= 1
        name = species_name(species_id)
        return [self.player.card_fact(f"{name} joins the player: {how}")]

    def team_lock(self) -> str:
        if self.player_sheet.registered is not None:
            return LOCKED
        if self.season_over():
            return TEAM_FINAL
        return MATCH_ON if self.battle is not None else ""

    def pending_team_lock(self) -> str:
        if self.season_over():
            return TEAM_FINAL
        if self.battle is not None:
            return MATCH_ON
        if self.player_sheet.registered is not None and self.pending_team is None:
            return LOCKED
        return ""

    def require_team_editable(self) -> None:
        refuse(self.team_lock())

    def editing_team(self) -> PendingTeam:
        refuse(self.pending_team_lock())
        if self.pending_team is None:
            self.pending_team = PendingTeam.of_team(self.player_sheet.team)
        return self.pending_team

    def shown_team(self) -> PendingTeam:
        if self.season_over() or self.pending_team is None:
            return PendingTeam.of_team(self.player_sheet.team)
        return self.pending_team

    def copy_lock(self) -> str:
        if self.season_over():
            return TEAM_FINAL
        if self.player_sheet.registered is None:
            return NOT_LOCKED
        if self.battle is not None:
            return MATCH_ON
        return PENDING_OPEN if self.pending_team is not None else ""

    def copy_registered_team(self) -> None:
        refuse(self.copy_lock())
        registered = self.player_sheet.registered
        assert registered is not None
        self.pending_team = PendingTeam.of_team(registered)

    def load_pending_team(self, sets: Sequence[PendingSet | None]) -> None:
        refuse(self.pending_team_lock())
        if not any(sets):
            raise Refusal("there is no Pokemon to load")
        refuse(
            unowned_refusal(
                (each.species_id for each in sets if each), self.player_sheet.allowed_species_ids
            )
        )
        size = champions_data().legal.team_size
        self.pending_team = PendingTeam(slots=[*sets, *[None] * (size - len(sets))])

    def pending_team_dirty(self) -> bool:
        pending = self.pending_team
        if pending is None or self.season_over():
            return False
        return pending != PendingTeam.of_team(self.player_sheet.team)

    def save_pending_team(self) -> None:
        self.require_team_editable()
        if self.pending_team is None:
            raise Refusal(NO_CHANGES)
        self.player_sheet.replace_team(self.pending_team.completed())
        self.pending_team = None

    def discard_pending_team(self) -> None:
        refuse(self.pending_team_lock())
        if self.pending_team is None:
            raise Refusal(NO_CHANGES)
        self.pending_team = None

    def season_lines(self, *, worldsmith: bool) -> str:
        sheet = self.player_sheet
        unlocked = sheet.unlocked_tiers()
        if worldsmith:
            names = ", ".join(f"{TIERS[tier].name} ({tier})" for tier in unlocked)
            return f"CP {sheet.cp()}; tiers allowed for the next event: {names}"
        lines = [
            f"CP {sheet.cp()}; open tiers: " + ", ".join(TIERS[tier].name for tier in unlocked),
            *(
                f"- {finish.event_name}: placed {finish.placing} ({finish.record}), +{finish.cp} CP"
                for finish in sheet.finishes
            ),
        ]
        return "\n".join(lines)

    def event_lines(self) -> str:
        event = self.event
        if event is None:
            return ""
        venue = self.places[event.venue_id]
        lines = [
            f"{event.name}, {TIERS[event.tier].name} at {venue.ref}; stage: {event.stage}",
        ]
        if event.stage == "open":
            lines.append("registration is open: call `register_team` when the player signs up")
            return "\n".join(lines)
        player = event.require_entrant(PLAYER_ID)
        lines.append(f"{_round_name(event)}; the player's record: {player.wins}-{player.losses}")
        lines += [
            f"- {rank}. {each.name} {each.wins}-{each.losses}"
            for rank, each in event.shown_standings()
        ]
        if event.stage == "done":
            lines.append(f"over: the player placed {event.placing}")
            return "\n".join(lines)
        opponent = event.require_player_opponent()
        if opponent.npc_id is None:
            lines.append(f"next opponent: {opponent.name}, a field team")
        else:
            npc = self.npcs[opponent.npc_id]
            lines.append(f"next opponent: {npc.ref}; {opponent.style}")
        return "\n".join(lines)

    def season_over(self) -> bool:
        return any(finish.tier == "worlds" for finish in self.player_sheet.finishes)

    def _finish_event(self, event: Event, sheet: ChampionsSheet) -> list[Fact]:
        player = self.player
        unlocked = sheet.unlocked_tiers()
        finish = event.finish()
        sheet.finishes.append(finish)
        sheet.registered = None
        sheet.recruits_left = RECRUITS_PER_EVENT
        assert event.winner_id is not None
        winner = event.require_entrant(event.winner_id).name
        facts = [
            player.card_fact(
                f"{event.name} is over: {player.name} places {finish.placing} ({finish.record}), "
                f"+{finish.cp} CP. {winner} wins the event"
            )
        ]
        facts += [
            player.card_fact(f"{TIERS[tier].name} is open to {player.name} now")
            for tier in sheet.unlocked_tiers()
            if tier not in unlocked
        ]
        return facts

    def _next_match_line(self, event: Event) -> str:
        opponent = event.require_player_opponent()
        cut = TIERS[event.tier].cut_size
        if event.stage == "cut" and event.round == 1 and len(event.bracket) == cut:
            return f"{self.player.name} makes the top {cut}. Next: {opponent.name}"
        return f"Next, {_round_name(event)}: {opponent.name}"

    def _music_against(self, opponent: Entrant, event: Event) -> BattleMusic:
        if opponent.npc_id is not None and self.npcs[opponent.npc_id].rival:
            return "bw-rival"
        return "spl-elite4" if event.stage == "cut" else "bw-trainer"

    def _entering_npc_ids(self) -> list[Slug]:
        rival = self.find_rival()
        rival_ids = [] if rival is None or not rival.alive else [rival.id]
        return [*rival_ids, *(npc_id for npc_id in self.key_trainer_ids if self.npcs[npc_id].alive)]

    def _npc_entrant(self, npc_id: Slug) -> Entrant:
        npc = self.npcs[npc_id]
        archetype = "" if npc.archetype_id is None else require_archetype(npc.archetype_id).name
        return Entrant(
            entrant_id=npc.id,
            name=npc.name,
            avatar_id=npc.avatar_id,
            style="; ".join(part for part in (archetype, npc.style) if part),
            sets=npc.team,
            strength=STRENGTH["rival" if npc.rival else "key_trainer"],
            npc_id=npc.id,
        )

    def _refuse_key(self, entity_id: Slug) -> None:
        person = self.find_person(entity_id)
        if person is not None and person.is_key():
            raise Refusal(
                f"{person.name} has a part to play in the season; they do not die or join you"
            )


ChampionsGame = Game[ChampionsWorld]


def competitive_set_line(competitive_set: CompetitiveSet) -> str:
    pokedex = dex()
    species = pokedex.require_species(competitive_set.species_id)
    moves = ", ".join(pokedex.moves[move_id].name for move_id in competitive_set.move_ids)
    points = "/".join(str(points) for points in competitive_set.sp)
    return (
        f"- {pokedex.species_ref(competitive_set.species_id)} @ "
        f"{pokedex.item_name(competitive_set.item_id)}; "
        f"{pokedex.ability_names[competitive_set.ability_id]}; {competitive_set.nature}; "
        f"SP {points}; moves: {moves} — {species.entry}"
    )


def _field_entrant(
    drawn: RealTeam | Archetype, entrant_id: Slug, name: str, avatar_id: Slug
) -> Entrant:
    if isinstance(drawn, Archetype):
        return Entrant(
            entrant_id=entrant_id,
            name=name,
            avatar_id=avatar_id,
            style=drawn.name,
            sets=drawn.team.sets,
            strength=STRENGTH["archetype"],
        )
    return Entrant(
        entrant_id=entrant_id,
        name=name,
        avatar_id=avatar_id,
        style=require_archetype(drawn.archetype_ids[0]).name,
        sets=drawn.sets,
        strength=STRENGTH[drawn.pool],
    )


def _field_name(names: Names, taken: set[str], rng: Random) -> str:
    firsts = [*names.female, *names.male, *names.neutral]
    choices = [
        name
        for first in firsts
        for surname in names.surnames
        if (name := f"{first} {surname[0]}.") not in taken
    ]
    return rng.choice(choices)


def _battlers(sets: tuple[CompetitiveSet, ...]) -> tuple[Battler, ...]:
    return tuple(battler_of_set(each, each.species_id) for each in sets)


def _round_name(event: Event) -> str:
    if event.stage == "cut":
        return {2: "the final", 4: "the semifinal"}.get(len(event.bracket), "the quarterfinal")
    return f"round {event.round}"


def _locked_tier(tier: Tier) -> str:
    if tier == "worlds":
        return f"Worlds needs an invite: {TIERS['worlds'].unlock_cp} CP, and it is played once"
    return f"{TIERS[tier].name} opens at {TIERS[tier].unlock_cp} CP"
