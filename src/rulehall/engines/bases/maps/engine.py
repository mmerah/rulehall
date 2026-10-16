from collections.abc import Mapping
from pathlib import Path
from random import Random
from typing import Any

from rulehall.core.decisions import ActionOption
from rulehall.core.facts import Fact, Resolution
from rulehall.core.game import Game, RoleAnswer, WorldsmithRequest
from rulehall.core.narration import NarratorView
from rulehall.core.prompt import Sections, render_log, section_if
from rulehall.core.tools import action, tool
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import Panel, PanelRows
from rulehall.engines.args import Words
from rulehall.engines.bases.maps.args import (
    CarryChange,
    DropHere,
    ExtendMap,
    FallChange,
    Meanwhile,
    MoveItem,
    MoveTo,
    OpenChange,
    ShutChange,
    UnlockWay,
    WalkChange,
)
from rulehall.engines.bases.maps.panels import MORE_MAP, carried_panel, map_view, ways_panel
from rulehall.engines.bases.maps.world import EXTEND_REQUEST, Dweller, MapWorld, RegionProposal, Way
from rulehall.engines.bases.maps.worldsmith import (
    MAP_ASK,
    OPENING_SECTIONS,
    check_next,
)
from rulehall.engines.engine import Engine, RequestHandler, Revealing, ViewHeader
from rulehall.engines.packs import Pack
from rulehall.engines.panels import character_panel, here_panel, party_panel
from rulehall.engines.world import ARC_SO_FAR_TITLE, ARC_TITLE, HIDDEN_TITLE, party_section

ELSEWHERE = "ELSEWHERE (time has passed: call `meanwhile` this turn, before `direct`)"
NOTHING_OFFSCREEN = "no time has passed offscreen; call this only while ELSEWHERE is shown"
MOVES_OFFSCREEN = "something moves where the player cannot see"
MOVED_CARD = "Elsewhere, something moves."
MEANWHILE_FIRST = (
    "ELSEWHERE is due: call `meanwhile` first, with your changes, or with an empty list when "
    "nothing moves"
)
FRONTIER_LEFT = (
    "an open way the player knows still leads to a place they have not visited; go there first"
)
PAST_THE_EDGE = "the player heads past the map's edge"
MAP_EDGE = (
    "No open way the player knows leads to a place they have not visited. When the player heads "
    "on, call extend_map."
)
MAP_UNWRITTEN = Fact(
    told=True,
    trace="the map could not be written",
    card="The map could not be written. You are still where you were.",
)


