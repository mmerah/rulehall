from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random

from rulehall.core.creation import CreationStep, Picks, find_option
from rulehall.core.decisions import ActionOption, DecisionOption
from rulehall.core.facts import Fact, roll
from rulehall.core.game import AnyCharacter, Character, Check, RoleAnswer, WorldsmithRequest
from rulehall.core.prompt import Sections, lines_of, ref_of, section_if
from rulehall.core.tools import action, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import NarratorView, Panel, Rows
from rulehall.engines.args import Words
from rulehall.engines.engine import RequestHandler, Resolution, Revealing
from rulehall.engines.hiring import HIRE_PENDING, HIRE_UNWRITTEN, Hiring, signed_on
from rulehall.engines.packs import unique_options
from rulehall.engines.panels import here_panel, party_panel
from rulehall.engines.scenes.engine import SceneEngine
from rulehall.engines.scenes.panels import trail_panel
from rulehall.engines.sheet import PLAYER_ID, joined
from rulehall.engines.twentyfourxx.args import (
    BringIn,
    CarriedItem,
    ChangeHindrances,
    Defend,
    DefendHit,
    FindAgain,
    FromHold,
    GainItem,
    Job,
    LoseHoldItem,
    NextScene,
    Raise,
    RaiseSkill,
    RepairItem,
    Roll,
    ShipUpgrade,
    Spend,
    TakeLead,
)
from rulehall.engines.twentyfourxx.pack import (
    Origin,
    Specialty,
    TwentyFourXXBody,
    TwentyFourXXHead,
    TwentyFourXXPack,
)
from rulehall.engines.twentyfourxx.panels import (
    MOVE_ON,
    NEWCOMER,
    SHEET_HELP,
    SKILL_INCREASE_HELP,
    commit_decision,
    crew_rows,
    job_panel,
    look_again_move,
    newcomer_decision,
    raise_decision,
    sheet_panel,
    ship_panel,
    succession_decision,
)
from rulehall.engines.twentyfourxx.risk import DicePool, defend_or_land
from rulehall.engines.twentyfourxx.rules import (
    NO_TROUBLE,
    SIGNS_OF_TROUBLE,
    SKILL_COUNT,
    TROUBLE,
    next_die,
    outcome_band,
)
from rulehall.engines.twentyfourxx.sheet import Crewmate, CrewSheet, Gear, Kit, items_from_kits
from rulehall.engines.twentyfourxx.world import (
    NewcomerProposal,
    SheetProposal,
    TwentyFourXXGame,
    TwentyFourXXNextProposal,
    TwentyFourXXSceneProposal,
    TwentyFourXXWorld,
)
from rulehall.engines.twentyfourxx.worldsmith import (
    COMPLICATING,
    FLOWN,
    HIRING,
    NEW_LOCATION,
    NEWCOMING,
    WORLDSMITH_GUIDANCE,
    check_newcomer,
)
from rulehall.engines.world import IS_DEAD

