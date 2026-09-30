from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random

from rulehall.core.creation import (
    CreationStep,
    Picks,
    find_option,
    other_than,
)
from rulehall.core.decisions import ActionOption, DecisionOption
from rulehall.core.facts import Fact
from rulehall.core.game import (
    AnyCharacter,
    AnyScenario,
    Character,
    RoleAnswer,
    WorldsmithRequest,
)
from rulehall.core.log import Voice
from rulehall.core.prompt import Sections, section_if
from rulehall.core.tools import MasterTool, NoArgs, action, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import NarratorView, Panel
from rulehall.engines.args import Words
from rulehall.engines.engine import Joining, RequestHandler, Resolution
from rulehall.engines.loner4e.args import (
    Ask,
    ChangeTags,
    CloseScene,
    ConfirmEnd,
    Drive,
    EndAdventure,
    Fight,
    SpendLuck,
)
from rulehall.engines.loner4e.pack import Loner4eBody, Loner4eHead, Loner4ePack
from rulehall.engines.loner4e.panels import (
    SHEET_HELP,
    growth_decision,
    living_world_decision,
    loner_moves,
    own_ending_decision,
    proposed_ending_decision,
    scene_panel,
    sheet_panel,
)
from rulehall.engines.loner4e.rules import (
    ALTERS_THE_LOCATION,
    CHANGES_THE_GOAL,
    DEAD_END_QUESTION,
    ENDS_THE_SCENE,
    RUN_ITS_COURSE_QUESTION,
    SCENE_ID,
    RollOutcome,
    position_for,
    same_question,
)
from rulehall.engines.loner4e.world import (
    ENDING_ASKS_NOTHING,
    LivingWorldProposal,
    Loner4eEntity,
    Loner4eGame,
    Loner4eMeanwhileProposal,
    Loner4eNextProposal,
    Loner4eSceneProposal,
    Loner4eWorld,
    OracleRoll,
)
from rulehall.engines.loner4e.worldsmith import (
    DRAMATIC,
    LIVING_WORLD,
    MEANWHILE,
    MEANWHILE_DRAMATIC,
    MEANWHILE_QUIET,
    MEANWHILE_TWIST,
    OFFSCREEN,
    OPENING_FRAME,
    QUIET,
    TIPPED,
    WORLDSMITH_GUIDANCE,
    check_living_world,
    check_meanwhile,
)
from rulehall.engines.packs import unique_options
from rulehall.engines.panels import party_panel
from rulehall.engines.scenes.engine import SceneEngine
from rulehall.engines.scenes.worldsmith import OPENING
from rulehall.engines.sheet import PLAYER_ID