class MapEngine[
    P: Dweller,
    W: MapWorld[Any, Any, Any, Any],
    K: Pack,
    R: RegionProposal[Any, Any, Any, Any],
](Revealing[W], Engine[P, W, K, R]):
    base_dir = Path(__file__).parent
    opening_sections = OPENING_SECTIONS
    opening_intent = MAP_ASK
    play_hint = "What does {name} do? Or tap the map."
    way_model: type[Way] = Way

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {EXTEND_REQUEST: RequestHandler(self.write_region, MAP_UNWRITTEN)}

    def worldsmith_sections(self, draft: Game[W], /) -> Sections:
        world = draft.world
        return (
            ("MAP SO FAR", world.map_so_far()),
            *section_if(ARC_SO_FAR_TITLE, world.arc),
            ("SCENES SO FAR", render_log(draft.chapters)),
            ("THE PLAYER", world.line(world.player)),
        )

    def master_sections(self, state: Game[W]) -> Sections:
        world = state.world
        return (
            ("CURRENT PLACE", world.place_text()),
            ("YOU PLAY FOR", world.line(world.player)),
            ("CARRYING", world.carrying_lines()),
            ("HERE WITH THE PLAYER", world.place_lines(known=True)),
            *party_section([world.line(member) for member in world.party_members()]),
            (HIDDEN_TITLE, world.place_lines(known=False)),
            *section_if(ARC_TITLE, world.arc),
            ("WAYS OUT", world.ways_lines()),
            *section_if("REGIONS", world.region_lines()),
            *section_if("MAP EDGE", MAP_EDGE if world.at_map_edge() else ""),
            *self.packs.rules_section(state.pack_id),
            *(((ELSEWHERE, world.elsewhere_lines()),) if world.meanwhile_due else ()),
        )

    def context_text(self, state: Game[W]) -> str:
        return f"place: {state.world.current.name}"

    def view_header(self, state: Game[W], /) -> ViewHeader:
        world = state.world
        place = world.current
        return ViewHeader(
            place_id=place.id,
            title=place.name,
            situation=place.description,
            narrator_brief=place.brief,
            map_view=map_view(world),
        )

    def narrator_view(self, state: Game[W]) -> NarratorView:
        world = state.world
        view = super().narrator_view(state)
        carrying = ", ".join(item.name for item in world.carried(world.player.id))
        return view.model_copy(update={"sheet": (*view.sheet, ("Carrying", carrying or "nothing"))})

    def standing_options(self, state: Game[W], /) -> tuple[ActionOption, ...]:
        return (MORE_MAP,) if state.world.at_map_edge() else ()

    def view_panels(self, state: Game[W], /) -> tuple[Panel | None, ...]:
        world = state.world
        return (
            character_panel(world.player.subject(), self.player_rows(world)),
            party_panel(world.party_members(), self.person_rows),
            here_panel(other.subject() for other in world.others()),
            carried_panel(world),
            ways_panel(world),
        )

    def player_rows(self, world: W, /) -> PanelRows:
        return self.person_rows(world.player)

    @action
    def drop_here(self, draft: Game[W], args: DropHere, _rng: Random) -> list[Fact]:
        world = draft.world
        _ = world.require_carried_items(world.player, (args.item_id,))
        return world.move_item(args.item_id, world.current.id)

    @tool
    def move_item(self, draft: Game[W], args: MoveItem, _rng: Random) -> list[Fact]:
        """Move an item to a new holder."""
        return draft.world.move_item(args.item_id, args.holder_id)

    @tool
    def unlock_way(self, draft: Game[W], args: UnlockWay, _rng: Random) -> list[Fact]:
        """Open a locked way out of this place."""
        return draft.world.unlock_way(args.to_id)

    @tool
    def move(self, draft: Game[W], args: MoveTo, _rng: Random) -> list[Fact]:
        """Move the player through an unlocked way out of this place."""
        return draft.world.move(args.to_id, args.with_ids)

    @tool
    def meanwhile(self, draft: Game[W], args: Meanwhile, _rng: Random) -> list[Fact]:
        """Pass time in the world. Call this before `direct` on each turn that shows ELSEWHERE.
        Give at most the number of changes that ELSEWHERE shows. Give an empty list when nothing
        moves."""
        world = draft.world
        if not world.meanwhile_due:
            raise Refusal(NOTHING_OFFSCREEN)
        cap = world.meanwhile_cap()
        if len(args.changes) > cap:
            raise Refusal(f"at most {cap} changes in one call, not {len(args.changes)}")
        facts: list[Fact] = []
        for change in args.changes:
            match change:
                case WalkChange():
                    npc = world.require_dweller(change.dweller_id)
                    fact = world.walk(npc, world.require_place(change.to_id))
                case CarryChange():
                    item = world.require_item(change.item_id)
                    fact = world.carry(item, world.require_entity(change.to_id))
                case ShutChange():
                    start = world.require_place(change.from_id)
                    fact = world.shut_way(start, world.require_place(change.to_id))
                case OpenChange():
                    start = world.require_place(change.from_id)
                    fact = world.open_way(start, world.require_place(change.to_id))
                case FallChange():
                    fact = world.fall(world.require_dweller(change.dweller_id))
            facts.append(fact)
        if any(not fact.told for fact in facts):
            facts.append(Fact(trace=MOVES_OFFSCREEN, told=True, card=MOVED_CARD))
        world.meanwhile_due = False
        return facts

    def direct_refusal(self, draft: Game[W], /) -> str | None:
        return MEANWHILE_FIRST if draft.world.meanwhile_due and draft.pending is None else None

    @tool
    def extend_map(self, draft: Game[W], args: ExtendMap, _rng: Random) -> list[Fact]:
        """Extend the map past its edge. Call this when MAP EDGE shows and the player heads past
        it: after the goal here is met, or when they set out somewhere new. Call it last: it ends
        your turn."""
        if not draft.world.at_map_edge():
            raise Refusal(FRONTIER_LEFT)
        draft.request = WorldsmithRequest(kind=EXTEND_REQUEST, detail=args.heading)
        return [Fact(trace=PAST_THE_EDGE, told=True)]

    @action
    def extend(self, draft: Game[W], args: Words, _rng: Random) -> list[Fact]:
        draft.request = WorldsmithRequest(kind=EXTEND_REQUEST, detail=args.words)
        return []

    def after_master_turn(self, draft: Game[W], /, *, acted: bool) -> None:
        if acted:
            draft.world.count_turn()

    def check_next(self, draft: Game[W], proposal: R, /) -> None:
        check_next(proposal, draft.world)

    def install_next(self, draft: Game[W], proposal: R, /) -> list[Fact]:
        draft.world.apply_region(proposal, self.way_model)
        draft.chapters[-1].recap = proposal.recap
        self.open_chapter(draft)
        return []

    async def write_region(
        self, draft: Game[W], request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        facts = await self.write_and_install_next(draft, request.detail, worldsmith)
        return Resolution(tuple(facts), None)
