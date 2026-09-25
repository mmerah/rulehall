from collections.abc import Mapping
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
from rulehall.core.prompt import Sections, lines_of, render_history, section_if
from rulehall.core.tools import action, tool
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import NarratorView, PlayerView
from rulehall.engines.engine import Engine, RequestHandler, Resolution
from rulehall.engines.entities import ARC_TITLE, HIDDEN_TITLE, party_section
from rulehall.engines.packs import Pack
from rulehall.engines.panels import character_panel, here_panel, party_panel
from rulehall.engines.rooms.args import (
    ELSEWHERE,
    MOVED_CARD,
    MOVES_OFFSCREEN,
    NOTHING_OFFSCREEN,
    DropHere,
    Meanwhile,
    Move,
    MoveItem,
    UnlockWay,
)
from rulehall.engines.rooms.panels import carried_panel, map_view, ways_panel
from rulehall.engines.rooms.world import Dweller, MapProposal, Prop, RegionProposal, RoomWorld
from rulehall.engines.rooms.worldsmith import MAP_ASK, OPENING_SECTIONS, check_map, check_next_map

EXTEND: Slug = "extend"
MORE_MAP = DecisionOption(
    id=EXTEND, name="More map", brief="The map runs out here: say where you push on."
)
MAP_UNWRITTEN = Fact(
    told=True,
    trace="the map could not be written",
    card="The map could not be written. You are still where you were.",
)


