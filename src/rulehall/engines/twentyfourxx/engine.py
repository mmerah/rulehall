from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import NamedTuple

from rulehall.core.creation import (
    CreationStep,
    Picks,
    check_picks,
    chosen_option,
    option_of,
    picked,
)
from rulehall.core.facts import DiceEvent, Fact, notation, roll
from rulehall.core.model import AnyCharacter, Character, Check, RoleAnswer, WorldsmithRequest
from rulehall.core.play import (
    Cause,
    DecisionOption,
    PendingDecision,
    PendingOption,
    Refused,
    SpokenLine,
)
from rulehall.core.prompt import Sections, lines_of, section_if, sentence
from rulehall.core.tools import action, tool
from rulehall.core.validation import EngineId, Refusal, Slug, slug
from rulehall.core.views import NarratorView, Panel, Rows, tag_of
from rulehall.engines.args import LeaveParty, Words
from rulehall.engines.engine import RequestHandler, Resolution, Revealing
from rulehall.engines.entities import IS_DEAD, PLAYER_ID, joined
from rulehall.engines.hiring import HIRE_PENDING, HIRE_UNWRITTEN, Hiring, signed_on
from rulehall.engines.packs import unique_options
from rulehall.engines.panels import character_panel, here_panel, party_panel
from rulehall.engines.scenes.engine import SceneEngine, trail_panel
from rulehall.engines.scenes.world import SceneProposal
from rulehall.engines.scenes.worldsmith import check_next, check_opening
from rulehall.engines.twentyfourxx.args import (
    BY_SHIP,
    CANNOT_SUCCEED,
    COMPLICATION_UNWRITTEN,
    CROSSING,
    FLOWN,
    GEAR_TOOK_THE_HIT,
    JOB_PAID,
    JOINING,
    MOVE_ON,
    MOVING_ON,
    NEW_LEAD_HERE,
    NEW_LOCATION,
    NEWCOMER_PROMPT,
    NO_JOB,
    ODD_JOB,
    RAISE_OWED,
    RAISE_PROMPT,
    SCENE_LEFT,
    TURNING,
    TWO_JOBS,
    WAY_OFFERED,
    WAY_UNWRITTEN,
    BringIn,
    CarriedItem,
    ChangeHindrances,
    Defend,
    DefendHit,
    FindAgain,
    FromHold,
    GainItem,
    Helper,
    Job,
    LoseHoldItem,
    NextScene,
    Raise,
    RaiseSkill,
    RepairItem,
    Roll,
    ShipUpgrade,
    Spend,
    Staked,
    TakeLead,
)
from rulehall.engines.twentyfourxx.pack import (
    COMPLICATING,
    HIRING,
    NEWCOMING,
    SKILL_COUNT,
    WORLDSMITH_GUIDANCE,
    NewcomerProposal,
    Origin,
    SheetProposal,
    Specialty,
    TwentyFourXXBody,
    TwentyFourXXHead,
    TwentyFourXXPack,
)
from rulehall.engines.twentyfourxx.panels import crew_rows, gear_rows, job_panel, ship_panel
from rulehall.engines.twentyfourxx.rules import (
    DEFAULT_DIE,
    HELP_DIE,
    HINDERED_DIE,
    NO_WORK,
    ODD_WORK,
    TWO_JOBS_FOUND,
    SkillDie,
    outcome_band,
    raised,
    risk_text,
    roll_band,
    spared,
)
from rulehall.engines.twentyfourxx.world import (
    SHIP_IDS,
    WORK_AT,
    Crewmate,
    CrewSheet,
    Gear,
    Kit,
    TwentyFourXXGame,
    TwentyFourXXNext,
    TwentyFourXXScene,
    TwentyFourXXWorld,
    filed_by_name,
)

DEPARTURE: Slug = "departure"
FLIGHT: Slug = "flight"
COMPLICATION: Slug = "complication"
NEWCOMER: Slug = "newcomer"


class Helping(NamedTuple):
    who: Crewmate
    terms: Helper
    skill: str
    die: int


@dataclass(frozen=True, slots=True)
class DicePool:
    roll: Roll
    actor: Crewmate
    helping: Helping | None
    faces: tuple[int, ...]
    label: str

    @property
    def die(self) -> int:
        return self.faces[0]

    def stakes(self) -> list[tuple[Crewmate, Staked]]:
        staked: list[tuple[Crewmate, Staked]] = [(self.actor, self.roll)]
        if self.helping is not None:
            staked.append((self.helping.who, self.helping.terms))
        return staked


