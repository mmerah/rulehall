from pathlib import Path
from random import Random

from rulehall.core.creation import (
    CreationStep,
    Picks,
    chosen_option,
    other_than,
    picked,
)
from rulehall.core.facts import Fact, roll
from rulehall.core.model import Character
from rulehall.core.play import PendingDecision
from rulehall.core.prompt import Sections
from rulehall.core.tools import tool
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import Rows
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.hiring import Joining
from rulehall.engines.loner3e.args import (
    DEFEAT_NOTE,
    TWIST_NOTE,
    ChangeTags,
    Drive,
    RestoreLuck,
    Roll,
    SpendLuck,
)
from rulehall.engines.loner3e.pack import (
    WORLDSMITH_GUIDANCE,
    Loner3eBody,
    Loner3eHead,
    Loner3ePack,
)
from rulehall.engines.loner3e.rules import (
    DIE_FACE,
    RollOutcome,
    outcome_for,
    pack_meanings,
    twist_pairing,
)
from rulehall.engines.loner3e.world import (
    Loner3eEntity,
    Loner3eGame,
    Loner3eWorld,
)
from rulehall.engines.packs import unique_options
from rulehall.engines.scenes.engine import SceneEngine
from rulehall.engines.scenes.world import NextProposal, SceneProposal


