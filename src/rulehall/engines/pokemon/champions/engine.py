from collections.abc import Sequence
from pathlib import Path
from random import Random

from rulehall.core.creation import CreationStep, Picks
from rulehall.core.decisions import DecisionOption
from rulehall.core.facts import Fact
from rulehall.core.game import AnyCharacter, AnyScenario, Character
from rulehall.core.log import Voice
from rulehall.core.prompt import Sections, lines_of, section_if
from rulehall.core.tools import NoArgs, action, tool
from rulehall.core.validation import EngineId, Slug
from rulehall.core.views import Panel, Sprite
from rulehall.engines.args import Words
from rulehall.engines.engine import Joining
from rulehall.engines.pokemon.battle.battling import ShowdownBattling
from rulehall.engines.pokemon.champions.args import (
    ApplyPreset,
    LoadTemplate,
    MoveSlot,
    Recruit,
    SaveTeam,
    SetSlot,
)
from rulehall.engines.pokemon.champions.data import CompetitiveSet, champions_data
from rulehall.engines.pokemon.champions.pack import ChampionsPack
from rulehall.engines.pokemon.champions.panels import SHEET_HELP, season_panel, team_panel
from rulehall.engines.pokemon.champions.rules import (
    RECRUITS_PER_EVENT,
    TEAM_SLOT_PREFIX,
    build_rival,
    require_archetype,
    require_preset,
    require_template,
)
from rulehall.engines.pokemon.champions.sheet import ChampionsSheet, ChampionsTrainer, Roster
from rulehall.engines.pokemon.champions.world import (
    ChampionsGame,
    ChampionsOpeningProposal,
    ChampionsRegionProposal,
    ChampionsWorld,
    competitive_set_line,
)
from rulehall.engines.pokemon.champions.worldsmith import (
    WORLDSMITH_GUIDANCE,
    check_next,
    check_opening,
)
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import SEED_LIMIT
from rulehall.engines.pokemon.sprites import AVATAR, look_step, mon_sprite, trainer_sprite
from rulehall.engines.rooms.args import ExtendMap
from rulehall.engines.rooms.engine import RoomEngine
from rulehall.engines.sheet import PLAYER_ID

ROSTER = "roster"
TEAM = "team"
ROSTERS: dict[Roster, tuple[str, str]] = {
    "open": ("Open", "Every legal species, build freely"),
    "story": ("Story", "Start with a rental team; recruit more"),
}
SEASON_ENDED = "Worlds is played. The season is over."


