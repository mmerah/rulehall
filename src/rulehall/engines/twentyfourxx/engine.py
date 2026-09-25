from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import NamedTuple

from rulehall.core.creation import (
    CreationStep,
    Picks,
    chosen_option,
    option_of,
    picked,
)
from rulehall.core.facts import Fact, roll
from rulehall.core.model import AnyCharacter, Character, Check
from rulehall.core.play import DecisionOption, PendingDecision, PendingOption
from rulehall.core.prompt import Sections, lines_of, section_if, sentence
from rulehall.core.tools import action, tool
from rulehall.core.validation import EngineId, Refusal, Slug, slug
from rulehall.core.views import Panel, Rows, tag_of
from rulehall.engines.args import Kill
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.hiring import Hiring
from rulehall.engines.packs import unique_options
from rulehall.engines.panels import character_panel, here_panel, party_panel
from rulehall.engines.scenes.engine import SceneEngine, trail_panel
from rulehall.engines.twentyfourxx.args import (
    AskWorld,
    CarriedItem,
    ChangeHindrances,
    Defend,
    FromHold,
    GainItem,
    Helper,
    Job,
    LoseHoldItem,
    Raise,
    RepairItem,
    Roll,
    ShipUpgrade,
    Spend,
    Staked,
    TakeLead,
)
from rulehall.engines.twentyfourxx.pack import (
    HIRING,
    SKILL_COUNT,
    WORLDSMITH_GUIDANCE,
    Origin,
    SheetProposal,
    Specialty,
    TwentyFourXXBody,
    TwentyFourXXHead,
    TwentyFourXXPack,
)
from rulehall.engines.twentyfourxx.panels import gear_rows, job_panel, ship_panel
from rulehall.engines.twentyfourxx.rules import (
    DEFAULT_DIE,
    HELP_DIE,
    HINDERED_DIE,
    SkillDie,
    outcome_band,
    raised,
)
from rulehall.engines.twentyfourxx.world import (
    SHIP_IDS,
    Crewmate,
    CrewSheet,
    Gear,
    Kit,
    TwentyFourXXGame,
    TwentyFourXXNext,
    TwentyFourXXScene,
    TwentyFourXXWorld,
)


class Helping(NamedTuple):
    who: Crewmate
    terms: Helper


@dataclass(frozen=True, slots=True)
class DicePool:
    faces: tuple[int, ...]
    label: str
    die: int
    helped_by: str


