"""Lengthen a played Loner save of The Whispering Vault: many turns, a party of four.

Each added turn has the player's words, one or two narrations of two or three paragraphs, two
or three spoken lines from the companions, a closing line, two or three told fact cards (one
with Chance and Risk dice) and two untold traces. The entries are split into chapters of twenty.
"""

import random
from copy import deepcopy
from typing import Any

PARTY_IDS = ("mara", "brother-tomas", "elena")
CHAPTER_TURNS = 20
SENTENCES = (
    "Rain needles the shutters and the candle gutters low.",
    "Somewhere below, a door groans on its hinges and falls silent.",
    "Dust lifts from the shelves as you pass, gold in the lamplight.",
    "The smell of wax and old parchment hangs over everything.",
    "A bell tolls once in the far tower, then nothing.",
    "Footsteps cross the cloister and stop beneath the window.",
    "The ledger's ink has run where water once touched it.",
    "Cold air seeps through the cracked flagstones at your feet.",
)
SAYINGS = (
    "Keep your voice down. They listen at night.",
    "I have seen this mark before, in Varr.",
    "We should not linger here, Kael.",
    "Give me the lamp; my eyes are better than yours.",
    "The abbot lied to us. I am sure of it now.",
)


def lengthen(save: dict[str, Any], turns: int) -> dict[str, Any]:
    """A copy of the save with its opening kept and `turns - 1` turns after it, seeded."""
    save = deepcopy(save)
    rng = random.Random(7)
    world = save["world"]
    cast = world["cast"]
    world["party_ids"] = list(PARTY_IDS)
    here = world["scenes"][-1]["here_ids"]
    here += [person_id for person_id in PARTY_IDS if person_id not in here]
    for person_id in PARTY_IDS:
        cast[person_id]["known"] = True
        cast[person_id]["alive"] = True
    chapter = save["chapters"][0]
    opening = chapter["entries"][0]
    entries = [opening]
    entries += [_turn(rng, cast, number, opening["context"]) for number in range(1, turns)]
    save["chapters"] = [
        dict(
            chapter,
            entries=entries[start : start + CHAPTER_TURNS],
            title=f"{chapter['title']} {start // CHAPTER_TURNS + 1}",
            recap="" if start + CHAPTER_TURNS >= len(entries) else "Kael searched the abbey.",
        )
        for start in range(0, len(entries), CHAPTER_TURNS)
    ]
    return save


def _turn(rng: random.Random, cast: dict[str, Any], number: int, context: str) -> dict[str, Any]:
    lines = [
        _line(
            None, "\n\n".join(" ".join(rng.sample(SENTENCES, 3)) for _ in range(rng.randint(2, 3)))
        )
        for _ in range(rng.randint(1, 2))
    ]
    for _ in range(rng.randint(2, 3)):
        person = cast[rng.choice(PARTY_IDS)]
        lines.append(_line(person, rng.choice(SAYINGS)))
    lines.append(_line(None, " ".join(rng.sample(SENTENCES, 2))))
    chance, risk = rng.randint(1, 6), rng.randint(1, 6)
    question = f"Does turn {number} go my way?"
    facts = [
        _fact(f"{question} - chance: d6 [{chance}]"),
        _fact(f"{question} - risk: d6 [{risk}]"),
        _fact(
            f"oracle: {question}",
            f"{question}\nyes, but at a cost\nThe answer comes slowly.",
            [_die("Chance", chance), _die("Risk", risk)],
        ),
        _fact(f"tag change {number}", f"Kael gains a tag\nShaken (turn {number})"),
    ]
    if rng.random() < 0.5:
        facts.append(_fact(f"luck {number}", "Luck 5/6"))
    return {
        "words": f"Turn {number}: I look around the study again and ask Mara what she sees.",
        "by_option": False,
        "cause": None,
        "lines": lines,
        "facts": facts,
        "decision": "",
        "context": context,
    }


def _line(person: dict[str, Any] | None, text: str) -> dict[str, Any]:
    if person is None:
        return {"speaker_id": None, "speaker": "", "voice": None, "text": text}
    return {
        "speaker_id": person["id"],
        "speaker": person["name"],
        "voice": person.get("voice"),
        "text": text,
    }


def _fact(trace: str, card: str = "", dice: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"trace": trace, "told": bool(card), "card": card, "dice": dice or []}


def _die(label: str, rolled: int) -> dict[str, Any]:
    return {"label": label, "faces": [6], "rolled": [rolled], "highlight": []}
