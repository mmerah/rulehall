from pathlib import Path
from random import Random

from rulehall.core.creation import CreationStep, Picks
from rulehall.core.decisions import DecisionOption
from rulehall.core.facts import Fact, roll
from rulehall.core.game import AnyCharacter, AnyScenario, Character, RoleAnswer
from rulehall.core.prompt import Sections, lines_of, ref_of, section_if, sentence
from rulehall.core.tools import NoArgs, action, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import Panel, Sprite
from rulehall.engines.battles import Battling, Transport
from rulehall.engines.engine import Joining, Resolution
from rulehall.engines.pokemon.args import (
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
)
from rulehall.engines.pokemon.battle.models import Battler, BattleResult, Throw
from rulehall.engines.pokemon.battle.simulator import SHOWDOWN, ShowdownRun
from rulehall.engines.pokemon.dex import ITEMS, avatars, dex
from rulehall.engines.pokemon.pack import PokemonHead, PokemonPack
from rulehall.engines.pokemon.panels import (
    SHEET_HELP,
    item_sprite,
    mon_sprite,
    pending_decision,
    scheme_panels,
    team_panels,
    trainer_sprite,
)
from rulehall.engines.pokemon.rules import (
    CHALLENGES,
    HELP_BONUS,
    RANKS_AT_CREATION,
    RANKS_PER_SKILL_AT_CREATION,
    SKILL_BONUS,
    SKILL_USES,
    SKILLS,
    START_BAG,
    START_MONEY,
    STARTER_LEVEL,
    TIMES,
    Challenge,
    Skill,
    catch_rate,
    counter_pick,
    item_of,
    succeeds,
)
from rulehall.engines.pokemon.sheet import Mon, Trainer, TrainerSheet
from rulehall.engines.pokemon.world import (
    PokemonGame,
    PokemonOpeningProposal,
    PokemonRegionProposal,
    PokemonWorld,
    challenge_line,
)
from rulehall.engines.pokemon.worldsmith import (
    DUE_ASKS,
    WORLDSMITH_GUIDANCE,
    check_next,
    check_opening,
)
from rulehall.engines.rooms.args import MoveTo
from rulehall.engines.rooms.engine import RoomEngine
from rulehall.engines.sheet import PLAYER_ID

SIMULATOR = SHOWDOWN / "node_modules" / "pokemon-showdown" / "pokemon-showdown"
ASSETS = Path(__file__).parents[4] / "vendor" / "showdown"
ASSETS_COMPLETE = ASSETS / "complete"
SETUP_HINT = (
    "the battle simulator is not installed: run "
    "`npm --prefix src/rulehall/engines/pokemon/showdown run setup`, then start the app again"
)
ASSETS_HINT = (
    "the Pokemon art and sound are not fetched yet: run "
    "`npm --prefix src/rulehall/engines/pokemon/showdown run setup`, then start the app again; "
    "in Docker, the container fetches them on its first start, so wait for "
    "'Pokemon art and sound: ready' in its log"
)
SCHEME = "THE SCHEME"
STARTER = "starter"
CHALLENGE = "challenge"
AVATAR = "avatar"
FIRST_MET = "your first Pokemon"
TEAM_FALLEN = "Your whole team has fallen. The journey ends."
TEAM_BEATEN = "The team is beaten. Your journey is complete."
BOSS_BEATEN = (
    "The boss is beaten. Tell how it ended from WHAT HAPPENED, then close the story in a short "
    "epilogue."
)
BATTLE_OVER = (
    "The battle is over. Tell how it ended from WHAT HAPPENED, in a few sentences. The player "
    "watched every move, so do not tell the fight again. Settle nothing else."
)