DEPARTURE: Slug = "departure"
FLIGHT: Slug = "flight"
COMPLICATION: Slug = "complication"
MOVING_ON = (
    "The player moves on. PLAYER ACTION says where the player means to go. Play the leaving if "
    "nothing stops the player. Then call `next_scene` with `pursuit` in the player's own words. "
    "The worldsmith writes the crossing after this turn."
)
CROSSING = (
    "The player is leaving {left} for the place in SCENE{how}. The narrator told the leaving "
    "already. Write the arrival in the place that SCENE describes, and nothing the player "
    "planned for it. Give the distance and the time in the fewest words that make them real. "
    "End on what the player sees first. WHAT HAPPENED names everyone who travelled with the "
    "player. The player has not acted in the new place, so settle nothing."
)
TURNING = (
    "The situation changes where the player stands. The player did nothing to cause the "
    "change. Write what arrives or changes, as the player sees it, from SCENE and WHAT "
    "HAPPENED. End on what the new situation asks of the player. The player has not answered "
    "it, so settle nothing."
)
BY_SHIP = ", flying there in the crew's own ship. Tell a flight and a landing, not a walk"
JOINING = (
    "{name} joins the crew here, in SCENE, and leads now. Tell the arrival in a line or two. "
    "Settle nothing else."
)
NEW_LEAD_HERE = (
    "{name} leads now and is here, in {scene}, where the dead operator fell. Play them here, "
    "never anywhere else."
)
SCENE_LEFT = "the worldsmith writes the crossing once this turn ends: stop here and exit"
WAY_OFFERED = (
    "This scene offers a way on. Ask the player what they want to pursue next. Ask in the "
    "fiction, and name what the scene left open. Never ask with a list of choices. The player "
    "can also stay and keep playing here, so ask; do not push the player out."
)
WAY_UNWRITTEN = Fact(
    told=True,
    trace="the crossing could not be written yet: the player arrives once they move on again",
    card="The crossing is not written yet. Move on again to arrive.",
)
COMPLICATION_UNWRITTEN = Fact(
    told=True,
    trace="the complication could not be written",
    card="Nothing new came down on this place after all. You are still where you were.",
)
JOB_PAID = (
    "the job is over, done or failed: the credits each operator earned above are their cut for "
    "the work done. Tell them as that pay; never say that no pay came"
)
RAISE_OWED = "A raise is owed: when the player names a skill, call `raise_skill` with it."
TROUBLE_COMES = (
    "bad luck: the worldsmith writes the trouble once this turn ends: {trouble}; nothing more "
    "happens this turn, so stop and exit"
)
SIGNS_SHOW = (
    "bad luck shows only its signs: tell in `direct` a sign of this trouble, never the trouble "
    "itself: {trouble}"
)
NO_TROUBLE_COMES = "no bad luck: the trouble does not come; play on"


