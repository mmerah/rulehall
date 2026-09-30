from collections.abc import Mapping
from pathlib import Path
from random import Random
from typing import Any

from rulehall.core.decisions import ActionOption
from rulehall.core.facts import Fact
from rulehall.core.game import AnyCharacter, AnyScenario, Game, RoleAnswer, WorldsmithRequest
from rulehall.core.prompt import Sections, lines_of, render_log, section_if
from rulehall.core.tools import action, tool
from rulehall.core.validation import Refusal, Slug
from rulehall.core.views import NarratorView, Panel
from rulehall.engines.args import Words
from rulehall.engines.engine import Engine, RequestHandler, Resolution, Revealing, SceneHeader
from rulehall.engines.packs import Pack
from rulehall.engines.panels import character_panel, here_panel, party_panel
from rulehall.engines.rooms.args import (
    ELSEWHERE,
    MOVED_CARD,
    MOVES_OFFSCREEN,
    NOTHING_OFFSCREEN,
    DropHere,
    Meanwhile,
    MoveItem,
    MoveTo,
    UnlockWay,
)
from rulehall.engines.rooms.panels import (
    EXTEND,
    MORE_MAP,
    carried_panel,
    map_view,
    ways_panel,
)
from rulehall.engines.rooms.world import Dweller, Item, MapProposal, RegionProposal, RoomWorld
from rulehall.engines.rooms.worldsmith import MAP_ASK, OPENING_SECTIONS, check_next, check_opening
from rulehall.engines.world import ARC_SO_FAR_TITLE, ARC_TITLE, HIDDEN_TITLE, party_section

MAP_UNWRITTEN = Fact(
    told=True,
    trace="the map could not be written",
    card="The map could not be written. You are still where you were.",
)


class RoomEngine[P: Dweller, W: RoomWorld[Any], K: Pack, R: RegionProposal[Any]](
    Revealing[W], Engine[P, W, K, R]
):
    family_dir = Path(__file__).parent
    opening_sections = OPENING_SECTIONS
    opening_intent = MAP_ASK
    play_hint = "What does {name} do? Or tap the map."

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> W:
        proposal: MapProposal[P] = scenario.opening
        check_opening(proposal)
        player = self.player_of(character)
        return self.world_model.opening(proposal, player, self.starting_items(proposal, player))

    def starting_items(self, _proposal: MapProposal[P], _player: P, /) -> tuple[Item, ...]:
        return ()

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {EXTEND: RequestHandler(self.write_region, MAP_UNWRITTEN)}

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
        place = world.current
        player = world.player
        return (
            ("CURRENT PLACE", f"{place.ref}\n{place.description}"),
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

    def context_text(self, state: Game[W]) -> str:
        return f"place: {state.world.current.name}"

    def scene_header(self, state: Game[W], /) -> SceneHeader:
        world = state.world
        place = world.current
        return SceneHeader(
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

    def moves(self, state: Game[W], /) -> tuple[ActionOption, ...]:
        return () if state.world.has_frontier() else (MORE_MAP,)

    def scene_panels(self, state: Game[W], /) -> tuple[Panel | None, ...]:
        world = state.world
        return (
            character_panel(world.player.subject(), world.sheet_rows(), sheet_help=self.sheet_help),
            party_panel(world.party_members(), self.sheet_help),
            here_panel(other.subject() for other in world.others()),
            carried_panel(world),
            ways_panel(world),
        )

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
        """Pass time where the player is not: move a dweller, move a loose item, and shut a
        way the player knows. Use any combination in one call. Call this only while ELSEWHERE is
        shown."""
        world = draft.world
        if not world.meanwhile_due:
            raise Refusal(NOTHING_OFFSCREEN)
        facts: list[Fact] = []
        if args.dweller_id is not None and args.dweller_to_id is not None:
            npc = world.require_dweller(args.dweller_id)
            facts.append(
                world.walk_offscreen(npc, world.require_offscreen_place(args.dweller_to_id))
            )
        if args.item_id is not None and args.item_to_id is not None:
            item = world.require_item(args.item_id)
            facts.append(world.drift_item(item, world.require_offscreen_place(args.item_to_id)))
        if args.shut_from_id is not None and args.shut_to_id is not None:
            start = world.require_place(args.shut_from_id)
            facts.append(world.shut_way(start, world.require_place(args.shut_to_id)))
        facts.append(Fact(trace=MOVES_OFFSCREEN, told=True, card=MOVED_CARD))
        world.meanwhile_due = False
        return facts

    @action
    def extend(self, draft: Game[W], args: Words, _rng: Random) -> list[Fact]:
        draft.request = WorldsmithRequest(kind=EXTEND, detail=args.words)
        return []

    def end_turn(self, draft: Game[W], /, *, acted: bool) -> None:
        if acted:
            draft.world.count_turn()

    def check_next(self, draft: Game[W], proposal: R, /) -> None:
        check_next(proposal, draft.world)

    def install_next(self, draft: Game[W], proposal: R, /) -> list[Fact]:
        draft.world.apply_region(proposal)
        draft.chapters[-1].recap = proposal.recap
        self.open_chapter(draft)
        return []

    async def write_region(
        self, draft: Game[W], request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        facts = await self.write_and_install_next(draft, request.detail, worldsmith)
        return Resolution(tuple(facts), None)
