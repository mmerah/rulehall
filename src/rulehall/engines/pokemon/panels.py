from collections.abc import Collection
from pathlib import Path

from rulehall.core.play import PendingOption
from rulehall.core.validation import Slug
from rulehall.core.views import Meter, Panel, PanelRow, Sprite, Tag
from rulehall.engines.pokemon.battle.models import FRIENDSHIP_MAX, LEVEL_MAX
from rulehall.engines.pokemon.dex import Species, dex
from rulehall.engines.pokemon.rules import (
    ITEMS,
    STAT_NAMES,
    TIMES,
    BagId,
    item_of,
    nature_effect,
    tm_move,
)
from rulehall.engines.pokemon.world import Mon, MoveSlot, TrainerSheet

type StatLine = tuple[str, int, str]
ICON_SHEET = Path("sprites/pokemonicons-sheet.png")
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
GENDER_SIGNS = {"M": "♂", "F": "♀", "N": ""}
RAISED, LOWERED = " ▲", " ▼"
ITEMS_GROUP, LEARN_GROUP, TEAM_GROUP = "Items", "Learn", "Team"
POCKETS = {
    "potion": "Medicine",
    "full-heal": "Medicine",
    "revive": "Medicine",
    "candy": "Medicine",
    "ball": "Balls",
    "held": "Held items",
    "evolution": "Evolution",
    "tm": "TMs",
}
POCKET_ORDER = tuple(dict.fromkeys(POCKETS.values()))
KIND_TEXT = {
    "ball": "Thrown at a wild Pokemon on the battle screen.",
    "potion": "Restores {heal} HP.",
    "full-heal": "Cures any status.",
    "revive": "Revives a fainted Pokemon with half its HP.",
    "candy": "Raises a Pokemon one level.",
}


def mon_sprite(species: Species) -> Sprite:
    row, column = divmod(species.icon, ICONS_PER_ROW)
    x, y = column * ICON_WIDTH, row * ICON_HEIGHT
    return Sprite(path=ICON_SHEET, x=x, y=y, width=ICON_WIDTH, height=ICON_HEIGHT)


def item_sprite(item_id: BagId) -> Sprite:
    name = item_id if item_id in ITEMS else f"tm-{tm_move(item_id).type.lower()}"
    return Sprite(path=Path(f"sprites/items/{name}.png"))


def trainer_sprite(avatar_id: Slug) -> Sprite:
    return Sprite(path=Path(f"sprites/trainers/{avatar_id}.png"))


def type_tag(kind: str) -> Tag:
    return Tag(name=kind, colour=TYPE_COLOURS[kind])


def team_panels(sheet: TrainerSheet, species_pool: Collection[Slug]) -> tuple[Panel, ...]:
    bag = sorted(sheet.bag, key=_pocket_key)
    usable = [item_id for item_id in bag if item_of(item_id).kind != "ball"]
    return (
        Panel(
            title="Team",
            rows=tuple(
                mon_row(mon, mon_options(mon, sheet, usable, species_pool)) for mon in sheet.team
            ),
            tab="Team",
        ),
        Panel(
            title="Box",
            rows=tuple(mon_row(mon, box_options(mon, sheet)) for mon in sheet.box),
            tab="Team",
        ),
        Panel(
            title="Bag",
            rows=(
                *(
                    bag_row(item_id, sheet.bag[item_id], sheet.team, species_pool)
                    for item_id in bag
                ),
                PanelRow(name="Money", brief=f"₽{sheet.money}"),
                PanelRow(name="Badges", brief=", ".join(sheet.badges) or "none"),
            ),
            tab="Team",
        ),
    )


