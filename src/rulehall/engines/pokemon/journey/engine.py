from pathlib import Path
from random import Random

from rulehall.core.creation import CreationStep, Picks
from rulehall.core.decisions import DecisionOption
from rulehall.core.facts import Fact, roll
from rulehall.core.game import AnyCharacter, AnyScenario, Character
from rulehall.core.log import Voice
from rulehall.core.prompt import Sections, lines_of, ref_of, section_if, sentence
from rulehall.core.tools import NoArgs, action, tool
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import Panel, Sprite
from rulehall.engines.engine import Joining
from rulehall.engines.pokemon.battle.battling import ShowdownBattling
from rulehall.engines.pokemon.dex import ITEMS, dex
from rulehall.engines.pokemon.door import ART_STYLE, DOOR_ID, TITLE
from rulehall.engines.pokemon.journey.args import (
    DIFFICULTY,
    ChosenMon,
    EvolveInto,
    GainMoney,
    HoldItem,
    ItemCount,
    LearnMove,
    Nickname,
    RaiseSkill,
    RelearnMove,
    SkillCheck,
    StartBattle,
    StartWildBattle,
    SwapMon,
    TeachMove,
    UseItem,
    WildPick,
)
from rulehall.engines.pokemon.journey.pack import JourneyHead, JourneyPack
from rulehall.engines.pokemon.journey.panels import (
    SHEET_HELP,
    WILD_ICON_PREFIX,
    bag_panel,
    bag_sprite,
    box_panel,
    pending_decision,
    scheme_panel,
    team_panel,
    wild_panel,
)
from rulehall.engines.pokemon.journey.rules import (
    CHALLENGES,
    FRIENDSHIP_PER_HELP,
    RANKS_AT_CREATION,
    RANKS_PER_SKILL_AT_CREATION,
    SKILL_BONUS,
    SKILL_USES,
    SKILLS,
    START_BAG,
    START_MONEY,
    STARTER_LEVEL,
    Challenge,
    Skill,
    counter_pick,
    help_bonus,
    item_of,
)
from rulehall.engines.pokemon.journey.sheet import JourneySheet, JourneyTrainer, Mon
from rulehall.engines.pokemon.journey.world import (
    JourneyGame,
    JourneyOpeningProposal,
    JourneyRegionProposal,
    JourneyWorld,
    challenge_line,
)
from rulehall.engines.pokemon.journey.worldsmith import (
    DUE_ASKS,
    WORLDSMITH_GUIDANCE,
    check_next,
    check_opening,
)
from rulehall.engines.pokemon.rules import TIMES, succeeds
from rulehall.engines.pokemon.sprites import AVATAR, look_step, mon_sprite, trainer_sprite
from rulehall.engines.rooms.args import MoveTo
from rulehall.engines.rooms.engine import RoomEngine
from rulehall.engines.sheet import PLAYER_ID

SCHEME = "THE SCHEME"
STARTER = "starter"
CHALLENGE = "challenge"
FIRST_MET = "your first Pokemon"
TEAM_FALLEN = "Your whole team has fallen. The journey ends."
TEAM_BEATEN = "The team is beaten. Your journey is complete."
EDGE_LINE = "{edge}: the next battle here starts with it. It is lost when the player leaves."


