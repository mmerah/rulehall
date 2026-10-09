from collections.abc import Mapping, Sequence

from rulehall.core.prompt import sentence
from rulehall.engines.pokemon.dex import showdown_id

STATUS_WORDS = {
    "brn": "burned",
    "par": "paralysed",
    "slp": "asleep",
    "frz": "frozen",
    "psn": "poisoned",
    "tox": "badly poisoned",
    "confusion": "confused",
}
STAT_WORDS = {
    "atk": "Attack",
    "def": "Defense",
    "spa": "Sp. Atk",
    "spd": "Sp. Def",
    "spe": "Speed",
    "accuracy": "accuracy",
    "evasion": "evasion",
}
CANT_WORDS = {"flinch": "it flinched", "recharge": "it had to recharge", "nopp": "no PP left"}
FIELD_WORDS: dict[str, tuple[str, str]] = {
    "raindance": ("Rain", "Water moves 1.5x, Fire moves 0.5x"),
    "primordialsea": ("Heavy rain", "Water moves 1.5x, Fire moves fail"),
    "sunnyday": ("Harsh sunlight", "Fire moves 1.5x, Water moves 0.5x"),
    "desolateland": ("Extremely harsh sunlight", "Fire moves 1.5x, Water moves fail"),
    "sandstorm": ("Sandstorm", "hurts all but Rock, Ground and Steel types each turn"),
    "snowscape": ("Snow", "Ice types get 1.5x Defense"),
    "snow": ("Snow", "Ice types get 1.5x Defense"),
    "hail": ("Hail", "hurts all but Ice types each turn"),
    "deltastream": ("Strong winds", "moves are not super effective on Flying types"),
    "electricterrain": (
        "Electric Terrain",
        "grounded Pokemon's Electric moves 1.3x, they cannot fall asleep",
    ),
    "grassyterrain": (
        "Grassy Terrain",
        "grounded Pokemon's Grass moves 1.3x, they heal a little each turn",
    ),
    "mistyterrain": (
        "Misty Terrain",
        "Dragon moves on grounded Pokemon 0.5x, they cannot get a status",
    ),
    "psychicterrain": (
        "Psychic Terrain",
        "grounded Pokemon's Psychic moves 1.3x, priority moves cannot hit them",
    ),
    "trickroom": ("Trick Room", "the slowest Pokemon moves first"),
    "gravity": ("Gravity", "every Pokemon is grounded"),
    "magicroom": ("Magic Room", "held items do nothing"),
    "wonderroom": ("Wonder Room", "Defense and Sp. Def are swapped"),
    "stealthrock": ("Stealth Rock", "hurts each Pokemon that comes in, more if weak to Rock"),
    "spikes": ("Spikes", "hurt each grounded Pokemon that comes in"),
    "toxicspikes": ("Toxic Spikes", "poison each grounded Pokemon that comes in"),
    "stickyweb": ("Sticky Web", "lowers the Speed of each grounded Pokemon that comes in"),
    "reflect": ("Reflect", "physical damage reduced"),
    "lightscreen": ("Light Screen", "special damage reduced"),
    "auroraveil": ("Aurora Veil", "all damage reduced"),
    "tailwind": ("Tailwind", "Speed doubled"),
    "safeguard": ("Safeguard", "no status can be caused"),
    "mist": ("Mist", "stats cannot be lowered"),
}
PROTECTIONS = frozenset({"Protect", "Detect", "King's Shield", "Spiky Shield", "Baneful Bunker"})
FIRST_PART = "Start"
FROM = "[from] "


def recent_turns(log: Sequence[str], owners: Mapping[str, str], shown: int) -> tuple[str, ...]:
    turns: list[tuple[str, list[str]]] = [(FIRST_PART, [])]
    for line in log:
        _, kind, *fields = line.split("|")
        if kind == "turn":
            turns.append((f"Turn {fields[0]}", []))
        elif event := _event(kind, fields, owners):
            turns[-1][1].append(sentence(event))
    told = [f"{label}: {'. '.join(events)}." for label, events in turns if events]
    return tuple(told[-shown:])