def mon_row(mon: Mon, options: tuple[PendingOption, ...] = ()) -> PanelRow:
    stat_lines = _stat_lines(mon)
    lines = stat_lines[1:]
    top = max(value for _, value, _ in lines)
    status = "fnt" if mon.fainted else mon.status
    share = mon.hp.current / mon.hp.maximum
    hp_colour = "#48d040" if share > 0.5 else "#f8d030" if share > 0.2 else "#f05030"
    return PanelRow(
        name=f"{mon.species_name} {GENDER_SIGNS[mon.gender]}".rstrip(),
        brief=" · ".join(f"{slot.move.name} {slot.pp}/{slot.move.pp}" for slot in mon.moves),
        icon_id=mon.mon_id,
        tags=(
            Tag(name=f"Lv{mon.level}"),
            *(type_tag(kind) for kind in mon.species.types),
            *((Tag(name=status.upper(), colour=STATUS_COLOURS[status]),) if status else ()),
            nature_tag(mon.nature),
            *((Tag(name=ITEMS[mon.item_id].name),) if mon.item_id else ()),
            Tag(name=f"♥ {mon.friendship}"),
        ),
        meters=(
            Meter(name="HP", current=mon.hp.current, maximum=mon.hp.maximum, colour=hp_colour),
            *(
                Meter(name=name, current=value, maximum=top, colour="#6890f0", hint=hint)
                for name, value, hint in lines
            ),
        ),
        options=options,
        detail=_mon_detail(mon, stat_lines),
    )


def move_row(slot: MoveSlot) -> PanelRow:
    move = slot.move
    accuracy = "never misses" if move.accuracy is None else f"{move.accuracy}% accuracy"
    return PanelRow(
        name=move.name,
        brief=" · ".join((*((f"Power {move.power}",) if move.power else ()), accuracy, move.text)),
        tags=(type_tag(move.type), Tag(name=move.category)),
        meters=(Meter(name="PP", current=slot.pp, maximum=move.pp),),
    )


def bag_row(
    item_id: BagId, count: int, team: list[Mon], species_pool: Collection[Slug]
) -> PanelRow:
    item = item_of(item_id)
    return PanelRow(
        name=item.name,
        brief=item_text(item_id),
        icon_id=item_id,
        tags=(Tag(name=f"{TIMES}{count}"), Tag(name=POCKETS[item.kind])),
        options=()
        if item.kind == "ball"
        else tuple(item_option(mon, item_id, species_pool) for mon in team),
    )


def item_text(item_id: BagId) -> str:
    item = item_of(item_id)
    match item.kind:
        case "tm":
            move = tm_move(item_id)
            return f"Teaches {move.name}. {move.text}"
        case "held" | "evolution":
            return item.text or dex().items[item_id.replace("-", "")]
        case kind:
            return KIND_TEXT[kind].format(heal=item.heal)


def nature_tag(nature: str) -> Tag:
    return Tag(name=nature, hint=nature_text(nature))


def nature_text(nature: str) -> str:
    arrows = nature_arrows(nature)
    if not arrows:
        return "no stat changed"
    return " · ".join(STAT_NAMES[index] + arrow for index, arrow in arrows.items())


def nature_arrows(nature: str) -> dict[int, str]:
    effect = nature_effect(nature)
    return {} if effect is None else dict(zip(effect, (RAISED, LOWERED), strict=True))


def mon_options(
    mon: Mon, sheet: TrainerSheet, bag: list[BagId], species_pool: Collection[Slug]
) -> tuple[PendingOption, ...]:
    name = mon.species_name
    take = (
        ()
        if mon.item_id is None
        else (
            PendingOption(
                id=f"take-{mon.mon_id}",
                name=f"Take the {ITEMS[mon.item_id].name} from {name}",
                action_name="hold_item",
                args={"mon_id": mon.mon_id, "item_id": None},
                group=ITEMS_GROUP,
            ),
        )
    )
    remembered = (
        PendingOption(
            id=f"remember-{move_id}",
            name=f"Remember {dex().moves[move_id].name}",
            action_name="relearn_move",
            args={"mon_id": mon.mon_id, "move_id": move_id},
            group=LEARN_GROUP,
        )
        for move_id in mon.relearnable()
    )
    return (
        *take,
        *(item_option(mon, item_id, species_pool) for item_id in bag),
        *remembered,
        PendingOption(
            id=f"store-mon-{mon.mon_id}",
            name=f"Send {name} to the Box",
            action_name="store_mon",
            args={"mon_id": mon.mon_id},
            group=TEAM_GROUP,
            refusal=sheet.store_refusal(mon),
        ),
        PendingOption(
            id=f"lead-mon-{mon.mon_id}",
            name=f"{name} leads the team",
            action_name="lead_mon",
            args={"mon_id": mon.mon_id},
            group=TEAM_GROUP,
            refusal=sheet.lead_refusal(mon),
        ),
    )