class JourneyEngine(
    ShowdownBattling[JourneyTrainer, JourneyWorld, JourneyPack, JourneyRegionProposal],
    Joining[JourneyWorld],
    RoomEngine[JourneyTrainer, JourneyWorld, JourneyPack, JourneyRegionProposal],
):
    id = DOOR_ID
    title = TITLE
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = ART_STYLE
    portraits = False
    directory = Path(__file__).parent
    pack_model = JourneyPack
    pack_head_model = JourneyHead
    world_model = JourneyWorld
    person_model = JourneyTrainer
    opening_model = JourneyOpeningProposal
    next_proposal_model = JourneyRegionProposal
    sheet_help = SHEET_HELP

    @property
    def mode_name(self) -> str:
        return "Journey"

    def creation_steps(self, pack_id: Slug, picks: Picks) -> tuple[CreationStep, ...]:
        ranks = _rank_picks(picks)
        rank_steps = tuple(
            CreationStep(
                id=f"rank-{number}",
                name=f"Skill rank {number}",
                help=SHEET_HELP["Skills"],
                options=tuple(
                    DecisionOption(id=skill, name=skill.title(), brief=SKILL_USES[skill])
                    for skill in SKILLS
                    if ranks[: number - 1].count(skill) < RANKS_PER_SKILL_AT_CREATION
                ),
            )
            for number in range(1, RANKS_AT_CREATION + 1)
        )
        starters = tuple(
            DecisionOption(id=species_id, name=dex().require_species(species_id).name)
            for species_id in self.packs.require_pack(pack_id).starters
        )
        challenges = tuple(
            DecisionOption(id=challenge, name=challenge.title(), brief=brief)
            for challenge, brief in CHALLENGES.items()
        )
        return (
            *rank_steps,
            CreationStep(
                id=STARTER,
                name="Starter",
                options=starters,
                help="Your first Pokemon; your rival picks the starter that beats it.",
            ),
            CreationStep(
                id=CHALLENGE,
                name="Challenge",
                options=challenges,
                help="How hard the journey is; it holds for the whole game.",
            ),
            look_step(),
        )

    def build_character(
        self, name: str, brief: str, voice: Voice, _pack_id: Slug, picks: Picks
    ) -> Character[JourneyTrainer]:
        ranks = _rank_picks(picks)
        skills: dict[Skill, int] = {skill: ranks.count(skill) for skill in SKILLS}
        starter = Mon.new(picks.get(STARTER, ""), STARTER_LEVEL, Random(name), ())
        starter.met = FIRST_MET
        challenge: Challenge = next(key for key in CHALLENGES if key == picks.get(CHALLENGE, ""))
        player = JourneyTrainer(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            voice=voice,
            known=True,
            place_id=PLAYER_ID,
            avatar_id=picks.get(AVATAR, ""),
            sheet=JourneySheet(
                skills=skills,
                money=START_MONEY,
                bag=dict(START_BAG),
                team=[starter],
                challenge=challenge,
                caught_species_ids=[starter.species_id],
            ),
        )
        return self.character_of(name, player)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> JourneyWorld:
        opening: JourneyOpeningProposal = scenario.opening
        pack = self.packs.require_joined(scenario.pack_id, scenario.extra_pack_ids)
        check_opening(opening, pack.species_ids)
        world = self.world_model.opening(
            opening, self.player_of(character), (), species_ids=pack.species_ids
        )
        world.apply_opening_extras(opening)
        starter_id = world.player_sheet.caught_species_ids[0]
        others = [species_id for species_id in pack.starters if species_id != starter_id]
        world.rival_team.starter_id = counter_pick(
            others or pack.species_ids, dex().species[starter_id].types, STARTER_LEVEL
        )
        return world

    def check_next(self, draft: JourneyGame, proposal: JourneyRegionProposal, /) -> None:
        check_next(proposal, draft.world)

    def install_next(self, draft: JourneyGame, proposal: JourneyRegionProposal, /) -> list[Fact]:
        facts = super().install_next(draft, proposal)
        draft.world.apply_region_extras(proposal)
        return facts

    def worldsmith_sections(self, draft: JourneyGame, /) -> Sections:
        world = draft.world
        due = world.scheme_due()
        return (
            *super().worldsmith_sections(draft),
            *section_if(SCHEME, world.scheme_lines(worldsmith=True)),
            *section_if("DUE", "" if due is None else f"{sentence(DUE_ASKS[due])}."),
        )

    def sprite(self, state: JourneyGame, entity_id: Slug) -> Sprite | None:
        if entity_id.startswith(WILD_ICON_PREFIX):
            species = dex().species.get(entity_id.removeprefix(WILD_ICON_PREFIX))
            return None if species is None else mon_sprite(species)
        world = state.world
        found = world.find_entity(entity_id)
        if isinstance(found, JourneyTrainer):
            if found.legendary_id is not None:
                return mon_sprite(dex().species[found.legendary_id])
            return trainer_sprite(found.avatar_id)
        sheet = world.player_sheet
        if entity_id in sheet.bag or entity_id in ITEMS:
            return bag_sprite(entity_id)
        mon = next((mon for mon in sheet.owned() if mon.mon_id == entity_id), None)
        return None if mon is None else mon_sprite(mon.species)

    def master_sections(self, state: JourneyGame) -> Sections:
        world = state.world
        sheet = world.player_sheet
        pokedex = dex()
        wild = "\n".join(
            f"- {pokedex.species_ref(slot.species_id)} L{slot.lowest}-{slot.highest}, "
            f"weight {slot.weight} — {pokedex.species[slot.species_id].entry}"
            for slot in world.wild.get(world.current.id, ())
        )
        edge = world.pending_edge
        return (
            *super().master_sections(state),
            ("CHALLENGE", sheet.challenge_line()),
            *section_if("EDGE", "" if edge is None else EDGE_LINE.format(edge=edge)),
            *section_if("TOWNS", world.towns_line()),
            *world.rival_ledger.section(world.find_rival()),
            *section_if(SCHEME, world.scheme_lines(worldsmith=False)),
            ("TYPE CHART", pokedex.type_chart_text()),
            ("THE TEAM", lines_of(mon.line() for mon in sheet.team)),
            ("THE BOX", lines_of(mon.line() for mon in sheet.box)),
            (
                "THE BAG",
                lines_of(
                    f"- {ref_of(item_of(item_id).name, item_id)} {TIMES}{count}"
                    for item_id, count in sheet.bag.items()
                ),
            ),
            *section_if("WILD HERE", wild),
        )

    def scene_panels(self, state: JourneyGame, /) -> tuple[Panel | None, ...]:
        world = state.world
        return (
            *super().scene_panels(state),
            scheme_panel(world),
            team_panel(world),
            box_panel(world),
            bag_panel(world),
            wild_panel(world),
        )

    def ending(self, state: JourneyGame) -> str | None:
        if state.world.evil_team.boss_beaten:
            return TEAM_BEATEN
        sheet = state.world.player_sheet
        if sheet.challenge == "nuzlocke" and not sheet.able():
            return TEAM_FALLEN
        return super().ending(state)

    def accept(self, draft: JourneyGame) -> JourneyGame:
        draft.pending = pending_decision(draft.world.player_sheet)
        return super().accept(draft)

    @tool
    def check(self, draft: JourneyGame, args: SkillCheck, rng: Random) -> list[Fact]:
        """Roll a check when the player tries something hard outside a battle. The engine rolls
        d20, adds twice the skill rank and 2 to 4 for a helping Pokemon by its friendship, and
        compares the total with the difficulty. A success earns the edge the attempt aims for.
        You decide what a failure costs."""
        world = draft.world
        player = world.player
        sheet = world.player_sheet
        helper = None if args.helper_mon_id is None else sheet.require_mon(args.helper_mon_id)
        if helper is not None and helper.fainted:
            raise Refusal(f"{helper.name} has fainted and cannot help")
        here = world.current
        if args.edge == "bait" and not world.wild.get(here.id):
            raise Refusal(f"{here.name} has no wild Pokemon to bait")
        dc = DIFFICULTY[args.difficulty]
        rolled = roll((20,), f"{args.what} — {args.skill}", rng)
        helped = 0 if helper is None else help_bonus(helper.friendship)
        total = rolled.total + SKILL_BONUS * sheet.skills.get(args.skill, 0) + helped
        success = succeeds(rolled.total, total, dc)
        if helper is not None:
            helper.befriend(FRIENDSHIP_PER_HELP)
        if success and args.edge is not None:
            world.earn_edge(args.edge)
        line = (
            f"{args.what} — {args.skill.title()} {total} vs DC {dc}"
            + ("" if helper is None else f", helped by {helper.name} +{helped} ({args.reason})")
            + f" → {'success' if success else 'failure'}"
            + (f"; edge earned: {args.edge}" if success and args.edge is not None else "")
        )
        return [rolled.fact, player.card_fact(line, (rolled.event,))]

    @tool
    def heal_team(self, draft: JourneyGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        """Heal the whole team and the box: HP, PP and status. Only in a town: the engine
        refuses anywhere else."""
        return draft.world.heal_team()

    @tool
    def nickname(self, draft: JourneyGame, args: Nickname, _rng: Random) -> list[Fact]:
        """Name a Pokemon of the team or the box as the player chose."""
        return draft.world.player.nickname(args.mon_id, args.name)

    @tool
    def buy(self, draft: JourneyGame, args: ItemCount, _rng: Random) -> list[Fact]:
        """Buy items for the player at their price. Only in a town: the engine refuses anywhere
        else."""
        draft.world.require_town()
        return draft.world.player.buy(args.item_id, args.count)

    @tool
    def gain_item(self, draft: JourneyGame, args: ItemCount, _rng: Random) -> list[Fact]:
        """Give the player items they find or get for free."""
        return draft.world.player.gain_item(args.item_id, args.count)

    @tool
    def gain_money(self, draft: JourneyGame, args: GainMoney, _rng: Random) -> list[Fact]:
        """Give the player money, such as a reward."""
        return draft.world.player.gain_money(args.amount)

    @tool
    @action
    def use_item(self, draft: JourneyGame, args: UseItem, _rng: Random) -> list[Fact]:
        """Use a potion, a super potion, a full heal, a revive, a Rare Candy, a stone, another
        evolution item or a Linking Cord on a team Pokemon, outside a battle."""
        world = draft.world
        return world.player.use_item(args.item_id, args.mon_id, world.species_ids)

    @tool
    @action
    def swap_mon(self, draft: JourneyGame, args: SwapMon, _rng: Random) -> list[Fact]:
        """Swap a team Pokemon with one in the box. The player can do this anywhere from the Team
        page."""
        return draft.world.player.swap_mon(args.team_mon_id, args.box_mon_id)

    @action
    def hold_item(self, draft: JourneyGame, args: HoldItem, _rng: Random) -> list[Fact]:
        return draft.world.player.hold_item(args.mon_id, args.item_id)

    @action
    def teach_move(self, draft: JourneyGame, args: TeachMove, _rng: Random) -> list[Fact]:
        return draft.world.player.teach_move(args.mon_id, args.item_id)

    @action
    def relearn_move(self, draft: JourneyGame, args: RelearnMove, _rng: Random) -> list[Fact]:
        return draft.world.player.relearn_move(args.mon_id, args.move_id)

    @action
    def store_mon(self, draft: JourneyGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.player.store_mon(args.mon_id)

    @action
    def withdraw_mon(self, draft: JourneyGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.player.withdraw_mon(args.mon_id)

    @action
    def lead_mon(self, draft: JourneyGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.player.lead_mon(args.mon_id)

    @tool
    def move(self, draft: JourneyGame, args: MoveTo, rng: Random) -> list[Fact]:
        """Move the player through an unlocked way out of this place. While the rival waits here
        to battle, the engine refuses every way but the one back to the place the player came
        from; before the first move, it refuses every way."""
        draft.world.require_road_open(args.to_id)
        facts = super().move(draft, args, rng)
        draft.world.drop_edge()
        placed, notes = draft.world.place_rival()
        for note in notes:
            draft.note(note)
        return facts + placed

    @tool
    def start_battle(self, draft: JourneyGame, args: StartBattle, rng: Random) -> list[Fact]:
        """Start a battle when a trainer here and the player agree to one. The battle screen plays
        the fight, and the engine applies the result. Call it last: it ends your turn. A trainer
        battles once per visit. A gym leader never battles again once beaten. The rival battles
        once before the first badge, then once after each badge. A double trainer battles
        two-on-two, and the player needs two Pokemon that can fight. In a tag battle, the first
        party member with a team fights beside the player, two-on-two; the player then needs one
        Pokemon that can fight. A legendary Pokemon here battles alone as a wild Pokemon, never in
        a tag battle."""
        world = draft.world
        trainer = world.require_person_here(args.trainer_id)
        legendary_id = trainer.legendary_id
        if legendary_id is None and not trainer.roster and not trainer.rival:
            raise Refusal(f"{trainer.name} has no team and does not battle")
        if trainer.badge and trainer.beaten:
            raise Refusal(f"{trainer.name} is beaten and gives no rematch")
        if trainer.last_battle_visit == len(world.visited_place_ids):
            raise Refusal(f"{trainer.name} already battled you on this visit; come back later")
        if legendary_id is not None:
            if args.tag:
                raise Refusal(f"{trainer.name} battles alone; leave `tag` false")
            sheet = world.player_sheet
            foe = Mon.new(legendary_id, sheet.table_level(), rng, sheet.mon_ids())
            world.setup_battle(
                None,
                (foe.battler(),),
                rng,
                weather=args.weather,
                terrain=args.terrain,
                companion=None,
                legendary_id=trainer.id,
            )
            return [trainer.card_fact(f"The legendary {foe.species_name} appears")]
        companion = world.require_companion(trainer) if args.tag else None
        foes = tuple(mon.battler() for mon in world.trainer_team(trainer, rng))
        world.setup_battle(
            trainer,
            foes,
            rng,
            weather=args.weather,
            terrain=args.terrain,
            companion=companion,
            legendary_id=None,
        )
        return [trainer.card_fact(challenge_line(trainer.name, foes))]

    @tool
    def start_wild_battle(
        self, draft: JourneyGame, args: StartWildBattle, rng: Random
    ) -> list[Fact]:
        """Start a battle when the player meets a wild Pokemon here, such as in tall grass.
        Set `species_id` to one from WILD HERE, or leave it null to roll on the table; in a
        Nuzlocke, always leave it null. Call it last: it ends your turn."""
        return draft.world.start_wild_battle(
            args.species_id, rng, weather=args.weather, terrain=args.terrain
        )

    @action
    def battle_wild(self, draft: JourneyGame, args: WildPick, rng: Random) -> list[Fact]:
        return draft.world.start_wild_battle(args.species_id, rng, weather=None, terrain=None)

    @action
    def learn_move(self, draft: JourneyGame, args: LearnMove, _rng: Random) -> list[Fact]:
        return draft.world.player.learn_move(args.mon_id, args.move_id, args.forget_id)

    @action
    def evolve(self, draft: JourneyGame, args: EvolveInto, _rng: Random) -> list[Fact]:
        world = draft.world
        return world.player.evolve(args.mon_id, args.species_id, world.species_ids)

    @action
    def raise_skill(self, draft: JourneyGame, args: RaiseSkill, _rng: Random) -> list[Fact]:
        return draft.world.player.raise_skill(args.skill)


def _rank_picks(picks: Picks) -> list[str]:
    return [picks.get(f"rank-{number}", "") for number in range(1, RANKS_AT_CREATION + 1)]
