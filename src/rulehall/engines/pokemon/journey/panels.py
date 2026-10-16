from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.validation import Slug
from rulehall.core.views import Meter, Panel, PanelRow, PanelRows, Score, Sprite, Tag
from rulehall.engines.panels import described_tag, score_block, tag_list, text_rows
from rulehall.engines.pokemon.battle.models import FRIENDSHIP_MAX, LEVEL_MAX
from rulehall.engines.pokemon.dex import dex, move_brief, species_name
from rulehall.engines.pokemon.journey.items import ITEMS, BagId, bag_name, item_of, tm_move
from rulehall.engines.pokemon.journey.mon import Learning, Mon
from rulehall.engines.pokemon.journey.rules import (
    FRIENDSHIP_EVOLVE,
    HELP_BONUSES,
    SKILL_USES,
    SKILLS,
    help_bonus,
)
from rulehall.engines.pokemon.journey.scheme import SCHEME_STAGES
from rulehall.engines.pokemon.journey.sheet import JourneySheet, JourneyTrainer
from rulehall.engines.pokemon.journey.world import JourneyWorld
from rulehall.engines.pokemon.rules import STAT_NAMES, TIMES
from rulehall.engines.pokemon.sprites import (
    ITEM_SPRITES,
    LOWERED,
    RAISED,
    STAT_COLOUR,
    ability_tag,
    hp_meter,
    item_sprite,
    move_tag,
    nature_arrows,
    nature_tag,
    nature_text,
    status_tag,
    type_tag,
)

type StatLine = tuple[str, int, str]
GENDER_SIGNS = {"M": "♂", "F": "♀", "N": ""}
ITEMS_GROUP, LEARN_GROUP, TEAM_GROUP = "Items", "Learn", "Team"
WILD_ICON_PREFIX = "wild-"
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
    "Grows as this Pokemon levels up and as it helps in checks. It sets the help bonus in a "
    "check: "
    + ", ".join(
        f"+{bonus} from {floor}" if floor else f"+{bonus} at first"
        for floor, bonus in reversed(HELP_BONUSES)
    )
    + f". At {FRIENDSHIP_EVOLVE} some species are ready to evolve."
)
TRAINER_HELP = {
    "Legendary": "The legendary Pokemon this trainer guards.",
    "Team": "The Pokemon this trainer battles with.",
    "Double": "This trainer battles two Pokemon at a time.",
    "Style": "How this trainer battles.",
    "Trial": "What this trainer asks before a battle.",
    "Badge": "The badge this trainer gives when beaten.",
    "Beaten": "The player has beaten this trainer.",
}
KIND_TEXT = {
    "ball": "Thrown at a wild Pokemon on the battle screen.",
    "potion": "Restores {heal} HP.",
    "full-heal": "Cures any status.",
    "revive": "Revives a fainted Pokemon with half its HP.",
    "candy": "Raises a Pokemon one level.",
}


def person_rows(trainer: JourneyTrainer) -> PanelRows:
    sheet = trainer.sheet
    if sheet is None:
        legendary_id = trainer.legendary_id
        legendary = "" if legendary_id is None else species_name(legendary_id)
        return (
            *text_rows("Legendary", TRAINER_HELP["Legendary"], legendary),
            *tag_list(
                "Team", TRAINER_HELP["Team"], [Tag(name=slot.text()) for slot in trainer.roster]
            ),
            *text_rows("Double", TRAINER_HELP["Double"], "two-on-two" if trainer.double else ""),
            *text_rows("Style", TRAINER_HELP["Style"], trainer.style),
            *text_rows("Trial", TRAINER_HELP["Trial"], trainer.trial),
            *text_rows("Badge", TRAINER_HELP["Badge"], trainer.badge),
            *text_rows("Beaten", TRAINER_HELP["Beaten"], "yes" if trainer.beaten else ""),
        )
    skills = tuple(
        Score(
            name=skill.title(),
            value=str(sheet.skills.get(skill, 0)),
            help=f"Used to {SKILL_USES[skill]}.",
        )
        for skill in SKILLS
    )
    team = [Tag(name=f"{mon.label()} L{mon.level}", help=mon.summary()) for mon in sheet.team]
    return (
        *score_block("Skills", SHEET_HELP["Skills"], skills),
        PanelRow(name="Money", brief=f"₽{sheet.money}", help=SHEET_HELP["Money"]),
        *_badge_rows(sheet),
        *tag_list("Team", SHEET_HELP["Team"], team),
        *tag_list(
            "Memorial", SHEET_HELP["Memorial"], [Tag(name=fallen) for fallen in sheet.memorial]
        ),
    )


def rival_rows(world: JourneyWorld) -> PanelRows:
    return text_rows("Rival", SHEET_HELP["Rival"], "; ".join(world.rival_ledger.lines))


def team_panel(world: JourneyWorld) -> Panel:
    sheet = world.player_sheet
    usable = [item_id for item_id in _bag_ids(world) if item_of(item_id).kind != "ball"]
    return Panel(
        title="Team",
        rows=tuple(
            mon_row(mon, sheet.level_cap(), mon_options(mon, world, usable)) for mon in sheet.team
        ),
        help=SHEET_HELP["Team"],
        tab="Team",
    )


