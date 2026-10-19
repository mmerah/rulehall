from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random
from typing import get_args

from rulehall.core.creation import CreationStep, Picks, numbered_picks
from rulehall.core.decisions import ActionOption, Option, find_option, unique_options
from rulehall.core.facts import Fact
from rulehall.core.game import AnyCharacter, AnyScenario, Character
from rulehall.core.log import Voice
from rulehall.core.prompt import Sections, section_if
from rulehall.core.tools import NoArgs, action, edit, tool
from rulehall.core.validation import EngineId, Refusal, Slug, parse
from rulehall.core.views import Panel, PanelRows, ScreenSlot, Sprite
from rulehall.engines.args import HireOrJoin, Kill
from rulehall.engines.bases.maps.args import Meanwhile, MoveItem, MoveTo, UnlockWay
from rulehall.engines.bases.maps.engine import MapEngine
from rulehall.engines.bases.maps.panels import carried_panel, ways_panel
from rulehall.engines.hiring import HIRED, Hiring
from rulehall.engines.lite5e.args import (
    AbilityCheck,
    CastSpell,
    CoinChange,
    FontOfMagic,
    FormationEdit,
    GearGift,
    GearUse,
    GiveReward,
    GoalReward,
    Harm,
    HitDie,
    InspirationReward,
    LayOnHands,
    LevelPick,
    MakeItem,
    Rest,
    StartBattle,
    Trade,
    Unprepare,
)
from rulehall.engines.lite5e.battle.aftermath import start_battle
from rulehall.engines.lite5e.battle.battling import BATTLE_SCREEN_ID, Lite5eBattles
from rulehall.engines.lite5e.data import (
    Ability,
    Species,
    portrait_sprite,
    srd,
)
from rulehall.engines.lite5e.hire import HireAnswer, SheetProposal
from rulehall.engines.lite5e.pack import Background, Lite5eBody, Lite5ePack
from rulehall.engines.lite5e.panels import (
    gear_panel,
    kit_rows,
    level_pick_option,
    party_panel,
    pending_decision,
    person_rows,
    sheet_panel,
)
from rulehall.engines.lite5e.rules import (
    ABILITIES,
    CASTING_ABILITIES,
    POINT_BUY_COST,
    POINT_BUY_TOTAL,
    STANDARD_ARRAY,
    AbilityMethod,
)
from rulehall.engines.lite5e.sheet import (
    Lite5ePerson,
    Lite5eSheet,
    level_pick_rules,
)
from rulehall.engines.lite5e.world import (
    Lite5eGame,
    Lite5eMapProposal,
    Lite5eRegionProposal,
    Lite5eWay,
    Lite5eWorld,
)
from rulehall.engines.lite5e.worldsmith import (
    WORLDSMITH_GUIDANCE,
    check_next,
    check_opening,
    hire_guidance_lines,
)
from rulehall.engines.panels import here_panel
from rulehall.engines.sheet import PLAYER_ID

ASSETS = Path(__file__).parent / "assets"
MAX_COMPANIONS = 3
CLASS = "class"
SPECIES = "species"
SUBSPECIES = "subspecies"
BACKGROUND = "background"
INCREASES = "increases"
METHOD = "method"
METHOD_HELP = (
    f"Array: {', '.join(map(str, STANDARD_ARRAY))}, once each. Point buy: {POINT_BUY_TOTAL} "
    f"points on scores from {min(POINT_BUY_COST)} to {max(POINT_BUY_COST)}."
)
SPECIES_ABILITY = "species-ability"
EACH_PLUS_ONE = "each-plus-one"
LOOK = "look"
CASTING_OPTIONS: tuple[Option, ...] = tuple(
    Option(id=ability, name=ability.title()) for ability in CASTING_ABILITIES
)
HIRING = (
    f"{HIRED}Pick a class companion or a stat-block companion. A beast or a monster keeps its "
    "stat block. Fit the picks to the person and the work."
)
GROUP_SPLIT = "{name} steps out of {group}"


