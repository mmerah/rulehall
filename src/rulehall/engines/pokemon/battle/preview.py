from collections.abc import Sequence

from rulehall.core.prompt import Prompt, lines_of, sections
from rulehall.core.tools import render_schema
from rulehall.core.validation import Slug
from rulehall.engines.pokemon.battle.choices import Hand
from rulehall.engines.pokemon.battle.models import Battler, BattleSetup, RoleSeat
from rulehall.engines.pokemon.battle.opponent import Offer, OpponentAnswer, opponent_system
from rulehall.engines.pokemon.dex import Species, dex
from rulehall.engines.pokemon.rules import STAT_NAMES, effectiveness

STAB = 1.5
SPEED_EDGE = 0.5
LEAD_BONUS = 2.0
LEAD_MOVE_IDS = frozenset({"fakeout", "tailwind", "trickroom"})
SPEED_INDEX = STAT_NAMES.index("Spe")
TEAM_PREVIEW = (
    "The battle has not started: both trainers see each other's team. Bring {size} of your "
    "Pokemon. The first {leads} you pick lead, the others wait on the bench; the rest sit this "
    "battle out. Give one `team N` command for each pick in THE CHOICES, in their order: N is "
    "the number of a Pokemon in YOUR POKEMON, and each Pokemon can be picked once. A Pokemon "
    "that holds its Mega Stone can Mega Evolve in battle, and your team can Mega Evolve only "
    "once per battle."
)
MATCHUPS = (
    "How each of your Pokemon fares against each foe: its best damaging move's effectiveness x "
    "power / 100 (x1.5 when the move is of its own type), minus the foe's best type "
    "effectiveness against it x1.5, plus 0.5 when its base Speed is higher. Higher is better."
)


def matchup_score(own: Battler, foe: Species) -> float:
    species = dex().species[own.species_id]
    known = dex().moves
    attack = max(
        (
            effectiveness(found.type, foe.types)
            * (STAB if found.type in species.types else 1.0)
            * found.power
            / 100
            for move in own.moves
            if (found := known.get(move.move_id)) is not None and found.power
        ),
        default=0.0,
    )
    threat = max(effectiveness(kind, species.types) * STAB for kind in foe.types)
    faster = SPEED_EDGE if species.base_stats[SPEED_INDEX] > foe.base_stats[SPEED_INDEX] else 0.0
    return attack - threat + faster


def scripted_preview(
    own: Sequence[Battler], foes: Sequence[Species], hand: Hand, size: int, leads: int
) -> tuple[str, ...]:
    scores = {at: sum(matchup_score(own[at], foe) for foe in foes) for at in sorted(hand)}
    brought = sorted(scores, key=lambda at: -scores[at])[:size]
    led = sorted(brought, key=lambda at: -scores[at] - _lead_bonus(own[at]))[:leads]
    return tuple(f"team {at + 1}" for at in (*led, *(at for at in brought if at not in led)))


def render_preview(
    setup: BattleSetup,
    seat: RoleSeat,
    offers: Sequence[Offer],
    own: Sequence[Battler],
    hand: Hand,
    foes: Sequence[Species],
) -> Prompt:
    leads = setup.format_spec().active_slots
    picks = scripted_preview(own, foes, hand, len(offers), leads)
    names = {f"team {at + 1}": own[at].name for at in hand}
    parts = (
        ("TEAM PREVIEW", TEAM_PREVIEW.format(size=len(offers), leads=leads)),
        ("YOUR POKEMON", "\n".join(_own_block(at, own[at]) for at in sorted(hand))),
        ("FOE TEAM", lines_of(f"- {foe.name}: {foe.types_text()}" for foe in foes)),
        ("MATCHUPS", "\n".join((MATCHUPS, *(_matchup_line(own[at], foes) for at in sorted(hand))))),
        (
            "SUGGESTION",
            "\n".join(
                f"- {offer.mon_name}: {pick} ({names[pick]})"
                for offer, pick in zip(offers, picks, strict=True)
            ),
        ),
        ("THE CHOICES", "\n\n".join(_offer_block(offer) for offer in offers)),
        ("ANSWER WITH", render_schema(OpponentAnswer)),
    )
    return Prompt(system=opponent_system(setup, seat), user=sections(parts))


def _lead_bonus(battler: Battler) -> float:
    return LEAD_BONUS if any(move.move_id in LEAD_MOVE_IDS for move in battler.moves) else 0.0


def _own_block(at: int, battler: Battler) -> str:
    species = dex().species[battler.species_id]
    named = battler.name if battler.name == species.name else f"{battler.name} ({species.name})"
    return "\n".join(
        (
            f"- {at + 1}. {named}, level {battler.level}, {species.types_text()}",
            f"  Ability: {battler.ability}. Item: {_item_text(battler.item_id)}",
            f"  Moves: {', '.join(move.name for move in battler.moves)}",
        )
    )


def _item_text(item_id: Slug | None) -> str:
    if item_id is None:
        return "none."
    pokedex = dex()
    name, text = pokedex.item_name(item_id), pokedex.item_text(item_id)
    return f"{name}: {text}" if text else f"{name}."


def _matchup_line(battler: Battler, foes: Sequence[Species]) -> str:
    scores = [matchup_score(battler, foe) for foe in foes]
    each = ", ".join(f"{foe.name} {score:+.1f}" for foe, score in zip(foes, scores, strict=True))
    return f"- {battler.name}: {each}; total {sum(scores):+.1f}"


def _offer_block(offer: Offer) -> str:
    return "\n".join(
        (f"{offer.mon_name}:", *(f"- {choice.command}: {choice.name}" for choice in offer.choices))
    )
