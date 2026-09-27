from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random
from typing import cast

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
from rulehall.core.play import DecisionOption, PendingDecision, PendingOption
from rulehall.core.prompt import Sections, section_if
from rulehall.core.tools import MasterTool, NoArgs, action, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import NarratorView, Panel
from rulehall.engines.args import Words
from rulehall.engines.engine import RequestHandler, Resolution
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.hiring import Joining
from rulehall.engines.loner4e.args import (
    ARRIVING,
    ARRIVING_QUIET,
    ASK_ORACLE,
    BROKE_AWAY,
    CONCEPT_GROWS,
    CONFLICT_MARKS,
    DEFEATED,
    DRAMATIC_CLOSES,
    ENDING_PROMPT,
    EPILOGUE,
    GROWN,
    GROWTH,
    GROWTH_PROMPT,
    GROWTH_WAITS,
    LAST_WORDS,
    LIVING_WORLD_UNWRITTEN,
    MARK_ONLY,
    MAY_END,
    MEANWHILE_CUE,
    MEANWHILE_UNSAID,
    NO_MARK,
    PLAY_ON,
    QUESTION_REQUIRED,
    QUIET_LASTS,
    RECOVERING,
    SCENE_UNWRITTEN,
    STATUS_PROMPT,
    STILL_IN_IT,
    TAKE_BREATHER,
    TWIST_ACTION_NOTES,
    TWIST_NOTE,
    UNWRITTEN_PROMPT,
    WRITE_LIVING_WORLD,
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
from rulehall.engines.loner4e.panels import here_panel, scene_panel, sheet_panel
from rulehall.engines.loner4e.rules import (
    ENDS_THE_SCENE,
    SCENE_ID,
    STATUS_TAGS,
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
from rulehall.engines.scenes.engine import SceneEngine
from rulehall.engines.scenes.world import SceneProposal
from rulehall.engines.scenes.worldsmith import OPENING, check_next, check_opening, next_needs

LET_PLAY_DECIDE = "Leave empty to let play decide"
ELSEWHERE_TITLE = "MET, NOT HERE (use these ids when one of them comes back)"


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
            "quiet": RequestHandler(self.write_quiet, SCENE_UNWRITTEN),
            "recovery": RequestHandler(self.write_quiet, SCENE_UNWRITTEN),
            "dramatic": RequestHandler(self.write_dramatic, SCENE_UNWRITTEN),
            "meanwhile": RequestHandler(self.write_meanwhile, SCENE_UNWRITTEN),
            "living-world": RequestHandler(self.write_living_world, LIVING_WORLD_UNWRITTEN),
        }

    def check_opening(self, proposal: SceneProposal[Loner4eEntity]) -> None:
        # Safe: the engine opens on a Loner4eOpening only.
        opening = cast(Loner4eOpening, proposal)
        check_opening(opening, needs=_loner_needs(opening))

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
        _sheet, *party, _here, trail = super().scene_panels(state)
        scene = scene_panel(world, played=_played_here(state))
        return (sheet_panel(world), scene, *party, here_panel(world), trail)

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
        # SRD: recovery needs a scene framed around it, not just time passing.
        if request.kind == "recovery":
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
                needs += next_needs(scene, moved, needs=_loner_needs(scene))
            if needs:
                raise Refusal("the meanwhile needs " + "; ".join(needs))

        answer = await self.ask_worldsmith(draft, intent, worldsmith, Loner4eMeanwhile, check)
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
        answer = await self.ask_worldsmith(draft, intent, worldsmith, LivingWorld, check)
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
        """SPECIAL RULES come from the played pack, so the cost in luck does too."""
        return self.packs.require(state.pack_id).spends_luck

    async def _frame_next(
        self, draft: Loner4eGame, intent: str, worldsmith: RoleAnswer
    ) -> list[Fact]:
        world = draft.world

        def check(answer: Loner4eNext) -> None:
            check_next(answer, world, needs=_loner_needs(answer))

        return await self.write_scene(draft, intent, worldsmith, Loner4eNext, check)

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
            # SRD: the player invents their traits; the pack tables are suggestions.
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
        # The concept's pack blurb is generic where the entity's own brief is not: skip it.
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
        # A player's question with no conflict open asks what is true: it opens no exchange.
        fought = args.against_id if world.opponent_ids or not asked else None
        # SRD: in Harm & Luck every question is an exchange; the one fought last by default.
        against_id = fought or next(reversed(world.opponent_ids), None)
        opponent, entered = (None, []) if against_id is None else world.met_here(against_id)
        world.check_cited(args.helps, args.hinders)
        position = position_for(len(args.helps), len(args.hinders))
        faced, facing = _absorbed([] if opponent is None else world.face(opponent))
        # An exchange is not an established fact: the next exchange asks it again.
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
        end_it = PendingOption(
            id="end-it", name="End it", action_name="confirm_end", args={"why": args.why}
        )
        draft.pending = PendingDecision(
            kind="ending",
            prompt=ENDING_PROMPT.format(why=args.why.rstrip(".")),
            options=(end_it, PLAY_ON),
            allows_text=False,
        )
        return [Fact(trace=f"the end is proposed: {args.why}")]

    @action
    def confirm_end(self, draft: Loner4eGame, args: ConfirmEnd, _rng: Random) -> list[Fact]:
        world = draft.world
        world.end_why = args.why
        draft.pending = PendingDecision(
            kind="growth",
            prompt=GROWTH_PROMPT.format(name=world.player.name),
            options=(),
            allows_text=True,
        )
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
        draft.request = WorldsmithRequest(kind="quiet", detail=args.words)
        return []

    @action
    def recover(self, draft: Loner4eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        aim = RECOVERING.format(status=draft.world.status.active)
        draft.request = WorldsmithRequest(kind="recovery", detail=aim)
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
    """The end is confirmed: until the Living World lands, the only way on is its write."""
    draft.pending = PendingDecision(
        kind="living-world",
        prompt=UNWRITTEN_PROMPT,
        options=(WRITE_LIVING_WORLD,),
        allows_text=False,
    )
    draft.request = WorldsmithRequest(kind="living-world", detail=draft.world.end_why)


def _hand_over(draft: Loner4eGame) -> None:
    frame = draft.world.frame
    if frame.meanwhile:
        draft.request = WorldsmithRequest(kind="meanwhile", detail=frame.coming)
    elif frame.next == "dramatic":
        draft.request = WorldsmithRequest(kind="dramatic")


def _status_options(box: int) -> tuple[PendingOption, ...]:
    return tuple(
        PendingOption(
            id=column,
            name=column.capitalize(),
            brief=tags[box],
            action_name="mark_status",
            args={"column": column},
        )
        for column, tags in STATUS_TAGS.items()
    )


def _defeated(draft: Loner4eGame, beaten: Loner4eEntity) -> None:
    draft.note(DEFEATED.format(name=beaten.name))
    status = draft.world.status
    if beaten is draft.world.player and not status.full:
        draft.note(MARK_ONLY)
        draft.pending = PendingDecision(
            kind="status",
            prompt=STATUS_PROMPT,
            options=(*_status_options(len(status.boxes)), NO_MARK),
            allows_text=False,
        )


def _exchange(draft: Loner4eGame, opponent: Loner4eEntity, outcome: RollOutcome) -> list[Fact]:
    facts, beaten = draft.world.strike(opponent, outcome)
    if beaten is not None:
        _defeated(draft, beaten)
        return facts
    return [*facts, Fact(trace=STILL_IN_IT.format(name=opponent.name))]


def _grow(world: Loner4eWorld, gained: Sequence[str]) -> None:
    """SRD: a new skill or frailty is the post-game growth, written once after the end."""
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
    """Move on is not the player's words: the ones before it belong to the scene left behind."""
    if draft.world.frame.closed_by == "moved_on":
        return ""
    return LAST_WORDS.format(words=draft.last_words())


def _played_here(draft: Loner4eGame) -> bool:
    """A turn the player played in this scene; the scene's own arrival is the story's."""
    return any(exchange.cause is None for exchange in draft.log[-1].exchanges)


def _loner_needs(proposal: Loner4eOpening | Loner4eNext) -> list[str]:
    if SCENE_ID in proposal.cast:
        return [f"no cast entry filed under `{SCENE_ID}`: that id names the scene"]
    return []


def _absorbed(exchange: list[Fact]) -> tuple[list[Fact], tuple[str, ...]]:
    """The exchange reads as lines inside the Oracle card, so it shows no cards of its own."""
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