QUIET_SCENE_REQUEST = "quiet"
DRAMATIC_SCENE_REQUEST = "dramatic"
MEANWHILE_REQUEST = "meanwhile"
LIVING_WORLD_REQUEST = "living-world"
LET_PLAY_DECIDE = "Leave empty to let play decide"
ELSEWHERE_TITLE = "MET, NOT HERE (use these ids when one of them comes back)"
TWIST_NOTE = (
    "A twist arrives: {subject} / {action}. The pair is one beat: read it in what "
    "is already here, and develop it this turn. Read the room, then the table: if SETTLED and "
    "the sheet show pressure, land it hard; if the scene has been clean, it is a shift."
)
TWIST_ACTION_NOTES: dict[str, str] = {
    ENDS_THE_SCENE: "The scene is closing: develop the twist and direct.",
    CHANGES_THE_GOAL: "Call `drive` with `actor_id: scene` and the new goal.",
    ALTERS_THE_LOCATION: "Call `change_tags` with `actor_id: scene` and kind `detail`.",
}
DEFEATED = (
    "{name} is out of luck and lost the conflict. Tell now in `direct` what the defeat means: "
    "captured, disarmed, driven off, cornered or conceding. Defeat is not death. A defeat that "
    "leaves a lasting hurt may give a `condition`."
)
STILL_IN_IT = (
    "{name} is still in it: direct; the player's next words press on, change tack or break away"
)
BROKE_AWAY = "the protagonist broke away: name the cost with `change_tags`"
DRAMATIC_CLOSES = (
    "`turning_point` closes a quiet scene only: close this dramatic scene as `resolved`, "
    "`blocked` or `abandoned`"
)
QUESTION_REQUIRED = "`question` is required: write the question"
SECOND_DEAD_END = (
    "a second dead end in this scene is not asked again: the approach itself is blocked, not "
    "only this angle; close the scene as `blocked` and call `direct`"
)
RAN_ITS_COURSE = "The scene has run its course and is closing: direct."
INSPIRATION_NOTE = (
    "Read the inspiration into what is already here: it is a lens on the fiction, never a new "
    "thing from nothing."
)
QUIET_LASTS = (
    "a quiet scene lasts: it is the protagonist's pause to recover, plan or deepen a bond; it "
    "neither resolves nor turns on the player's first turn in it and ends later only on the "
    "player's Move on or a turning point; call `direct` now"
)
MEANWHILE_UNSAID = "The Meanwhile is the worldsmith's: say nothing of it and call `direct` now."
MAY_END = "If this settles what the protagonist set out to do, call `end_adventure` now."
SCENE_UNWRITTEN = Fact(
    told=True,
    trace="the next scene could not be written",
    card="The next scene could not be written. You are still where you were.",
)
LAST_WORDS = 'The player\'s last words: "{words}". '
ARRIVING = (
    "The player arrives in the place in SCENE. The narrator told the leaving already: tell only "
    "the arrival in the place SCENE describes, and end on what presses. The player has not "
    "acted here, so settle nothing."
)
MEANWHILE_CUE = (
    "Cut away from the protagonist: tell only what the Meanwhile card says moved, as the "
    "world's turn; the protagonist does not see it. Name nothing else in the cutaway."
)
GROWTH = (
    "The player ended the adventure and said what {name} learned: write that growth once with "
    "`change_tags`, or with `drive` for a new nemesis or the concept reworded. Drop with "
    "`change_tags` `lost` any gear on the sheet that the story gave away or lost. Then direct."
)
GROWTH_WAITS = (
    "a new skill or frailty on the protagonist is the growth at the end of the adventure: it is "
    "written only after the player picks End it; propose the end with `end_adventure`, or tell the "
    "change in `direct`"
)
CONCEPT_GROWS = (
    "the concept changes only in the growth, after the player picks End it; call `direct` now"
)
GROWN = "the growth is one new skill or frailty, and it is written; call `direct` now"
EPILOGUE = "The adventure is over. Tell WHAT HAPPENED as a short epilogue."
LIVING_WORLD_UNWRITTEN = Fact(
    told=True,
    trace="the living world could not be written",
    card="The Living World could not be written. Ask for it again.",
)
ARRIVING_QUIET = (
    "The protagonist has just arrived in SCENE to pursue their aim. Direct the arrival with "
    "your first result."
)


