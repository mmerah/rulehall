from collections.abc import Callable, Iterable
from pathlib import Path
from random import Random
from typing import Any

from pydantic import BaseModel

from rulehall.core.facts import Fact
from rulehall.core.model import AnyCharacter, AnyScenario, Character, Game, RoleAnswer
from rulehall.core.play import PendingOption
from rulehall.core.prompt import Sections, render_history, section_if
from rulehall.core.tools import tool
from rulehall.core.views import NarratorView, Panel, PanelRow, PlayerView
from rulehall.engines.engine import Engine
from rulehall.engines.entities import HIDDEN_TITLE, Person, party_section
from rulehall.engines.packs import Pack
from rulehall.engines.panels import character_panel, here_panel, party_panel
from rulehall.engines.scenes.args import Enter, Leave
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.scenes.worldsmith import OPENING, OPENING_SECTIONS, check_opening

SCENE_ARC_TITLE = (
    "THE ARC (pressure and intent the player has not found; SCENE, the sheet and SETTLED THIS "
    "SCENE override it)"
)
FIXED_TITLE = "FIXED (settled or told in play: they stand, whatever the arc says)"


class SceneEngine[C: Person, W: SceneWorld[Any], K: Pack](Engine[W, K]):
    family_dir = Path(__file__).parent
    opening_sections = OPENING_SECTIONS
    opening_intent = OPENING
    person: type[C]

    def __init__(self, player_packs: Path) -> None:
        super().__init__(player_packs)
        self.character = Character[self.person]

    def player_of(self, character: AnyCharacter) -> C:
        return self.player_as(character, self.person)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> W:
        # Copied: a restart reopens the same scenario file.
        proposal: SceneProposal[C] = scenario.opening.model_copy(deep=True)
        self.check_opening(proposal)
        world = self.world.opening(proposal, self.player_of(character))
        world.absorb(proposal)
        return world

    def check_opening(self, proposal: SceneProposal[C]) -> None:
        check_opening(proposal)

    def composer(self, _state: Game[W]) -> tuple[PendingOption | None, bool]:
        return None, False

    def scene_text(self, state: Game[W]) -> str:
        scene = state.world.scene
        return f"{scene.title}\nlocation: {scene.location}\n{scene.situation}"

    def master_sections(self, state: Game[W]) -> Sections:
        world = state.world
        return (
            ("SCENE", self.scene_text(state)),
            *self.player_sections(state),
            ("HERE WITH THE PLAYER", world.here_lines()),
            *party_section(world.party_members()),
            *section_if("SETTLED THIS SCENE", world.settled_lines()),
            *section_if(HIDDEN_TITLE, world.hidden_lines()),
            *section_if(SCENE_ARC_TITLE, world.arc),
            *self.packs.rules_section(state.pack_id),
        )

    def player_sections(self, state: Game[W]) -> Sections:
        return (("YOU PLAY FOR", state.world.player_line()),)

    def worldsmith_sections(self, draft: Game[W]) -> Sections:
        world = draft.world
        history = draft.exchanges()
        told = [f"- {fact.trace}" for fact in history[-1].facts if fact.told] if history else []
        return (
            ("SCENES SO FAR", render_history(draft.log)),
            ("THE WHOLE CAST", world.cast_lines()),
            ("THE SCENE NOW", world.scene_lines()),
            *section_if(FIXED_TITLE, "\n".join((world.settled_lines(), *told)).strip()),
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
        option, only = self.composer(state) if state.pending is None else (None, False)
        return PlayerView(
            premise=state.scenario.premise,
            player=world.player.subject(),
            scene_title=world.scene.title,
            situation=world.scene.situation,
            panels=self.scene_panels(state),
            decision=state.pending,
            ending=self.ending(state),
            composer_option=option,
            composer_only=only,
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

    async def write_scene[P: NextProposal[Any]](
        self,
        draft: Game[W],
        intent: str,
        worldsmith: RoleAnswer,
        answer_model: type[P],
        check: Callable[[P], None],
    ) -> list[Fact]:
        scene = await self.ask_worldsmith(draft, intent, worldsmith, answer_model, check)
        return self.install_scene(draft, scene)

    async def ask_worldsmith[A: BaseModel](
        self,
        draft: Game[W],
        intent: str,
        worldsmith: RoleAnswer,
        answer_model: type[A],
        check: Callable[[A], None],
    ) -> A:
        world = draft.world
        if world.arc:
            intent += (
                f"\n\nThe arc as last written (FIXED and SCENES SO FAR override it):\n{world.arc}"
            )
            if "arc" in answer_model.model_fields:
                intent += (
                    "\nRevise `arc` only where what happened makes a change necessary. Leave "
                    "`arc` empty to keep it."
                )
        prompt = self.render_request(
            draft,
            guidance=self.guidance_for(draft.pack_id, opening=False),
            intent=intent,
            answer_model=answer_model,
        )
        return await worldsmith(prompt, answer_model, check)

    def install_scene(self, draft: Game[W], scene: NextProposal[Any]) -> list[Fact]:
        world = draft.world
        draft.log[-1].recap = scene.recap
        world.apply_scene(scene)
        world.absorb(scene)
        self.open_chapter(draft)
        trace = f"the scene opens: {scene.title}"
        if travelling := [member.name for member in world.party_members()]:
            trace += f", the player travelling with {', '.join(travelling)}"
        return [Fact(trace=trace, told=True, card=f"New scene: {scene.title}")]


def trail_panel(titles: Iterable[str]) -> Panel:
    return Panel(title="Trail", rows=tuple(PanelRow(name=title, brief="") for title in titles))