# Generic over its dweller: the family cannot import the one engine that names it.
class RoomEngine[N: Dweller, W: RoomWorld[Any], K: Pack](Engine[W, K]):
    family_dir = Path(__file__).parent
    opening_sections = OPENING_SECTIONS
    opening_intent = MAP_ASK
    person: type[N]
    next_proposal: type[RegionProposal[N]]

    def __init__(self, player_packs: Path) -> None:
        super().__init__(player_packs)
        self.character = Character[self.person]

    def player_of(self, character: AnyCharacter) -> N:
        return self.player_as(character, self.person)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> W:
        proposal: MapProposal[N] = scenario.opening
        check_map(proposal)
        player = self.player_of(character)
        world = self.world.opening(proposal, player, self.starting_items(proposal, player))
        world.absorb(proposal)
        return world

    def starting_items(self, _proposal: MapProposal[N], _player: N, /) -> tuple[Prop, ...]:
        return ()

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {EXTEND: RequestHandler(self.extend, MAP_UNWRITTEN)}

    def worldsmith_sections(self, draft: Game[W]) -> Sections:
        world = draft.world
        return (
            ("MAP SO FAR", world.map_so_far()),
            *section_if("THE ARC SO FAR", world.arc),
            ("SCENES SO FAR", render_history(draft.log)),
            ("THE PLAYER", world.line(world.player)),
        )

    def master_sections(self, state: Game[W]) -> Sections:
        world = state.world
        place = world.current
        player = world.player
        return (
            ("CURRENT PLACE", f"{place.tag}\n{place.description}"),
            ("YOU PLAY FOR", world.line(player)),
            ("CARRYING", lines_of(world.line(item) for item in world.carried(player.id))),
            ("HERE WITH THE PLAYER", world.place_lines(known=True)),
            *party_section(world.party_members()),
            (HIDDEN_TITLE, world.place_lines(known=False)),
            *section_if(ARC_TITLE, world.arc),
            ("WAYS OUT", world.ways_lines()),
            *self.packs.rules_section(state.pack_id),
            *(((ELSEWHERE, world.elsewhere_lines()),) if world.meanwhile_due else ()),
        )

    def context_lines(self, state: Game[W]) -> str:
        return f"place: {state.world.current.name}"

    def narrator_view(self, state: Game[W]) -> NarratorView:
        world = state.world
        place = world.current
        here = tuple(entity for entity in world.here() if entity.known)
        carrying = ", ".join(item.name for item in world.carried(world.player.id))
        return NarratorView(
            place_id=place.id,
            title=place.name,
            situation="\n".join(part for part in (place.brief, place.description) if part),
            subjects=tuple(entity.subject() for entity in here),
            # A corpse may stay a subject in the room; it does not speak.
            speakers=tuple(entity.id for entity in here if entity.alive),
            party=(world.player.id, *world.party),
            sheet=(*world.sheet_rows(), ("Carrying", carrying or "nothing")),
        )

    def player_view(self, state: Game[W]) -> PlayerView:
        world = state.world
        player = world.player
        return PlayerView(
            premise=state.scenario.premise,
            player=player.subject(),
            scene_title=world.current.name,
            situation=world.current.description,
            panels=(
                character_panel(world.sheet_rows()),
                *party_panel(world.party_members()),
                here_panel(other.subject() for other in world.others()),
                carried_panel(world),
                ways_panel(world),
            ),
            decision=state.pending,
            way_on=MORE_MAP if world.frontier() == 0 else None,
            ending=self.ending(state),
            map=map_view(world),
        )

    @action
    def drop_here(self, draft: Game[W], args: DropHere, _rng: Random) -> list[Fact]:
        world = draft.world
        _ = world.carried_items(world.player, (args.item_id,))
        return world.move_item(args.item_id, world.current.id)

    @tool
    def move_item(self, draft: Game[W], args: MoveItem, _rng: Random) -> list[Fact]:
        """Move an item to a new holder."""
        return draft.world.move_item(args.item_id, args.to_id)

    @tool
    def unlock_way(self, draft: Game[W], args: UnlockWay, _rng: Random) -> list[Fact]:
        """Open a locked way out of this place."""
        return draft.world.unlock_way(args.to_id)

    @tool
    def move(self, draft: Game[W], args: Move, _rng: Random) -> list[Fact]:
        """Move the player through an unlocked way out of this place."""
        return draft.world.move(args.to_id, args.with_ids)

    @tool
    def meanwhile(self, draft: Game[W], args: Meanwhile, _rng: Random) -> list[Fact]:
        """Time passes where the player is not. Move a dweller, move a loose item, and shut a
        way the player knows. Use any combination in one call. Call this only while ELSEWHERE is
        shown."""
        world = draft.world
        if not world.meanwhile_due:
            raise Refusal(NOTHING_OFFSCREEN)
        facts: list[Fact] = []
        if args.dweller_id is not None and args.dweller_to_id is not None:
            npc = world.require_dweller(args.dweller_id)
            facts.append(world.walk_offscreen(npc, world.offscreen_place(args.dweller_to_id)))
        if args.item_id is not None and args.item_to_id is not None:
            item = world.require_prop(args.item_id)
            facts.append(world.drift_item(item, world.offscreen_place(args.item_to_id)))
        if args.shut_from_id is not None and args.shut_to_id is not None:
            start = world.require_place(args.shut_from_id)
            facts.append(world.shut_way(start, world.require_place(args.shut_to_id)))
        facts.append(Fact(trace=MOVES_OFFSCREEN, told=True, card=MOVED_CARD))
        world.clear_meanwhile()
        return facts

    def take_way_on(self, draft: Game[W], way_on_id: Slug, words: str) -> None:
        if way_on_id != EXTEND or draft.world.frontier():
            raise Refusal("the map still has ways to walk; the page was drawn before them")
        if not words:
            raise Refusal("say where you push on")
        draft.request = WorldsmithRequest(kind=EXTEND, detail=words)

    def check_next(self, draft: Game[W], proposal: RegionProposal[N]) -> None:
        check_next_map(proposal, draft.world)

    async def write_next(
        self, draft: Game[W], intent: str, worldsmith: RoleAnswer
    ) -> RegionProposal[N]:
        prompt = self.render_request(
            draft,
            intent=intent,
            guidance=self.guidance_for(draft.pack_id, opening=False),
            answer_model=self.next_proposal,
        )
        return await worldsmith(
            prompt, self.next_proposal, lambda answer: self.check_next(draft, answer)
        )

    def install(self, draft: Game[W], proposal: RegionProposal[N]) -> None:
        """Hidden, so nothing is told: the region reaches the player only as they walk it."""
        draft.world.attach(proposal, proposal.start_id)
        draft.world.absorb(proposal)
        draft.log[-1].recap = proposal.recap
        self.open_chapter(draft)

    async def extend(
        self, draft: Game[W], request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        self.install(draft, await self.write_next(draft, request.detail, worldsmith))
        return Resolution((), None)