class Loner4eEngine(
    Joining[Loner4eWorld],
    SceneEngine[Loner4eEntity, Loner4eWorld, Loner4ePack, Loner4eNextProposal],
):
    id = EngineId("loner4e")
    title = "LONER 4E"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Painterly illustration, muted colours, no text or lettering."
    directory = Path(__file__).parent
    pack_model = Loner4ePack
    pack_head_model = Loner4eHead
    pack_body_model = Loner4eBody
    world_model = Loner4eWorld
    person_model = Loner4eEntity
    opening_model = Loner4eSceneProposal
    next_proposal_model = Loner4eNextProposal
    opening_intent = f"{OPENING} {OPENING_FRAME}"
    play_hint = "What does {name} do? Or ask the oracle."
    sheet_help = SHEET_HELP

    def request_handlers(self) -> Mapping[Slug, RequestHandler[Loner4eWorld]]:
        return {
            **super().request_handlers(),
            QUIET_SCENE_REQUEST: RequestHandler(self.write_quiet, SCENE_UNWRITTEN),
            DRAMATIC_SCENE_REQUEST: RequestHandler(self.write_dramatic, SCENE_UNWRITTEN),
            MEANWHILE_REQUEST: RequestHandler(self.write_meanwhile, SCENE_UNWRITTEN),
            LIVING_WORLD_REQUEST: RequestHandler(self.write_living_world, LIVING_WORLD_UNWRITTEN),
        }

    def published(self, state: Loner4eGame, /) -> tuple[MasterTool, ...]:
        tools = super().published(state)
        if self._spends_luck(state):
            return tools
        return tuple(tool for tool in tools if tool.name != self.spend_luck.__name__)

    def moves(self, state: Loner4eGame, /) -> tuple[ActionOption, ...]:
        return loner_moves(state.world, played=_played_here(state))

    def allows_text(self, state: Loner4eGame, /) -> bool:
        return not state.world.frame.breather

    def scene_text(self, state: Loner4eGame) -> str:
        frame = state.world.frame
        return (
            f"{super().scene_text(state)}\n{frame.lines()}\nphase: {frame.phase()}\n"
            f"twist counter: {state.world.twist}"
        )

    def narrator_view(self, state: Loner4eGame) -> NarratorView:
        view = super().narrator_view(state)
        world = state.world
        frame = world.frame
        situation = (
            f"{view.situation}\n\nWhat {world.player.name} is here for: {frame.goal}. The place: "
            f"{', '.join(frame.details)}. Add no one and nothing beyond this, the cards and the "
            "notes: the oracle decides what else is here. THE PLAYER'S SHEET is current: a "
            "condition it no longer shows has passed, so never describe it."
        )
        return view.model_copy(update={"situation": situation})

    def lead_panels(self, state: Loner4eGame, /) -> tuple[Panel | None, ...]:
        world = state.world
        return (
            sheet_panel(world, self.sheet_help),
            scene_panel(world),
            # The sheet help speaks of the player: a companion's luck and goal work otherwise.
            party_panel(world.party_members(), {}),
        )

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> Loner4eWorld:
        world = super().new_game(scenario, character)
        world.apply_scene_extras(scenario.opening)
        return world

    def install_next(self, draft: Loner4eGame, proposal: Loner4eNextProposal, /) -> list[Fact]:
        draft.world.apply_scene_extras(proposal)
        return super().install_next(draft, proposal)

    def end_turn(self, draft: Loner4eGame, /, *, acted: bool) -> None:  # noqa: ARG002
        draft.world.player_question = ""
        if draft.pending is not None or draft.request is not None:
            return
        if draft.world.end_why:
            _await_living_world(draft)
            return
        _hand_over(draft)

    async def write_dramatic(
        self, draft: Loner4eGame, _request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        intent = _dramatic_intent(draft)
        facts = await self.write_and_install_next(draft, intent, worldsmith)
        return Resolution(tuple(facts), ARRIVING)

    async def write_quiet(
        self, draft: Loner4eGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        intent = QUIET.format(aim=request.detail)
        if offscreen := draft.world.frame.offscreen:
            intent += f" {OFFSCREEN.format(offscreen=offscreen)}"
        facts = await self.write_and_install_next(draft, intent, worldsmith)
        facts += draft.world.player.refill("a quiet scene")
        draft.note(ARRIVING_QUIET)
        return Resolution(tuple(facts), None)

    async def write_meanwhile(
        self, draft: Loner4eGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        world = draft.world
        then = (
            MEANWHILE_DRAMATIC.format(dramatic=_dramatic_intent(draft))
            if request.detail == "dramatic"
            else MEANWHILE_QUIET
        )
        intent = MEANWHILE.format(ally=world.frame.ally, then=then)
        if twist := world.frame.twist:
            intent += f" {MEANWHILE_TWIST.format(twist=twist)}"
        answer = await self.ask_worldsmith(
            draft,
            worldsmith,
            intent,
            Loner4eMeanwhileProposal,
            lambda answer: check_meanwhile(answer, world, request.detail),
        )
        facts = world.apply_offscreen_updates(answer.updates)
        cutaway = MEANWHILE_CUE if any(fact.card for fact in facts) else ""
        if answer.scene is None:
            world.frame.meanwhile = False
            return Resolution(tuple(facts), cutaway or None)
        facts += self.install_next(draft, answer.scene)
        return Resolution(tuple(facts), f"{cutaway} {ARRIVING}".strip())

    async def write_living_world(
        self, draft: Loner4eGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        world = draft.world
        answer = await self.ask_worldsmith(
            draft,
            worldsmith,
            LIVING_WORLD.format(why=request.detail),
            LivingWorldProposal,
            lambda answer: check_living_world(answer, world),
        )
        lines = world.living_world_lines(answer)
        world.player.living_world.extend(lines)
        world.ended = True
        draft.pending = None
        card = "\n".join(("The Living World", *lines))
        return Resolution((Fact(trace=card, told=True, card=card),), EPILOGUE)

    def ending(self, state: Loner4eGame) -> str | None:
        return "The adventure is over." if state.world.ended else super().ending(state)

    def grown_character(self, state: Loner4eGame, /) -> AnyCharacter | None:
        if not state.world.ended:
            return None
        sheet = state.world.player.model_copy(deep=True)
        sheet.luck.current = sheet.luck.maximum
        return self.character_model(id=state.character_id, engine_id=self.id, person=sheet)

    def worldsmith_sections(self, draft: Loner4eGame, /) -> Sections:
        carried = "\n".join(f"- {line}" for line in draft.world.player.living_world)
        return (
            *super().worldsmith_sections(draft),
            *section_if("WHAT THE PROTAGONIST CARRIES FORWARD", carried),
        )

    def _spends_luck(self, state: Loner4eGame) -> bool:
        return self.packs.require_pack(state.pack_id).spends_luck

    def creation_steps(self, pack_id: Slug, picks: Picks) -> tuple[CreationStep, ...]:
        played = self.packs.played(pack_id)
        concepts = unique_options(entry for pack in played for entry in pack.concepts)
        skills = unique_options(option for pack in played for option in pack.skills)
        frailties = unique_options(option for pack in played for option in pack.frailties)
        gear = unique_options(option for pack in played for option in pack.gear)
        return (
            CreationStep(
                id="concept",
                name="Write a one-line concept",
                hint=", ".join(entry.name for entry in concepts[:3]),
                help=SHEET_HELP["Concept"],
            ),
            CreationStep(
                id="goal",
                name="What does your character want?",
                hint=LET_PLAY_DECIDE,
                help=SHEET_HELP["Goal"],
                optional=True,
            ),
            CreationStep(
                id="motive",
                name="Why do they want it?",
                hint=LET_PLAY_DECIDE,
                help=SHEET_HELP["Motive"],
                optional=True,
            ),
            CreationStep(
                id="nemesis",
                name="Who or what stands against them?",
                hint=LET_PLAY_DECIDE,
                help=SHEET_HELP["Nemesis"],
                optional=True,
            ),
            _invented("skill-1", "Choose skill 1", skills, "Skills"),
            _invented(
                "skill-2", "Choose skill 2", other_than(skills, picks.get("skill-1", "")), "Skills"
            ),
            _invented("frailty", "Choose a frailty", frailties, "Frailties"),
            _invented("gear-1", "Choose gear 1", gear, "Gear"),
            _invented("gear-2", "Choose gear 2", other_than(gear, picks.get("gear-1", "")), "Gear"),
        )

    def build_character(
        self, name: str, brief: str, voice: Voice, pack_id: Slug, picks: Picks
    ) -> Character[Loner4eEntity]:
        steps = self.creation_steps(pack_id, picks)
        by_id = {step.id: step for step in steps}

        def taken(step_id: Slug) -> str:
            answer = picks.get(step_id, "")
            chosen = find_option(by_id[step_id].options, answer)
            return answer.strip() if chosen is None else chosen.name

        sheet = Loner4eEntity(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            voice=voice,
            known=True,
            concept=picks.get("concept", ""),
            tags={
                "skill": [taken(f"skill-{slot}") for slot in (1, 2)],
                "frailty": [taken("frailty")],
                "gear": [taken(f"gear-{slot}") for slot in (1, 2)],
            },
            goal=picks.get("goal", ""),
            motive=picks.get("motive", ""),
            nemesis=picks.get("nemesis", ""),
        )
        return self.character_of(name, sheet)

    def master_sections(self, state: Loner4eGame) -> Sections:
        world = state.world
        brief_of = {
            entry.name: entry.brief
            for pack in self.packs.played(state.pack_id)
            for entry in (*pack.skills, *pack.frailties, *pack.gear)
            if entry.brief
        }
        in_play = (
            tag
            for member in world.here()
            for kind in ("skill", "frailty", "gear")
            for tag in member.tagged(kind)
            if tag in brief_of
        )
        glossary = "\n".join(f"- {tag}: {brief_of[tag]}" for tag in dict.fromkeys(in_play))
        growth = GROWTH.format(name=world.player.name) if world.end_why else ""
        return (
            *super().master_sections(state),
            *section_if(ELSEWHERE_TITLE, world.elsewhere_lines()),
            *section_if("THE PLAYER ASKS", world.player_question),
            *section_if("THE END IS PROPOSED", growth),
            *section_if(
                "CONFLICT (Harm & Luck: every `ask` is an exchange, against the last opponent "
                "below unless `opponent_id` names another)",
                world.conflict_lines(),
            ),
            *section_if("WHAT THE TAGS IN PLAY MEAN", glossary),
        )

    @tool
    def change_tags(self, draft: Loner4eGame, args: ChangeTags, _rng: Random) -> list[Fact]:
        """Add tags to a character here or to the scene, remove tags, or do both."""
        world = draft.world
        if args.kind == "detail":
            world.require_open()
            return world.frame.change_details(args.gained, args.lost)
        actor, entered = world.here_or_entering(args.actor_id)
        if actor is world.player and args.kind in ("skill", "frailty") and args.gained:
            _grow(world, args.gained)
        return [*entered, *actor.change_tags(args.kind, args.gained, args.lost)]

    @tool
    def drive(self, draft: Loner4eGame, args: Drive, _rng: Random) -> list[Fact]:
        """Change the goal, the motive or the nemesis of a living character, or the goal of
        the scene; in the growth, the protagonist's concept too."""
        world = draft.world
        growth = bool(world.end_why) and args.actor_id == PLAYER_ID
        if args.concept and not growth:
            raise Refusal(CONCEPT_GROWS)
        if not growth:
            world.require_open()
        if args.actor_id == SCENE_ID:
            return world.frame.rewrite_goal(args.goal)
        actor = world.require_living_here(args.actor_id)
        return actor.drive(
            goal=args.goal, motive=args.motive, nemesis=args.nemesis, concept=args.concept
        )

    @tool
    def ask(self, draft: Loner4eGame, args: Ask, rng: Random) -> list[Fact]:
        """Ask the oracle: the engine nets the cited tags, rolls and reads the answer."""
        world = draft.world
        asked = world.pop_player_question()
        question = asked or args.question
        if question is None:
            raise Refusal(QUESTION_REQUIRED)
        if same_question(question, DEAD_END_QUESTION) and world.was_settled(question):
            raise Refusal(SECOND_DEAD_END)
        fought = args.opponent_id if world.opponent_ids or not asked else None
        opponent_id = fought or next(reversed(world.opponent_ids), None)
        opponent, entered = (
            (None, []) if opponent_id is None else world.here_or_entering(opponent_id)
        )
        world.check_cited(args.helps, args.hinders)
        position = position_for(len(args.helps), len(args.hinders))
        faced, facing = _cards_as_lines([] if opponent is None else world.engage(opponent))
        consulted = world.consult(question, position, rng, settle=opponent is None)
        cited = (*(f"+{tag}" for tag in args.helps), *(f"-{tag}" for tag in args.hinders))
        lines = (*((f"tags: {', '.join(cited)}",) if cited else ()), *facing)
        hoped = not asked
        if opponent is None:
            facts = [*consulted.facts(*lines, hoped=hoped), *_twist(draft, consulted, rng)]
            ran = same_question(question, RUN_ITS_COURSE_QUESTION) and consulted.outcome.yes
            if ran and world.frame.open:
                draft.note(RAN_ITS_COURSE)
                facts += world.close("ran_its_course", rng)
            return facts
        absorbed, more = _cards_as_lines(_exchange(draft, opponent, consulted.outcome))
        return [*entered, *consulted.facts(*lines, *more, hoped=hoped), *faced, *absorbed]

    @tool
    @action
    def roll_inspiration(self, draft: Loner4eGame, _args: NoArgs, rng: Random) -> list[Fact]:
        """Roll the inspiration tables for an open question no yes or no can answer: an
        unclear answer, a stalled story. The engine rolls a verb, an adjective and a noun."""
        facts = draft.world.roll_inspiration(rng)
        draft.note(INSPIRATION_NOTE)
        return facts

    @action
    def fight(self, draft: Loner4eGame, args: Fight, _rng: Random) -> list[Fact]:
        world = draft.world
        opponent = world.require_living_here(args.opponent_id)
        trace = f"the protagonist fights {opponent.ref}: each `ask` is an exchange"
        card = Fact(trace=trace, told=True, card=f"Fight: {opponent.name}")
        return [card, *world.engage(opponent)]

    @tool
    @action
    def withdraw(self, draft: Loner4eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        """Break off the Harm & Luck conflict when the protagonist stops fighting: always
        allowed, never free. While the conflict is open every `ask` is an exchange, so call this
        first when the protagonist turns to anything else."""
        world = draft.world
        if not world.opponent_ids:
            raise Refusal("no conflict is open")
        absorbed, lines = _cards_as_lines(world.end_conflict("the protagonist breaks away"))
        draft.note(BROKE_AWAY)
        card = "\n".join(("Breaks away", *lines))
        return [Fact(trace="the protagonist breaks away", told=True, card=card), *absorbed]

    @tool
    def close_scene(self, draft: Loner4eGame, args: CloseScene, rng: Random) -> list[Fact]:
        """Close the scene for the `reason` that holds, once the player's action is resolved.
        After it, call only `direct`. The engine opens what comes next."""
        world = draft.world
        quiet = world.frame.kind == "quiet"
        if args.reason == "turning_point" and not quiet:
            raise Refusal(DRAMATIC_CLOSES)
        if quiet and args.reason in ("resolved", "turning_point") and not _played_here(draft):
            raise Refusal(QUIET_LASTS)
        if args.reason in ("resolved", "abandoned"):
            draft.note(MAY_END)
        facts = world.close(args.reason, rng)
        if world.frame.meanwhile:
            draft.note(MEANWHILE_UNSAID)
        return facts

    @action
    def move_on(self, draft: Loner4eGame, _args: NoArgs, rng: Random) -> list[Fact]:
        facts = draft.world.close("moved_on", rng)
        _hand_over(draft)
        return facts

    @tool
    def end_adventure(self, draft: Loner4eGame, args: EndAdventure, _rng: Random) -> list[Fact]:
        """Propose the end of the adventure when one sign shows: the protagonist's goal is
        achieved or definitively failed; the goal is abandoned and the story found no new
        direction; a major revelation changed everything; the conflict reached a satisfying
        resolution; or the momentum slowed and the next significant scene is hard to find. The
        player ends it or plays on."""
        if draft.world.end_why:
            raise Refusal(ENDING_ASKS_NOTHING)
        draft.pending = proposed_ending_decision(args.why)
        return [Fact(trace=f"the end is proposed: {args.why}")]

    @action
    def offer_end(self, draft: Loner4eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        draft.pending = own_ending_decision()
        return [Fact(trace="the player offers to end the adventure")]

    @action
    def confirm_end(self, draft: Loner4eGame, args: ConfirmEnd, _rng: Random) -> list[Fact]:
        world = draft.world
        world.end_why = args.why
        draft.pending = growth_decision(world.player.name)
        return [Fact(trace=f"the player ends the adventure: {args.why}")]

    @action
    def play_on(self, _draft: Loner4eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        return [Fact(trace="the player plays on: the adventure continues")]

    @action
    def request_living_world(self, draft: Loner4eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        _await_living_world(draft)
        return []

    @action
    def ask_oracle(self, draft: Loner4eGame, args: Words, _rng: Random) -> list[Fact]:
        draft.world.player_question = args.words
        return []

    @action
    def take_breather(self, draft: Loner4eGame, args: Words, _rng: Random) -> list[Fact]:
        draft.request = WorldsmithRequest(kind=QUIET_SCENE_REQUEST, detail=args.words)
        return []

    @tool
    def spend_luck(self, draft: Loner4eGame, args: SpendLuck, _rng: Random) -> list[Fact]:
        """Spend luck for a character here."""
        world = draft.world
        facts, beaten = world.spend(world.require_living_here(args.actor_id), args.amount, args.why)
        if beaten is not None:
            draft.note(DEFEATED.format(name=beaten.name))
        return facts


def _invented(
    step_id: Slug, name: str, options: tuple[DecisionOption, ...], sheet_row: str
) -> CreationStep:
    return CreationStep(
        id=step_id, name=name, options=options, help=SHEET_HELP[sheet_row], allows_text=True
    )


def _await_living_world(draft: Loner4eGame) -> None:
    draft.pending = living_world_decision()
    draft.request = WorldsmithRequest(kind=LIVING_WORLD_REQUEST, detail=draft.world.end_why)


def _hand_over(draft: Loner4eGame) -> None:
    frame = draft.world.frame
    if frame.meanwhile:
        draft.request = WorldsmithRequest(kind=MEANWHILE_REQUEST, detail=frame.coming)
    elif frame.next == "dramatic":
        draft.request = WorldsmithRequest(kind=DRAMATIC_SCENE_REQUEST)


def _exchange(draft: Loner4eGame, opponent: Loner4eEntity, outcome: RollOutcome) -> list[Fact]:
    facts, beaten = draft.world.strike(opponent, outcome)
    if beaten is not None:
        draft.note(DEFEATED.format(name=beaten.name))
        return facts
    return [*facts, Fact(trace=STILL_IN_IT.format(name=opponent.name))]


def _grow(world: Loner4eWorld, gained: Sequence[str]) -> None:
    if not world.end_why:
        raise Refusal(GROWTH_WAITS)
    if world.grown or len(gained) > 1:
        raise Refusal(GROWN)
    world.grown = True


def _dramatic_intent(draft: Loner4eGame) -> str:
    closed_by = draft.world.frame.closed_by
    assert closed_by is not None
    intent = DRAMATIC.format(reason=closed_by.replace("_", " "), words=_last_words(draft))
    return f"{intent} {TIPPED}" if closed_by == "turning_point" else intent


def _last_words(draft: Loner4eGame) -> str:
    if draft.world.frame.closed_by == "moved_on":
        return ""
    return LAST_WORDS.format(words=draft.last_words())


def _played_here(draft: Loner4eGame) -> bool:
    return any(entry.cause is None for entry in draft.chapters[-1].entries)


def _cards_as_lines(exchange: list[Fact]) -> tuple[list[Fact], tuple[str, ...]]:
    lines = tuple(fact.card for fact in exchange if fact.told and fact.card)
    return [fact.model_copy(update={"card": ""}) for fact in exchange], lines


def _twist(draft: Loner4eGame, consulted: OracleRoll, rng: Random) -> list[Fact]:
    world = draft.world
    if (twisted := world.roll_twist(consulted, rng)) is None:
        return []
    (subject, action), facts = twisted
    note = TWIST_NOTE.format(subject=subject.upper(), action=action.upper())
    draft.note(f"{note} {TWIST_ACTION_NOTES[action]}" if action in TWIST_ACTION_NOTES else note)
    return [*facts, *world.close("twist", rng)] if action == ENDS_THE_SCENE else facts
