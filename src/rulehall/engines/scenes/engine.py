from collections.abc import Iterable, Mapping
from pathlib import Path
from random import Random
from typing import Any

from rulehall.core.facts import Fact
from rulehall.core.model import (
    AnyCharacter,
    AnyScenario,
    Character,
    Game,
    RoleAnswer,
    WorldsmithRequest,
)
from rulehall.core.play import DecisionOption
from rulehall.core.prompt import Prompt, Sections, render_history, section_if
from rulehall.core.tools import tool
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import NarratorView, Panel, PanelRow, PlayerView
from rulehall.engines.engine import Engine, RequestHandler, Resolution
from rulehall.engines.entities import ARC_TITLE, HIDDEN_TITLE, Person, party_section
from rulehall.engines.packs import Pack
from rulehall.engines.panels import character_panel, here_panel, party_panel
from rulehall.engines.scenes.args import MOVING_ON, SCENE_LEFT, Enter, Leave, NextScene
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.scenes.worldsmith import (
    COMPLICATING,
    CROSSING,
    MEANWHILE_NUDGE,
    OPENING,
    OPENING_SECTIONS,
    TURNING,
    check_next,
    check_opening,
)

DEPARTURE: Slug = "departure"
COMPLICATION: Slug = "complication"
MOVE_ON = DecisionOption(
    id="move-on", name="Move on", brief="Keep playing, or say where you go and move on."
)
WAY_UNWRITTEN = Fact(
    told=True,
    trace="the way on could not be written",
    card="The way on could not be written. You are still where you were.",
)
COMPLICATION_UNWRITTEN = Fact(
    told=True,
    trace="the complication could not be written",
    card="Nothing new came down on this place after all. You are still where you were.",
)


