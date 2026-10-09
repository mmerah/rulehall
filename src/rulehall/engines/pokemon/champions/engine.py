from pathlib import Path
from random import Random

from rulehall.core.creation import CreationStep, Picks
from rulehall.core.decisions import DecisionOption
from rulehall.core.facts import Fact
from rulehall.core.game import AnyCharacter, AnyScenario, Character
from rulehall.core.log import Voice
from rulehall.core.prompt import Sections, lines_of, section_if
from rulehall.core.tools import NoArgs, action, edit, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import Panel, Sprite, Surface
from rulehall.engines.args import Words
from rulehall.engines.engine import Joining
from rulehall.engines.pokemon.battle.battling import ShowdownBattling
from rulehall.engines.pokemon.champions.advice import suggested_species
from rulehall.engines.pokemon.champions.args import (
    ChoiceEdit,
    MoveSlotEdit,
    PasteEdit,
    PickEdit,
    PointsEdit,
    PresetEdit,
    Recruit,
    SlotEdit,
    TemplateEdit,
)
from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.pack import ChampionsPack
from rulehall.engines.pokemon.champions.panels import SHEET_HELP, season_panel, team_panel
from rulehall.engines.pokemon.champions.paste import parse_paste
from rulehall.engines.pokemon.champions.pending import SP, SPECIES, PendingSet
from rulehall.engines.pokemon.champions.rules import (
    RECRUITS_PER_EVENT,
    TEAM_SLOT_PREFIX,
    build_rival,
    require_archetype,
    require_preset,
    require_template,
)
from rulehall.engines.pokemon.champions.sheet import ChampionsSheet, ChampionsTrainer, Roster
from rulehall.engines.pokemon.champions.team_builder import quick_spread, team_builder_surface
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
from rulehall.engines.pokemon.door import ART_STYLE, DOOR_ID, TITLE
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
    ShowdownBattling[ChampionsTrainer, ChampionsWorld, ChampionsPack, ChampionsRegionProposal],
    Joining[ChampionsWorld],
    RoomEngine[ChampionsTrainer, ChampionsWorld, ChampionsPack, ChampionsRegionProposal],
):
    id = EngineId("pokemon-champions")
    title = TITLE
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = ART_STYLE
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
        return DOOR_ID

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
            *world.rival_ledger.section(world.find_rival()),
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

    def surfaces(self, state: ChampionsGame, /) -> tuple[Surface, ...]:
        return (
            *super().surfaces(state),
            team_builder_surface(state.world, live=not self.in_battle(state)),
        )

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

    @edit
    def pick(self, draft: ChampionsGame, args: PickEdit, _rng: Random) -> None:
        world = draft.world
        team = world.editing_team()
        allowed_species_ids = world.player_sheet.allowed_species_ids
        team.pick(args.slot, args.field_id, args.choice_ids, allowed_species_ids)
        if args.preset and args.field_id == SPECIES:
            species_id = team.require_set(args.slot).species_id
            index = team.free_preset_index(args.slot, species_id)
            if index is not None:
                team.place(
                    args.slot, champions_data().presets[species_id][index], allowed_species_ids
                )

    @edit
    def set_points(self, draft: ChampionsGame, args: PointsEdit, _rng: Random) -> None:
        _require_points_field(args.field_id)
        draft.world.editing_team().set_points(args.slot, args.row, args.points)

    @edit
    def apply_quick(self, draft: ChampionsGame, args: ChoiceEdit, _rng: Random) -> None:
        _require_points_field(args.field_id)
        team = draft.world.editing_team()
        nature, sp = quick_spread(team.require_set(args.slot), args.choice_id)
        team.apply_spread(args.slot, nature, sp)

    @edit
    def apply_preset(self, draft: ChampionsGame, args: PresetEdit, _rng: Random) -> None:
        world = draft.world
        world.editing_team().place(
            args.slot, require_preset(args.preset_id), world.player_sheet.allowed_species_ids
        )

    @edit
    def move_slot(self, draft: ChampionsGame, args: MoveSlotEdit, _rng: Random) -> None:
        draft.world.editing_team().move_slot(args.slot, args.to_slot)

    @edit
    def clear_slot(self, draft: ChampionsGame, args: SlotEdit, _rng: Random) -> None:
        draft.world.editing_team().clear_slot(args.slot)

    @edit
    def import_text(self, draft: ChampionsGame, args: PasteEdit, _rng: Random) -> None:
        draft.world.load_pending_team([row.pending_set for row in parse_paste(args.text)])

    @edit
    def load_template(self, draft: ChampionsGame, args: TemplateEdit, _rng: Random) -> None:
        sets = require_template(args.template_id)
        draft.world.load_pending_team([PendingSet.of_set(each) for each in sets])

    @edit
    def copy_registered_team(self, draft: ChampionsGame, _args: NoArgs, _rng: Random) -> None:
        draft.world.copy_registered_team()

    @edit
    def fill_empty_slots(self, draft: ChampionsGame, _args: NoArgs, _rng: Random) -> None:
        world = draft.world
        team = world.editing_team()
        allowed_species_ids = world.player_sheet.allowed_species_ids
        empty = [number for number, each in enumerate(team.slots, 1) if each is None]
        suggested = suggested_species(team.slots, len(empty), allowed_species_ids)
        for number, species_id in zip(empty, suggested, strict=False):
            index = team.free_preset_index(number, species_id)
            if index is not None:
                team.place(number, champions_data().presets[species_id][index], allowed_species_ids)

    @edit
    def save(self, draft: ChampionsGame, _args: NoArgs, _rng: Random) -> None:
        draft.world.save_pending_team()

    @edit
    def discard(self, draft: ChampionsGame, _args: NoArgs, _rng: Random) -> None:
        draft.world.discard_pending_team()


def _require_points_field(field_id: Slug) -> None:
    if field_id != SP:
        raise Refusal(f"{field_id!r} is no field of stat points")
