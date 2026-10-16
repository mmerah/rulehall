from functools import cache
from pathlib import Path

from rulehall.core.validation import Slug
from rulehall.core.views import Meter, Sprite, Tag
from rulehall.engines.panels import described_tag
from rulehall.engines.pokemon.dex import Move, Species, dex, move_brief
from rulehall.engines.pokemon.rules import STAT_NAMES, nature_effect

AVATAR = "avatar"
ICON_SHEET = Path("sprites/pokemonicons-sheet.png")
ITEM_SPRITES = Path("sprites/items")
ICON_WIDTH, ICON_HEIGHT, ICONS_PER_ROW = 40, 30, 12
TYPE_COLOURS = {
    "Normal": "#a8a878",
    "Fire": "#f08030",
    "Water": "#6890f0",
    "Electric": "#f8d030",
    "Grass": "#78c850",
    "Ice": "#98d8d8",
    "Fighting": "#c03028",
    "Poison": "#a040a0",
    "Ground": "#e0c068",
    "Flying": "#a890f0",
    "Psychic": "#f85888",
    "Bug": "#a8b820",
    "Rock": "#b8a038",
    "Ghost": "#705898",
    "Dragon": "#7038f8",
    "Dark": "#705848",
    "Steel": "#b8b8d0",
    "Fairy": "#ee99ac",
}
STATUS_COLOURS = {
    "psn": "#a040a0",
    "tox": "#a040a0",
    "brn": "#f08030",
    "par": "#f8d030",
    "slp": "#8c888c",
    "frz": "#98d8d8",
    "fnt": "#c03028",
}
STATUS_HELP = {
    "psn": "Poisoned: loses 1/8 of its max HP at the end of each turn.",
    "tox": "Badly poisoned: loses more HP at the end of each turn, more each turn.",
    "brn": "Burned: loses 1/16 of its max HP each turn, and its physical moves deal half damage.",
    "par": "Paralyzed: its Speed is halved, and it may be unable to move.",
    "slp": "Asleep: it cannot move for one to three turns.",
    "frz": "Frozen: it cannot move until it thaws.",
    "fnt": "Fainted: it cannot battle until it is revived.",
}
CATEGORY_COLOURS = {"Physical": "#c92112", "Special": "#4f5870", "Status": "#8c888c"}
LOW_COLOUR, OUT_COLOUR = "#f8d030", "#f05030"
STAT_COLOUR = "#6890f0"
PP_LOW_SHARE = 0.25
MEGA_COLOUR = "#c060d0"
RAISED, LOWERED = " ▲", " ▼"


def mon_sprite(species: Species) -> Sprite:
    row, column = divmod(species.icon, ICONS_PER_ROW)
    x, y = column * ICON_WIDTH, row * ICON_HEIGHT
    return Sprite(path=ICON_SHEET, x=x, y=y, width=ICON_WIDTH, height=ICON_HEIGHT)


def item_sprite(item_id: Slug) -> Sprite:
    return Sprite(path=ITEM_SPRITES / f"{item_id}.png")


def trainer_sprite(avatar_id: Slug) -> Sprite:
    return Sprite(path=Path(f"sprites/trainers/{avatar_id}.png"))


def type_tag(kind: str) -> Tag:
    return Tag(name=kind, colour=TYPE_COLOURS[kind], help=defence_text(kind))


def status_tag(status: str) -> Tag:
    return Tag(name=status.upper(), colour=STATUS_COLOURS[status], help=STATUS_HELP[status])


def move_tag(move: Move, pp: int | None = None) -> Tag:
    tag = described_tag(
        move.name if pp is None else f"{move.name} {pp}/{move.pp}",
        move.text,
        stat_line=move_brief(move, pp),
        colour=TYPE_COLOURS[move.type],
    )
    return tag if pp is None else tag.model_copy(update={"meter": pp_meter(pp, move.pp)})


def ability_tag(name: str) -> Tag:
    return described_tag(name, dex().abilities.get(name, ""))


@cache
def defence_text(kind: str) -> str:
    chart = dex().type_chart.items()
    taken = (
        ("weak to", [attacker for attacker, matchups in chart if kind in matchups.strong]),
        ("resists", [attacker for attacker, matchups in chart if kind in matchups.weak]),
        ("immune to", [attacker for attacker, matchups in chart if kind in matchups.none]),
    )
    parts = [f"{label} {', '.join(attackers)}" for label, attackers in taken if attackers]
    return f"{kind}: {'; '.join(parts)}." if parts else f"{kind}."


def category_tag(category: str) -> Tag:
    return Tag(name=category, colour=CATEGORY_COLOURS[category])


def hp_meter(current: int, maximum: int) -> Meter:
    share = current / maximum
    colour = "#48d040" if share > 0.5 else LOW_COLOUR if share > 0.2 else OUT_COLOUR
    return Meter(name="HP", current=current, maximum=maximum, colour=colour)


def pp_meter(current: int, maximum: int) -> Meter:
    colour = (
        STAT_COLOUR if current > maximum * PP_LOW_SHARE else LOW_COLOUR if current else OUT_COLOUR
    )
    return Meter(name="PP", current=current, maximum=maximum, colour=colour)


def nature_tag(nature: str) -> Tag:
    return Tag(name=nature, help=nature_text(nature))


def nature_text(nature: str) -> str:
    arrows = nature_arrows(nature)
    if not arrows:
        return "no stat changed"
    return " · ".join(STAT_NAMES[index] + arrow for index, arrow in arrows.items())


def nature_arrows(nature: str) -> dict[int, str]:
    effect = nature_effect(nature)
    return {} if effect is None else dict(zip(effect, (RAISED, LOWERED), strict=True))