class Loner3eEngine(Joining, SceneEngine[Loner3eEntity, Loner3eWorld, Loner3ePack]):
    id = EngineId("loner3e")
    title = "LONER 3E"
    worldsmith_guidance = WORLDSMITH_GUIDANCE
    art_style = "Painterly illustration, muted colours, no text or lettering."
    directory = Path(__file__).parent
    pack = Loner3ePack
    head = Loner3eHead
    body = Loner3eBody
    world = Loner3eWorld
    person = Loner3eEntity
    opening = SceneProposal[Loner3eEntity]
    next_proposal = NextProposal[Loner3eEntity]

    def __init__(self, player_packs: Path) -> None:
        super().__init__(player_packs)
        srd = self.packs.srd()  # only the SRD pack publishes the twist table
        if srd.twist_subjects is None or srd.twist_actions is None:
            raise ValueError("the SRD table set has no twist columns")
        self.twists: Rows = tuple(zip(srd.twist_subjects, srd.twist_actions, strict=True))

    def creation_steps(self, pack_id: Slug, picks: Picks) -> tuple[CreationStep, ...]:
        played = self.packs.played(pack_id)
        concepts = unique_options(entry for pack in played for entry in pack.concepts)
        skills = unique_options(option for pack in played for option in pack.skills)
        frailties = unique_options(option for pack in played for option in pack.frailties)
        gear = unique_options(option for pack in played for option in pack.gear)
        return (
            CreationStep(
                id="concept",
                name="Write a one-line concept",
                hint=", ".join(entry.name for entry in concepts[:3]),
            ),
            CreationStep(id="goal", name="What does your character want?"),
            CreationStep(id="motive", name="Why do they want it?"),
            CreationStep(id="skill-1", name="Choose skill 1", options=skills),
            CreationStep(
                id="skill-2",
                name="Choose skill 2",
                options=other_than(skills, picked(picks, "skill-1")),
            ),
            CreationStep(id="frailty", name="Choose a frailty", options=frailties),
            CreationStep(id="gear-1", name="Choose gear 1", options=gear),
            CreationStep(
                id="gear-2",
                name="Choose gear 2",
                options=other_than(gear, picked(picks, "gear-1")),
            ),
        )

    def build_character(
        self, name: str, brief: str, pack_id: Slug, picks: Picks
    ) -> Character[Loner3eEntity]:
        steps = self.creation_steps(pack_id, picks)
        by_id = {step.id: step for step in steps}

        def taken(step_id: Slug) -> str:
            return chosen_option(by_id[step_id].options, picked(picks, step_id)).name

        sheet = Loner3eEntity(
            id=PLAYER_ID,
            name=name,
            brief=brief,
            known=True,
            concept=picked(picks, "concept"),
            tags={
                "skill": [taken(f"skill-{slot}") for slot in (1, 2)],
                "frailty": [taken("frailty")],
                "gear": [taken(f"gear-{slot}") for slot in (1, 2)],
            },
            goal=picked(picks, "goal"),
            motive=picked(picks, "motive"),
        )
        return self.sheet_character(name, sheet)

    def master_sections(self, state: Loner3eGame) -> Sections:
        packs = self.packs.played(state.pack_id)
        # The concept's pack blurb is generic where the entity's own brief is not: skip it.
        entries = tuple(
            entry for pack in packs for entry in (*pack.skills, *pack.frailties, *pack.gear)
        )
        spelled: dict[str, str] = {}
        for member in state.world.here():
            spelled.update(
                pack_meanings(
                    entries,
                    (*member.tagged("skill"), *member.tagged("frailty"), *member.tagged("gear")),
                )
            )
        lines = "\n".join(f"- {tag}: {detail}" for tag, detail in spelled.items())
        glossary = (("WHAT THE TAGS IN PLAY MEAN", lines),) if spelled else ()
        return (
            *super().master_sections(state),
            *glossary,
        )

    @tool
    def change_tags(self, draft: Loner3eGame, args: ChangeTags, _rng: Random) -> list[Fact]:
        """A character here gains tags, loses tags, or does both."""
        actor = draft.world.require_living_here(args.actor_id)
        return actor.change_tags(args.kind, args.gained, args.lost)

    @tool
    def drive(self, draft: Loner3eGame, args: Drive, _rng: Random) -> list[Fact]:
        """Change the goal, the motive or the nemesis of a living character."""
        actor = draft.world.require_living_here(args.actor_id)
        return actor.drive(goal=args.goal, motive=args.motive, nemesis=args.nemesis)

    @tool
    def restore_luck(self, draft: Loner3eGame, args: RestoreLuck, _rng: Random) -> list[Fact]:
        """Fill the luck of a character. Any defeat of that character ends."""
        actor = draft.world.require_living_here(args.actor_id)
        # Full luck and no defeat is a quiet no-op: a zero delta writes no fact.
        return actor.recover("the conflict is behind them")

    @tool
    def roll(self, draft: Loner3eGame, args: Roll, rng: Random) -> list[Fact]:
        """Call this for one closed question about the story. The engine rolls Chance against
        Risk and reads the answer. In a conflict, the engine also moves luck."""
        world = draft.world
        actor = world.require_living_here(args.actor_id)
        opponent = None
        if args.target_id is not None:
            opponent = world.require_living_here(args.target_id)
        world.check_conflict(actor, opponent)

        chance_faces, risk_faces = args.faces()
        chance = roll(
            chance_faces, f"{args.question} — chance", rng, label="Chance", highlight_kept=True
        )
        risk = roll(risk_faces, f"{args.question} — risk", rng, label="Risk", highlight_kept=True)

        outcome = outcome_for(chance.kept, risk.kept)
        line = _oracle_line(args, opponent, outcome)
        exchange: list[Fact] = []
        effects: tuple[str, ...] = ()
        if opponent is not None:
            facts, loser = world.strike(actor, opponent, outcome)
            exchange, effects = _absorbed(facts)
            if loser:
                draft.note(DEFEAT_NOTE.format(name=loser))
            elif PLAYER_ID in (actor.id, opponent.id):
                draft.pending = PendingDecision(
                    kind="conflict",
                    prompt=world.conflict_prompt(actor, opponent),
                    options=(),
                    allows_text=True,
                )
        # SRD: the Twist Counter skips Harm & Luck, so a tied conflict roll never ticks it.
        tied = chance.kept == risk.kept and opponent is None
        twist_facts = self._twist(draft, actor, rng) if tied and world.tick_twist() else []
        return [
            chance.fact,
            risk.fact,
            # The question is master-authored and may name unrevealed canon: never told.
            Fact(trace=f"asked: {args.question}"),
            actor.fact(line, card="\n".join((line, *effects)), dice=(chance.event, risk.event)),
            *exchange,
            *twist_facts,
        ]

    @tool
    def spend_luck(self, draft: Loner3eGame, args: SpendLuck, _rng: Random) -> list[Fact]:
        """A character here spends luck. The SPECIAL RULES of the selected pack gives the cost,
        for example a spell."""
        if not self.packs.require(draft.pack_id).spends_luck:
            raise Refusal("this pack does not spend luck")
        actor = draft.world.require_living_here(args.actor_id)
        return actor.spend_luck(args.amount, args.why)

    def _twist(self, draft: Loner3eGame, actor: Loner3eEntity, rng: Random) -> list[Fact]:
        """The dice must trace, so the SRD table is rolled here; the model reads the pairing."""
        rolled = roll((DIE_FACE, DIE_FACE), "twist — subject, action", rng, label="Twist")
        subject_face, action_face = rolled.event.rolled
        subject, action = twist_pairing(subject_face, action_face, self.twists)
        draft.note(TWIST_NOTE.format(subject=subject.upper(), action=action.upper()))
        due = actor.fact(
            f"a twist interrupts the scene: {subject} / {action}",
            card=f"Twist — {subject} / {action}",
            dice=(rolled.event,),
        )
        return [rolled.fact, due]


def _oracle_line(args: Roll, opponent: Loner3eEntity | None, outcome: RollOutcome) -> str:
    footing = args.position + (f" ({args.edge})" if args.edge else "")
    against = f" against {opponent.name}" if opponent is not None else ""
    return f"{args.what}{against} — oracle, {footing}: {outcome.wording}"


def _absorbed(exchange: list[Fact]) -> tuple[list[Fact], tuple[str, ...]]:
    """The exchange reads as lines inside the Oracle card, so it shows no cards of its own."""
    lines = tuple(fact.card for fact in exchange if fact.told and fact.card)
    return [fact.model_copy(update={"card": ""}) for fact in exchange], lines
