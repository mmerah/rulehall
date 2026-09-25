from pathlib import Path
from random import Random

from rulehall.core.creation import CreationStep, Picks, picked
from rulehall.core.facts import Fact, roll
from rulehall.core.model import AnyCharacter, Character
from rulehall.core.play import DecisionOption
from rulehall.core.tools import NoArgs, action, tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import Rows
from rulehall.engines.entities import PLAYER_ID, Gauge
from rulehall.engines.hiring import Hiring
from rulehall.engines.rooms.engine import RoomEngine
from rulehall.engines.rooms.world import MapProposal, Prop, RegionProposal
from rulehall.engines.tunnelgoons.args import LevelUp, Roll
from rulehall.engines.tunnelgoons.pack import (
    HIRE_GUIDANCE,
    HIRING,
    WORLDSMITH_GUIDANCE,
    AbilitiesProposal,
    TunnelGoonsBody,
    TunnelGoonsHead,
    TunnelGoonsPack,
)
from rulehall.engines.tunnelgoons.world import (
    ABILITIES,
    ABILITY_POINTS,
    HP_START,
    STARTING_ITEMS,
    Ability,
    Goon,
    GoonSheet,
    TunnelGoonsGame,
    TunnelGoonsWorld,
    level_up_decision,
)

POINT_OPTIONS: tuple[DecisionOption, ...] = tuple(
    DecisionOption(id=str(points), name=str(points)) for points in range(ABILITY_POINTS + 1)
)


class TunnelGoonsEngine(
    Hiring[TunnelGoonsWorld, TunnelGoonsPack, Goon, AbilitiesProposal],
    RoomEngine[Goon, TunnelGoonsWorld, TunnelGoonsPack],
):
    id = EngineId("tunnelgoons")
    title = "TUNNEL GOONS"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Old-school fantasy illustration in black ink, cross-hatched, no text or lettering."
    directory = Path(__file__).parent
    pack = TunnelGoonsPack
    head = TunnelGoonsHead
    body = TunnelGoonsBody
    world = TunnelGoonsWorld
    person = Goon
    opening = MapProposal[Goon]
    next_proposal = RegionProposal[Goon]
    hire_model = AbilitiesProposal
    hire_intent = HIRING

    def hire_guidance(self, _draft: TunnelGoonsGame) -> str:
        return HIRE_GUIDANCE

    def sign_on(self, person: Goon, answer: AbilitiesProposal) -> str:
        return person.sign_on(answer.abilities)

    @tool
    def rest(self, draft: TunnelGoonsGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        """The player and the party rest here for one night. Their Health goes to full."""
        return draft.world.rest()

    def creation_steps(self, pack_id: Slug, _picks: Picks) -> tuple[CreationStep, ...]:
        ability_steps = tuple(
            CreationStep(
                id=ability,
                name=f"Points in {ability.capitalize()}",
                options=POINT_OPTIONS,
                hint=f"{ABILITY_POINTS} points across the three",
            )
            for ability in ABILITIES
        )
        hint = ", ".join(name for pack in self.packs.played(pack_id) for name in pack.items)
        item_steps = tuple(
            CreationStep(id=f"item-{number}", name=f"Item {number}", hint=hint)
            for number in range(1, STARTING_ITEMS + 1)
        )
        return (*ability_steps, *item_steps)

    def build_character(
        self, name: str, brief: str, _pack_id: Slug, picks: Picks
    ) -> Character[Goon]:
        abilities: dict[Ability, int] = {
            ability: int(picked(picks, ability)) for ability in ABILITIES
        }
        if sum(abilities.values()) != ABILITY_POINTS:
            raise Refusal(f"the three abilities share exactly {ABILITY_POINTS} points")
        sheet = Goon(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            place_id=PLAYER_ID,
            hp=Gauge(current=HP_START, maximum=HP_START),
            sheet=GoonSheet(abilities=abilities),
            kit=tuple(picked(picks, f"item-{number}") for number in range(1, STARTING_ITEMS + 1)),
        )
        sheet.unpack_kit(())
        return self.sheet_character(name, sheet)

    def preview_character(self, character: AnyCharacter) -> Rows:
        sheet = self.player_of(character)
        return (*sheet.rows(), ("Items", ", ".join(sheet.kit)))

    def starting_items(self, proposal: MapProposal[Goon], player: Goon) -> tuple[Prop, ...]:
        return player.unpack_kit((*proposal.places, *proposal.npcs, *proposal.items))

    @tool
    def roll(self, draft: TunnelGoonsGame, args: Roll, rng: Random) -> list[Fact]:
        """Call this for an uncertain action that has a real cost. The engine rolls 2d6, adds
        the ability and the items, and reads the total."""
        world = draft.world
        actor = world.require_actor(args.actor_id)
        sheet = actor.require_sheet()
        items = world.carried_items(actor, args.item_ids)
        npc = world.require_person_here(args.target_id) if args.target_id is not None else None
        if npc is actor:
            raise Refusal(f"{actor.name} cannot roll against themselves")
        difficulty = npc.hp.current if npc is not None else args.difficulty
        if difficulty is None:
            raise ValueError("a roll names an npc or a difficulty, by `Roll._one_target`")
        penalty = 0
        if args.ability in ("brute", "skulker"):
            penalty = max(0, len(list(world.carried(actor.id))) - sheet.inventory)

        rolled = roll((6, 6), f"{args.what} — {args.ability}", rng)
        total = rolled.total + sheet.abilities[args.ability] + len(items) - penalty
        success = total >= difficulty
        outcome = "success" if success else "failure"
        line = (
            f"{args.what} — {actor.card_line(args.ability.capitalize())}"
            + (f" with {', '.join(item.name for item in items)}" if items else "")
            + (f" against {npc.name}" if npc is not None else "")
            + f", {total} vs DS {difficulty} → {outcome}"
        )
        facts = [rolled.fact, actor.card_fact(line, (rolled.event,))]

        # SRD: only a dangerous action turns the margin into damage; an npc's DS alone does not.
        if not args.dangerous:
            return facts
        margin = total - difficulty
        if npc is not None and success:
            facts.extend(npc.change(npc.hp, -margin, "Health", f"{actor.name}'s action"))
            if npc.hp.current == 0:
                facts.extend(world.kill(npc.id))
        elif not success:
            facts.extend(actor.change(actor.hp, margin, "Health", args.what))
            if actor.hp.current == 0:
                facts.extend(world.kill(actor.id))
        return facts

    @tool
    @action
    def level_up(self, draft: TunnelGoonsGame, args: LevelUp, _rng: Random) -> list[Fact]:
        """Call this one time, when the whole adventure ends. The engine gives the choice to the
        player first, then to each living hired member in turn."""
        world = draft.world
        player = world.player
        actor = player if player.require_sheet().level == 1 else world.next_to_level(player)
        if actor is None:
            raise Refusal("the player and every hired member have already levelled up")
        # Both or neither, by `LevelUp`; `or` narrows both for the fall-through.
        if args.ability is None or args.boost is None:
            draft.pending = level_up_decision(actor)
            return []
        facts = actor.level(args.ability, args.boost)
        following = world.next_to_level(actor)
        if following is not None:
            draft.pending = level_up_decision(following)
        return facts
