from pathlib import Path

from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.validation import Slug
from rulehall.core.views import Meter, Panel, PanelRow, Sprite, Tag
from rulehall.engines.pokemon.battle.models import FRIENDSHIP_MAX, LEVEL_MAX
from rulehall.engines.pokemon.dex import ITEMS, Move, Species, dex
from rulehall.engines.pokemon.rules import (
    FRIENDSHIP_EVOLVE,
    SKILL_USES,
    STAT_NAMES,
    TIMES,
    BagId,
    item_of,
    nature_effect,
    tm_move,
)
from rulehall.engines.pokemon.scheme import SCHEME_STAGES
from rulehall.engines.pokemon.sheet import Mon, MoveSlot, TrainerSheet
from rulehall.engines.pokemon.world import PokemonWorld

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
SHEET_HELP = {
    "Skills": "Trainer skills ranked 0 to 3: a check rolls a d20 plus twice the rank, and each "
    "badge adds a rank.",
    "Money": "Pokedollars (₽) to spend in shops; blacking out costs half of it.",
    "Badges": "Won from gym leaders: each adds a skill rank and, on a hard or Nuzlocke run, lifts "
    "the level cap.",
    "Team": "The Pokemon that travel and battle with this trainer, up to six; the first one leads.",
    "Rival": "Your record against your rival, who battles you before the first badge and after "
    "each one.",
    "Memorial": "Pokemon that fainted on a Nuzlocke run and are gone for good.",
}
SCHEME_HELP = {
    "Stage": "How many of the evil team's four operations have ended.",
    "Foiled": "Operations you stopped by beating their leader.",
    "Succeeded": "Operations that went through: each one makes the boss's team stronger.",
    "Now": "The operation the evil team runs now; beat its leader before your next badge.",
}
FRIENDSHIP_HELP = (
    f"Grows as this Pokemon levels up; at {FRIENDSHIP_EVOLVE} some species are ready to evolve."
)
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


def team_panels(world: PokemonWorld) -> tuple[Panel, ...]:
    sheet = world.player_sheet
    bag = sorted(sheet.bag, key=_pocket_key)
    usable = [item_id for item_id in bag if item_of(item_id).kind != "ball"]
    cap = sheet.level_cap()
    return (
        Panel(
            title="Team",
            rows=tuple(mon_row(mon, cap, mon_options(mon, world, usable)) for mon in sheet.team),
            help=SHEET_HELP["Team"],
            tab="Team",
        ),
        Panel(
            title="Box",
            rows=tuple(mon_row(mon, cap, box_options(mon, sheet)) for mon in sheet.box),
            help="Pokemon kept in storage, off the team; swap them in from here.",
            tab="Team",
        ),
        Panel(
            title="Bag",
            rows=(
                *(bag_row(item_id, world) for item_id in bag),
                PanelRow(name="Money", brief=f"₽{sheet.money}", help=SHEET_HELP["Money"]),
                PanelRow(
                    name="Badges",
                    brief=", ".join(sheet.badges) or "none",
                    help=SHEET_HELP["Badges"],
                ),
            ),
            help="Your items: use one on a Pokemon from its row; balls are thrown in battle.",
            tab="Team",
        ),
    )


def scheme_panels(world: PokemonWorld) -> tuple[Panel, ...]:
    evil_team = world.evil_team
    scheme = evil_team.scheme
    if scheme is None or not any(world.npcs[leader_id].known for leader_id in evil_team.leader_ids):
        return ()
    operation = evil_team.operation
    shown = (
        ("Stage", f"{evil_team.stage()}/{SCHEME_STAGES}"),
        ("Foiled", str(evil_team.foiled)),
        ("Succeeded", str(evil_team.succeeded)),
        *(() if operation is None else (("Now", operation.goal),)),
    )
    rows = tuple(PanelRow(name=name, brief=brief, help=SCHEME_HELP[name]) for name, brief in shown)
    help_text = "The evil team's scheme: stop each operation by beating its leader."
    return (Panel(title=scheme.name, rows=rows, help=help_text),)


def pending_decision(sheet: TrainerSheet) -> Decision | None:
    return _learning_decision(sheet) or _evolution_decision(sheet) or _rank_decision(sheet)