class TwentyFourXXEngine(
    Revealing,
    Hiring[TwentyFourXXWorld, TwentyFourXXPack, Crewmate, SheetProposal],
    SceneEngine[Crewmate, TwentyFourXXWorld, TwentyFourXXPack],
):
    id = EngineId("twentyfourxx")
    title = "24XX"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = (
        "Clean science-fiction illustration: hard light, neon on steel, lived-in "
        "technology, no text or lettering."
    )
    directory = Path(__file__).parent
    pack = TwentyFourXXPack
    head = TwentyFourXXHead
    body = TwentyFourXXBody
    world = TwentyFourXXWorld
    person = Crewmate
    opening = TwentyFourXXScene
    hire_model = SheetProposal
    hire_intent = HIRING

    def __init__(self, player_packs: Path) -> None:
        super().__init__(player_packs)
        srd = self.packs.srd()
        if len(srd.skills) != SKILL_COUNT:
            raise ValueError(
                f"the {self.id!r} srd pack lists {len(srd.skills)} skills, not {SKILL_COUNT}"
            )
        if not srd.starting_kit:
            raise ValueError(f"the {self.id!r} srd pack has no starting kit")

    def request_handlers(self) -> Mapping[Slug, RequestHandler[TwentyFourXXWorld]]:
        return {
            **super().request_handlers(),
            DEPARTURE: RequestHandler(self.depart, WAY_UNWRITTEN),
            FLIGHT: RequestHandler(self.fly, WAY_UNWRITTEN),
            COMPLICATION: RequestHandler(self.complicate, COMPLICATION_UNWRITTEN),
            NEWCOMER: RequestHandler(self.write_newcomer, HIRE_UNWRITTEN),
        }

    def record(
        self,
        draft: TwentyFourXXGame,
        lines: tuple[SpokenLine, ...],
        facts: tuple[Fact, ...],
        *,
        words: str = "",
        by_option: bool = False,
        cause: Cause | None = None,
        refused: tuple[Refused, ...] = (),
    ) -> TwentyFourXXGame:
        # Every exchange ends here, a failed newcomer write too, so no one plays a dead lead.
        if draft.pending is None and draft.request is None:
            self._succession(draft)
        if draft.pending is None and draft.request is None and draft.world.raise_owed:
            draft.pending = _raise_decision(draft.world.player.require_sheet())
        return super().record(
            draft, lines, facts, words=words, by_option=by_option, cause=cause, refused=refused
        )

    def file_stranger(self, draft: TwentyFourXXGame, target_id: Slug, /) -> list[Fact]:
        return draft.world.file_stranger(target_id)

    def composer(self, _state: TwentyFourXXGame) -> tuple[PendingOption | None, bool]:
        return MOVE_ON, False

    def hire_guidance(self, draft: TwentyFourXXGame) -> str:
        specialties, origins = self._offered(draft.pack_id)
        return "\n".join(
            (
                "Specialties:",
                *(specialty.line() for specialty in specialties),
                "Origins:",
                *(origin.line() for origin in origins),
                f"Skills: {', '.join(option.name for option in self.packs.srd().skills)}",
            )
        )

    def hire_check(self, draft: TwentyFourXXGame) -> Check[SheetProposal]:
        def check(answer: SheetProposal) -> None:
            self._operator_sheet(draft.pack_id, answer)

        return check

    def sign_on(self, draft: TwentyFourXXGame, person: Crewmate, answer: SheetProposal) -> str:
        sheet = self._operator_sheet(draft.pack_id, answer)
        person.sheet = sheet
        return joined(sheet.specialty, sheet.origin)

    def creation_steps(self, pack_id: Slug, picks: Picks) -> tuple[CreationStep, ...]:
        specialties, origins = self._offered(pack_id)
        # The rules fix the seventeen skills: a pack adds specialties and origins only.
        skills = self.packs.srd().skills
        steps = [CreationStep(id="specialty", name="Specialty", options=specialties)]
        specialty = option_of(specialties, picked(picks, "specialty"))
        if specialty is None:
            return tuple(steps)
        if specialty.choice:
            steps.append(
                CreationStep(
                    id="specialty-choice", name="Specialty skill", options=specialty.choice
                )
            )
        if specialty.kit_choice:
            steps.append(
                CreationStep(
                    id="weapon",
                    name="Weapon",
                    options=tuple(
                        DecisionOption(id=slug(kit.name, ()), name=kit.name)
                        for kit in specialty.kit_choice
                    ),
                )
            )
        steps.append(CreationStep(id="origin", name="Origin", options=origins))
        origin = option_of(origins, picked(picks, "origin"))
        if origin is None:
            return tuple(steps)
        steps.extend(
            CreationStep(id=f"trait-{number}", name=f"Trait {number}", hint=origin.brief)
            for number in range(1, origin.invents + 1)
        )
        if origin.choice:
            steps.append(CreationStep(id="body", name="Body", options=origin.choice))
        steps.extend(
            CreationStep(
                id=f"increase-{number}",
                name="Skill increase",
                options=skills,
                allows_text=True,
            )
            for number in range(1, origin.increases + 1)
        )
        return tuple(steps)

    def build_character(
        self, name: str, brief: str, pack_id: Slug, picks: Picks
    ) -> Character[Crewmate]:
        player = Crewmate(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            sheet=self._built_sheet(pack_id, picks),
        )
        return self.sheet_character(name, player)

    def _built_sheet(self, pack_id: Slug, picks: Picks) -> CrewSheet:
        offered_specialties, offered_origins = self._offered(pack_id)
        specialty = chosen_option(offered_specialties, picked(picks, "specialty"))
        origin = chosen_option(offered_origins, picked(picks, "origin"))

        skills: dict[str, SkillDie] = dict(specialty.skills)
        if specialty.choice:
            picked_skills = chosen_option(specialty.choice, picked(picks, "specialty-choice"))
            skills.update(picked_skills.skills)
        for number in range(1, origin.increases + 1):
            typed = picked(picks, f"increase-{number}")
            option = option_of(self.packs.srd().skills, typed)
            skill = option.name if option is not None else self._match_skill(skills, typed) or typed
            if (new_die := raised(skills.get(skill))) is None:
                raise Refusal("the skill is already at d12")
            skills[skill] = new_die

        weapon: Kit | None = None
        if specialty.kit_choice:
            wanted = picked(picks, "weapon")
            weapon = next(
                (kit for kit in specialty.kit_choice if slug(kit.name, ()) == wanted), None
            )
            if weapon is None:
                raise Refusal(f"{wanted!r} is not a weapon on offer")

        traits = tuple(picked(picks, f"trait-{number}") for number in range(1, origin.invents + 1))
        body = None
        if origin.choice:
            body = chosen_option(origin.choice, picked(picks, "body"))
            traits = (*traits, body.name)

        kits = [*self.packs.srd().starting_kit, *specialty.kit]
        if weapon is not None:
            kits.append(weapon)
        if body is not None and body.kit is not None:
            kits.append(body.kit)
        return CrewSheet(
            specialty=specialty.name,
            origin=origin.name,
            traits=traits,
            skills=skills,
            items=items_from_kits(kits),
        )

    def _operator_sheet(self, pack_id: Slug, answer: SheetProposal) -> CrewSheet:
        answers = {
            "specialty": answer.specialty,
            "specialty-choice": answer.specialty_skills,
            "weapon": answer.weapon,
            "origin": answer.origin,
            "body": answer.body,
            **{f"trait-{number}": trait for number, trait in enumerate(answer.traits, 1)},
            **{f"increase-{number}": skill for number, skill in enumerate(answer.increases, 1)},
        }
        picks: dict[Slug, str] = {}
        while steps := [
            step for step in self.creation_steps(pack_id, picks) if step.id not in picks
        ]:
            for step in steps:
                picks[step.id] = _answered(step, answers.get(step.id, ""))
        if unasked := [
            step_id for step_id, given in answers.items() if given and step_id not in picks
        ]:
            raise Refusal(f"these choices take no {', '.join(unasked)}: leave them empty")
        check_picks(self.creation_steps(pack_id, picks), picks)
        return self._built_sheet(pack_id, picks)

    def preview_character(self, character: AnyCharacter) -> Rows:
        sheet = self.player_of(character).require_sheet()
        return (*sheet.rows(), ("Gear", sheet.gear_text()))

    def player_sections(self, state: TwentyFourXXGame) -> Sections:
        world = state.world
        return (
            ("YOU PLAY FOR", world.player.line(gear=False)),
            ("GEAR", _item_lines(world.player.require_sheet().items)),
            *section_if("THE JOB", world.job),
            *section_if("RAISE", RAISE_OWED if world.raise_owed else ""),
            ("THE SHIP", _item_lines(world.ship)),
            ("THE HOLD", f"{world.ship_line()}\n{_item_lines(world.hold)}"),
        )

    def context_lines(self, state: TwentyFourXXGame) -> str:
        world = state.world
        return f"{super().context_lines(state)}\n{world.ship_line()}\njob: {world.job or '(none)'}"

    def narrator_view(self, state: TwentyFourXXGame) -> NarratorView:
        view = super().narrator_view(state)
        if not (line := state.world.new_lead_line()):
            return view
        return view.model_copy(update={"situation": f"{view.situation}\n{line}"})

    def scene_panels(self, state: TwentyFourXXGame) -> tuple[Panel, ...]:
        world = state.world
        player = world.player
        return (
            character_panel(player.rows(), *gear_rows(world, player)),
            *job_panel(world),
            ship_panel(world),
            *party_panel(world.party_members(), lambda member: crew_rows(world, member)),
            here_panel(other.subject() for other in world.others()),
            trail_panel(scene.title for scene in world.scenes),
        )

    def resolve_skill(self, sheet: CrewSheet, wanted: str) -> str:
        if (match := self._match_skill(sheet.skills, wanted)) is not None:
            return match
        known = ", ".join(sorted(sheet.skills)) or "none"
        listed = ", ".join(option.name for option in self.packs.srd().skills)
        raise Refusal(
            f"{wanted!r} is not a skill on the sheet ({known}) or in the rules ({listed})"
        )

    def _match_skill(self, known: Mapping[str, SkillDie], wanted: str) -> str | None:
        folded = wanted.casefold().split()
        names = (*known, *(option.name for option in self.packs.srd().skills))
        return next((name for name in names if name.casefold().split() == folded), None)

    @tool
    def change_hindrances(
        self, draft: TwentyFourXXGame, args: ChangeHindrances, _rng: Random
    ) -> list[Fact]:
        """The actor gains hindrances, loses hindrances, or does both."""
        return draft.world.require_actor(args.actor_id).change_hindrances(args.gained, args.lost)

    @tool
    def gain_item(self, draft: TwentyFourXXGame, args: GainItem, _rng: Random) -> list[Fact]:
        """The actor gains an item and pays for it."""
        actor = draft.world.require_actor(args.actor_id)
        return actor.gain_item(args.name, bulky=args.bulky, breaks=args.breaks, cost=args.cost)

    @tool
    @action
    def drop_item(self, draft: TwentyFourXXGame, args: CarriedItem, _rng: Random) -> list[Fact]:
        """The actor loses an item permanently."""
        actor = draft.world.require_actor(args.actor_id)
        return actor.require_sheet().drop_item(args.item_id, actor)

    @tool
    def repair_item(self, draft: TwentyFourXXGame, args: RepairItem, _rng: Random) -> list[Fact]:
        """The actor repairs a broken item."""
        world = draft.world
        actor = world.require_actor(args.actor_id)
        return actor.repair_item(world.require_gear(actor, args.item_id, hold=True), args.cost)

    @tool
    def spend(self, draft: TwentyFourXXGame, args: Spend, _rng: Random) -> list[Fact]:
        """The actor pays credits for a thing that is not an item and not a repair, or pays
        someone with `to_id`."""
        world = draft.world
        actor = world.require_actor(args.actor_id)
        if args.to_id is None:
            return actor.spend(args.amount, args.why)
        if args.to_id == actor.id:
            raise Refusal(f"{actor.name} cannot pay themselves")
        person = world.person_of(args.to_id)
        if args.to_id == world.player.id or (person and person.hired and person.id in world.party):
            taker = world.require_actor(args.to_id)
            return [*actor.spend(args.amount, args.why), *taker.earn(args.amount, giver=actor)]
        # Anyone outside the crew, a hire not yet signed on too, simply takes the credits.
        taker_name = args.to_id if person is None else person.name
        return actor.spend(args.amount, f"{args.why}, to {taker_name}")

    @action
    def let_go(self, draft: TwentyFourXXGame, args: LeaveParty, _rng: Random) -> list[Fact]:
        return draft.world.leave_party(args.target_id)

    @action
    def take_lead(self, draft: TwentyFourXXGame, args: TakeLead, _rng: Random) -> list[Fact]:
        return draft.world.take_lead(args.actor_id)

    @tool
    @action
    def ship_upgrade(self, draft: TwentyFourXXGame, args: ShipUpgrade, _rng: Random) -> list[Fact]:
        """The player upgrades one ship function."""
        return draft.world.upgrade_ship(args.function_id, args.upgrade)

    @action
    def stow_item(self, draft: TwentyFourXXGame, args: CarriedItem, _rng: Random) -> list[Fact]:
        world = draft.world
        return world.stow_item(world.require_actor(args.actor_id), args.item_id)

    @action
    def retrieve_item(self, draft: TwentyFourXXGame, args: FromHold, _rng: Random) -> list[Fact]:
        world = draft.world
        return world.retrieve_item(world.require_actor(args.actor_id), args.item_id)

    @tool
    def lose_hold_item(
        self, draft: TwentyFourXXGame, args: LoseHoldItem, _rng: Random
    ) -> list[Fact]:
        """An item leaves the ship's hold while the crew is away: a raid, an impound or a theft.
        Call this once for each item."""
        return draft.world.lose_hold_item(args.item_id, args.why)

    @tool
    def defend(self, draft: TwentyFourXXGame, args: Defend, _rng: Random) -> list[Fact]:
        """A carried item or a ship function breaks. The hit becomes a hindrance."""
        return draft.world.defend(args.actor_id, args.item_id, args.hindrance)

    @tool
    def next_scene(self, draft: TwentyFourXXGame, args: NextScene, _rng: Random) -> list[Fact]:
        """Call this with nothing set when the scene reaches a stopping point. Set `pursuit`
        instead when the player has left this place. Set `complication` instead to bring a new
        situation into this place."""
        if args.pursuit:
            if args.by_ship and (refusal := draft.world.ship_refusal()):
                raise Refusal(refusal)
            kind = FLIGHT if args.by_ship else DEPARTURE
            draft.request = WorldsmithRequest(kind=kind, detail=args.pursuit)
            draft.note(SCENE_LEFT)
            return [Fact(trace=f"the player leaves {draft.world.scene.title}", told=True)]
        if not args.complication:
            draft.note(WAY_OFFERED)
            return [Fact(trace="the scene reaches a stopping point")]
        draft.request = WorldsmithRequest(kind=COMPLICATION, detail=args.complication)
        return [
            Fact(
                trace=f"the worldsmith writes the complication once this turn ends: "
                f"{args.complication}. Nothing more happens this turn; stop and exit",
            )
        ]

    @action
    def move_on(self, draft: TwentyFourXXGame, _args: Words, _rng: Random) -> list[Fact]:
        draft.note(MOVING_ON)
        return []

    async def depart(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        return await self._cross(draft, request.detail, worldsmith, "")

    async def fly(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        place_id = draft.world.scene.place_id
        resolution = await self._cross(
            draft,
            request.detail,
            worldsmith,
            BY_SHIP,
            lambda answer: [FLOWN.format(place_id=place_id)] if answer.place_id == place_id else [],
        )
        draft.world.dock_here()
        return resolution

    async def _cross(
        self,
        draft: TwentyFourXXGame,
        pursuit: str,
        worldsmith: RoleAnswer,
        how: str,
        needs: Callable[[TwentyFourXXNext], list[str]] = lambda _answer: [],
    ) -> Resolution:
        left = draft.world.scene.title
        facts = await self._write_next(draft, pursuit, worldsmith, needs)
        return Resolution(tuple(facts), CROSSING.format(left=left, how=how))

    async def complicate(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        location = draft.world.scene.location
        facts = await self._write_next(
            draft,
            COMPLICATING.format(brief=request.detail),
            worldsmith,
            lambda answer: [NEW_LOCATION] if answer.location not in ("", location) else [],
        )
        return Resolution(tuple(facts), TURNING)

    async def _write_next(
        self,
        draft: TwentyFourXXGame,
        intent: str,
        worldsmith: RoleAnswer,
        needs: Callable[[TwentyFourXXNext], list[str]] = lambda _answer: [],
    ) -> list[Fact]:
        world = draft.world

        def check(answer: TwentyFourXXNext) -> None:
            check_next(filed_by_name(answer), world, needs=needs(answer))

        scene = await self.ask_worldsmith(draft, intent, worldsmith, TwentyFourXXNext, check)
        return [*world.end_brief_hindrances(), *self.install_scene(draft, filed_by_name(scene))]

    def check_opening(self, proposal: SceneProposal[Crewmate]) -> None:
        check_opening(filed_by_name(proposal))

    def _offered(self, pack_id: Slug) -> tuple[tuple[Specialty, ...], tuple[Origin, ...]]:
        played = self.packs.played(pack_id)
        return (
            unique_options(option for pack in played for option in pack.specialties),
            unique_options(option for pack in played for option in pack.origins),
        )

    def _succession(self, draft: TwentyFourXXGame) -> None:
        world = draft.world
        dead = world.player
        if dead.alive:
            return
        if not (members := world.hired_party_members()):
            draft.pending = PendingDecision(
                kind=NEWCOMER,
                prompt=NEWCOMER_PROMPT.format(name=dead.name),
                options=(),
                allows_text=True,
            )
            return
        draft.pending = PendingDecision(
            kind="succession",
            prompt="Who leads now?",
            options=tuple(
                PendingOption(
                    id=member.id,
                    name=member.name,
                    brief=member.brief,
                    action_name="take_lead",
                    args={"actor_id": member.id},
                )
                for member in members
            ),
            allows_text=False,
        )

    def ending(self, state: TwentyFourXXGame) -> str | None:  # noqa: ARG002
        return None

    @tool
    def bring_in(self, draft: TwentyFourXXGame, args: BringIn, _rng: Random) -> list[Fact]:
        """A new operator joins the crew after the lead died; the worldsmith writes them."""
        world = draft.world
        if world.player.alive or world.hired_party_members():
            raise Refusal(
                "a new operator joins only when the lead is dead and no hired member lives"
            )
        draft.request = WorldsmithRequest(kind=NEWCOMER, detail=args.who)
        return [Fact(trace=HIRE_PENDING.format(name="the new operator", terms=args.who))]

    async def write_newcomer(
        self, draft: TwentyFourXXGame, request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        world = draft.world

        def check(answer: NewcomerProposal) -> None:
            self._operator_sheet(draft.pack_id, answer.sheet)
            world.check_unnamed(answer.name, answer.brief)
            if any(
                answer.name.casefold() == entry.name.casefold() for entry in world.cast.values()
            ):
                raise Refusal(f"{answer.name!r} is already in the cast: name a new operator")

        prompt = self.render_request(
            draft,
            intent=NEWCOMING.format(who=request.detail),
            guidance=self.hire_guidance(draft),
            answer_model=NewcomerProposal,
        )
        answer = await worldsmith(prompt, NewcomerProposal, check)
        newcomer = Crewmate(
            id=PLAYER_ID,
            name=answer.name,
            brief=answer.brief,
            known=True,
        )
        summary = self.sign_on(draft, newcomer, answer.sheet)
        facts = [*world.lead(newcomer), signed_on(newcomer, summary)]
        draft.note(NEW_LEAD_HERE.format(name=newcomer.name, scene=world.scene.title))
        return Resolution(tuple(facts), JOINING.format(name=newcomer.name))

    @tool
    @action
    def roll(self, draft: TwentyFourXXGame, args: Roll, rng: Random) -> list[Fact]:
        """Call this only to avoid a risk. The engine checks the dice and asks the player to
        commit, unless `committed` is set; then it rolls and reads the result."""
        pool = self._pool(draft.world, args)
        if args.committed:
            return self._rolled(draft, pool, rng)
        draft.pending = PendingDecision(
            kind="risk",
            prompt=" ".join(
                part
                for part in (
                    f"{_roll_lines(pool)[1]}. Dice: {notation(pool.faces)}, the highest counts.",
                    *_burdens(pool.actor),
                    CANNOT_SUCCEED if max(pool.faces) < 5 else "",
                    "Commit, or revise in your own words.",
                )
                if part
            ),
            options=(
                PendingOption(
                    id="commit",
                    name="Commit",
                    action_name="roll",
                    args={**args.model_dump(mode="json"), "committed": True},
                ),
            ),
            allows_text=True,
        )
        return []

    @action
    def defend_hit(self, draft: TwentyFourXXGame, args: DefendHit, _rng: Random) -> list[Fact]:
        return _defend_or_land(draft, self._pool(draft.world, args.roll), args.rolled, args.choices)

    def _rolled(self, draft: TwentyFourXXGame, pool: DicePool, rng: Random) -> list[Fact]:
        args = pool.roll
        rolled = roll(pool.faces, f"{args.what} — {pool.label}", rng, highlight_kept=True)
        return [rolled.fact, *_defend_or_land(draft, pool, rolled.event, {})]

    def _skill_die(self, sheet: CrewSheet, skill: str) -> tuple[str, int]:
        if not skill:
            return "unskilled", DEFAULT_DIE
        label = self.resolve_skill(sheet, skill)
        return label, sheet.skills.get(label, DEFAULT_DIE)

    def _pool(self, world: TwentyFourXXWorld, args: Roll) -> DicePool:
        actor = world.require_actor(args.actor_id)
        if not actor.alive:
            raise Refusal(IS_DEAD.format(name=actor.name))
        helping = None
        if (helper := args.helped_by) is not None:
            who = world.require_actor(helper.actor_id)
            if who is actor:
                raise Refusal(f"{actor.name} cannot help their own roll")
            if not helper.risk:
                helper = helper.model_copy(
                    update={"risk": args.risk, "harm": args.harm, "deadly": args.deadly}
                )
            sheet = who.require_sheet()
            skill = self._skill_die(sheet, helper.skill) if helper.skill else sheet.best_skill()
            helping = Helping(who, helper, *skill)

        label, die = self._skill_die(actor.require_sheet(), args.skill)
        if args.hindered:
            die = HINDERED_DIE

        faces = [die]
        if args.helped:
            faces.append(HELP_DIE)
        if helping is not None:
            faces.append(HINDERED_DIE if helping.terms.hindered else helping.die)

        pool = DicePool(roll=args, actor=actor, helping=helping, faces=tuple(faces), label=label)
        world.check_defenses(
            [
                (who, stake.defend.item_id, stake.defend.hindrance)
                for who, stake in pool.stakes()
                if stake.defend is not None
            ]
        )
        return pool

    @tool
    def job(self, draft: TwentyFourXXGame, args: Job, rng: Random) -> list[Fact]:
        """Work for the crew. With `find` the engine rolls the d6 of the SRD. With `finish` it
        raises one skill for each hired member, pays each operator d6 credits, and asks the
        player which skill they raise."""
        world = draft.world
        match args.verb:
            case "find":
                return _find(world, args.where, rng)
            case "take":
                return world.take_job(args.terms)
            case "finish":
                return self._finish(draft, args.raises, rng)

    @tool
    @action
    def raise_skill(self, draft: TwentyFourXXGame, args: RaiseSkill, _rng: Random) -> list[Fact]:
        """Raise the skill the player chose after a job."""
        world = draft.world
        if not world.raise_owed:
            raise Refusal("no raise is owed: the player raises one skill after each job")
        facts = self._raise(world.player, args.skill)
        world.raise_owed = False
        return facts

    @action
    def find_again(self, draft: TwentyFourXXGame, args: FindAgain, rng: Random) -> list[Fact]:
        spent = draft.world.player.spend(1, "another look for work")
        return [*spent, *_find(draft.world, args.where, rng)]

    def _finish(self, draft: TwentyFourXXGame, raises: Sequence[Raise], rng: Random) -> list[Fact]:
        world = draft.world
        if not world.job:
            raise Refusal("no job is open to finish")
        if not world.work_rolled:
            raise Refusal(
                "no roll has played the job's work since it was taken: play the work, then finish"
            )
        if not world.player.alive:
            raise Refusal(IS_DEAD.format(name=world.player.name))
        members = world.hired_party_members()
        expected = sorted(member.id for member in members)
        given = sorted(world.require_actor(raise_.actor_id).id for raise_ in raises)
        if given != expected:
            raise Refusal(
                "`job` `finish` names every living hired member once each, never the player: "
                f"expected {', '.join(expected) or '(nobody)'}; given {', '.join(given)}"
            )

        facts: list[Fact] = []
        for raise_ in raises:
            facts.extend(self._raise(world.require_actor(raise_.actor_id), raise_.skill))
        for actor in (world.player, *members):
            rolled = roll((6,), f"credits earned by {actor.name}", rng)
            facts.append(rolled.fact)
            facts.extend(actor.earn(rolled.face, dice=(rolled.event,)))
        world.close_job()
        world.raise_owed = True
        return [*facts, Fact(trace=JOB_PAID)]

    def _raise(self, actor: Crewmate, skill: str) -> list[Fact]:
        return actor.raise_skill(self._match_skill(actor.require_sheet().skills, skill) or skill)


def items_from_kits(kits: Sequence[Kit]) -> dict[Slug, Gear]:
    taken: list[str] = list(SHIP_IDS)
    items: dict[Slug, Gear] = {}
    for kit in kits:
        key = slug(kit.name, taken)
        taken.append(key)
        items[key] = Gear(**kit.model_dump())
    return items


def _answered(step: CreationStep, given: str) -> str:
    if not step.options:
        return given
    folded = given.casefold()
    chosen = next(
        (option.id for option in step.options if folded in (option.id, option.name.casefold())),
        None,
    )
    if chosen is None and not step.allows_text:
        names = " / ".join(option.name for option in step.options)
        raise Refusal(f"{step.name}: {given!r} is not one of {names}")
    return chosen or given


def _find(world: TwentyFourXXWorld, where: str, rng: Random) -> list[Fact]:
    world.require_no_job()
    rolled = roll((6,), where, rng)
    face = rolled.face
    result = outcome_band(face, NO_WORK, ODD_WORK, TWO_JOBS_FOUND)
    world.settle(f"{WORK_AT}{where}", result)
    return [
        rolled.fact,
        world.player.card_fact(f"{where} — d6 → {result}", (rolled.event,)),
        Fact(trace=outcome_band(face, NO_JOB, ODD_JOB, TWO_JOBS)),
    ]


def _defend_or_land(
    draft: TwentyFourXXGame, pool: DicePool, rolled: DiceEvent, choices: dict[Slug, Slug | None]
) -> list[Fact]:
    band = roll_band(max(rolled.rolled))
    for who, stake in pool.stakes():
        hurt = (band == "disaster" and stake.harm) or (band != "success" and stake.deadly)
        defences = draft.world.defences_for(who)
        if not hurt or stake.defend is not None or who.id in choices or not defences:
            continue
        hit = (
            f"{who.name} is maimed"
            if band == "setback"
            else f"{sentence(stake.risk)} hits {who.name}"
        )
        draft.pending = PendingDecision(
            kind="defence",
            prompt=f"{pool.roll.what}: {band}. {hit}. Break an item to turn it into a brief "
            "hindrance, or take it.",
            options=(
                *(
                    _defence(
                        f"Break {gear.name}", pool, rolled, {**choices, who.id: item_id}, item_id
                    )
                    for item_id, gear in defences
                ),
                _defence("Take it", pool, rolled, {**choices, who.id: None}, None),
            ),
            allows_text=False,
        )
        return []
    return _land(draft, pool, band, rolled, choices)


def _land(
    draft: TwentyFourXXGame,
    pool: DicePool,
    band: str,
    rolled: DiceEvent,
    choices: dict[Slug, Slug | None],
) -> list[Fact]:
    world = draft.world
    world.work_rolled = True
    line, staked = _roll_lines(pool)
    facts = [pool.actor.fact(f"{staked} → {band}", card=f"{line} → {band}", dice=(rolled,))]
    if band != "success":
        # Hits land helper-first, the reverse of the actor-first claims checked before.
        for who, stake in reversed(pool.stakes()):
            defend = stake.defend
            item_id = None if defend is None else defend.item_id
            hindrance = "" if defend is None else defend.hindrance
            if (chosen := choices.get(who.id)) is not None:
                harmless = world.require_gear(who, chosen).harmless
                item_id, hindrance = chosen, "" if harmless else spared(deadly=stake.deadly)
            facts.extend(
                world.take_hit(
                    who,
                    item_id,
                    hindrance,
                    risk=stake.risk,
                    disaster=band == "disaster",
                    deadly=stake.deadly,
                    harm=stake.harm,
                )
            )
    if any(chosen is not None for chosen in choices.values()):
        facts.append(Fact(trace=GEAR_TOOK_THE_HIT))
    return facts


def _raise_decision(sheet: CrewSheet) -> PendingDecision:
    return PendingDecision(
        kind="raise",
        prompt=RAISE_PROMPT,
        options=tuple(
            PendingOption(
                id=slug(skill, ()),
                name=f"{skill} d{die} → d{next_die}",
                action_name="raise_skill",
                args={"skill": skill},
            )
            for skill, die in sheet.skills.items()
            if (next_die := raised(die)) is not None
        ),
        allows_text=True,
    )


def _defence(
    name: str,
    pool: DicePool,
    rolled: DiceEvent,
    choices: dict[Slug, Slug | None],
    item_id: Slug | None,
) -> PendingOption:
    hit = DefendHit(roll=pool.roll, rolled=rolled, choices=choices)
    return PendingOption(
        id=item_id or "take-it",
        name=name,
        action_name="defend_hit",
        args=hit.model_dump(mode="json"),
    )


def _roll_lines(pool: DicePool) -> tuple[str, str]:
    args = pool.roll
    line = f"{args.what} — {pool.actor.card_line(sentence(pool.label))} d{pool.die}"
    if args.helped:
        line += f", helped ({args.helped})"
    if (helping := pool.helping) is not None:
        hindered = f", hindered ({helping.terms.hindered})" if helping.terms.hindered else ""
        skill = sentence(helping.skill or "unskilled")
        line += f", helped by {helping.who.name} ({skill} d{pool.faces[-1]}{hindered})"
    if args.hindered:
        line += f", hindered ({args.hindered})"
    staked = line
    if helping is not None and (terms := helping.terms).risk:
        risked = risk_text(terms.risk, harm=terms.harm, deadly=terms.deadly)
        staked += f", {helping.who.name} risking {risked}"
    return line, f"{staked}, risking {risk_text(args.risk, harm=args.harm, deadly=args.deadly)}"


def _burdens(actor: Crewmate) -> list[str]:
    sheet = actor.require_sheet()
    burdens: list[str] = []
    if sheet.hindrances:
        burdens.append(f"Hindrances: {', '.join(sheet.hindrances)}.")
    if (bulky := sum(item.bulky for item in sheet.items.values())) > 1:
        burdens.append(f"Carries {bulky} bulky items.")
    return burdens


def _item_lines(items: Mapping[Slug, Gear]) -> str:
    return lines_of(
        f"- {tag_of(item.name, key)}" + (f" — {detail}" if (detail := item.notes()) else "")
        for key, item in items.items()
    )
