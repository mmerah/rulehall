from abc import abstractmethod
from pathlib import Path
from random import Random
from typing import Any

from rulehall.core.facts import Fact
from rulehall.core.game import AnyCharacter, AnyScenario, Game
from rulehall.core.prompt import Sections, render_log, section_if
from rulehall.core.tools import tool
from rulehall.core.views import Panel
from rulehall.engines.engine import Engine, SceneHeader
from rulehall.engines.packs import Pack
from rulehall.engines.panels import here_panel
from rulehall.engines.scenes.args import Enter, Leave
from rulehall.engines.scenes.panels import trail_panel
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.scenes.worldsmith import OPENING, OPENING_SECTIONS, check_next, check_opening
from rulehall.engines.sheet import Person
from rulehall.engines.world import ARC_SO_FAR_TITLE, HIDDEN_TITLE, party_section

SCENE_ARC_TITLE = (
    "THE ARC (pressure and intent the player has not found; SCENE, the sheet and SETTLED THIS "
    "SCENE override it)"
)
FIXED_TITLE = "FIXED (settled or told in play: they stand, whatever the arc says)"


class SceneEngine[P: Person, W: SceneWorld[Any], K: Pack, R: NextProposal[Any]](Engine[P, W, K, R]):
    family_dir = Path(__file__).parent
    opening_sections = OPENING_SECTIONS
    opening_intent = OPENING

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> W:
        proposal: SceneProposal[P] = scenario.opening.filed_by_name()
        check_opening(proposal)
        return self.world_model.opening(proposal, self.player_of(character))

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

    def worldsmith_sections(self, draft: Game[W], /) -> Sections:
        world = draft.world
        history = draft.log_entries()
        told = [f"- {fact.trace}" for fact in history[-1].facts if fact.told] if history else []
        return (
            *section_if(ARC_SO_FAR_TITLE, world.arc),
            ("SCENES SO FAR", render_log(draft.chapters)),
            ("THE WHOLE CAST", world.cast_lines()),
            ("THE SCENE NOW", world.scene_lines()),
            *section_if(FIXED_TITLE, "\n".join((world.settled_lines(), *told)).strip()),
        )

    def context_text(self, state: Game[W]) -> str:
        return f"location: {state.world.scene.location}"

    def scene_header(self, state: Game[W], /) -> SceneHeader:
        scene = state.world.scene
        return SceneHeader(place_id=scene.place_id, title=scene.title, situation=scene.situation)

    def scene_panels(self, state: Game[W], /) -> tuple[Panel | None, ...]:
        world = state.world
        return (
            *self.lead_panels(state),
            here_panel(other.subject() for other in world.others()),
            trail_panel(scene.title for scene in world.scenes),
        )

    @abstractmethod
    def lead_panels(self, state: Game[W], /) -> tuple[Panel | None, ...]: ...

    @tool
    def enter(self, draft: Game[W], args: Enter, _rng: Random) -> list[Fact]:
        """Bring a cast member into the scene."""
        return draft.world.enter(args.target_id, args.voice)

    @tool
    def leave(self, draft: Game[W], args: Leave, _rng: Random) -> list[Fact]:
        """Send a cast member out of the scene."""
        return draft.world.leave(args.target_id)

    def check_next(self, draft: Game[W], proposal: R, /) -> None:
        check_next(proposal, draft.world)

    def install_next(self, draft: Game[W], proposal: R, /) -> list[Fact]:
        world = draft.world
        proposal = proposal.filed_by_name()
        draft.chapters[-1].recap = proposal.recap
        world.apply_scene(proposal)
        self.open_chapter(draft)
        trace = f"the scene opens: {proposal.title}"
        if travelling := [member.name for member in world.party_members()]:
            trace += f", the player travelling with {', '.join(travelling)}"
        return [Fact(trace=trace, told=True, card=f"New scene: {proposal.title}")]