def mon_row(mon: Mon, cap: int, options: tuple[ActionOption, ...] = ()) -> PanelRow:
    stat_lines = _stat_lines(mon)
    lines = stat_lines[1:]
    top = max(value for _, value, _ in lines)
    status = "fnt" if mon.fainted else mon.status
    share = mon.hp.current / mon.hp.maximum
    hp_colour = "#48d040" if share > 0.5 else "#f8d030" if share > 0.2 else "#f05030"
    return PanelRow(
        name=f"{mon.label()} {GENDER_SIGNS[mon.gender]}".rstrip(),
        brief=" · ".join(f"{slot.move.name} {slot.pp}/{slot.move.pp}" for slot in mon.moves),
        icon_id=mon.mon_id,
        tags=(
            Tag(name=f"Lv{mon.level}"),
            *((_cap_tag(cap),) if cap < LEVEL_MAX and mon.level >= cap else ()),
            *(type_tag(kind) for kind in mon.species.types),
            *((Tag(name=status.upper(), colour=STATUS_COLOURS[status]),) if status else ()),
            nature_tag(mon.nature),
            *((Tag(name=ITEMS[mon.item_id].name),) if mon.item_id else ()),
            Tag(name=f"♥ {mon.friendship}", help=FRIENDSHIP_HELP),
        ),
        meters=(
            Meter(name="HP", current=mon.hp.current, maximum=mon.hp.maximum, colour=hp_colour),
            *(
                Meter(name=name, current=value, maximum=top, colour="#6890f0", help=help_text)
                for name, value, help_text in lines
            ),
        ),
        options=options,
        detail=_mon_detail(mon, stat_lines),
    )


def move_row(slot: MoveSlot) -> PanelRow:
    move = slot.move
    return PanelRow(
        name=move.name,
        brief=move_summary(move),
        tags=(type_tag(move.type), Tag(name=move.category)),
        meters=(Meter(name="PP", current=slot.pp, maximum=move.pp),),
    )


def move_summary(move: Move) -> str:
    accuracy = "never misses" if move.accuracy is None else f"{move.accuracy}% accuracy"
    return " · ".join((*((f"Power {move.power}",) if move.power else ()), accuracy, move.text))


