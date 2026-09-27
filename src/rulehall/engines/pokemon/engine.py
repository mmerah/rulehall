from collections.abc import Collection
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
from rulehall.engines.pokemon.dex import avatars, dex
from rulehall.engines.pokemon.pack import WORLDSMITH_GUIDANCE, PokemonHead, PokemonPack
from rulehall.engines.pokemon.panels import (
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
    ITEMS,
    LEVEL_SPREAD,
    RANKS_AT_CREATION,
    RANKS_PER_SKILL_AT_CREATION,
    REGULAR_TRAINERS_MAX,
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
    is_legendary,
    item_of,
    level_for,
    succeeds,
)
from rulehall.engines.pokemon.sheet import KEY_TRAINER, Mon, Trainer, TrainerSheet
from rulehall.engines.pokemon.world import (
    Operation,
    Owed,
    PokemonGame,
    PokemonMap,
    PokemonOpening,
    PokemonRegion,
    PokemonWorld,
    Scheme,
    unknown_wild_places,
)
from rulehall.engines.rooms.args import Move
from rulehall.engines.rooms.engine import RoomEngine
from rulehall.engines.rooms.world import RegionProposal

SIMULATOR = SHOWDOWN / "node_modules" / "pokemon-showdown" / "pokemon-showdown"
ASSETS = Path(__file__).parents[4] / "vendor" / "showdown"
ASSETS_COMPLETE = ASSETS / "complete"
SETUP_HINT = (
    "The battle simulator is not installed. "
    "Run `npm --prefix src/rulehall/engines/pokemon/showdown run setup`, then start the app again."
)
ASSETS_HINT = (
    "The Pokemon art and sound are not fetched yet. "
    "Run `npm --prefix src/rulehall/engines/pokemon/showdown run setup`, then start the app again. "
    "In Docker, the container fetches them on its first start: wait for "
    "'Pokemon art and sound: ready' in its log."
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
NOT_DUE = "Leave `{field}` null: this request does not ask for it."
OWED_ASKS: dict[Owed, str] = {
    "operation": "This region carries the team's next operation: write `operation`.",
    "lair": "This region holds the team's lair: write the boss as an npc of this region with a "
    "roster, no badge and the three key lines, and name it in `boss_id`.",
}
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
    assets = ASSETS
    battle_script = SHOWDOWN / "view.js"
    pack = PokemonPack
    head = PokemonHead
    world = PokemonWorld
    person = Trainer
    opening = PokemonOpening
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
            CreationStep(id=STARTER, name="Starter", options=starters),
            CreationStep(id=CHALLENGE, name="Challenge", options=challenges),
            CreationStep(id=AVATAR, name="Look", options=looks),
        )

    def build_character(
        self, name: str, brief: str, _pack_id: Slug, picks: Picks
    ) -> Character[Trainer]:
        ranks = _rank_picks(picks)
        skills: dict[Skill, int] = {skill: ranks.count(skill) for skill in SKILLS}
        starter = Mon.new(picked(picks, STARTER), STARTER_LEVEL, Random(name), ())
        starter.met = FIRST_MET
        challenge: Challenge = next(key for key in CHALLENGES if key == picked(picks, CHALLENGE))
        player = Trainer(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            place_id=PLAYER_ID,
            avatar_id=picked(picks, AVATAR),
            sheet=TrainerSheet(
                skills=skills,
                money=START_MONEY,
                bag=dict(START_BAG),
                team=[starter],
                challenge=challenge,
                caught_species_ids=[starter.species_id],
            ),
        )
        return self.sheet_character(name, player)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> PokemonWorld:
        opening: PokemonOpening = scenario.opening
        pack = self.packs.require(scenario.pack_id)
        self._check_proposal(scenario.pack_id, opening, gyms_before=0, leader_ids=())
        _check_scheme(opening.scheme, pack.species)
        world = super().new_game(scenario, character)
        starter_id = world.player.require_sheet().caught_species_ids[0]
        others = [species_id for species_id in pack.starters if species_id != starter_id]
        world.rival_record.starter_id = counter_pick(
            others or pack.species, dex().species[starter_id].types, STARTER_LEVEL
        )
        return world

    def check_next(self, draft: PokemonGame, proposal: RegionProposal[Trainer]) -> None:
        super().check_next(draft, proposal)
        world = draft.world
        gyms = sum(1 for npc in world.npcs.values() if npc.badge)
        # Safe: the engine writes only this proposal type.
        region = cast(PokemonRegion, proposal)
        owed = world.evil_team.owed()
        operation_due, lair_due = owed == "operation", owed == "lair"
        if (region.operation is not None) != operation_due:
            raise Refusal(
                OWED_ASKS["operation"] if operation_due else NOT_DUE.format(field="operation")
            )
        if (region.boss_id is not None) != lair_due:
            raise Refusal(OWED_ASKS["lair"] if lair_due else NOT_DUE.format(field="boss_id"))
        self._check_proposal(
            draft.pack_id, region, gyms_before=gyms, leader_ids=world.evil_team.leader_ids
        )

    async def write_next(
        self, draft: PokemonGame, intent: str, worldsmith: RoleAnswer
    ) -> RegionProposal[Trainer]:
        owed = draft.world.evil_team.owed()
        asked = intent if owed is None else f"{intent}\n\n{OWED_ASKS[owed]}"
        return await super().write_next(draft, asked, worldsmith)

    def worldsmith_sections(self, draft: PokemonGame) -> Sections:
        scheme = draft.world.scheme_lines(worldsmith=True)
        return (*super().worldsmith_sections(draft), *section_if(SCHEME, scheme))

    def sprite(self, state: PokemonGame, entity_id: Slug) -> Sprite | None:
        world = state.world
        found = world.entity(entity_id)
        if isinstance(found, Trainer):
            return trainer_sprite(found.avatar_id)
        sheet = world.player.require_sheet()
        if entity_id in sheet.bag or entity_id in ITEMS:
            return item_sprite(entity_id)
        mon = next((mon for mon in sheet.owned() if mon.mon_id == entity_id), None)
        return None if mon is None else mon_sprite(mon.species)

    def _check_proposal(
        self,
        pack_id: Slug,
        proposal: PokemonOpening | PokemonRegion,
        *,
        gyms_before: int,
        leader_ids: Collection[Slug],
    ) -> None:
        opening = isinstance(proposal, PokemonOpening)
        operation = proposal.operation
        boss_id = None if opening else proposal.boss_id
        if strays := unknown_wild_places(proposal.wild, proposal.places):
            raise Refusal(f"wild tables for places this map does not add: {strays}")
        if strays := sorted(set(proposal.center_place_ids) - set(proposal.places)):
            raise Refusal(f"Pokemon Centers that this map does not add: {strays}")
        if opening and not proposal.center_place_ids:
            raise Refusal("the opening map needs a Pokemon Center in `center_place_ids`")
        trainers = list(proposal.npcs.values())
        used = {slot.species_id for rows in proposal.wild.values() for slot in rows} | {
            slot.species_id for npc in trainers for slot in npc.roster
        }
        if strays := sorted(used - set(self._species_pool(pack_id))):
            raise Refusal(f"species outside this region: {strays}. Use only ids from SPECIES")
        leader_id = None if operation is None else operation.leader_id
        named = [key_id for key_id in (leader_id, boss_id) if key_id is not None]
        if mute := [
            npc.id
            for npc in trainers
            if npc.is_key(named) and not (npc.style and npc.win_line and npc.lose_line)
        ]:
            raise Refusal(f"each {KEY_TRAINER} needs a style, a win_line and a lose_line: {mute}")
        for index, leader in enumerate((npc for npc in trainers if npc.badge), gyms_before):
            _check_ace(leader, index)
        regulars = [npc.id for npc in trainers if npc.roster and not npc.is_key(named)]
        if len(regulars) > REGULAR_TRAINERS_MAX:
            raise Refusal(
                f"at most {REGULAR_TRAINERS_MAX} people besides the key trainers battle in one "
                f"map, not {len(regulars)}: {regulars}. Give the others no roster"
            )
        rivals = [npc for npc in trainers if npc.rival]
        if opening and len(rivals) != 1:
            raise Refusal(f"the opening map needs exactly one rival, not {len(rivals)}")
        if not opening and rivals:
            raise Refusal("the rival stands in the opening map; a new region adds no rival")
        if any(rival.roster for rival in rivals):
            raise Refusal("the rival has no roster: code builds their team")
        if operation is not None:
            _check_operation(proposal, operation, leader_ids)
        boss = None if boss_id is None else proposal.npcs.get(boss_id)
        if boss_id is not None and (boss is None or not boss.roster or boss.badge):
            raise Refusal(f"the boss {boss_id!r} is a person of this map with a roster, no badge")

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
                    f"- {tag_of(item_of(item_id).name, item_id)} {TIMES}{count}"
                    for item_id, count in sheet.bag.items()
                ),
            ),
            *section_if("WILD HERE", wild),
        )

    def player_view(self, state: PokemonGame) -> PlayerView:
        view = super().player_view(state)
        world = state.world
        panels = team_panels(world.player.require_sheet(), self._species_pool(state.pack_id))
        return view.model_copy(update={"panels": (*view.panels, *scheme_panels(world), *panels)})

    def ending(self, state: PokemonGame) -> str | None:
        if state.world.evil_team.boss_beaten:
            return TEAM_BEATEN
        sheet = state.world.player.require_sheet()
        if sheet.challenge == "nuzlocke" and not sheet.able():
            return TEAM_FALLEN
        return super().ending(state)

    def accept(self, draft: PokemonGame) -> PokemonGame:
        draft.pending = pending_decision(draft.world)
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
        facts, notes = draft.world.settle_battle(result, self._species_pool(draft.pack_id))
        for note in notes:
            draft.note(note)
        return Resolution(
            tuple(facts), BOSS_BEATEN if draft.world.evil_team.boss_beaten else BATTLE_OVER
        )

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
        """The player names a Pokemon of the team or the box."""
        return draft.world.nickname(args.mon_id, args.name)

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
    def move(self, draft: PokemonGame, args: Move, rng: Random) -> list[Fact]:
        """Move the player through an unlocked way out of this place."""
        facts = super().move(draft, args, rng)
        placed, notes = draft.world.place_rival()
        for note in notes:
            draft.note(note)
        return facts + placed

    @tool
    def start_battle(self, draft: PokemonGame, args: StartBattle, rng: Random) -> list[Fact]:
        """Call this when a trainer here and the player agree to battle. The battle screen plays
        the fight, and the engine applies the result. Call it last: it ends your turn. A trainer
        battles once per visit. A gym leader never battles again once beaten. The rival battles
        once before the first badge, then once after each badge."""
        world = draft.world
        trainer = world.require_person_here(args.trainer_id)
        if not trainer.roster and not trainer.rival:
            raise Refusal(f"{trainer.name} has no team and does not battle")
        if trainer.badge and trainer.beaten:
            raise Refusal(f"{trainer.name} is beaten and gives no rematch")
        if trainer.rival and world.rival_record.fought_at_badges == len(
            world.player.require_sheet().badges
        ):
            raise Refusal(f"{trainer.name} will battle you again after your next badge")
        if trainer.last_battle_visit == len(world.visits):
            raise Refusal(f"{trainer.name} already battled you on this visit; come back later")
        team = world.trainer_team(trainer, self._species_pool(draft.pack_id), rng)
        world.setup_battle(trainer, tuple(mon.battler() for mon in team), rng)
        return [trainer.card_fact(f"{trainer.name} challenges you to a battle")]

    @tool
    def start_wild_battle(
        self, draft: PokemonGame, args: StartWildBattle, rng: Random
    ) -> list[Fact]:
        """Call this when the player meets a wild Pokemon at this place, such as in tall grass.
        Set `species_id` to one from WILD HERE, or leave it null to roll on the table; in a
        Nuzlocke, always leave it null. Call it last: it ends your turn."""
        world = draft.world
        rows = world.wild_rows(args.species_id)
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