class PokemonEngine(
    Battling, Joining, RoomEngine[Trainer, PokemonWorld, PokemonPack, PokemonRegionProposal]
):
    id = EngineId("pokemon")
    title = "POKEMON"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Bright anime-style illustration, clean lines, soft colours, no text or lettering."
    portraits = False
    directory = Path(__file__).parent
    assets = ASSETS
    battle_script = SHOWDOWN / "view.js"
    pack_model = PokemonPack
    pack_head_model = PokemonHead
    world_model = PokemonWorld
    person_model = Trainer
    opening_model = PokemonOpeningProposal
    next_proposal_model = PokemonRegionProposal
    sheet_help = SHEET_HELP

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
        looks = tuple(
            DecisionOption(
                id=avatar_id, name=avatar_id.title(), sprite=str(trainer_sprite(avatar_id).path)
            )
            for avatar_id in avatars().player
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
            CreationStep(id=AVATAR, name="Look", options=looks),
        )

    def build_character(
        self, name: str, brief: str, _pack_id: Slug, picks: Picks
    ) -> Character[Trainer]:
        ranks = _rank_picks(picks)
        skills: dict[Skill, int] = {skill: ranks.count(skill) for skill in SKILLS}
        starter = Mon.new(picks.get(STARTER, ""), STARTER_LEVEL, Random(name), ())
        starter.met = FIRST_MET
        challenge: Challenge = next(key for key in CHALLENGES if key == picks.get(CHALLENGE, ""))
        player = Trainer(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            place_id=PLAYER_ID,
            avatar_id=picks.get(AVATAR, ""),
            sheet=TrainerSheet(
                skills=skills,
                money=START_MONEY,
                bag=dict(START_BAG),
                team=[starter],
                challenge=challenge,
                caught_species_ids=[starter.species_id],
            ),
        )
        return self.character_of(name, player)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> PokemonWorld:
        opening: PokemonOpeningProposal = scenario.opening
        pack = self.packs.require_pack(scenario.pack_id)
        check_opening(opening, pack.species_ids)
        world = self.world_model.opening(
            opening, self.player_of(character), (), species_ids=pack.species_ids
        )
        starter_id = world.player_sheet.caught_species_ids[0]
        others = [species_id for species_id in pack.starters if species_id != starter_id]
        world.rival_record.starter_id = counter_pick(
            others or pack.species_ids, dex().species[starter_id].types, STARTER_LEVEL
        )
        return world

    def check_next(self, draft: PokemonGame, proposal: PokemonRegionProposal, /) -> None:
        check_next(proposal, draft.world)

    def worldsmith_sections(self, draft: PokemonGame, /) -> Sections:
        world = draft.world
        due = world.evil_team.due()
        return (
            *super().worldsmith_sections(draft),
            *section_if(SCHEME, world.scheme_lines(worldsmith=True)),
            *section_if("DUE", "" if due is None else f"{sentence(DUE_ASKS[due])}."),
        )

    def sprite(self, state: PokemonGame, entity_id: Slug) -> Sprite | None:
        world = state.world
        found = world.find_entity(entity_id)
        if isinstance(found, Trainer):
            return trainer_sprite(found.avatar_id)
        sheet = world.player_sheet
        if entity_id in sheet.bag or entity_id in ITEMS:
            return item_sprite(entity_id)
        mon = next((mon for mon in sheet.owned() if mon.mon_id == entity_id), None)
        return None if mon is None else mon_sprite(mon.species)

    def master_sections(self, state: PokemonGame) -> Sections:
        world = state.world
        sheet = world.player_sheet
        pokedex = dex()
        wild = "\n".join(
            f"- {pokedex.species_ref(slot.species_id)} L{slot.lowest}-{slot.highest}, "
            f"weight {slot.weight} — {pokedex.species[slot.species_id].entry}"
            for slot in world.wild.get(world.current.id, ())
        )
        return (
            *super().master_sections(state),
            ("CHALLENGE", sheet.challenge_line()),
            *section_if("POKEMON CENTERS", world.centers_line()),
            *_rival_section(world),
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

    def scene_panels(self, state: PokemonGame, /) -> tuple[Panel, ...]:
        world = state.world
        return (*super().scene_panels(state), *scheme_panels(world), *team_panels(world))

    def ending(self, state: PokemonGame) -> str | None:
        if state.world.evil_team.boss_beaten:
            return TEAM_BEATEN
        sheet = state.world.player_sheet
        if sheet.challenge == "nuzlocke" and not sheet.able():
            return TEAM_FALLEN
        return super().ending(state)

    def accept(self, draft: PokemonGame) -> PokemonGame:
        draft.pending = pending_decision(draft.world.player_sheet)
        return super().accept(draft)

    def in_battle(self, state: PokemonGame) -> bool:
        return state.world.battle is not None

    def simulator_argv(self) -> tuple[str, ...]:
        if not SIMULATOR.is_file():
            raise Refusal(SETUP_HINT)
        if not ASSETS_COMPLETE.is_file():
            raise Refusal(ASSETS_HINT)
        # The npm package ships built; a build run prints to stdout before the first block.
        return ("node", str(SIMULATOR), "simulate-battle", "--skip-build")

    async def open_battle(
        self, draft: PokemonGame, transport: Transport, opponent: RoleAnswer | None
    ) -> ShowdownRun:
        return await ShowdownRun.start(draft, transport, self, opponent)

    def end_battle(self, draft: PokemonGame, result: BattleResult) -> Resolution:
        facts, notes = draft.world.settle_battle(result)
        for note in notes:
            draft.note(note)
        return Resolution(
            tuple(facts), BOSS_BEATEN if draft.world.evil_team.boss_beaten else BATTLE_OVER
        )

    def throw_ball(self, draft: PokemonGame, ball_id: Slug, foe: Battler, rng: Random) -> Throw:
        battle = draft.world.battle
        if battle is None or not battle.can_throw():
            raise Refusal("no ball can be thrown now: pick a move first")
        player = draft.world.player
        sheet = draft.world.player_sheet
        ball = ITEMS.get(ball_id)
        if ball is None or ball.kind != "ball":
            raise Refusal(f"{ball_id!r} is no ball")
        sheet.take(ball_id)
        rate = catch_rate(foe, ball.catch_bonus)
        rolled = roll((100,), f"{ball.name} at {foe.name}", rng, label="d100")
        success = rolled.face == 1 or rolled.face <= rate
        line = f"{ball.name} at {foe.name} — d100 {rolled.face} vs {rate} → " + (
            "caught" if success else "it breaks free"
        )
        throw = Throw(
            ball_id=ball_id,
            caught=success,
            fact=player.card_fact(line, (rolled.event,)),
            input_index=len(battle.inputs),
        )
        battle.throws.append(throw)
        return throw

    @tool
    def check(self, draft: PokemonGame, args: SkillCheck, rng: Random) -> list[Fact]:
        """Roll a check when the player tries something hard outside a battle. The engine rolls
        d20, adds twice the skill rank and 2 for a helping Pokemon, and compares the total with
        the difficulty. You decide what a failure costs."""
        world = draft.world
        player = world.player
        sheet = world.player_sheet
        helper = None if args.helper_mon_id is None else sheet.require_mon(args.helper_mon_id)
        if helper is not None and helper.fainted:
            raise Refusal(f"{helper.name} has fainted and cannot help")
        dc = DIFFICULTY[args.difficulty]
        rolled = roll((20,), f"{args.what} — {args.skill}", rng)
        total = (
            rolled.total
            + SKILL_BONUS * sheet.skills.get(args.skill, 0)
            + (0 if helper is None else HELP_BONUS)
        )
        outcome = "success" if succeeds(rolled.total, total, dc) else "failure"
        line = (
            f"{args.what} — {args.skill.title()} {total} vs DC {dc}"
            + ("" if helper is None else f", helped by {helper.name} ({args.reason})")
            + f" → {outcome}"
        )
        return [rolled.fact, player.card_fact(line, (rolled.event,))]

    @tool
    def heal_team(self, draft: PokemonGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        """Heal the whole team and the box: HP, PP and status. Only at a Pokemon Center: the
        engine refuses anywhere else."""
        return draft.world.heal_team()

    @tool
    def nickname(self, draft: PokemonGame, args: Nickname, _rng: Random) -> list[Fact]:
        """Name a Pokemon of the team or the box as the player chose."""
        return draft.world.player.nickname(args.mon_id, args.name)

    @tool
    def buy(self, draft: PokemonGame, args: ItemCount, _rng: Random) -> list[Fact]:
        """Buy items for the player at their price."""
        return draft.world.player.buy(args.item_id, args.count)

    @tool
    def gain_item(self, draft: PokemonGame, args: ItemCount, _rng: Random) -> list[Fact]:
        """Give the player items they find or get for free."""
        return draft.world.player.gain_item(args.item_id, args.count)

    @tool
    def gain_money(self, draft: PokemonGame, args: GainMoney, _rng: Random) -> list[Fact]:
        """Give the player money, such as a reward."""
        return draft.world.player.gain_money(args.amount)

    @tool
    @action
    def use_item(self, draft: PokemonGame, args: UseItem, _rng: Random) -> list[Fact]:
        """Use a potion, a super potion, a full heal, a revive, a Rare Candy, a stone, another
        evolution item or a Linking Cord on a team Pokemon, outside a battle."""
        world = draft.world
        return world.player.use_item(args.item_id, args.mon_id, world.species_ids)

    @tool
    @action
    def swap_mon(self, draft: PokemonGame, args: SwapMon, _rng: Random) -> list[Fact]:
        """Swap a team Pokemon with one in the box. The player can do this anywhere from the Team
        page."""
        return draft.world.player.swap_mon(args.team_mon_id, args.box_mon_id)

    @action
    def hold_item(self, draft: PokemonGame, args: HoldItem, _rng: Random) -> list[Fact]:
        return draft.world.player.hold_item(args.mon_id, args.item_id)

    @action
    def teach_move(self, draft: PokemonGame, args: TeachMove, _rng: Random) -> list[Fact]:
        return draft.world.player.teach_move(args.mon_id, args.item_id)

    @action
    def relearn_move(self, draft: PokemonGame, args: RelearnMove, _rng: Random) -> list[Fact]:
        return draft.world.player.relearn_move(args.mon_id, args.move_id)

    @action
    def store_mon(self, draft: PokemonGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.player.store_mon(args.mon_id)

    @action
    def withdraw_mon(self, draft: PokemonGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.player.withdraw_mon(args.mon_id)

    @action
    def lead_mon(self, draft: PokemonGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.player.lead_mon(args.mon_id)

    @tool
    def move(self, draft: PokemonGame, args: MoveTo, rng: Random) -> list[Fact]:
        """Move the player through an unlocked way out of this place."""
        facts = super().move(draft, args, rng)
        placed, notes = draft.world.place_rival()
        for note in notes:
            draft.note(note)
        return facts + placed

    @tool
    def start_battle(self, draft: PokemonGame, args: StartBattle, rng: Random) -> list[Fact]:
        """Start a battle when a trainer here and the player agree to one. The battle screen plays
        the fight, and the engine applies the result. Call it last: it ends your turn. A trainer
        battles once per visit. A gym leader never battles again once beaten. The rival battles
        once before the first badge, then once after each badge."""
        world = draft.world
        trainer = world.require_person_here(args.trainer_id)
        if not trainer.roster and not trainer.rival:
            raise Refusal(f"{trainer.name} has no team and does not battle")
        if trainer.badge and trainer.beaten:
            raise Refusal(f"{trainer.name} is beaten and gives no rematch")
        if trainer.rival and world.rival_record.fought_at_badges == len(world.player_sheet.badges):
            raise Refusal(f"{trainer.name} will battle you again after your next badge")
        if trainer.last_battle_visit == len(world.visited_place_ids):
            raise Refusal(f"{trainer.name} already battled you on this visit; come back later")
        foes = tuple(mon.battler() for mon in world.trainer_team(trainer, rng))
        world.setup_battle(trainer, foes, rng)
        return [trainer.card_fact(challenge_line(trainer.name, foes))]

    @tool
    def start_wild_battle(
        self, draft: PokemonGame, args: StartWildBattle, rng: Random
    ) -> list[Fact]:
        """Start a battle when the player meets a wild Pokemon here, such as in tall grass.
        Set `species_id` to one from WILD HERE, or leave it null to roll on the table; in a
        Nuzlocke, always leave it null. Call it last: it ends your turn."""
        world = draft.world
        rows = world.wild_rows(args.species_id)
        row = rng.choices(rows, weights=[row.weight for row in rows])[0]
        level = rng.randint(row.lowest, row.highest)
        foe = Mon.new(row.species_id, level, rng, world.player_sheet.mon_ids())
        world.setup_battle(None, (foe.battler(),), rng)
        return [world.player.card_fact(f"A wild {foe.species_name} appears")]

    @action
    def learn_move(self, draft: PokemonGame, args: LearnMove, _rng: Random) -> list[Fact]:
        return draft.world.player.learn_move(args.mon_id, args.move_id, args.forget_id)

    @action
    def evolve(self, draft: PokemonGame, args: EvolveInto, _rng: Random) -> list[Fact]:
        world = draft.world
        return world.player.evolve(args.mon_id, args.species_id, world.species_ids)

    @action
    def raise_skill(self, draft: PokemonGame, args: RaiseSkill, _rng: Random) -> list[Fact]:
        return draft.world.player.raise_skill(args.skill)


def _rival_section(world: PokemonWorld) -> Sections:
    rival = world.find_rival()
    if rival is None:
        return ()
    ledger = (f"- {line}" for line in world.rival_record.ledger)
    return (("THE RIVAL", "\n".join((f"{rival.ref}; style: {rival.style}", *ledger))),)


def _rank_picks(picks: Picks) -> list[str]:
    return [picks.get(f"rank-{number}", "") for number in range(1, RANKS_AT_CREATION + 1)]