def box_panel(world: JourneyWorld) -> Panel:
    sheet = world.player_sheet
    return Panel(
        title="Box",
        rows=tuple(mon_row(mon, sheet.level_cap(), box_options(mon, sheet)) for mon in sheet.box),
        help="Pokemon kept in storage, off the team; swap them in from here.",
        tab="Team",
    )


def bag_panel(world: JourneyWorld) -> Panel:
    sheet = world.player_sheet
    return Panel(
        title="Bag",
        rows=(
            *(bag_row(item_id, world) for item_id in _bag_ids(world)),
            PanelRow(name="Money", brief=f"₽{sheet.money}", help=SHEET_HELP["Money"]),
            *_badge_rows(sheet),
        ),
        help="Your items: use one on a Pokemon from its row; balls are thrown in battle.",
        tab="Team",
    )


def scheme_panel(world: JourneyWorld) -> Panel | None:
    evil_team = world.evil_team
    scheme = evil_team.scheme
    if scheme is None or not any(world.npcs[leader_id].known for leader_id in evil_team.leader_ids):
        return None
    operation = evil_team.operation
    shown = (
        ("Stage", f"{evil_team.stage()}/{SCHEME_STAGES}"),
        ("Foiled", str(evil_team.foiled())),
        ("Succeeded", str(evil_team.succeeded())),
        *(() if operation is None else (("Now", operation.goal),)),
    )
    rows = tuple(PanelRow(name=name, brief=brief, help=SCHEME_HELP[name]) for name, brief in shown)
    help_text = "The evil team's scheme: stop each operation by beating its leader."
    return Panel(title=scheme.name, rows=rows, help=help_text)


def wild_panel(world: JourneyWorld) -> Panel | None:
    slots = world.wild.get(world.current.id, ())
    if not slots:
        return None
    total = sum(slot.weight for slot in slots)
    species = dex().species
    rows = tuple(
        PanelRow(
            name=species[slot.species_id].name,
            brief=f"L{slot.lowest}-{slot.highest} · {round(100 * slot.weight / total)}%",
            icon_id=f"{WILD_ICON_PREFIX}{slot.species_id}",
            options=(
                ActionOption(
                    id=f"wild-{slot.species_id}",
                    name=f"Battle {species[slot.species_id].name}",
                    action_name="battle_wild",
                    args={"species_id": slot.species_id},
                    refusal=world.wild_pick_refusal(slot.species_id),
                ),
            ),
        )
        for slot in slots
    )
    search = PanelRow(
        name="Search the grass",
        brief="Meet a wild Pokemon rolled on this table.",
        options=(
            ActionOption(
                id="wild-search",
                name="Search the grass",
                action_name="battle_wild",
                args={"species_id": None},
            ),
        ),
    )
    return Panel(
        title="Wild here",
        rows=(*rows, search),
        help="The wild Pokemon of this place: battle one, or search the grass for a random one.",
    )


def pending_decision(sheet: JourneySheet) -> Decision | None:
    return _learning_decision(sheet) or _evolution_decision(sheet) or _rank_decision(sheet)


def mon_row(mon: Mon, cap: int, options: tuple[ActionOption, ...] = ()) -> PanelRow:
    stat_lines = _stat_lines(mon)
    lines = stat_lines[1:]
    top = max(value for _, value, _ in lines)
    status = "fnt" if mon.fainted else mon.status
    return PanelRow(
        name=f"{mon.label()} {GENDER_SIGNS[mon.gender]}".rstrip(),
        brief="",
        icon_id=mon.mon_id,
        tags=(
            Tag(name=f"Lv{mon.level}"),
            *((_cap_tag(cap),) if cap < LEVEL_MAX and mon.level >= cap else ()),
            *(type_tag(kind) for kind in mon.species.types),
            *((status_tag(status),) if status else ()),
            nature_tag(mon.nature),
            *(
                ()
                if mon.item_id is None
                else (described_tag(dex().item_name(mon.item_id), item_text(mon.item_id)),)
            ),
            Tag(
                name=f"♥ {mon.friendship} · help +{help_bonus(mon.friendship)}",
                help=FRIENDSHIP_HELP,
            ),
        ),
        lower_tags=tuple(move_tag(slot.move, slot.pp) for slot in mon.moves),
        meters=(
            hp_meter(mon.hp.current, mon.hp.maximum),
            *(
                Meter(name=name, current=value, maximum=top, colour=STAT_COLOUR, help=help_text)
                for name, value, help_text in lines
            ),
        ),
        options=options,
        detail=_mon_detail(mon, stat_lines),
    )


def bag_row(item_id: BagId, world: JourneyWorld) -> PanelRow:
    sheet = world.player_sheet
    item = item_of(item_id)
    return PanelRow(
        name=bag_name(item_id),
        brief=item_text(item_id),
        icon_id=item_id,
        tags=(Tag(name=f"{TIMES}{sheet.bag[item_id]}"), Tag(name=POCKETS[item.kind])),
        options=()
        if item.kind == "ball"
        else tuple(item_option(mon, item_id, world) for mon in sheet.team),
    )


