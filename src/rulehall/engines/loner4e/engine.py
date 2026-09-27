from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random

from rulehall.core.creation import (
    CreationStep,
    Picks,
    option_of,
    other_than,
    picked,
)
from rulehall.core.facts import Fact
from rulehall.core.model import (
    AnyCharacter,
    Character,
    RoleAnswer,
    WorldsmithRequest,
)
from rulehall.core.play import DecisionOption, PendingOption
from rulehall.core.prompt import Sections, section_if
from rulehall.core.tools import MasterTool, NoArgs, action, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import NarratorView, Panel
from rulehall.engines.args import Words
from rulehall.engines.engine import RequestHandler, Resolution
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.hiring import Joining
from rulehall.engines.loner4e.args import (
    Ask,
    ChangeTags,
    CloseScene,
    ConfirmEnd,
    Drive,
    EndAdventure,
    Fight,
    MarkStatus,
    SpendLuck,
)
from rulehall.engines.loner4e.pack import (
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
    LivingWorld,
    Loner4eBody,
    Loner4eHead,
    Loner4ePack,
)
from rulehall.engines.loner4e.panels import (
    ASK_ORACLE,
    TAKE_BREATHER,
    ending_decision,
    growth_decision,
    here_panel,
    living_world_decision,
    scene_panel,
    sheet_panel,
    status_mark_decision,
)
from rulehall.engines.loner4e.rules import (
    ALTERS_THE_LOCATION,
    CHANGES_THE_GOAL,
    ENDS_THE_SCENE,
    SCENE_ID,
    RollOutcome,
    position_for,
)
from rulehall.engines.loner4e.world import (
    ENDING_ASKS_NOTHING,
    Consulted,
    Loner4eEntity,
    Loner4eGame,
    Loner4eMeanwhile,
    Loner4eNext,
    Loner4eOpening,
    Loner4eWorld,
)
from rulehall.engines.packs import unique_options
from rulehall.engines.panels import party_panel
from rulehall.engines.scenes.engine import SceneEngine
from rulehall.engines.scenes.panels import trail_panel
from rulehall.engines.scenes.worldsmith import OPENING, check_next, next_needs

QUIET_SCENE_REQUEST = "quiet"
RECOVERY_SCENE_REQUEST = "recovery"
DRAMATIC_SCENE_REQUEST = "dramatic"
MEANWHILE_REQUEST = "meanwhile"
LIVING_WORLD_REQUEST = "living-world"
LET_PLAY_DECIDE = "Leave empty to let play decide"
ELSEWHERE_TITLE = "MET, NOT HERE (use these ids when one of them comes back)"
TWIST_NOTE = (
    "A twist interrupts the scene: {subject} / {action}. The pair is one beat: read it in what "
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
    "captured, disarmed, driven off, cornered or conceding. Defeat is not death."
)
MARK_ONLY = "The player picks only the lasting mark, never what the defeat means."
STILL_IN_IT = (
    "{name} is still in it: direct; the player's next words press on, change tack or break away"
)
RECOVERING = "Rest and recover from being {status}"
BROKE_AWAY = "the protagonist broke away: name the cost with `change_tags`"
CONFLICT_MARKS = (
    "a Harm & Luck conflict is open: the protagonist gains no condition from it. Luck is the "
    "harm, and the player's Status pick after a defeat is the only lasting mark. Tell the hurt "
    "in `direct`."
)
DRAMATIC_CLOSES = (
    "`turning_point` closes a quiet scene only: close this dramatic scene as `resolved`, "
    "`blocked` or `abandoned`"
)
QUESTION_REQUIRED = "`question` is required: write the question"
QUIET_LASTS = (
    "a quiet scene lasts: it is the protagonist's pause to recover, plan or deepen a bond, and "
    "it neither resolves nor turns on the player's first turn in it. Later, the player's Move "
    "on or a turning point ends it. Call `direct` now."
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
    "written only after the player picks End it. Propose the end with `end_adventure`, or tell the "
    "change in `direct`"
)
CONCEPT_GROWS = (
    "the concept changes only in the growth, after the player picks End it. Call `direct` now."
)
GROWN = "the growth is one new skill or frailty, and it is written. Call `direct` now."
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