class TwentyFourXXEngine(
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
    next_proposal = TwentyFourXXNext
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

    def hire_guidance(self, draft: TwentyFourXXGame) -> str:
        lines = [pack.specialty_lines() for pack in self.packs.played(draft.pack_id)]
        lines.append(f"Skills: {', '.join(option.name for option in self.packs.srd().skills)}")
        return "\n".join(lines)

    def hire_check(self, draft: TwentyFourXXGame) -> Check[SheetProposal]:
        packs = self.packs.played(draft.pack_id)
        return lambda sheet: sheet.check(packs)

    def sign_on(self, person: Crewmate, answer: SheetProposal) -> str:
        return person.sign_on(
            answer.specialty,
            answer.skills,
            items_from_kits(tuple(Kit(name=name) for name in answer.items)),
            answer.hindrances,
        )

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
        player = Crewmate(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            sheet=CrewSheet(
                specialty=specialty.name,
                origin=origin.name,
                traits=traits,
                skills=skills,
                items=items_from_kits(kits),
            ),
        )
        return self.sheet_character(name, player)

    def preview_character(self, character: AnyCharacter) -> Rows:
        sheet = self.player_of(character).require_sheet()
        return (*sheet.rows(), ("Gear", sheet.gear_text()))

    def player_sections(self, state: TwentyFourXXGame) -> Sections:
        world = state.world
        return (
            ("YOU PLAY FOR", world.player.line(gear=False)),
            ("GEAR", _item_lines(world.player.require_sheet().items)),
            *section_if("THE JOB", world.job),
            ("THE SHIP", _item_lines(world.ship)),
            (
                "THE HOLD",
                f"the ship is {'here' if world.ship_here else 'not here'}\n"
                f"{_item_lines(world.hold)}",
            ),
        )

    def context_lines(self, state: TwentyFourXXGame) -> str:
        return f"{super().context_lines(state)}\njob: {state.world.job or '(none)'}"

    def scene_panels(self, state: TwentyFourXXGame) -> tuple[Panel, ...]:
        world = state.world
        player = world.player
        return (
            character_panel(player.rows(), *gear_rows(world, player)),
            *job_panel(world),
            ship_panel(world),
            *party_panel(world.party_members(), lambda member: gear_rows(world, member)),
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
        actor = draft.world.require_actor(args.actor_id)
        return actor.change_hindrances(args.gained, args.lost)

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
        return actor.repair_item(world.require_gear(actor, args.item_id), args.cost)

    @tool
    def spend(self, draft: TwentyFourXXGame, args: Spend, _rng: Random) -> list[Fact]:
        """The actor pays credits for a thing that is not an item and not a repair."""
        actor = draft.world.require_actor(args.actor_id)
        return actor.spend(args.amount, args.why)

    @action
    def take_lead(self, draft: TwentyFourXXGame, args: TakeLead, _rng: Random) -> list[Fact]:
        return draft.world.take_lead(args.actor_id)

    @tool
    @action
    def ship_upgrade(self, draft: TwentyFourXXGame, args: ShipUpgrade, _rng: Random) -> list[Fact]:
        """The player upgrades one ship function."""
        return draft.world.upgrade_ship(args.function_id)

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
    def kill(self, draft: TwentyFourXXGame, args: Kill, rng: Random) -> list[Fact]:
        """A character here dies. If that character is the lead, the crew choose a new lead."""
        facts = super().kill(draft, args, rng)
        self._succession(draft)
        return facts

    def _offered(self, pack_id: Slug) -> tuple[tuple[Specialty, ...], tuple[Origin, ...]]:
        played = self.packs.played(pack_id)
        return (
            unique_options(option for pack in played for option in pack.specialties),
            unique_options(option for pack in played for option in pack.origins),
        )

    def _succession(self, draft: TwentyFourXXGame) -> None:
        """`kill` and `roll` are the two tools that can kill the lead."""
        world = draft.world
        if world.player.alive or not (members := world.hired_party_members()):
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

    def ending(self, state: TwentyFourXXGame) -> str | None:
        """A dead lead with a hired member alive is a succession, not an ending."""
        return None if state.world.hired_party_members() else super().ending(state)

    @tool
    def roll(self, draft: TwentyFourXXGame, args: Roll, rng: Random) -> list[Fact]:
        """Call this only to avoid a risk. The engine selects the dice, rolls the dice, and reads
        the result."""
        world = draft.world
        actor = world.require_actor(args.actor_id)
        helper = args.helped_by
        helping = None if helper is None else Helping(world.require_actor(helper.actor_id), helper)
        pool = self._pool(actor, helping, args)

        staked: list[tuple[Crewmate, Staked]] = [(actor, args)]
        if helping is not None:
            staked.append(helping)

        claims: list[tuple[Crewmate, Slug, str]] = [
            (who, terms.defend_with_id, terms.hindrance)
            for who, terms in staked
            if terms.defend_with_id is not None
        ]
        world.check_defenses(claims)

        label = "+".join(f"d{face}" for face in pool.faces)
        rolled = roll(
            pool.faces, f"{args.what} — {pool.label}", rng, label=label, highlight_kept=True
        )
        result = outcome_band(rolled.kept, "disaster", "setback", "success")

        line, card = _roll_lines(actor, helping, args, pool, result)

        facts = [rolled.fact, actor.fact(line, card=card, dice=(rolled.event,))]
        if result != "success":
            disaster = result == "disaster"
            # Hits land helper-first, the reverse of the actor-first claims above.
            for who, stake in reversed(staked):
                if not stake.risk:
                    continue
                facts.extend(
                    world.take_hit(
                        who,
                        stake.defend_with_id,
                        stake.hindrance,
                        risk=stake.risk,
                        disaster=disaster,
                        deadly=stake.deadly,
                    )
                )
        self._succession(draft)
        return facts

    def _skill_die(self, sheet: CrewSheet, skill: str) -> tuple[str, int]:
        if not skill:
            return "unskilled", DEFAULT_DIE
        label = self.resolve_skill(sheet, skill)
        return label, sheet.skills.get(label, DEFAULT_DIE)

    def _pool(self, actor: Crewmate, helping: Helping | None, args: Roll) -> DicePool:
        sheet = actor.require_sheet()
        if helping is not None and helping.who is actor:
            raise Refusal(f"{actor.name} cannot help their own roll")

        label, die = self._skill_die(sheet, args.skill)
        if args.hindered:
            die = HINDERED_DIE

        faces = [die]
        if args.helped:
            faces.append(HELP_DIE)
        helped_by = ""
        if helping is not None:
            who, terms = helping
            own_die = who.require_sheet().skills.get(label, DEFAULT_DIE)
            helper_die = HINDERED_DIE if terms.hindered else own_die
            hindered_note = f", hindered ({terms.hindered})" if terms.hindered else ""
            faces.append(helper_die)
            helped_by = f", helped by {who.name} (d{helper_die}{hindered_note})"

        return DicePool(faces=tuple(faces), label=label, die=die, helped_by=helped_by)

    @tool
    def ask_world(self, _draft: TwentyFourXXGame, args: AskWorld, rng: Random) -> list[Fact]:
        """Call this to ask about bad luck in the world when no character acts. The engine
        rolls one d6 and reads the die."""
        rolled = roll((6,), args.question, rng)
        result = outcome_band(rolled.face, "trouble now", "signs of it", "nothing")
        # The dice trace; the answer itself is never told.
        return [rolled.fact, Fact(trace=f"{args.question} — d6 [{rolled.face}] → {result}")]

    @tool
    def job(self, draft: TwentyFourXXGame, args: Job, rng: Random) -> list[Fact]:
        """Call this with `find` to look for work, with `take` to record agreed work, and with
        `finish` to close the job. With `find` the engine rolls the d6 of the SRD. With
        `finish` the engine raises one skill for each operator, then pays each operator d6
        credits."""
        match args.verb:
            case "find":
                return self._find(draft, args.where, rng)
            case "take":
                return draft.world.take_job(args.terms)
            case "finish":
                return self._finish(draft, args.raises, rng)

    def _find(self, draft: TwentyFourXXGame, where: str, rng: Random) -> list[Fact]:
        world = draft.world
        if world.job:
            raise Refusal(f"a job is open: {world.job}")
        rolled = roll((6,), where, rng)
        face = rolled.face
        result = outcome_band(
            face,
            "nothing; the player owes somebody to get in on a job",
            "a job, but something seems off",
            "a choice between two jobs",
        )
        line = f"{where} — d6 → {result}"
        return [rolled.fact, world.player.card_fact(line, (rolled.event,))]

    def _finish(self, draft: TwentyFourXXGame, raises: Sequence[Raise], rng: Random) -> list[Fact]:
        world = draft.world
        if not world.job:
            raise Refusal("no job is open to finish")
        expected = sorted((world.player.id, *(member.id for member in world.hired_party_members())))
        given = sorted(world.require_actor(raise_.actor_id).id for raise_ in raises)
        if given != expected:
            raise Refusal(
                "`job` `finish` names the player and every living hired member once each: "
                f"expected {', '.join(expected)}; given {', '.join(given) or '(nobody)'}"
            )

        facts: list[Fact] = []
        for raise_ in raises:
            actor = world.require_actor(raise_.actor_id)
            sheet = actor.require_sheet()
            skill = self._match_skill(sheet.skills, raise_.skill) or raise_.skill
            facts.extend(actor.raise_skill(skill))

            rolled = roll((6,), f"credits earned by {actor.name}", rng)
            facts.append(rolled.fact)
            facts.extend(actor.earn(rolled.face, rolled.event))
        world.close_job()
        return facts


def items_from_kits(kits: Sequence[Kit]) -> dict[Slug, Gear]:
    taken: list[str] = list(SHIP_IDS)
    items: dict[Slug, Gear] = {}
    for kit in kits:
        key = slug(kit.name, taken)
        taken.append(key)
        items[key] = Gear(**kit.model_dump())
    return items


def _roll_lines(
    actor: Crewmate, helping: Helping | None, args: Roll, pool: DicePool, result: str
) -> tuple[str, str]:
    """The fact line names every stake; the card line leaves them out."""
    led = actor.card_line(sentence(pool.label))
    line = f"{args.what} — {led} d{pool.die}"
    if args.helped:
        line += f", helped ({args.helped})"
    line += pool.helped_by
    if args.hindered:
        line += f", hindered ({args.hindered})"
    card = f"{line} → {result}"
    if helping is not None and helping.terms.risk:
        terms = helping.terms
        line += f", {helping.who.name} risking {_risk_text(terms.risk, deadly=terms.deadly)}"
    if args.risk:
        line += f", risking {_risk_text(args.risk, deadly=args.deadly)}"
    line += f" → {result}"
    return line, card


def _risk_text(risk: str, *, deadly: bool) -> str:
    return f"{risk} (deadly)" if deadly else risk


def _item_lines(items: Mapping[Slug, Gear]) -> str:
    return lines_of(
        f"- {tag_of(item.name, key)}" + (f" — {detail}" if (detail := item.notes()) else "")
        for key, item in items.items()
    )