class TwentyFourXXEngine(
    Revealing,
    Hiring[Crewmate, TwentyFourXXWorld, TwentyFourXXPack, TwentyFourXXNextProposal, SheetProposal],
    SceneEngine[Crewmate, TwentyFourXXWorld, TwentyFourXXPack, TwentyFourXXNextProposal],
):
    id = EngineId("twentyfourxx")
    title = "24XX"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = (
        "Clean science-fiction illustration: hard light, neon on steel, lived-in "
        "technology, no text or lettering."
    )
    directory = Path(__file__).parent
    pack_model = TwentyFourXXPack
    pack_head_model = TwentyFourXXHead
    pack_body_model = TwentyFourXXBody
    world_model = TwentyFourXXWorld
    person_model = Crewmate
    opening_model = TwentyFourXXSceneProposal
    next_proposal_model = TwentyFourXXNextProposal
    hire_model = SheetProposal
    hire_intent = HIRING
    sheet_help = SHEET_HELP

    def __init__(self, player_packs: Path) -> None:
        super().__init__(player_packs)
        srd = self.packs.srd()
        if len(srd.skills) != SKILL_COUNT:
            raise ValueError(
                f"the {self.id!r} srd pack lists {len(srd.skills)} skills, not {SKILL_COUNT}"
            )
        if not srd.starting_kit:
            raise ValueError(f"the {self.id!r} srd pack has no starting kit")

    def request_handlers(self) -> Mapping[Slug, RequestHandler[TwentyFourXXWorld]]:
        return {
            **super().request_handlers(),
            DEPARTURE: RequestHandler(self.depart, WAY_UNWRITTEN),
            FLIGHT: RequestHandler(self.fly, WAY_UNWRITTEN),
            COMPLICATION: RequestHandler(self.complicate, COMPLICATION_UNWRITTEN),
            NEWCOMER: RequestHandler(self.write_newcomer, HIRE_UNWRITTEN),
        }

    def before_record(self, draft: TwentyFourXXGame, /) -> None:
        if draft.pending is None and draft.request is None:
            self._succession(draft)
        if draft.pending is None and draft.request is None and draft.world.raise_owed:
            draft.pending = raise_decision(draft.world.player.require_sheet())

    def moves(self, state: TwentyFourXXGame, /) -> tuple[ActionOption, ...]:
        return (MOVE_ON, *look_again_move(state.world))

    def hire_guidance(self, draft: TwentyFourXXGame) -> str:
        specialties, origins = self._offered(draft.pack_id)
        return "\n".join(
            (
                "Specialties:",
                *(specialty.line() for specialty in specialties),
                "Origins:",
                *(origin.line() for origin in origins),
                f"Skills: {', '.join(self._rulebook_skills())}",
            )
        )

    def check_hire(self, draft: TwentyFourXXGame, answer: SheetProposal, /) -> None:
        self.build_sheet(draft.pack_id, answer)

    def sign_on(self, draft: TwentyFourXXGame, person: Crewmate, answer: SheetProposal) -> str:
        sheet = self.build_sheet(draft.pack_id, answer)
        person.sheet = sheet
        return joined(sheet.specialty, sheet.origin)

    def creation_steps(self, pack_id: Slug, picks: Picks) -> tuple[CreationStep, ...]:
        specialties, origins = self._offered(pack_id)
        skills = self.packs.srd().skills
        steps = [
            CreationStep(
                id="specialty",
                name="Specialty",
                options=specialties,
                help=SHEET_HELP["Specialty"],
            )
        ]
        specialty = find_option(specialties, picks.get("specialty", ""))
        if specialty is None:
            return tuple(steps)
        if specialty.choice:
            steps.append(
                CreationStep(
                    id="specialty-choice", name="Specialty skill", options=specialty.choice
                )
            )
        if specialty.kit_choice:
            steps.append(CreationStep(id="weapon", name="Weapon", options=specialty.kit_choice))
        steps.append(
            CreationStep(id="origin", name="Origin", options=origins, help=SHEET_HELP["Origin"])
        )
        origin = find_option(origins, picks.get("origin", ""))
        if origin is None:
            return tuple(steps)
        steps.extend(
            CreationStep(
                id=f"trait-{number}",
                name=f"Trait {number}",
                hint=origin.brief,
                help=SHEET_HELP["Traits"],
            )
            for number in range(1, origin.invents + 1)
        )
        if origin.choice:
            steps.append(CreationStep(id="body", name="Body", options=origin.choice))
        steps.extend(
            CreationStep(
                id=f"increase-{number}",
                name="Skill increase",
                options=skills,
                help=SKILL_INCREASE_HELP,
                allows_text=True,
            )
            for number in range(1, origin.increases + 1)
        )
        return tuple(steps)

    def build_character(
        self, name: str, brief: str, pack_id: Slug, picks: Picks
    ) -> Character[Crewmate]:
        proposal = SheetProposal(
            specialty=picks.get("specialty", ""),
            specialty_skills=picks.get("specialty-choice", ""),
            weapon=picks.get("weapon", ""),
            origin=picks.get("origin", ""),
            traits=_numbered(picks, "trait"),
            body=picks.get("body", ""),
            increases=_numbered(picks, "increase"),
        )
        player = Crewmate(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            sheet=self.build_sheet(pack_id, proposal),
        )
        return self.character_of(name, player)

    def build_sheet(self, pack_id: Slug, proposal: SheetProposal) -> CrewSheet:
        specialties, origins = self._offered(pack_id)
        specialty = _chosen(specialties, proposal.specialty, "specialty")
        origin = _chosen(origins, proposal.origin, "origin")
        skill_choice = _chosen_if_offered(
            specialty.choice, proposal.specialty_skills, "specialty skills"
        )
        weapon = _chosen_if_offered(specialty.kit_choice, proposal.weapon, "weapon")
        body = _chosen_if_offered(origin.choice, proposal.body, "body")
        _require_count(proposal.traits, origin.invents, "traits to invent")
        _require_count(proposal.increases, origin.increases, "skill increases")

        kits: list[Kit] = [*self.packs.srd().starting_kit, *specialty.kit]
        if weapon is not None:
            kits.append(weapon.kit)
        if body is not None and body.kit is not None:
            kits.append(body.kit)
        sheet = CrewSheet(
            specialty=specialty.name,
            origin=origin.name,
            traits=(*proposal.traits, *(() if body is None else (body.name,))),
            skills={**specialty.skills, **({} if skill_choice is None else skill_choice.skills)},
            items=items_from_kits(kits),
        )
        for wanted in proposal.increases:
            skill = sheet.match_skill(wanted, self._rulebook_skills()) or wanted
            if (raised_die := next_die(sheet.skills.get(skill))) is None:
                raise Refusal(f"{skill} is already at d12")
            sheet.skills[skill] = raised_die
        return sheet

    def preview_character(self, character: AnyCharacter) -> Rows:
        sheet = self.player_of(character).require_sheet()
        return (*sheet.rows(), ("Gear", sheet.gear_text()))

    def player_sections(self, state: TwentyFourXXGame) -> Sections:
        world = state.world
        return (
            ("YOU PLAY FOR", world.player.line(gear=False)),
            ("GEAR", _item_lines(world.player.require_sheet().items)),
            *section_if("THE JOB", world.job),
            *section_if("RAISE", RAISE_OWED if world.raise_owed else ""),
            ("THE SHIP", _item_lines(world.ship)),
            ("THE HOLD", f"{world.ship_line()}\n{_item_lines(world.hold)}"),
        )

    def context_text(self, state: TwentyFourXXGame) -> str:
        world = state.world
        return f"{super().context_text(state)}\n{world.ship_line()}\njob: {world.job or '(none)'}"

    def narrator_view(self, state: TwentyFourXXGame) -> NarratorView:
        view = super().narrator_view(state)
        if not (line := state.world.new_lead_line()):
            return view
        return view.model_copy(update={"situation": f"{view.situation}\n{line}"})

    def scene_panels(self, state: TwentyFourXXGame, /) -> tuple[Panel, ...]:
        world = state.world
        return (
            sheet_panel(world, self.sheet_help),
            *job_panel(world),
            ship_panel(world),
            *party_panel(
                world.party_members(), self.sheet_help, lambda member: crew_rows(world, member)
            ),
            here_panel(other.subject() for other in world.others()),
            trail_panel(scene.title for scene in world.scenes),
        )

    @tool
    def change_hindrances(
        self, draft: TwentyFourXXGame, args: ChangeHindrances, _rng: Random
    ) -> list[Fact]:
        """Add hindrances to the actor, remove hindrances, or do both."""
        return draft.world.require_actor(args.actor_id).change_hindrances(args.gained, args.lost)

    @tool
    def gain_item(self, draft: TwentyFourXXGame, args: GainItem, _rng: Random) -> list[Fact]:
        """Give the actor an item they pay for."""
        actor = draft.world.require_actor(args.actor_id)
        return actor.gain_item(args.name, bulky=args.bulky, breaks=args.breaks, cost=args.cost)

    @tool
    @action
    def drop_item(self, draft: TwentyFourXXGame, args: CarriedItem, _rng: Random) -> list[Fact]:
        """Take an item from the actor permanently."""
        actor = draft.world.require_actor(args.actor_id)
        return actor.require_sheet().drop_item(args.item_id, actor)

    @tool
    def repair_item(self, draft: TwentyFourXXGame, args: RepairItem, _rng: Random) -> list[Fact]:
        """Repair a broken item of the actor."""
        world = draft.world
        actor = world.require_actor(args.actor_id)
        return actor.repair_item(world.require_gear(actor, args.item_id, hold=True), args.cost)

    @tool
    def spend(self, draft: TwentyFourXXGame, args: Spend, _rng: Random) -> list[Fact]:
        """Pay the actor's credits for a thing that is not an item and not a repair, or pay
        someone with `to_id`."""
        world = draft.world
        actor = world.require_actor(args.actor_id)
        if args.to_id is None:
            return actor.spend(args.amount, args.why)
        if args.to_id == actor.id:
            raise Refusal(f"{actor.name} cannot pay themselves")
        person = world.find_person(args.to_id)
        if args.to_id == world.player.id or (
            person and person.has_sheet and person.id in world.party_ids
        ):
            taker = world.require_actor(args.to_id)
            return [*actor.spend(args.amount, args.why), *taker.earn(args.amount, giver=actor)]
        taker_name = args.to_id if person is None else person.name
        return actor.spend(args.amount, f"{args.why}, to {taker_name}")

    @action
    def take_lead(self, draft: TwentyFourXXGame, args: TakeLead, _rng: Random) -> list[Fact]:
        return draft.world.take_lead(args.member_id)

    @tool
    def ship_upgrade(self, draft: TwentyFourXXGame, args: ShipUpgrade, _rng: Random) -> list[Fact]:
        """Upgrade one ship function for the player."""
        return draft.world.upgrade_ship(args.function_id, args.upgrade)

    @action
    def stow_item(self, draft: TwentyFourXXGame, args: CarriedItem, _rng: Random) -> list[Fact]:
        world = draft.world
        return world.stow_item(world.require_actor(args.actor_id), args.item_id)

    @action
    def retrieve_item(self, draft: TwentyFourXXGame, args: FromHold, _rng: Random) -> list[Fact]:
        world = draft.world
        return world.retrieve_item(world.require_actor(args.actor_id), args.item_id)

    @tool
    def lose_hold_item(
        self, draft: TwentyFourXXGame, args: LoseHoldItem, _rng: Random
    ) -> list[Fact]:
        """Take an item out of the ship's hold while the crew is away: a raid, an impound or a
        theft. Call this once for each item."""
        return draft.world.lose_hold_item(args.item_id, args.why)

    @tool
    def defend(self, draft: TwentyFourXXGame, args: Defend, _rng: Random) -> list[Fact]:
        """Break a carried item or a ship function. The hit becomes a hindrance."""
        return draft.world.defend(args.actor_id, args.item_id, args.hindrance)

    @tool
    def next_scene(self, draft: TwentyFourXXGame, args: NextScene, rng: Random) -> list[Fact]:
        """Open the next scene: with nothing set when this one reaches a stopping point. Set
        `pursuit` instead when the player has left this place. Set `complication` instead to
        test for bad luck here: on 1-2 the trouble comes, on 3-4 only its signs."""
        if args.pursuit:
            if args.by_ship and (refusal := draft.world.ship_refusal()):
                raise Refusal(refusal)
            kind = FLIGHT if args.by_ship else DEPARTURE
            draft.request = WorldsmithRequest(kind=kind, detail=args.pursuit)
            draft.note(SCENE_LEFT)
            return [Fact(trace=f"the player leaves {draft.world.scene.title}", told=True)]
        if not args.complication:
            draft.note(WAY_OFFERED)
            return [Fact(trace="the scene reaches a stopping point")]
        trouble = args.complication
        rolled = roll((6,), "bad luck", rng, label="Bad luck")
        band = outcome_band(rolled.face, TROUBLE, SIGNS_OF_TROUBLE, NO_TROUBLE)
        tested = [
            rolled.fact,
            draft.world.player.card_fact(f"Bad luck — d6 → {band}", (rolled.event,)),
        ]
        if band == TROUBLE:
            draft.request = WorldsmithRequest(kind=COMPLICATION, detail=trouble)
            return [*tested, Fact(trace=TROUBLE_COMES.format(trouble=trouble))]
        if band == SIGNS_OF_TROUBLE:
            return [*tested, Fact(trace=SIGNS_SHOW.format(trouble=trouble))]
        return [*tested, Fact(trace=NO_TROUBLE_COMES)]

    @action
    def move_on(self, draft: TwentyFourXXGame, _args: Words, _rng: Random) -> list[Fact]:
        draft.note(MOVING_ON)
        return []

    async def depart(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        return await self._cross(draft, request.detail, worldsmith, "")

    async def fly(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        place_id = draft.world.scene.place_id

        def check_flown_away(answer: TwentyFourXXNextProposal) -> None:
            if answer.place_id == place_id:
                raise Refusal(FLOWN.format(place_id=place_id))

        resolution = await self._cross(draft, request.detail, worldsmith, BY_SHIP, check_flown_away)
        draft.world.dock_here()
        return resolution

    async def _cross(
        self,
        draft: TwentyFourXXGame,
        pursuit: str,
        worldsmith: RoleAnswer,
        how: str,
        extra_check: Check[TwentyFourXXNextProposal] = lambda _: None,
    ) -> Resolution:
        left = draft.world.scene.title
        facts = await self.write_and_install_next(
            draft, pursuit, worldsmith, extra_check=extra_check
        )
        return Resolution(tuple(facts), CROSSING.format(left=left, how=how))

    async def complicate(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        location = draft.world.scene.location

        def check_same_location(answer: TwentyFourXXNextProposal) -> None:
            if answer.location not in ("", location):
                raise Refusal(NEW_LOCATION)

        intent = COMPLICATING.format(brief=request.detail)
        facts = await self.write_and_install_next(
            draft, intent, worldsmith, extra_check=check_same_location
        )
        return Resolution(tuple(facts), TURNING)

    def install_next(
        self, draft: TwentyFourXXGame, proposal: TwentyFourXXNextProposal, /
    ) -> list[Fact]:
        ended = draft.world.end_brief_hindrances()
        return [*ended, *super().install_next(draft, proposal)]

    def _offered(self, pack_id: Slug) -> tuple[tuple[Specialty, ...], tuple[Origin, ...]]:
        played = self.packs.played(pack_id)
        return (
            unique_options(option for pack in played for option in pack.specialties),
            unique_options(option for pack in played for option in pack.origins),
        )

    def _succession(self, draft: TwentyFourXXGame) -> None:
        world = draft.world
        dead = world.player
        if dead.alive:
            return
        if not (members := world.hired_party_members()):
            draft.pending = newcomer_decision(dead)
            return
        draft.pending = succession_decision(members)

    def ending(self, state: TwentyFourXXGame) -> str | None:  # noqa: ARG002
        return None

    @tool
    def bring_in(self, draft: TwentyFourXXGame, args: BringIn, _rng: Random) -> list[Fact]:
        """Bring a new operator into the crew after the lead died; the worldsmith writes them."""
        world = draft.world
        if world.player.alive or world.hired_party_members():
            raise Refusal(
                "a new operator joins only when the lead is dead and no hired member lives"
            )
        draft.request = WorldsmithRequest(kind=NEWCOMER, detail=args.who)
        return [Fact(trace=HIRE_PENDING.format(name="the new operator", terms=args.who))]

    async def write_newcomer(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        world = draft.world

        def check(answer: NewcomerProposal) -> None:
            self.build_sheet(draft.pack_id, answer.sheet)
            check_newcomer(answer, world)

        answer = await self.ask_worldsmith(
            draft,
            worldsmith,
            NEWCOMING.format(who=request.detail),
            NewcomerProposal,
            check,
            guidance=self.hire_guidance(draft),
        )
        world.hear(answer.name, answer.brief)
        newcomer = Crewmate(
            id=PLAYER_ID,
            name=answer.name,
            brief=answer.brief,
            known=True,
        )
        summary = self.sign_on(draft, newcomer, answer.sheet)
        facts = [*world.lead(newcomer), signed_on(newcomer, summary)]
        draft.note(NEW_LEAD_HERE.format(name=newcomer.name, scene=world.scene.title))
        return Resolution(tuple(facts), JOINING.format(name=newcomer.name))

    @tool
    @action
    def roll(self, draft: TwentyFourXXGame, args: Roll, rng: Random) -> list[Fact]:
        """Roll only to avoid a risk. The engine checks the dice and asks the player to
        commit, unless `committed` is set; then it rolls and reads the result."""
        pool = DicePool.build(draft.world, args, self._rulebook_skills())
        if args.committed:
            return self._rolled(draft, pool, rng)
        draft.pending = commit_decision(args, pool.lines()[1], pool.actor, pool.faces)
        return []

    @action
    def defend_hit(self, draft: TwentyFourXXGame, args: DefendHit, _rng: Random) -> list[Fact]:
        pool = DicePool.build(draft.world, args.roll, self._rulebook_skills())
        return defend_or_land(draft, pool, args.rolled, args.choices)

    def _rolled(self, draft: TwentyFourXXGame, pool: DicePool, rng: Random) -> list[Fact]:
        args = pool.roll
        rolled = roll(pool.faces, f"{args.what} — {pool.label}", rng, highlight_kept=True)
        return [rolled.fact, *defend_or_land(draft, pool, rolled.event, {})]

    @tool
    def job(self, draft: TwentyFourXXGame, args: Job, rng: Random) -> list[Fact]:
        """Work for the crew. With `find` the engine rolls the d6 of the SRD. With `finish` it
        raises one skill for each hired member, pays each operator d6 credits, and asks the
        player which skill they raise."""
        world = draft.world
        match args.verb:
            case "find":
                return world.find_work(args.where, rng)
            case "take":
                return world.take_job(args.terms)
            case "finish":
                return self._finish(draft, args.raises, rng)

    @tool
    @action
    def raise_skill(self, draft: TwentyFourXXGame, args: RaiseSkill, _rng: Random) -> list[Fact]:
        """Raise the skill the player chose after a job."""
        world = draft.world
        if not world.raise_owed:
            raise Refusal("no raise is owed: the player raises one skill after each job")
        facts = self._raise(world.player, args.skill)
        world.raise_owed = False
        return facts

    @action
    def find_again(self, draft: TwentyFourXXGame, args: FindAgain, rng: Random) -> list[Fact]:
        spent = draft.world.player.spend(1, "another look for work")
        return [*spent, *draft.world.find_work(args.where, rng)]

    def _finish(self, draft: TwentyFourXXGame, raises: Sequence[Raise], rng: Random) -> list[Fact]:
        world = draft.world
        if not world.job:
            raise Refusal("no job is open to finish")
        if not world.work_rolled:
            raise Refusal(
                "no roll has played the job's work since it was taken: play the work, then finish"
            )
        if not world.player.alive:
            raise Refusal(IS_DEAD.format(name=world.player.name))
        members = world.hired_party_members()
        expected = sorted(member.id for member in members)
        given = sorted(world.require_actor(raise_.actor_id).id for raise_ in raises)
        if given != expected:
            raise Refusal(
                "`job` `finish` names every living hired member once each, never the player: "
                f"expected {', '.join(expected) or '(nobody)'}; given {', '.join(given)}"
            )

        facts: list[Fact] = []
        for raise_ in raises:
            facts.extend(self._raise(world.require_actor(raise_.actor_id), raise_.skill))
        for actor in (world.player, *members):
            rolled = roll((6,), f"credits earned by {actor.name}", rng)
            facts.append(rolled.fact)
            facts.extend(actor.earn(rolled.face, dice=(rolled.event,)))
        world.close_job()
        world.raise_owed = True
        return [*facts, Fact(trace=JOB_PAID)]

    def _raise(self, actor: Crewmate, skill: str) -> list[Fact]:
        matched = actor.require_sheet().match_skill(skill, self._rulebook_skills())
        return actor.raise_skill(matched or skill)

    def _rulebook_skills(self) -> tuple[str, ...]:
        return tuple(option.name for option in self.packs.srd().skills)


def _item_lines(items: Mapping[Slug, Gear]) -> str:
    return lines_of(
        f"- {ref_of(item.name, key)}" + (f" — {detail}" if (detail := item.notes()) else "")
        for key, item in items.items()
    )


def _numbered(picks: Picks, prefix: str) -> tuple[str, ...]:
    numbered = (f"{prefix}-{number}" for number in range(1, len(picks) + 1))
    return tuple(picks[key] for key in numbered if key in picks)


def _chosen[T: DecisionOption](options: Sequence[T], answer: str, what: str) -> T:
    folded = answer.casefold()
    chosen = next(
        (option for option in options if folded in (option.id, option.name.casefold())), None
    )
    if chosen is None:
        names = " / ".join(option.name for option in options)
        raise Refusal(f"{what}: {answer!r} is not one of {names}")
    return chosen


def _chosen_if_offered[T: DecisionOption](options: Sequence[T], answer: str, what: str) -> T | None:
    if options:
        return _chosen(options, answer, what)
    if answer:
        raise Refusal(f"{what}: none is on offer here, so leave it empty")
    return None


def _require_count(answers: Sequence[str], offered: int, what: str) -> None:
    if len(answers) != offered or not all(answer.strip() for answer in answers):
        raise Refusal(f"the origin takes exactly {offered} {what}, each one named")