class Lite5eEngine(
    Hiring[Lite5ePerson, Lite5eWorld, HireAnswer],
    MapEngine[Lite5ePerson, Lite5eWorld, Lite5ePack, Lite5eRegionProposal],
):
    id = rule_set_id = EngineId("lite5e")
    title = "5E LITE"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Painterly fantasy illustration, warm candlelight, worn leather and stone, no text."
    directory = Path(__file__).parent
    pack_model = Lite5ePack
    pack_body_model = Lite5eBody
    world_model = Lite5eWorld
    person_model = Lite5ePerson
    opening_model = Lite5eMapProposal
    next_proposal_model = Lite5eRegionProposal
    way_model = Lite5eWay
    hire_model = HireAnswer
    hire_intent = HIRING
    portraits = False
    assets = ASSETS
    battles = Lite5eBattles()
    opening_dice = Random()

    def screen_slots(self, state: Lite5eGame, /) -> tuple[ScreenSlot, ...]:
        return (
            *super().screen_slots(state),
            ScreenSlot(screen_id=BATTLE_SCREEN_ID, live=self.in_battle(state)),
        )

    def hire_guidance(self, draft: Lite5eGame, /) -> str:
        world = draft.world
        species = "; ".join(
            species_id + (f" ({', '.join(found.subspecies)})" if found.subspecies else "")
            for species_id, found in srd().character_options.species.items()
        )
        backgrounds = ", ".join(background.id for background in self._backgrounds(draft.pack_id))
        return "\n".join(
            (
                hire_guidance_lines(world),
                f"Species (lineages): {species}",
                f"Backgrounds: {backgrounds}",
            )
        )

    def sign_on(self, draft: Lite5eGame, person: Lite5ePerson, answer: HireAnswer, /) -> str:
        summary = draft.world.sign_on(person, answer.hire, self._backgrounds(draft.pack_id))
        if person.sheet is not None:
            person.portrait_id = portrait_id(person.sheet)
        return summary

    def sprite(self, state: Lite5eGame, entity_id: Slug, /) -> Sprite | None:
        world = state.world
        found = world.player if entity_id == world.player.id else world.find_person(entity_id)
        if found is None:
            return None
        return found.sprite()

    def portrait(self, portrait_id: Slug, /) -> Sprite | None:
        return portrait_sprite(portrait_id)

    def creation_steps(self, pack_id: Slug, picks: Picks, /) -> tuple[CreationStep, ...]:
        data = srd()
        options = data.character_options
        backgrounds = self._backgrounds(pack_id)
        steps = [
            CreationStep(
                id=CLASS,
                name="Class",
                options=tuple(
                    Option(id=class_id, name=data.require_class(class_id).name)
                    for class_id in options.classes
                ),
            ),
            CreationStep(
                id=SPECIES,
                name="Species",
                options=tuple(
                    Option(id=species_id, name=species.name)
                    for species_id, species in options.species.items()
                ),
            ),
        ]
        species = options.species.get(picks.get(SPECIES, ""))
        if species is not None and species.subspecies:
            steps.append(
                CreationStep(
                    id=SUBSPECIES,
                    name="Lineage",
                    options=tuple(
                        Option(id=key, name=found.name) for key, found in species.subspecies.items()
                    ),
                )
            )
        if species is not None:
            traits = species.lineage_traits(picks.get(SUBSPECIES))
            if any(trait.spell_ids for trait in traits):
                steps.append(
                    CreationStep(
                        id=SPECIES_ABILITY, name="Species spellcasting", options=CASTING_OPTIONS
                    )
                )
        steps.append(CreationStep(id=BACKGROUND, name="Background", options=backgrounds))
        background = find_option(backgrounds, picks.get(BACKGROUND, ""))
        if background is not None:
            steps.append(
                CreationStep(
                    id=INCREASES,
                    name="Ability increases",
                    options=tuple(
                        Option(id=key, name=_increase_name(increases))
                        for key, increases in _increase_splits(background.abilities).items()
                    ),
                )
            )
        method = picks.get(METHOD, "")
        steps.append(
            CreationStep(
                id=METHOD,
                name="Ability scores",
                options=tuple(
                    Option(id=offered, name=offered.replace("-", " ").capitalize())
                    for offered in get_args(AbilityMethod.__value__)
                ),
                hint=_points_spent(picks) if method == "point-buy" else "",
                help=METHOD_HELP,
            )
        )
        if method == "array":
            chosen = [picks.get(ability, "") for ability in ABILITIES]
            steps.extend(
                CreationStep(
                    id=ability,
                    name=ability.title(),
                    options=tuple(
                        Option(id=str(value), name=str(value))
                        for value in STANDARD_ARRAY
                        if str(value) not in chosen[:index]
                    ),
                )
                for index, ability in enumerate(ABILITIES)
            )
        if method == "point-buy":
            steps.extend(
                CreationStep(
                    id=ability,
                    name=ability.title(),
                    options=tuple(
                        Option(
                            id=str(value),
                            name=str(value),
                            brief=f"{cost} point{'' if cost == 1 else 's'}",
                        )
                        for value, cost in POINT_BUY_COST.items()
                    ),
                )
                for ability in ABILITIES
            )
        class_id = picks.get(CLASS, "")
        if class_id not in options.classes or background is None or species is None:
            return tuple(steps)
        answered = {
            step.id: picks[step.id] for step in steps if step.offers(picks.get(step.id, ""))
        }
        if species.subspecies and SUBSPECIES not in answered:
            return tuple(steps)
        origin = parse(SheetProposal, _origin_fields(answered, background))
        steps.extend(_level_pick_steps(origin.start_sheet(background), picks))
        steps.append(look_step(picks[SPECIES], species, picks))
        return tuple(steps)

    def build_character(
        self, name: str, brief: str, voice: Voice, pack_id: Slug, picks: Picks, /
    ) -> Character[Lite5ePerson]:
        backgrounds = self._backgrounds(pack_id)
        background = find_option(backgrounds, picks.get(BACKGROUND, ""))
        if background is None:
            raise Refusal("pick a background")
        proposal = parse(
            SheetProposal,
            {
                **_origin_fields(picks, background),
                "method": picks.get(METHOD, ""),
                "scores": {ability: int(picks[ability]) for ability in ABILITIES},
                "increases": _increase_splits(background.abilities)[picks[INCREASES]],
                "species_ability": picks.get(SPECIES_ABILITY),
                "picks": {kind: numbered_picks(picks, kind) for kind in level_pick_rules()},
            },
        )
        sheet = proposal.build_sheet(1, backgrounds)
        player = Lite5ePerson(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            voice=voice,
            known=True,
            place_id=PLAYER_ID,
            sheet=sheet,
            portrait_id=picks.get(LOOK) or portrait_id(sheet),
        )
        return self.character_of(name, player)

    def preview_character(self, character: AnyCharacter) -> PanelRows:
        player = self.player_of(character)
        return (*person_rows(player), *kit_rows(player.require_sheet()))

    def person_rows(self, person: Lite5ePerson, /) -> PanelRows:
        return person_rows(person)

    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> Lite5eWorld:
        opening: Lite5eMapProposal = scenario.opening
        check_opening(opening)
        world = self.world_model.opening(opening, self.player_of(character), ())
        world.apply_opening_extras(opening, self.opening_dice)
        return world

    def check_next(self, draft: Lite5eGame, proposal: Lite5eRegionProposal, /) -> None:
        check_next(proposal, draft.world)

    def install_next(self, draft: Lite5eGame, proposal: Lite5eRegionProposal, /) -> list[Fact]:
        facts = super().install_next(draft, proposal)
        draft.world.apply_next_extras(proposal)
        return facts

    def master_sections(self, state: Lite5eGame) -> Sections:
        world = state.world
        return (
            *super().master_sections(state),
            *section_if("GOALS", world.goal_lines()),
            *section_if("SETTLED HERE", world.settled_lines()),
        )

    def view_panels(self, state: Lite5eGame, /) -> tuple[Panel | None, ...]:
        world = state.world
        return (
            sheet_panel(world),
            party_panel(world),
            gear_panel(world),
            here_panel(other.subject() for other in world.others()),
            carried_panel(world),
            ways_panel(world),
        )

    def play_edit(self, draft: Lite5eGame, chosen: ActionOption, rng: Random) -> None:
        if draft.world.battle is not None:
            raise Refusal("a battle is on: change the party once it ends")
        super().play_edit(draft, chosen, rng)

    def after_each_change(self, draft: Lite5eGame, /) -> None:
        draft.pending = pending_decision(draft.world)
        if draft.pending is None:
            draft.world.finish_rest()

    def after_master_turn(self, draft: Lite5eGame, /, *, acted: bool) -> None:
        draft.world.end_turn()
        super().after_master_turn(draft, acted=acted)

    def grown_character(self, state: Lite5eGame, /) -> AnyCharacter | None:
        world = state.world
        if world.grown_sheet is None:
            return None
        grown = world.player.model_copy(
            deep=True, update={"sheet": world.grown_sheet, "conditions": []}
        )
        return self.character_model(id=state.character_id, engine_id=self.id, person=grown)

    @tool
    def check(self, draft: Lite5eGame, args: AbilityCheck, rng: Random) -> list[Fact]:
        """Roll one ability check for a party member. Roll only when the result is uncertain
        and a failure costs something. A difficulty word or a target sets the DC.
        A target is a hidden thing (perception or investigation), a locked way
        (thieves-tools with no skill, or athletics to force it), a trap (thieves-tools with no
        skill, or sleight-of-hand to disarm it), or a person (deception, intimidation,
        performance, persuasion, insight, stealth, sleight-of-hand, or animal-handling on a beast
        or a monstrosity).
        A success applies itself: a search reveals the hidden thing, a lock check unlocks the
        way, and a disarm removes the trap. An intimidation success against a routed group here
        makes it a captive group with no battle: it is the one check on a person that changes
        the state. After a failure, the same member cannot try the same thing here again until
        the party moves or rests."""
        return draft.world.check(args, rng)

    @tool
    def harm(self, draft: Lite5eGame, args: Harm, rng: Random) -> list[Fact]:
        """Harm party members: a trap here fires, a danger allows a dodge (a save), harm that the
        story makes certain, or a fall. It never takes a member below 1 HP."""
        return draft.world.harm(args, rng)

    @tool
    def cast(self, draft: Lite5eGame, args: CastSpell, rng: Random) -> list[Fact]:
        """Cast a spell outside a battle. Call it before you tell any effect. The engine spends
        the slot, rolls the saves of the persons it targets, and returns the effect: play it as
        established. Story spells, rituals and healing spells work here. Other battle spells wait
        for the battle."""
        return draft.world.cast(args, rng)

    @tool
    def rest(self, draft: Lite5eGame, args: Rest, rng: Random) -> list[Fact]:
        """Rest the party here. A long rest needs a battle or a first visit to a place since the
        last long rest. At most two short rests come between long rests. No rest while a hostile
        person is here or one way away; captives and routed groups do not count. A hostile group
        with a path to the party can break a long rest."""
        return draft.world.rest(args.kind, rng)

    @tool
    def move(self, draft: Lite5eGame, args: MoveTo, rng: Random) -> list[Fact]:
        """Move the player through an unlocked way out of this place. On arrival, the party's
        best passive Perception meets each hidden person, and each hidden item with a find word."""
        return [*super().move(draft, args, rng), *draft.world.notice_strangers(rng)]

    @tool
    def meanwhile(self, draft: Lite5eGame, args: Meanwhile, rng: Random) -> list[Fact]:
        """Pass time in the world. Call this before `direct` on each turn that shows ELSEWHERE.
        Give at most the number of changes that ELSEWHERE shows. Give an empty list when nothing
        moves. A hidden person who walks in rolls Stealth against the party's passive
        Perception."""
        return [*super().meanwhile(draft, args, rng), *draft.world.notice_strangers(rng)]

    @tool
    def reward(self, draft: Lite5eGame, args: GiveReward, _rng: Random) -> list[Fact]:
        """Reward the party: Heroic Inspiration for a party member, the XP of a completed goal,
        or a change of the party's coins."""
        world = draft.world
        match args.reward:
            case InspirationReward() as inspiration:
                return world.inspire(inspiration)
            case GoalReward() as goal:
                return world.complete_goal(goal)
            case CoinChange() as change:
                return world.change_coins(change)

    @tool
    def move_item(self, draft: Lite5eGame, args: MoveItem, _rng: Random) -> list[Fact]:
        """Move an item to a new holder. Gear that a party member takes joins their gear."""
        return draft.world.move_item(args.item_id, args.holder_id)

    @tool
    def unlock_way(self, draft: Lite5eGame, args: UnlockWay, _rng: Random) -> list[Fact]:
        """Open a locked way out of this place when the story opens it. A way with a lock opens
        here only when a party member carries its key, a story item from `make_item` that opens
        this way; otherwise pick or force the lock with `check`."""
        return draft.world.unlock_by_story(args.to_id)

    @tool
    def make_item(self, draft: Lite5eGame, args: MakeItem, _rng: Random) -> list[Fact]:
        """Make a story item with a name and a note, such as a letter, a map, a key or a trophy.
        It has no rules. A party member, a living person here or this place holds it. The name
        of SRD gear or of a magic item is refused. A key names the way with a lock that it opens
        with `unlock_way`."""
        return draft.world.make_item(args)

    @tool
    def trade(self, draft: Lite5eGame, args: Trade, _rng: Random) -> list[Fact]:
        """Buy or sell gear at the shop here for a party member. A shop sells SRD gear at SRD
        prices, and only the magic items of its stock. It buys gear for half its price."""
        return draft.world.trade(args)

    @tool
    def start_battle(self, draft: Lite5eGame, args: StartBattle, rng: Random) -> list[Fact]:
        """Start a battle with persons here as the foes. Any person here can fight, a friend too:
        the hostile flag does not limit it. A former class companion never fights the party.
        A group fights whole. Pick how it opens:
        face_to_face, party_ambush when the party strikes first from hiding, or foe_ambush when
        hidden persons here strike first (only hidden foes can). The engine rolls the opening
        and Initiative, and the battle screen plays the battle: your turn ends here."""
        return start_battle(draft.world, args, rng)

    @tool
    def kill(self, draft: Lite5eGame, args: Kill, _rng: Random) -> list[Fact]:
        """Kill a captive here. Nobody else dies by this tool."""
        return draft.world.kill(args.target_id)

    @tool
    def join_party(self, draft: Lite5eGame, args: HireOrJoin, rng: Random) -> list[Fact]:
        """Make a person here travel with the player. Set `terms` when the player hires them to
        work, also someone who already travels with the player: the worldsmith writes their
        sheet at the end of the turn, and nothing more happens this turn. Leave `terms` empty
        for someone who only comes along. The party holds three hired companions at most. A
        group never joins whole: one person steps out of it and joins."""
        world = draft.world
        person = world.require_person_here(args.target_id)
        hiring = bool(args.terms) or person.has_sheet
        hired_ids = {member.id for member in world.hired_party_members()}
        if hiring and len(hired_ids) >= MAX_COMPANIONS and person.id not in hired_ids:
            raise Refusal(f"the party holds {MAX_COMPANIONS} hired companions at most")
        if person.count == 1:
            return super().join_party(draft, args, rng)
        split = world.split_from_group(person)
        trace = GROUP_SPLIT.format(name=split.ref, group=person.ref)
        stepped = split.fact(trace, card=GROUP_SPLIT.format(name=split.name, group=person.name))
        joined = super().join_party(draft, args.model_copy(update={"target_id": split.id}), rng)
        return [stepped, *joined]

    @action
    def level_pick(self, draft: Lite5eGame, args: LevelPick, _rng: Random) -> list[Fact]:
        return draft.world.level_pick(args)

    @action
    def spend_hit_die(self, draft: Lite5eGame, args: HitDie, rng: Random) -> list[Fact]:
        return draft.world.spend_hit_die(args, rng)

    @action
    def finish_rest(self, draft: Lite5eGame, _args: NoArgs, _rng: Random) -> list[Fact]:
        draft.world.finish_rest()
        return []

    @action
    def unprepare(self, draft: Lite5eGame, args: Unprepare, _rng: Random) -> list[Fact]:
        return draft.world.unprepare(args)

    @action
    def use_gear(self, draft: Lite5eGame, args: GearUse, rng: Random) -> list[Fact]:
        return draft.world.use_gear(args, rng)

    @action
    def lay_on_hands(self, draft: Lite5eGame, args: LayOnHands, _rng: Random) -> list[Fact]:
        return draft.world.lay_on_hands(args)

    @action
    def font_of_magic(self, draft: Lite5eGame, args: FontOfMagic, _rng: Random) -> list[Fact]:
        return draft.world.font_of_magic(args)

    @action
    def give(self, draft: Lite5eGame, args: GearGift, _rng: Random) -> list[Fact]:
        return draft.world.give(args)

    @edit
    def set_formation_row(self, draft: Lite5eGame, args: FormationEdit, _rng: Random) -> None:
        draft.world.require_actor(args.actor_id).formation_row = args.row

    def _backgrounds(self, pack_id: Slug) -> tuple[Background, ...]:
        return unique_options(
            background for pack in self.packs.played(pack_id) for background in pack.backgrounds
        )