def bag_sprite(item_id: BagId) -> Sprite:
    if item_id in ITEMS:
        return item_sprite(item_id)
    return Sprite(path=ITEM_SPRITES / f"tm-{tm_move(item_id).type.lower()}.png")


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


def mon_options(mon: Mon, world: JourneyWorld, bag: list[BagId]) -> tuple[ActionOption, ...]:
    sheet = world.player_sheet
    name = mon.name
    take = (
        ()
        if mon.item_id is None
        else (
            ActionOption(
                id=f"take-{mon.mon_id}",
                name=f"Take the {dex().item_name(mon.item_id)} from {name}",
                action_name="hold_item",
                args={"mon_id": mon.mon_id, "item_id": None},
                group=ITEMS_GROUP,
            ),
        )
    )
    return (
        *take,
        *(item_option(mon, item_id, world) for item_id in bag),
        *(_remember_option(mon, move_id) for move_id in mon.relearnable()),
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


def box_options(boxed: Mon, sheet: JourneySheet) -> tuple[ActionOption, ...]:
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


def item_option(mon: Mon, item_id: BagId, world: JourneyWorld) -> ActionOption:
    item = item_of(item_id)
    name = mon.name
    brief = help_text = ""
    match item.kind:
        case "held":
            label, action_name, group = (
                f"Give the {bag_name(item_id)} to {name}",
                "hold_item",
                ITEMS_GROUP,
            )
        case "tm":
            move = tm_move(item_id)
            label, action_name = f"Teach {move.name} to {name}", "teach_move"
            group = LEARN_GROUP
            brief, help_text = move_brief(move), move.text
        case _:
            label, action_name, group = (
                f"Use the {bag_name(item_id)} on {name}",
                "use_item",
                ITEMS_GROUP,
            )
    return ActionOption(
        id=f"{item_id}-{mon.mon_id}",
        name=label,
        brief=brief,
        help=help_text,
        action_name=action_name,
        args={"mon_id": mon.mon_id, "item_id": item_id},
        group=group,
        refusal=mon.item_refusal(item_id, world.species_ids, world.player_sheet.level_cap()),
    )


def _learning_decision(sheet: JourneySheet) -> Decision | None:
    if not sheet.learning:
        return None
    learning = sheet.learning[0]
    mon = sheet.require_mon(learning.mon_id)
    new_move = dex().moves[learning.move_id]
    description = f": {new_move.text}" if new_move.text else ""
    return Decision(
        kind="new-move",
        prompt=(
            f"{mon.name} wants to learn {new_move.name} ({move_brief(new_move)}){description} "
            f"It knows four moves. Forget one, or skip {new_move.name}?"
        ),
        options=(
            *(
                _learn_option(
                    learning,
                    slot.move_id,
                    f"Forget {slot.move.name}",
                    move_brief(slot.move, slot.pp),
                    slot.move.text,
                )
                for slot in mon.moves
            ),
            _learn_option(
                learning, None, f"Skip {new_move.name}", move_brief(new_move), new_move.text
            ),
        ),
        allows_text=False,
        silent=True,
    )


def _learn_option(
    learning: Learning, forget_id: Slug | None, name: str, brief: str, help_text: str
) -> ActionOption:
    return ActionOption(
        id=forget_id or "skip",
        name=name,
        brief=brief,
        help=help_text,
        action_name="learn_move",
        args={
            "mon_id": learning.mon_id,
            "move_id": learning.move_id,
            "forget_id": forget_id,
        },
    )


def _remember_option(mon: Mon, move_id: Slug) -> ActionOption:
    move = dex().moves[move_id]
    return ActionOption(
        id=f"remember-{mon.mon_id}-{move_id}",
        name=f"Remember {move.name}",
        brief=move_brief(move),
        help=move.text,
        action_name="relearn_move",
        args={"mon_id": mon.mon_id, "move_id": move_id},
        group=LEARN_GROUP,
    )


def _evolution_decision(sheet: JourneySheet) -> Decision | None:
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


def _rank_decision(sheet: JourneySheet) -> Decision | None:
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
        silent=True,
    )


def _cap_tag(cap: int) -> Tag:
    return Tag(
        name="Cap", help=f"At the level cap, L{cap}: no more EXP until the next badge lifts it."
    )


def _badge_rows(sheet: JourneySheet) -> PanelRows:
    badges = [Tag(name=badge) for badge in sheet.badges]
    return tag_list("Badges", SHEET_HELP["Badges"], badges) or (
        PanelRow(name="Badges", brief="none", help=SHEET_HELP["Badges"]),
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
                name=dex().item_name(mon.item_id), brief=item_text(mon.item_id), icon_id=mon.item_id
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
                    tags=(ability_tag(mon.ability),),
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
    )


def _pocket_key(item_id: BagId) -> tuple[int, str]:
    return POCKET_ORDER.index(POCKETS[item_of(item_id).kind]), bag_name(item_id)


def _bag_ids(world: JourneyWorld) -> list[BagId]:
    return sorted(world.player_sheet.bag, key=_pocket_key)