class ChampionsEngine(
    ShowdownBattling,
    Joining[ChampionsWorld],
    RoomEngine[ChampionsTrainer, ChampionsWorld, ChampionsPack, ChampionsRegionProposal],
):
    id = EngineId("pokemon-champions")
    title = "POKEMON"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Bright anime-style illustration, clean lines, soft colours, no text or lettering."
    portraits = False
    directory = Path(__file__).parent
    pack_model = ChampionsPack
    world_model = ChampionsWorld
    person_model = ChampionsTrainer
    opening_model = ChampionsOpeningProposal
    next_proposal_model = ChampionsRegionProposal
    sheet_help = SHEET_HELP
    # Each new game draws a fresh season; a test sets a seeded Random here.
    season_seeds = Random()

    @property
    def door_id(self) -> EngineId:
        return EngineId("pokemon")

    @property
    def mode_name(self) -> str:
        return "Champions"

    def creation_steps(self, _pack_id: Slug, _picks: Picks) -> tuple[CreationStep, ...]:
        species = dex().species
        rosters = tuple(
            DecisionOption(id=roster, name=name, brief=brief)
            for roster, (name, brief) in ROSTERS.items()
        )
        teams = tuple(
            DecisionOption(
                id=archetype.archetype_id,
                name=archetype.name,
                brief=", ".join(species[each.species_id].name for each in archetype.team.sets),
            )
            for archetype in champions_data().archetypes
        )
        return (
            CreationStep(
                id=ROSTER,
                name="Roster",
                options=rosters,
                help="Which Pokemon the player can build with; it holds for the whole season.",
            ),
            CreationStep(
                id=TEAM,
                name="Team",
                options=teams,
                help="The team of six the season starts with; you edit it between events.",
            ),
            look_step(),
        )

    def build_character(
        self, name: str, brief: str, voice: Voice, _pack_id: Slug, picks: Picks
    ) -> Character[ChampionsTrainer]:
        sets = require_archetype(picks.get(TEAM, "")).team.sets
        roster: Roster = next(key for key in ROSTERS if key == picks.get(ROSTER, ""))
        player = ChampionsTrainer(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            voice=voice,
            known=True,
            place_id=PLAYER_ID,
            avatar_id=picks.get(AVATAR, ""),
            sheet=ChampionsSheet(
                roster=roster,
                team=list(sets),
                owned_species_ids=[each.species_id for each in sets],
                recruits_left=RECRUITS_PER_EVENT,
            ),
        )
        return self.character_of(name, player)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> ChampionsWorld:
        opening: ChampionsOpeningProposal = scenario.opening
        check_opening(opening)
        world = self.world_model.opening(
            opening,
            self.player_of(character),
            (),
            season_seed=self.season_seeds.randrange(SEED_LIMIT),
        )
        rival = world.find_rival()
        assert rival is not None
        rival.team = build_rival(
            [each.species_id for each in world.player_sheet.team],
            Random(f"{world.season_seed} {rival.id}"),
        )
        world.used_team_ids += [
            archetype.archetype_id
            for archetype in champions_data().archetypes
            if list(archetype.team.sets) == world.player_sheet.team
        ]
        world.install_event(opening)
        return world

    def check_next(self, draft: ChampionsGame, proposal: ChampionsRegionProposal, /) -> None:
        check_next(proposal, draft.world)

    def install_next(
        self, draft: ChampionsGame, proposal: ChampionsRegionProposal, /
    ) -> list[Fact]:
        facts = super().install_next(draft, proposal)
        draft.world.install_event(proposal)
        return facts

    def worldsmith_sections(self, draft: ChampionsGame, /) -> Sections:
        data = champions_data()
        species = dex().species
        archetypes = lines_of(
            f"- {archetype.name} ({archetype.archetype_id}): setter "
            f"{species[archetype.setter_id].name}, cores "
            + ", ".join(species[core_id].name for core_id in archetype.core_ids)
            for archetype in data.archetypes
        )
        return (
            *super().worldsmith_sections(draft),
            ("SEASON", draft.world.season_lines(worldsmith=True)),
            ("ARCHETYPES", archetypes),
            ("ACE SPECIES", ", ".join(data.pool.species_ids)),
        )

    def master_sections(self, state: ChampionsGame) -> Sections:
        world = state.world
        sheet = world.player_sheet
        species = dex().species
        owned = (
            ", ".join(species[species_id].name for species_id in sheet.owned_species_ids)
            if sheet.roster == "story"
            else ""
        )
        return (
            *super().master_sections(state),
            ("SEASON", world.season_lines(worldsmith=False)),
            *section_if("EVENT", world.event_lines()),
            ("THE TEAM", lines_of(competitive_set_line(each) for each in sheet.team)),
            *section_if("OWNED", owned),
            *_rival_section(world),
            ("TYPE CHART", dex().type_chart_text()),
        )

    def sprite(self, state: ChampionsGame, entity_id: Slug) -> Sprite | None:
        world = state.world
        team = world.player_sheet.team
        number = entity_id.removeprefix(TEAM_SLOT_PREFIX)
        if number != entity_id and number.isdecimal() and 1 <= int(number) <= len(team):
            return mon_sprite(dex().species[team[int(number) - 1].species_id])
        found = world.find_entity(entity_id)
        return trainer_sprite(found.avatar_id) if isinstance(found, ChampionsTrainer) else None

    def scene_panels(self, state: ChampionsGame, /) -> tuple[Panel | None, ...]:
        world = state.world
        return (*super().scene_panels(state), team_panel(world), season_panel(world))

    def ending(self, state: ChampionsGame) -> str | None:
        return SEASON_ENDED if state.world.season_over() else super().ending(state)

    @tool
    def register_team(self, draft: ChampionsGame, _args: NoArgs, rng: Random) -> list[Fact]:
        """Register the player's team for this map's event, at its venue, when the player signs
        up. The engine draws the field, pairs round 1 and locks the team until the event ends."""
        names = self.packs.require_joined(draft.pack_id, draft.extra_pack_ids).names
        return draft.world.register_team(names, rng)

    @tool
    def start_match(self, draft: ChampionsGame, _args: NoArgs, rng: Random) -> list[Fact]:
        """Start the player's next match of the event, against the opponent EVENT names, when
        the player sits down to play it. The battle screen plays the match, and the engine
        records the result. Call it last: it ends your turn."""
        return draft.world.start_match(rng)

    @tool
    def recruit(self, draft: ChampionsGame, args: Recruit, _rng: Random) -> list[Fact]:
        """Give the player a new Pokemon species in story mode, when the story brings one, such
        as a trade or a gift. One per event, never while the team is registered."""
        return draft.world.recruit(args.species_id, args.how)

    @tool
    def extend_map(self, draft: ChampionsGame, args: ExtendMap, rng: Random) -> list[Fact]:
        """Extend the map past its edge: the next host city and its event. Call this when MAP
        EDGE shows and the player sets out for the next event. The engine refuses while an event
        is under way. Call it last: it ends your turn."""
        draft.world.require_event_idle()
        return super().extend_map(draft, args, rng)

    @action
    def extend(self, draft: ChampionsGame, args: Words, rng: Random) -> list[Fact]:
        draft.world.require_event_idle()
        return super().extend(draft, args, rng)

    @action
    def set_slot(self, draft: ChampionsGame, args: SetSlot, _rng: Random) -> list[Fact]:
        team = list(draft.world.player_sheet.team)
        team[args.slot - 1] = args.competitive_set
        return self._replace_team(draft, team, f"Slot {args.slot} changed")

    @action
    def move_slot(self, draft: ChampionsGame, args: MoveSlot, _rng: Random) -> list[Fact]:
        team = list(draft.world.player_sheet.team)
        team.insert(args.to_slot - 1, team.pop(args.slot - 1))
        return self._replace_team(draft, team, f"Slot {args.slot} moved to slot {args.to_slot}")

    @action
    def apply_preset(self, draft: ChampionsGame, args: ApplyPreset, _rng: Random) -> list[Fact]:
        team = list(draft.world.player_sheet.team)
        team[args.slot - 1] = require_preset(args.preset_id)
        return self._replace_team(draft, team, f"Slot {args.slot} takes a preset")

    @action
    def load_template(self, draft: ChampionsGame, args: LoadTemplate, _rng: Random) -> list[Fact]:
        return self._replace_team(draft, require_template(args.template_id), "Team loaded")

    @action
    def save_team(self, draft: ChampionsGame, args: SaveTeam, _rng: Random) -> list[Fact]:
        return self._replace_team(draft, args.sets, "Team saved")

    def _replace_team(
        self, draft: ChampionsGame, sets: Sequence[CompetitiveSet], line: str
    ) -> list[Fact]:
        world = draft.world
        world.player_sheet.replace_team(sets)
        return [world.player.card_fact(line)]


def _rival_section(world: ChampionsWorld) -> Sections:
    rival = world.find_rival()
    if rival is None:
        return ()
    ledger = (f"- {line}" for line in world.rival_ledger)
    return (("THE RIVAL", "\n".join((f"{rival.ref}; style: {rival.style}", *ledger))),)