def hp_percent(hp: int, maxhp: int) -> int:
    if not maxhp:
        return 0
    # As a player sees a foe: rounded up, and never 100 below full HP.
    share = -(-100 * hp // maxhp)
    return 99 if share == 100 and hp < maxhp else share


def _event(kind: str, fields: Sequence[str], owners: Mapping[str, str]) -> str:
    def who(at: int) -> str:
        return _who(fields[at], owners) if len(fields) > at else ""

    source = _source(fields)
    match kind:
        case "switch":
            return f"{who(0)} came in"
        case "drag":
            return f"{who(0)} was dragged in"
        case "move" if len(fields) >= 2:
            spread = any(field.startswith("[spread]") for field in fields[3:])
            aimed = len(fields) > 2 and fields[2] and fields[2] != fields[0] and not spread
            return f"{who(0)} used {fields[1]}" + (f" on {who(2)}" if aimed else "")
        case "cant" if len(fields) >= 2:
            reason = _plain(fields[1])
            told = CANT_WORDS.get(reason, STATUS_WORDS.get(reason, reason))
            return f"{who(0)} could not move ({told})"
        case "-damage" if len(fields) >= 2:
            return f"{who(0)} fell to {_condition_percent(fields[1])}% HP{source}"
        case "-heal" if len(fields) >= 2:
            return f"{who(0)} healed to {_condition_percent(fields[1])}% HP{source}"
        case "faint":
            return f"{who(0)} fainted"
        case "-status" if len(fields) >= 2:
            return f"{who(0)} is now {STATUS_WORDS.get(fields[1], fields[1])}{source}"
        case "-curestatus" if len(fields) >= 2:
            return f"{who(0)} is no longer {STATUS_WORDS.get(fields[1], fields[1])}"
        case "-boost" | "-unboost" if len(fields) >= 3:
            change = "rose" if kind == "-boost" else "fell"
            stat = STAT_WORDS.get(fields[1], fields[1])
            return f"{who(0)}'s {stat} {change} by {fields[2]}{source}"
        case "-clearallboost":
            return "all stat changes were cleared"
        case "-clearboost":
            return f"{who(0)}'s stat changes were cleared"
        case "-miss":
            return f"{who(0)} missed"
        case "-crit":
            return f"a critical hit on {who(0)}"
        case "-supereffective":
            return f"it was super effective on {who(0)}"
        case "-resisted":
            return f"it was not very effective on {who(0)}"
        case "-immune":
            return f"{who(0)} was not affected{source}"
        case "-fail" if len(fields) >= 2 and fields[1] == "unboost":
            named = len(fields) >= 3 and not fields[2].startswith("[")
            stat = f"{STAT_WORDS.get(fields[2], fields[2])} did" if named else "stats did"
            return f"{who(0)}'s {stat} not fall{source}"
        case "-fail":
            return f"{who(0)}'s move failed"
        case "-enditem" if len(fields) >= 2:
            used = "ate" if "[eat]" in fields else "lost"
            return f"{who(0)} {used} its {fields[1]}{source}"
        case "-mega" if len(fields) >= 3:
            return f"{who(0)} Mega Evolved with its {fields[2]}"
        case "-item" if len(fields) >= 2:
            return f"{who(0)} holds {fields[1]}{source}"
        case "-ability" if len(fields) >= 2:
            return f"{who(0)}'s ability {fields[1]} acted"
        case "-activate" if len(fields) >= 2 and _plain(fields[1]) in PROTECTIONS:
            return f"{who(0)} protected itself"
        case "-activate" if len(fields) >= 2 and _plain(fields[1]) == "Substitute":
            return f"{who(0)}'s Substitute took the hit"
        case "-start" if len(fields) >= 2:
            effect = _plain(fields[1])
            return f"{who(0)} is {STATUS_WORDS.get(effect, 'under ' + effect)}{source}"
        case "-end" if len(fields) >= 2:
            return f"{_plain(fields[1])} ended on {who(0)}"
        case "-weather" if fields and "[upkeep]" not in fields:
            if fields[0] == "none":
                return "the weather cleared"
            return f"{_field_name(fields[0])} started{source}"
        case "-fieldstart" | "-fieldend" if fields:
            return f"{_plain(fields[0])} {'started' if kind == '-fieldstart' else 'ended'}"
        case "-sidestart" | "-sideend" if len(fields) >= 2:
            side = owners.get(fields[0].partition(":")[0], fields[0])
            change = "was set on" if kind == "-sidestart" else "ended on"
            return f"{_plain(fields[1])} {change} {side} side"
        case _:
            return ""


def _who(ident: str, owners: Mapping[str, str]) -> str:
    position, _, name = ident.partition(": ")
    owner = owners.get(f"{position[:2]}: {name}", owners.get(position[:2], ""))
    return f"{owner} {name}".strip()


def _source(fields: Sequence[str]) -> str:
    found = next((field for field in fields if field.startswith(FROM)), "")
    if not found:
        return ""
    cause = _plain(found.removeprefix(FROM))
    return f" ({STATUS_WORDS.get(cause, cause)})"


def _condition_percent(condition: str) -> int:
    hp, _, maxhp = condition.partition(" ")[0].partition("/")
    return hp_percent(int(hp), int(maxhp or 0))


def _field_name(text: str) -> str:
    words = FIELD_WORDS.get(showdown_id(text))
    return text if words is None else words[0]


def _plain(text: str) -> str:
    for prefix in ("move: ", "ability: ", "item: "):
        text = text.removeprefix(prefix)
    return text