class Loner4eEngine(Joining, SceneEngine[Loner4eEntity, Loner4eWorld, Loner4ePack]):
    id = EngineId("loner4e")
    title = "LONER 4E"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Painterly illustration, muted colours, no text or lettering."
    directory = Path(__file__).parent
    pack = Loner4ePack
    head = Loner4eHead
    body = Loner4eBody
    world = Loner4eWorld
    person = Loner4eEntity
    opening = Loner4eOpening
    opening_intent = f"{OPENING} {OPENING_FRAME}"

    def request_handlers(self) -> Mapping[Slug, RequestHandler[Loner4eWorld]]:
        return {
            **super().request_handlers(),
            QUIET_SCENE_REQUEST: RequestHandler(self.write_quiet, SCENE_UNWRITTEN),
            RECOVERY_SCENE_REQUEST: RequestHandler(self.write_quiet, SCENE_UNWRITTEN),
            DRAMATIC_SCENE_REQUEST: RequestHandler(self.write_dramatic, SCENE_UNWRITTEN),
            MEANWHILE_REQUEST: RequestHandler(self.write_meanwhile, SCENE_UNWRITTEN),
            LIVING_WORLD_REQUEST: RequestHandler(self.write_living_world, LIVING_WORLD_UNWRITTEN),
        }

    def published(self, state: Loner4eGame, /) -> tuple[MasterTool, ...]:
        tools = super().published(state)
        if self._spends_luck(state):
            return tools
        return tuple(tool for tool in tools if tool.name != self.spend_luck.__name__)

    def composer(self, state: Loner4eGame) -> tuple[PendingOption | None, bool]:
        world = state.world
        frame = world.frame
        if world.end_why:
            return None, False
        if frame.open:
            return ASK_ORACLE, False
        return (TAKE_BREATHER, True) if frame.breather else (None, False)

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
            "condition or status it no longer shows has passed, so never describe it."
        )
        return view.model_copy(update={"situation": situation})

    def scene_panels(self, state: Loner4eGame) -> tuple[Panel, ...]:
        world = state.world
        return (
            sheet_panel(world),
            scene_panel(world, played=_played_here(state)),
            *party_panel(world.party_members()),
            here_panel(world),
            trail_panel(scene.title for scene in world.scenes),
        )

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
        facts = await self._frame_next(draft, _dramatic_intent(draft), worldsmith)
        return Resolution(tuple(facts), ARRIVING)

    async def write_quiet(
        self, draft: Loner4eGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        intent = QUIET.format(aim=request.detail)
        if offscreen := draft.world.frame.offscreen:
            intent += f" {OFFSCREEN.format(offscreen=offscreen)}"
        facts = await self._frame_next(draft, intent, worldsmith)
        facts += draft.world.player.refill("a quiet scene")
        if request.kind == RECOVERY_SCENE_REQUEST:
            facts += draft.world.status.recover()
        draft.note(ARRIVING_QUIET)
        return Resolution(tuple(facts), None)

    async def write_meanwhile(
        self, draft: Loner4eGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        world = draft.world
        dramatic = request.detail == "dramatic"
        then = (
            MEANWHILE_DRAMATIC.format(dramatic=_dramatic_intent(draft))
            if dramatic
            else MEANWHILE_QUIET
        )
        intent = MEANWHILE.format(ally=world.frame.ally, then=then)
        if twist := world.frame.twist:
            intent += f" {MEANWHILE_TWIST.format(twist=twist)}"

        def check(answer: Loner4eMeanwhile) -> None:
            moved = world.model_copy(deep=True)
            needs: list[str] = []
            if answer.ally is not None and not world.frame.ally.startswith("yes"):
                needs.append("a null `ally`: the oracle said no, so allies hold")
            for update in answer.updates:
                try:
                    _ = moved.cut_to(update)
                except Refusal as refused:
                    needs.append(str(refused))
            scene = answer.scene
            if (scene is not None) != dramatic:
                needs.append(
                    f"a `scene` exactly when the follow-up is dramatic: it is {request.detail}"
                )
            elif scene is not None:
                needs += next_needs(scene, moved)
            if needs:
                raise Refusal("the meanwhile needs " + "; ".join(needs))

        answer = await self.ask_worldsmith_for_next_scene(
            draft, worldsmith, intent, Loner4eMeanwhile, check
        )
        facts = world.cut_away(answer.updates)
        cutaway = MEANWHILE_CUE if any(fact.card for fact in facts) else ""
        if answer.scene is None:
            world.frame.meanwhile = False
            return Resolution(tuple(facts), cutaway or None)
        facts += self.install_scene(draft, answer.scene)
        return Resolution(tuple(facts), f"{cutaway} {ARRIVING}".strip())

    async def write_living_world(
        self, draft: Loner4eGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        world = draft.world

        def named(entity_id: Slug) -> str:
            return world.require(entity_id).name

        def check(answer: LivingWorld) -> None:
            _ = answer.lines(named)

        intent = LIVING_WORLD.format(why=request.detail)
        answer = await self.ask_worldsmith_for_next_scene(
            draft, worldsmith, intent, LivingWorld, check
        )
        lines = answer.lines(named)
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
        return self.character(id=state.character_id, engine_id=self.id, sheet=sheet)

    def worldsmith_sections(self, draft: Loner4eGame) -> Sections:
        carried = "\n".join(f"- {line}" for line in draft.world.player.living_world)
        return (
            *super().worldsmith_sections(draft),
            *section_if("WHAT THE PROTAGONIST CARRIES FORWARD", carried),
        )

    def _spends_luck(self, state: Loner4eGame) -> bool:
        return self.packs.require(state.pack_id).spends_luck

    async def _frame_next(
        self, draft: Loner4eGame, intent: str, worldsmith: RoleAnswer
    ) -> list[Fact]:
        world = draft.world

        def check(answer: Loner4eNext) -> None:
            check_next(answer, world)

        scene = await self.ask_worldsmith_for_next_scene(
            draft, worldsmith, intent, Loner4eNext, check
        )
        return self.install_scene(draft, scene)

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
            ),
            CreationStep(
                id="goal",
                name="What does your character want?",
                hint=LET_PLAY_DECIDE,
                optional=True,
            ),
            CreationStep(
                id="motive", name="Why do they want it?", hint=LET_PLAY_DECIDE, optional=True
            ),
            CreationStep(
                id="nemesis",
                name="Who or what stands against them?",
                hint=LET_PLAY_DECIDE,
                optional=True,
            ),
            _invented("skill-1", "Choose skill 1", skills),
            _invented("skill-2", "Choose skill 2", other_than(skills, picked(picks, "skill-1"))),
            _invented("frailty", "Choose a frailty", frailties),
            _invented("gear-1", "Choose gear 1", gear),
            _invented("gear-2", "Choose gear 2", other_than(gear, picked(picks, "gear-1"))),
        )

    def build_character(
        self, name: str, brief: str, pack_id: Slug, picks: Picks
    ) -> Character[Loner4eEntity]:
        steps = self.creation_steps(pack_id, picks)
        by_id = {step.id: step for step in steps}

        def taken(step_id: Slug) -> str:
            answer = picked(picks, step_id)
            chosen = option_of(by_id[step_id].options, answer)
            return answer.strip() if chosen is None else chosen.name

        sheet = Loner4eEntity(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            concept=picked(picks, "concept"),
            tags={
                "skill": [taken(f"skill-{slot}") for slot in (1, 2)],
                "frailty": [taken("frailty")],
                "gear": [taken(f"gear-{slot}") for slot in (1, 2)],
            },
            goal=picked(picks, "goal"),
            motive=picked(picks, "motive"),
            nemesis=picked(picks, "nemesis"),
        )
        return self.sheet_character(name, sheet)

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
                "below unless `against_id` names another)",
                world.conflict_lines(),
            ),
            *section_if("WHAT THE TAGS IN PLAY MEAN", glossary),
        )

    @tool
    def change_tags(self, draft: Loner4eGame, args: ChangeTags, _rng: Random) -> list[Fact]:
        """A character here, or the scene, gains tags, loses tags, or does both."""
        world = draft.world
        if args.kind == "detail":
            world.require_open()
            return world.frame.change_details(args.gained, args.lost)
        actor, entered = world.met_here(args.actor_id)
        if actor is world.player and args.kind in ("skill", "frailty") and args.gained:
            _grow(world, args.gained)
        marked = actor is world.player and args.kind == "condition" and args.gained
        if marked and world.opponent_ids:
            raise Refusal(CONFLICT_MARKS)
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
        asked = world.take_question()
        question = asked or args.question
        if question is None:
            raise Refusal(QUESTION_REQUIRED)
        fought = args.against_id if world.opponent_ids or not asked else None
        against_id = fought or next(reversed(world.opponent_ids), None)
        opponent, entered = (None, []) if against_id is None else world.met_here(against_id)
        world.check_cited(args.helps, args.hinders)
        position = position_for(len(args.helps), len(args.hinders))
        faced, facing = _absorbed([] if opponent is None else world.face(opponent))
        consulted = world.consult(question, position, rng, settle=opponent is None)
        cited = (*(f"+{tag}" for tag in args.helps), *(f"-{tag}" for tag in args.hinders))
        lines = (*((f"tags: {', '.join(cited)}",) if cited else ()), *facing)
        hoped = not asked
        if opponent is None:
            return [*consulted.facts(*lines, hoped=hoped), *_twist(draft, consulted, rng)]
        absorbed, more = _absorbed(_exchange(draft, opponent, consulted.outcome))
        return [*entered, *consulted.facts(*lines, *more, hoped=hoped), *faced, *absorbed]

    @action
    def mark_status(self, draft: Loner4eGame, args: MarkStatus, _rng: Random) -> list[Fact]:
        if args.column is None:
            return [Fact(trace="the defeat leaves no lasting mark")]
        return draft.world.status.mark(args.column)

    @action
    def fight(self, draft: Loner4eGame, args: Fight, _rng: Random) -> list[Fact]:
        world = draft.world
        opponent = world.require_living_here(args.opponent_id)
        trace = f"the protagonist fights {opponent.tag}: each `ask` is an exchange"
        card = Fact(trace=trace, told=True, card=f"Fight: {opponent.name}")
        return [card, *world.face(opponent)]

    @tool
    @action
    def withdraw(self, draft: Loner4eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        """The protagonist stops fighting and breaks off the Harm & Luck conflict: always
        allowed, never free. While the conflict is open every `ask` is an exchange, so call this
        first when the protagonist turns to anything else."""
        world = draft.world
        if not world.opponent_ids:
            raise Refusal("no conflict is open")
        absorbed, lines = _absorbed(world.end_conflict("the protagonist breaks away"))
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
        draft.pending = ending_decision(args.why)
        return [Fact(trace=f"the end is proposed: {args.why}")]

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

    @action
    def recover(self, draft: Loner4eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        aim = RECOVERING.format(status=draft.world.status.active)
        draft.request = WorldsmithRequest(kind=RECOVERY_SCENE_REQUEST, detail=aim)
        return []

    @tool
    def spend_luck(self, draft: Loner4eGame, args: SpendLuck, _rng: Random) -> list[Fact]:
        """A character here spends luck."""
        world = draft.world
        facts, beaten = world.spend(world.require_living_here(args.actor_id), args.amount, args.why)
        if beaten is not None:
            _defeated(draft, beaten)
        return facts


def _invented(step_id: Slug, name: str, options: tuple[DecisionOption, ...]) -> CreationStep:
    return CreationStep(id=step_id, name=name, options=options, allows_text=True)


def _await_living_world(draft: Loner4eGame) -> None:
    draft.pending = living_world_decision()
    draft.request = WorldsmithRequest(kind=LIVING_WORLD_REQUEST, detail=draft.world.end_why)


def _hand_over(draft: Loner4eGame) -> None:
    frame = draft.world.frame
    if frame.meanwhile:
        draft.request = WorldsmithRequest(kind=MEANWHILE_REQUEST, detail=frame.coming)
    elif frame.next == "dramatic":
        draft.request = WorldsmithRequest(kind=DRAMATIC_SCENE_REQUEST)


def _defeated(draft: Loner4eGame, beaten: Loner4eEntity) -> None:
    draft.note(DEFEATED.format(name=beaten.name))
    status = draft.world.status
    if beaten is draft.world.player and not status.full:
        draft.note(MARK_ONLY)
        draft.pending = status_mark_decision(len(status.boxes))


def _exchange(draft: Loner4eGame, opponent: Loner4eEntity, outcome: RollOutcome) -> list[Fact]:
    facts, beaten = draft.world.strike(opponent, outcome)
    if beaten is not None:
        _defeated(draft, beaten)
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
    return any(exchange.cause is None for exchange in draft.log[-1].exchanges)


def _absorbed(exchange: list[Fact]) -> tuple[list[Fact], tuple[str, ...]]:
    lines = tuple(fact.card for fact in exchange if fact.told and fact.card)
    return [fact.model_copy(update={"card": ""}) for fact in exchange], lines


def _twist(draft: Loner4eGame, consulted: Consulted, rng: Random) -> list[Fact]:
    world = draft.world
    if (twisted := world.roll_twist(consulted, rng)) is None:
        return []
    (subject, action), facts = twisted
    note = TWIST_NOTE.format(subject=subject.upper(), action=action.upper())
    draft.note(f"{note} {TWIST_ACTION_NOTES[action]}" if action in TWIST_ACTION_NOTES else note)
    return [*facts, *world.close("twist", rng)] if action == ENDS_THE_SCENE else facts