def box_options(boxed: Mon, sheet: TrainerSheet) -> tuple[PendingOption, ...]:
    name = boxed.species_name
    return (
        PendingOption(
            id=f"withdraw-mon-{boxed.mon_id}",
            name=f"Add {name} to the team",
            action_name="withdraw_mon",
            args={"mon_id": boxed.mon_id},
            group=TEAM_GROUP,
            refusal=sheet.withdraw_refusal(boxed),
        ),
        *(
            PendingOption(
                id=f"swap-{mate.mon_id}",
                name=f"Swap with {mate.species_name}",
                action_name="swap_mon",
                args={"team_mon_id": mate.mon_id, "box_mon_id": boxed.mon_id},
                group=TEAM_GROUP,
            )
            for mate in sheet.team
        ),
    )


def item_option(mon: Mon, item_id: BagId, species_pool: Collection[Slug]) -> PendingOption:
    item = item_of(item_id)
    name = mon.species_name
    match item.kind:
        case "held":
            label, action_name, group = f"Give the {item.name} to {name}", "hold_item", ITEMS_GROUP
        case "tm":
            label, action_name = f"Teach {tm_move(item_id).name} to {name}", "teach_move"
            group = LEARN_GROUP
        case _:
            label, action_name, group = f"Use the {item.name} on {name}", "use_item", ITEMS_GROUP
    return PendingOption(
        id=f"{item_id}-{mon.mon_id}",
        name=label,
        action_name=action_name,
        args={"mon_id": mon.mon_id, "item_id": item_id},
        group=group,
        refusal=mon.item_refusal(item_id, species_pool),
    )


def _stat_lines(mon: Mon) -> tuple[StatLine, ...]:
    stats = mon.stats()
    arrows = nature_arrows(mon.nature)
    percents = {RAISED: "+10%", LOWERED: "-10%"}
    return tuple(
        (
            STAT_NAMES[index] + arrows.get(index, ""),
            stats[index],
            f"base {mon.species.base_stats[index]} · IV {mon.ivs[index]} · EV {mon.evs[index]}"
            + (f" · {mon.nature} {percents[arrows[index]]}" if index in arrows else ""),
        )
        for index in range(len(STAT_NAMES))
    )


def _mon_detail(mon: Mon, stat_lines: tuple[StatLine, ...]) -> tuple[Panel, ...]:
    species = mon.species
    floor, ceiling = mon.level**3, (mon.level + 1) ** 3
    held = (
        ()
        if mon.item_id is None
        else (
            PanelRow(
                name=ITEMS[mon.item_id].name, brief=item_text(mon.item_id), icon_id=mon.item_id
            ),
        )
    )
    return (
        Panel(
            title="About",
            rows=(
                *held,
                PanelRow(
                    name="Ability",
                    brief=dex().abilities[mon.ability],
                    tags=(Tag(name=mon.ability),),
                ),
                PanelRow(
                    name="Nature", brief=nature_text(mon.nature), tags=(nature_tag(mon.nature),)
                ),
                PanelRow(
                    name=f"Level {mon.level}",
                    brief="",
                    meters=()
                    if mon.level == LEVEL_MAX
                    else (Meter(name="EXP", current=mon.exp - floor, maximum=ceiling - floor),),
                ),
                PanelRow(
                    name="Friendship",
                    brief="",
                    meters=(
                        Meter(
                            name="♥",
                            current=mon.friendship,
                            maximum=FRIENDSHIP_MAX,
                            colour="#f85888",
                        ),
                    ),
                ),
                PanelRow(name="Pokedex", brief=species.entry),
            ),
        ),
        Panel(
            title="Stats",
            rows=tuple(
                PanelRow(name=name, brief=f"{value} · {hint}") for name, value, hint in stat_lines
            ),
        ),
        Panel(title="Moves", rows=tuple(move_row(slot) for slot in mon.moves)),
    )


def _pocket_key(item_id: BagId) -> tuple[int, str]:
    item = item_of(item_id)
    return POCKET_ORDER.index(POCKETS[item.kind]), item.name