def bag_row(item_id: BagId, world: PokemonWorld) -> PanelRow:
    sheet = world.player_sheet
    item = item_of(item_id)
    return PanelRow(
        name=item.name,
        brief=item_text(item_id),
        icon_id=item_id,
        tags=(Tag(name=f"{TIMES}{sheet.bag[item_id]}"), Tag(name=POCKETS[item.kind])),
        options=()
        if item.kind == "ball"
        else tuple(item_option(mon, item_id, world) for mon in sheet.team),
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
    return Tag(name=nature, help=nature_text(nature))


def nature_text(nature: str) -> str:
    arrows = nature_arrows(nature)
    if not arrows:
        return "no stat changed"
    return " · ".join(STAT_NAMES[index] + arrow for index, arrow in arrows.items())


def nature_arrows(nature: str) -> dict[int, str]:
    effect = nature_effect(nature)
    return {} if effect is None else dict(zip(effect, (RAISED, LOWERED), strict=True))


def mon_options(mon: Mon, world: PokemonWorld, bag: list[BagId]) -> tuple[ActionOption, ...]:
    sheet = world.player_sheet
    name = mon.name
    take = (
        ()
        if mon.item_id is None
        else (
            ActionOption(
                id=f"take-{mon.mon_id}",
                name=f"Take the {ITEMS[mon.item_id].name} from {name}",
                action_name="hold_item",
                args={"mon_id": mon.mon_id, "item_id": None},
                group=ITEMS_GROUP,
            ),
        )
    )
    remembered = (
        ActionOption(
            id=f"remember-{mon.mon_id}-{move_id}",
            name=f"Remember {dex().moves[move_id].name}",
            action_name="relearn_move",
            args={"mon_id": mon.mon_id, "move_id": move_id},
            group=LEARN_GROUP,
        )
        for move_id in mon.relearnable()
    )
    return (
        *take,
        *(item_option(mon, item_id, world) for item_id in bag),
        *remembered,
        ActionOption(
            id=f"store-mon-{mon.mon_id}",
            name=f"Send {name} to the Box",
            action_name="store_mon",
            args={"mon_id": mon.mon_id},
            group=TEAM_GROUP,
            refusal=sheet.store_refusal(mon),
        ),
        ActionOption(
            id=f"lead-mon-{mon.mon_id}",
            name=f"{name} leads the team",
            action_name="lead_mon",
            args={"mon_id": mon.mon_id},
            group=TEAM_GROUP,
            refusal=sheet.lead_refusal(mon),
        ),
    )


def box_options(boxed: Mon, sheet: TrainerSheet) -> tuple[ActionOption, ...]:
    name = boxed.name
    return (
        ActionOption(
            id=f"withdraw-mon-{boxed.mon_id}",
            name=f"Add {name} to the team",
            action_name="withdraw_mon",
            args={"mon_id": boxed.mon_id},
            group=TEAM_GROUP,
            refusal=sheet.withdraw_refusal(boxed),
        ),
        *(
            ActionOption(
                id=f"swap-{boxed.mon_id}-{mate.mon_id}",
                name=f"Swap with {mate.name}",
                action_name="swap_mon",
                args={"team_mon_id": mate.mon_id, "box_mon_id": boxed.mon_id},
                group=TEAM_GROUP,
            )
            for mate in sheet.team
        ),
    )


def item_option(mon: Mon, item_id: BagId, world: PokemonWorld) -> ActionOption:
    item = item_of(item_id)
    name = mon.name
    match item.kind:
        case "held":
            label, action_name, group = f"Give the {item.name} to {name}", "hold_item", ITEMS_GROUP
        case "tm":
            label, action_name = f"Teach {tm_move(item_id).name} to {name}", "teach_move"
            group = LEARN_GROUP
        case _:
            label, action_name, group = f"Use the {item.name} on {name}", "use_item", ITEMS_GROUP
    return ActionOption(
        id=f"{item_id}-{mon.mon_id}",
        name=label,
        action_name=action_name,
        args={"mon_id": mon.mon_id, "item_id": item_id},
        group=group,
        refusal=mon.item_refusal(item_id, world.species_ids, world.player_sheet.level_cap()),
    )


def _learning_decision(sheet: TrainerSheet) -> Decision | None:
    if not sheet.learning:
        return None
    learning = sheet.learning[0]
    mon = sheet.require_mon(learning.mon_id)
    move = dex().moves[learning.move_id].name
    return Decision(
        kind="new-move",
        prompt=(
            f"{mon.name} wants to learn {move}. It knows four moves. Forget one, or skip {move}?"
        ),
        options=tuple(
            ActionOption(
                id=forget_id or "skip",
                name=name,
                action_name="learn_move",
                args={
                    "mon_id": learning.mon_id,
                    "move_id": learning.move_id,
                    "forget_id": forget_id,
                },
            )
            for forget_id, name in (
                *((slot.move_id, f"Forget {slot.move.name}") for slot in mon.moves),
                (None, f"Skip {move}"),
            )
        ),
        allows_text=False,
    )


def _evolution_decision(sheet: TrainerSheet) -> Decision | None:
    if not sheet.evolving:
        return None
    evolving = sheet.evolving[0]
    mon = sheet.require_mon(evolving.mon_id)
    return Decision(
        kind="evolution",
        prompt=f"{mon.name} is ready to evolve. Into which?",
        options=tuple(
            ActionOption(
                id=species_id,
                name=dex().species[species_id].name,
                action_name="evolve",
                args={"mon_id": evolving.mon_id, "species_id": species_id},
            )
            for species_id in evolving.species_ids
        ),
        allows_text=False,
    )


def _rank_decision(sheet: TrainerSheet) -> Decision | None:
    options = tuple(
        ActionOption(
            id=skill,
            name=skill.title(),
            help=f"Used to {SKILL_USES[skill]}; each rank adds 2 to its d20 checks.",
            action_name="raise_skill",
            args={"skill": skill},
        )
        for skill in sheet.rankable()
    )
    if not (sheet.ranks_due and options):
        return None
    return Decision(
        kind="badge-rank",
        prompt="Your new badge gives one skill rank. Which skill gains it?",
        options=options,
        allows_text=False,
    )


def _cap_tag(cap: int) -> Tag:
    return Tag(
        name="Cap", help=f"At the level cap, L{cap}: no more EXP until the next badge lifts it."
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
                    else (
                        Meter(
                            name="EXP",
                            current=mon.exp - floor,
                            maximum=ceiling - floor,
                            help="Experience toward the next level, won in battle.",
                        ),
                    ),
                ),
                PanelRow(
                    name="Friendship",
                    brief="",
                    help=FRIENDSHIP_HELP,
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
                PanelRow(name=name, brief=f"{value} · {breakdown}")
                for name, value, breakdown in stat_lines
            ),
        ),
        Panel(title="Moves", rows=tuple(move_row(slot) for slot in mon.moves)),
    )


def _pocket_key(item_id: BagId) -> tuple[int, str]:
    item = item_of(item_id)
    return POCKET_ORDER.index(POCKETS[item.kind]), item.name