def look_step(species_id: Slug, species: Species, picks: Picks) -> CreationStep:
    lineages: list[tuple[Slug | None, str]] = [
        (lineage_id, lineage.name) for lineage_id, lineage in species.subspecies.items()
    ] or [(None, species.name)]
    matching = _look_id(species_id, picks.get(SUBSPECIES), picks.get(CLASS, ""))
    looks = (
        Option(
            id=_look_id(species_id, lineage_id, class_id),
            name=f"{name}, {srd().require_class(class_id).name}",
            sprite=str(portrait_sprite(_look_id(species_id, lineage_id, class_id)).path),
        )
        for lineage_id, name in lineages
        for class_id in srd().character_options.classes
    )
    return CreationStep(
        id=LOOK,
        name="Look",
        options=tuple(sorted(looks, key=lambda option: option.id != matching)),
        help="Empty: the portrait that matches your species, lineage and class.",
        optional=True,
    )


def portrait_id(sheet: Lite5eSheet) -> Slug:
    return _look_id(sheet.species_id, sheet.subspecies_id, sheet.class_id)


def _origin_fields(picks: Picks, background: Background) -> dict[str, object]:
    return {
        "kind": "class",
        "class_id": picks.get(CLASS, ""),
        "species_id": picks.get(SPECIES, ""),
        "subspecies_id": picks.get(SUBSPECIES),
        "background_id": background.id,
    }


