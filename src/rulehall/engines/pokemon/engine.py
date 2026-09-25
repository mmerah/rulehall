from pathlib import Path
from random import Random
from typing import cast

from rulehall.core.creation import CreationStep, Picks, picked
from rulehall.core.facts import Fact, roll
from rulehall.core.model import AnyCharacter, AnyScenario, Character, RoleAnswer
from rulehall.core.play import DecisionOption
from rulehall.core.prompt import Sections, lines_of, section_if
from rulehall.core.tools import NoArgs, action, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import PlayerView, Sprite, tag_of
from rulehall.engines.engine import Resolution, Transport
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.hiring import Joining
from rulehall.engines.pokemon.args import (
    DIFFICULTY,
    ChosenMon,
    EvolveInto,
    GainMoney,
    HoldItem,
    ItemCount,
    LearnMove,
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
from rulehall.engines.pokemon.dex import avatars, dex
from rulehall.engines.pokemon.pack import WORLDSMITH_GUIDANCE, PokemonHead, PokemonPack
from rulehall.engines.pokemon.panels import item_sprite, mon_sprite, team_panels, trainer_sprite
from rulehall.engines.pokemon.rules import (
    HELP_BONUS,
    ITEMS,
    RANKS_AT_CREATION,
    RANKS_PER_SKILL_AT_CREATION,
    SKILL_BONUS,
    SKILL_USES,
    SKILLS,
    START_BAG,
    START_MONEY,
    STARTER_LEVEL,
    TIMES,
    Skill,
    catch_rate,
    item_of,
    succeeds,
)
from rulehall.engines.pokemon.world import (
    Mon,
    PokemonGame,
    PokemonMap,
    PokemonRegion,
    PokemonWorld,
    Trainer,
    TrainerSheet,
    unknown_wild_places,
)
from rulehall.engines.rooms.engine import RoomEngine
from rulehall.engines.rooms.world import RegionProposal

SIMULATOR = SHOWDOWN / "node_modules" / "pokemon-showdown" / "pokemon-showdown"
SETUP_HINT = (
    "The battle simulator is not installed. "
    "Run `npm --prefix src/rulehall/engines/pokemon/showdown run setup`, then start the app again."
)
STARTER = "starter"
AVATAR = "avatar"
BATTLE_OVER = (
    "The battle is over. Tell how it ended from WHAT HAPPENED, in a few sentences. The player "
    "watched every move, so do not tell the fight again. Settle nothing else."
)


class PokemonEngine(Joining, RoomEngine[Trainer, PokemonWorld, PokemonPack]):
    id = EngineId("pokemon")
    title = "POKEMON"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Bright anime-style illustration, clean lines, soft colours, no text or lettering."
    portraits = False
    directory = Path(__file__).parent
    assets = Path(__file__).parents[4] / "vendor" / "showdown"
    battle_script = SHOWDOWN / "view.js"
    pack = PokemonPack
    head = PokemonHead
    world = PokemonWorld
    person = Trainer
    opening = PokemonMap
    next_proposal = PokemonRegion

    def creation_steps(self, pack_id: Slug, picks: Picks) -> tuple[CreationStep, ...]:
        ranks = _rank_picks(picks)
        rank_steps = tuple(
            CreationStep(
                id=f"rank-{number}",
                name=f"Skill rank {number}",
                options=tuple(
                    DecisionOption(id=skill, name=skill.title(), brief=SKILL_USES[skill])
                    for skill in SKILLS
                    if ranks[: number - 1].count(skill) < RANKS_PER_SKILL_AT_CREATION
                ),
            )
            for number in range(1, RANKS_AT_CREATION + 1)
        )
        starters = tuple(
            DecisionOption(id=species_id, name=dex().require(species_id).name)
            for species_id in self.packs.require(pack_id).starters
        )
        looks = tuple(
            DecisionOption(
                id=avatar_id, name=avatar_id.title(), sprite=str(trainer_sprite(avatar_id).path)
            )
            for avatar_id in avatars().player
        )
        return (
            *rank_steps,
            CreationStep(id=STARTER, name="Starter", options=starters),
            CreationStep(id=AVATAR, name="Look", options=looks),
        )

    def build_character(
        self, name: str, brief: str, _pack_id: Slug, picks: Picks
    ) -> Character[Trainer]:
        ranks = _rank_picks(picks)
        skills: dict[Skill, int] = {skill: ranks.count(skill) for skill in SKILLS}
        starter = Mon.new(picked(picks, STARTER), STARTER_LEVEL, Random(name), ())
        player = Trainer(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            place_id=PLAYER_ID,
            avatar_id=picked(picks, AVATAR),
            sheet=TrainerSheet(
                skills=skills, money=START_MONEY, bag=dict(START_BAG), team=[starter]
            ),
        )
        return self.sheet_character(name, player)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> PokemonWorld:
        world = super().new_game(scenario, character)
        self._check_wild_and_species(scenario.pack_id, scenario.opening)
        return world

    def check_next(self, draft: PokemonGame, proposal: RegionProposal[Trainer]) -> None:
        super().check_next(draft, proposal)
        # Safe: the engine's `next_proposal` makes every region a PokemonRegion.
        self._check_wild_and_species(draft.pack_id, cast(PokemonRegion, proposal))

    def sprite(self, state: PokemonGame, entity_id: Slug) -> Sprite | None:
        world = state.world
        found = world.entity(entity_id)
        if isinstance(found, Trainer):
            return trainer_sprite(found.avatar_id)
        sheet = world.player.require_sheet()
        if entity_id in sheet.bag or entity_id in ITEMS:
            return item_sprite(entity_id)
        mon = next((mon for mon in (*sheet.team, *sheet.box) if mon.mon_id == entity_id), None)
        return None if mon is None else mon_sprite(mon.species)

    def _check_wild_and_species(self, pack_id: Slug, proposal: PokemonMap) -> None:
        if strays := unknown_wild_places(proposal.wild, proposal.places):
            raise Refusal(f"wild tables for places this map does not add: {strays}")
        used = {slot.species_id for rows in proposal.wild.values() for slot in rows} | {
            slot.species_id for npc in proposal.npcs.values() for slot in npc.roster
        }
        if strays := sorted(used - set(self._species_pool(pack_id))):
            raise Refusal(f"species outside this region: {strays}. Use only ids from SPECIES")

    def _species_pool(self, pack_id: Slug) -> tuple[Slug, ...]:
        return self.packs.require(pack_id).species

    def master_sections(self, state: PokemonGame) -> Sections:
        world = state.world
        sheet = world.player.require_sheet()
        pokedex = dex()
        wild = "\n".join(
            f"- {pokedex.tag(slot.species_id)} L{slot.lowest}-{slot.highest}, "
            f"weight {slot.weight} — {pokedex.species[slot.species_id].entry}"
            for slot in world.wild.get(world.current.id, ())
        )
        return (
            *super().master_sections(state),
            ("TYPE CHART", pokedex.type_chart_text()),
            ("THE TEAM", lines_of(mon.line() for mon in sheet.team)),
            ("THE BOX", lines_of(mon.line() for mon in sheet.box)),
            (
                "THE BAG",
                lines_of(
                    f"- {tag_of(item_of(item_id).name, item_id)} {TIMES}{count}"
                    for item_id, count in sheet.bag.items()
                ),
            ),
            *section_if("WILD HERE", wild),
        )

    def player_view(self, state: PokemonGame) -> PlayerView:
        view = super().player_view(state)
        panels = team_panels(state.world.player.require_sheet(), self._species_pool(state.pack_id))
        return view.model_copy(update={"panels": (*view.panels, *panels)})

    def accept(self, draft: PokemonGame) -> PokemonGame:
        draft.pending = draft.world.next_decision()
        return super().accept(draft)

    def in_battle(self, state: PokemonGame) -> bool:
        return state.world.battle is not None

    def simulator_argv(self) -> tuple[str, ...]:
        if not SIMULATOR.is_file():
            raise Refusal(SETUP_HINT)
        # The npm package ships built; a build run prints to stdout before the first block.
        return ("node", str(SIMULATOR), "simulate-battle", "--skip-build")

    async def open_battle(
        self, draft: PokemonGame, transport: Transport, opponent: RoleAnswer | None
    ) -> ShowdownRun:
        return await ShowdownRun.start(draft, transport, self, opponent)

    def end_battle(self, draft: PokemonGame, result: BattleResult) -> Resolution:
        facts = draft.world.settle_battle(result, self._species_pool(draft.pack_id))
        return Resolution(tuple(facts), BATTLE_OVER)

    def throw_ball(self, draft: PokemonGame, ball_id: Slug, foe: Battler, rng: Random) -> Throw:
        battle = draft.world.battle
        if battle is None or not battle.can_throw():
            raise Refusal("No ball can be thrown now. Pick a move first.")
        player = draft.world.player
        sheet = player.require_sheet()
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
        """Call this when the player tries something hard outside a battle. The engine rolls
        d20, adds twice the skill rank and 2 for a helping Pokemon, and compares the total with
        the difficulty. You decide what a failure costs."""
        world = draft.world
        player = world.player
        sheet = player.require_sheet()
        helper = None if args.helper_id is None else sheet.require_mon(args.helper_id)
        if helper is not None and helper.fainted:
            raise Refusal(f"{helper.species_name} has fainted and cannot help")
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
            + ("" if helper is None else f", helped by {helper.species_name} ({args.reason})")
            + f" → {outcome}"
        )
        return [rolled.fact, player.card_fact(line, (rolled.event,))]

    @tool
    def heal_team(self, draft: PokemonGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        """Heal the whole team and the box: HP, PP and status. Call this at a Pokemon Center."""
        player = draft.world.player
        player.require_sheet().heal_team()
        return [player.card_fact("Team healed")]

    @tool
    def buy(self, draft: PokemonGame, args: ItemCount, _rng: Random) -> list[Fact]:
        """The player buys items and pays the price."""
        player = draft.world.player
        sheet = player.require_sheet()
        item = item_of(args.item_id)
        if not item.price:
            raise Refusal(f"{item.name} is not sold; it is found or given")
        cost = item.price * args.count
        sheet.pay(cost)
        sheet.add(args.item_id, args.count)
        return [player.card_fact(f"Bought {args.count} {item.name} (₽{cost})")]

    @tool
    def gain_item(self, draft: PokemonGame, args: ItemCount, _rng: Random) -> list[Fact]:
        """The player finds or gets items for free."""
        player = draft.world.player
        player.require_sheet().add(args.item_id, args.count)
        return [player.card_fact(f"Got {args.count} {item_of(args.item_id).name}")]

    @tool
    def gain_money(self, draft: PokemonGame, args: GainMoney, _rng: Random) -> list[Fact]:
        """The player gets money, such as a reward."""
        player = draft.world.player
        player.require_sheet().money += args.amount
        return [player.card_fact(f"Got ₽{args.amount}")]

    @tool
    @action
    def use_item(self, draft: PokemonGame, args: UseItem, _rng: Random) -> list[Fact]:
        """The player uses a potion, a super potion, a full heal, a revive, a Rare Candy, a stone,
        another evolution item or a Linking Cord on a team Pokemon, outside a battle."""
        return draft.world.use_item(args.item_id, args.mon_id, self._species_pool(draft.pack_id))

    @tool
    @action
    def swap_mon(self, draft: PokemonGame, args: SwapMon, _rng: Random) -> list[Fact]:
        """Swap a team Pokemon with one in the box. The player can do this anywhere from the Team
        page."""
        return draft.world.swap_mon(args.team_mon_id, args.box_mon_id)

    @action
    def hold_item(self, draft: PokemonGame, args: HoldItem, _rng: Random) -> list[Fact]:
        return draft.world.hold_item(args.mon_id, args.item_id)

    @action
    def teach_move(self, draft: PokemonGame, args: TeachMove, _rng: Random) -> list[Fact]:
        return draft.world.teach_move(args.mon_id, args.item_id)

    @action
    def relearn_move(self, draft: PokemonGame, args: RelearnMove, _rng: Random) -> list[Fact]:
        return draft.world.relearn_move(args.mon_id, args.move_id)

    @action
    def store_mon(self, draft: PokemonGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.store_mon(args.mon_id)

    @action
    def withdraw_mon(self, draft: PokemonGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.withdraw_mon(args.mon_id)

    @action
    def lead_mon(self, draft: PokemonGame, args: ChosenMon, _rng: Random) -> list[Fact]:
        return draft.world.lead_mon(args.mon_id)

    @tool
    def start_battle(self, draft: PokemonGame, args: StartBattle, rng: Random) -> list[Fact]:
        """Call this when a trainer here and the player agree to battle. The battle screen plays
        the fight, and the engine applies the result. Call it last: it ends your turn. A trainer
        battles once per visit. A gym leader never battles again once beaten."""
        world = draft.world
        trainer = world.require_person_here(args.trainer_id)
        if not trainer.roster:
            raise Refusal(f"{trainer.name} has no team and does not battle")
        if trainer.badge and trainer.beaten:
            raise Refusal(f"{trainer.name} is beaten and gives no rematch")
        if trainer.last_battle_visit == len(world.visits):
            raise Refusal(f"{trainer.name} already battled you on this visit; come back later")
        if not trainer.team:
            for slot in trainer.roster:
                trainer.team.append(
                    Mon.new(slot.species_id, slot.level, rng, [mon.mon_id for mon in trainer.team])
                )
        foes = tuple(mon.battler() for mon in trainer.team)
        world.setup_battle(trainer, foes, rng)
        return [trainer.card_fact(f"{trainer.name} challenges you to a battle")]

    @tool
    def start_wild_battle(
        self, draft: PokemonGame, args: StartWildBattle, rng: Random
    ) -> list[Fact]:
        """Call this when the player meets a wild Pokemon at this place, such as in tall grass.
        Set `species_id` to one from WILD HERE, or leave it null to roll on the table. Call it
        last: it ends your turn."""
        world = draft.world
        rows = world.wild.get(world.current.id, ())
        if not rows:
            raise Refusal(f"{world.current.name} has no wild Pokemon")
        if args.species_id is not None:
            rows = tuple(row for row in rows if row.species_id == args.species_id)
            if not rows:
                raise Refusal(f"{args.species_id!r} is not in WILD HERE")
        row = rng.choices(rows, weights=[row.weight for row in rows])[0]
        level = rng.randint(row.lowest, row.highest)
        foe = Mon.new(row.species_id, level, rng, world.player.require_sheet().mon_ids())
        world.setup_battle(None, (foe.battler(),), rng)
        return [world.player.card_fact(f"A wild {foe.species_name} appears")]

    @action
    def learn_move(self, draft: PokemonGame, args: LearnMove, _rng: Random) -> list[Fact]:
        return draft.world.learn_move(args.mon_id, args.move_id, args.forget_id)

    @action
    def evolve(self, draft: PokemonGame, args: EvolveInto, _rng: Random) -> list[Fact]:
        return draft.world.evolve(args.mon_id, args.species_id, self._species_pool(draft.pack_id))

    @action
    def raise_skill(self, draft: PokemonGame, args: RaiseSkill, _rng: Random) -> list[Fact]:
        return draft.world.raise_skill(args.skill)


def _rank_picks(picks: Picks) -> list[str]:
    return [picked(picks, f"rank-{number}") for number in range(1, RANKS_AT_CREATION + 1)]