class SceneEngine[C: Person, W: SceneWorld[Any], K: Pack](Engine[W, K]):
    family_dir = Path(__file__).parent
    opening_sections = OPENING_SECTIONS
    opening_intent = OPENING
    person: type[C]
    next_proposal: type[NextProposal[C]]

    def __init__(self, player_packs: Path) -> None:
        super().__init__(player_packs)
        self.character = Character[self.person]

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {
            DEPARTURE: RequestHandler(self.depart, WAY_UNWRITTEN),
            COMPLICATION: RequestHandler(self.complicate, COMPLICATION_UNWRITTEN),
        }

    def player_of(self, character: AnyCharacter) -> C:
        return self.player_as(character, self.person)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> W:
        # Copied: a restart reopens the same scenario file.
        proposal: SceneProposal[C] = scenario.opening.model_copy(deep=True)
        check_opening(proposal)
        world = self.world.opening(proposal, self.player_of(character))
        world.absorb(proposal)
        return world

    def master_sections(self, state: Game[W]) -> Sections:
        world = state.world
        scene = world.scene
        return (
            ("SCENE", f"{scene.title}\nlocation: {scene.location}\n{scene.situation}"),
            *self.player_sections(state),
            ("HERE WITH THE PLAYER", world.here_lines()),
            *party_section(world.party_members()),
            (HIDDEN_TITLE, world.hidden_lines()),
            *section_if(ARC_TITLE, world.arc),
            *self.packs.rules_section(state.pack_id),
        )

    def player_sections(self, state: Game[W]) -> Sections:
        return (("YOU PLAY FOR", state.world.player.line()),)

    def worldsmith_sections(self, draft: Game[W]) -> Sections:
        world = draft.world
        return (
            ("SCENES SO FAR", render_history(draft.log)),
            ("THE WHOLE CAST", world.cast_lines()),
            ("THE SCENE NOW", world.scene_lines()),
        )

    def context_lines(self, state: Game[W]) -> str:
        return f"location: {state.world.scene.location}"

    def narrator_view(self, state: Game[W]) -> NarratorView:
        world = state.world
        scene = world.scene
        here = list(world.here())
        return NarratorView(
            place_id=scene.place_id,
            title=scene.title,
            situation=scene.situation,
            subjects=tuple(member.subject() for member in here),
            speakers=tuple(member.id for member in here if member.alive),
            party=(world.player.id, *world.party),
            sheet=world.sheet_rows(),
        )

    def player_view(self, state: Game[W]) -> PlayerView:
        world = state.world
        return PlayerView(
            premise=state.scenario.premise,
            player=world.player.subject(),
            scene_title=world.scene.title,
            situation=world.scene.situation,
            panels=self.scene_panels(state),
            decision=state.pending,
            way_on=MOVE_ON if world.scene.way_offered else None,
            ending=self.ending(state),
        )

    def scene_panels(self, state: Game[W]) -> tuple[Panel, ...]:
        world = state.world
        return (
            character_panel(world.sheet_rows()),
            *party_panel(world.party_members()),
            here_panel(other.subject() for other in world.others()),
            trail_panel(scene.title for scene in world.scenes),
        )

    @tool
    def enter(self, draft: Game[W], args: Enter, _rng: Random) -> list[Fact]:
        """Bring a cast member into the scene."""
        return draft.world.enter(args.target_id)

    @tool
    def leave(self, draft: Game[W], args: Leave, _rng: Random) -> list[Fact]:
        """Send a cast member out of the scene."""
        return draft.world.leave(args.target_id)

    @tool
    def next_scene(self, draft: Game[W], args: NextScene, _rng: Random) -> list[Fact]:
        """Call this with nothing set when the scene reaches a stopping point. Set `pursuit`
        instead when the player has left this place. Set `complication` instead to bring a new
        situation into this place."""
        if args.pursuit:
            draft.request = WorldsmithRequest(kind=DEPARTURE, detail=args.pursuit)
            return [SCENE_LEFT]
        if not args.complication:
            return draft.world.offer_way_on()
        draft.request = WorldsmithRequest(kind=COMPLICATION, detail=args.complication)
        return [
            Fact(
                trace=f"the worldsmith writes the complication once this turn ends: "
                f"{args.complication}. Nothing more happens this turn; stop and exit",
            )
        ]

    def take_way_on(self, draft: Game[W], way_on_id: Slug, _words: str) -> None:
        if way_on_id != MOVE_ON.id or not draft.world.scene.way_offered:
            raise Refusal("the way on has changed since the page was drawn")
        draft.note(MOVING_ON)

    def render_next(self, draft: Game[W], intent: str) -> Prompt:
        world = draft.world
        if world.arc:
            intent += (
                f"\n\nThe arc as last written:\n{world.arc}\n"
                "Revise `arc` only where what happened makes a change necessary. Leave "
                "`arc` empty to keep it."
            )
        if world.meanwhile_due:
            intent += f"\n\n{MEANWHILE_NUDGE}"
        return self.render_request(
            draft,
            guidance=self.guidance_for(draft.pack_id, opening=False),
            intent=intent,
            answer_model=self.next_proposal,
        )

    async def write_next(
        self, draft: Game[W], intent: str, worldsmith: RoleAnswer, *, moving: bool
    ) -> NextProposal[C]:
        world = draft.world
        prompt = self.render_next(draft, intent)
        return await worldsmith(
            prompt,
            self.next_proposal,
            lambda answer: check_next(answer, world, moving=moving),
        )

    def install(self, draft: Game[W], proposal: NextProposal[C]) -> list[Fact]:
        world = draft.world
        draft.log[-1].recap = proposal.recap
        world.apply_scene(proposal)
        world.absorb(proposal)
        world.clear_meanwhile()
        self.open_chapter(draft)
        trace = f"the scene opens: {proposal.title}"
        if travelling := [member.name for member in world.party_members()]:
            trace += f", the player travelling with {', '.join(travelling)}"
        return [Fact(trace=trace, told=True, card=f"New scene: {proposal.title}")]

    async def depart(
        self, draft: Game[W], request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        left = draft.world.scene.title
        exchanges = draft.exchanges()
        # The master's `pursuit` is free text; the narrator reads the player's own words instead.
        asked = exchanges[-1].words if exchanges else ""
        scene = await self.write_next(draft, request.detail, worldsmith, moving=True)
        return Resolution(
            tuple(self.install(draft, scene)), CROSSING.format(left=left, asked=asked)
        )

    async def complicate(
        self, draft: Game[W], request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        scene = await self.write_next(
            draft, COMPLICATING.format(brief=request.detail), worldsmith, moving=False
        )
        return Resolution(tuple(self.install(draft, scene)), TURNING)


def trail_panel(titles: Iterable[str]) -> Panel:
    return Panel(title="Trail", rows=tuple(PanelRow(name=title, brief="") for title in titles))