def _level_pick_steps(sheet: Lite5eSheet, picks: Picks) -> list[CreationStep]:
    steps: list[CreationStep] = []
    for kind, rule in level_pick_rules().items():
        offered = [
            level_pick_option(sheet, kind, pick_id) for pick_id in sheet.level_pick_options(kind)
        ]
        if not offered:
            continue
        kind_steps = _numbered(kind, rule.label(), offered, sheet.picks_left(kind), picks)
        steps.extend(kind_steps)
        for step in kind_steps:
            if (answer := picks.get(step.id, "")) in sheet.level_pick_options(kind):
                _ = sheet.level_pick(kind, answer)
    return steps


def _look_id(species_id: Slug, lineage_id: Slug | None, class_id: Slug) -> Slug:
    return "-".join(part for part in (species_id, lineage_id, class_id) if part)


def _points_spent(picks: Picks) -> str:
    spent = sum(
        POINT_BUY_COST.get(int(score), 0)
        for ability in ABILITIES
        if (score := picks.get(ability, "")).isdigit()
    )
    return f"{spent} of {POINT_BUY_TOTAL} points spent"


def _increase_splits(abilities: Sequence[Ability]) -> dict[Slug, dict[Ability, int]]:
    splits: dict[Slug, dict[Ability, int]] = {
        f"{first}-2-{second}-1": {first: 2, second: 1}
        for first in abilities
        for second in abilities
        if first != second
    }
    splits[EACH_PLUS_ONE] = dict.fromkeys(abilities, 1)
    return splits


def _increase_name(increases: Mapping[Ability, int]) -> str:
    return ", ".join(f"{ability.title()} +{count}" for ability, count in increases.items())


def _numbered(
    prefix: str, name: str, options: Sequence[Option], count: int, picks: Picks
) -> list[CreationStep]:
    chosen = [picks.get(f"{prefix}-{number}", "") for number in range(1, count + 1)]
    return [
        CreationStep(
            id=f"{prefix}-{number}",
            name=f"{name} {number}" if count > 1 else name,
            options=tuple(option for option in options if option.id not in chosen[: number - 1]),
        )
        for number in range(1, count + 1)
    ]