def _check_ace(leader: Trainer, index: int) -> None:
    if not leader.roster:
        raise Refusal(f"{leader.name} gives a badge, so they need a roster")
    table = level_for(index)
    ace = max(slot.level for slot in leader.roster)
    if abs(ace - table) > LEVEL_SPREAD:
        raise Refusal(
            f"{leader.name}'s ace is L{ace}; the ace of gym {index + 1} is "
            f"L{table - LEVEL_SPREAD} to L{table + LEVEL_SPREAD}"
        )


def _check_scheme(scheme: Scheme, species_pool: Collection[Slug]) -> None:
    legendary_id = scheme.legendary_id
    if legendary_id is not None and (
        legendary_id not in species_pool or not is_legendary(dex().species[legendary_id])
    ):
        raise Refusal(f"`legendary_id` {legendary_id!r} is no legendary species of SPECIES")


def _check_operation(
    proposal: PokemonMap, operation: Operation, leader_ids: Collection[Slug]
) -> None:
    start_id, to_id = operation.place_id, operation.shut_to_id
    if start_id not in proposal.reachable(proposal.start_id):
        raise Refusal(
            f"the operation's place {start_id!r} is a place of this map that its start reaches "
            "without a lock"
        )
    leader = proposal.npcs.get(operation.leader_id)
    if (leader is None or not leader.roster or leader.badge) and (
        operation.leader_id not in leader_ids
    ):
        raise Refusal(
            f"the operation's leader {operation.leader_id!r} is a person of this map with a "
            f"roster and no badge, or an earlier leader: {list(leader_ids)}"
        )
    if (to_id is None) == (operation.consequence == "shut_way"):
        raise Refusal("`shut_to_id` is set for shut_way, and null for close_center")
    if to_id is None:
        return
    way = proposal.way(start_id, to_id)
    if way is None or way.locked:
        raise Refusal(f"no unlocked way leads from {start_id!r} to {to_id!r} for shut_way")
    if proposal.reachable(proposal.start_id, past_locks=True, cut=[(start_id, to_id)]) != set(
        proposal.places
    ):
        raise Refusal(
            f"the way from {start_id!r} to {to_id!r} is the only way to some places; shut_way "
            "needs a way the map can do without"
        )


def _rival_section(world: PokemonWorld) -> Sections:
    rival = world.rival_trainer()
    if rival is None:
        return ()
    ledger = (f"- {line}" for line in world.rival_record.ledger)
    return (("THE RIVAL", "\n".join((f"{rival.tag}; style: {rival.style}", *ledger))),)


def _rank_picks(picks: Picks) -> list[str]:
    return [picked(picks, f"rank-{number}") for number in range(1, RANKS_AT_CREATION + 1)]
