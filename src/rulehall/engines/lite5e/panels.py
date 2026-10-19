from collections.abc import Sequence

from pydantic import JsonValue

from rulehall.core.decisions import ActionOption, Decision, Option
from rulehall.core.validation import Slug
from rulehall.core.views import Meter, Panel, PanelRow, PanelRows, Score, Tag
from rulehall.engines.lite5e.args import GearUseKind
from rulehall.engines.lite5e.data import (
    Ability,
    Armor,
    FeatureUse,
    Gear,
    MagicItem,
    Weapon,
    srd,
)
from rulehall.engines.lite5e.rules import (
    ABILITIES,
    FONT_OF_MAGIC,
    LAY_ON_HANDS,
    LAY_ON_HANDS_CURE,
    MADE_SLOT_COST,
    MADE_SLOT_SORCERER_LEVEL,
    MAX_LEVEL,
    MAX_SCORE,
    SKILL_ABILITY,
    XP_FOR_LEVEL,
    FormationRow,
    skill_name,
)
from rulehall.engines.lite5e.sheet import (
    LevelPickKind,
    Lite5ePerson,
    Lite5eSheet,
    equip_slot,
    gear_name,
    is_drinkable,
    level_pick_rules,
)
from rulehall.engines.lite5e.world import Lite5eWorld, coins_text
from rulehall.engines.panels import (
    character_panel,
    described_tag,
    first_sentence,
    gauge_row,
    score_block,
    tag_list,
    text_rows,
)
from rulehall.engines.panels import party_panel as shared_party_panel

type Args = dict[str, JsonValue]
DONE_ID: Slug = "done"
SHEET_HELP = {
    "Class": "The class and its level. Levels run from 1 to 5.",
    "Background": "Where the character came from: its feat, skills and tool.",
    "HP": "Damage comes off temporary HP first, then HP. A fight or a rest changes it.",
    "Abilities": "The six ability scores, each with its modifier. A save proficiency adds the "
    "proficiency bonus to that saving throw.",
    "Defense": "Armor Class, proficiency bonus, passive Perception and, for a caster, the spell "
    "save DC.",
    "Skills": "The skills this character is trained in, with the check bonus. Expertise doubles "
    "the proficiency bonus.",
    "Resources": "Uses left of each limited resource.",
    "Hit Dice": "Spent on a short rest to heal. A long rest gives them all back.",
    "Heroic Inspiration": "Rerolls one failed check or attack roll, then it is spent.",
    "Spell slots": "Slots left of each spell level. A long rest gives them all back.",
    "Cantrips": "Spells cast at will.",
    "Prepared": "The spells ready to cast. They change after a long rest or a level up.",
    "Spellbook": "The Wizard's written spells. The Wizard prepares from them.",
    "Metamagic": "The Sorcerer's Metamagic options. Each is a variant of a spell in a battle.",
    "Coins": "The party's coins, shared by all.",
    "XP": "Experience of the party. Each level needs more than the one before.",
    "Stat block": "A companion who fights with the numbers of its stat block.",
    "Price": "What the shop asks for it. A shop pays half.",
    "Row": "The row this member starts a battle in. The front row fights in melee.",
}
LEVEL_UP = "level-up"
FORMATION_ROWS: tuple[FormationRow, ...] = ("front", "back")


def sheet_panel(world: Lite5eWorld) -> Panel:
    player = world.player
    sheet = player.require_sheet()
    upcoming = (
        f"{sheet.xp} of {XP_FOR_LEVEL[sheet.level + 1]}" if sheet.level < MAX_LEVEL else "top"
    )
    return character_panel(
        player.subject(),
        (
            *_member_rows(world, player),
            _coins_row(sheet),
            PanelRow(name="XP", brief=upcoming, help=SHEET_HELP["XP"]),
        ),
    )


def party_panel(world: Lite5eWorld) -> Panel | None:
    return shared_party_panel(
        world.hired_party_members(), lambda member: _member_rows(world, member)
    )


def gear_panel(world: Lite5eWorld) -> Panel:
    members = [member for member in world.members() if member.sheet is not None]
    rows: list[PanelRow] = []
    for member in members:
        sheet = member.require_sheet()
        others = [other for other in members if other.id != member.id]
        for gear_id, count in sheet.gear.items():
            rows.append(_gear_row(member, sheet, gear_id, count, others))
    return Panel(
        title="Gear",
        rows=tuple(rows),
        help="What each member carries. Tap a row to equip, drink, give or drop it.",
        tab="Gear",
    )


def person_rows(person: Lite5ePerson, world: Lite5eWorld | None = None) -> PanelRows:
    sheet = person.sheet
    if sheet is None:
        block = person.stat_block()
        return (
            PanelRow(
                name="Stat block",
                brief=f"{block.name}, CR {block.challenge_rating}",
                help=SHEET_HELP["Stat block"],
            ),
            _hp_row(person),
        )
    return (
        *text_rows("Class", SHEET_HELP["Class"], f"{sheet.srd_class().name} {sheet.level}"),
        *tag_list("Species", "", [_species_tag(sheet)]),
        *tag_list(
            "Background",
            SHEET_HELP["Background"],
            [
                described_tag(
                    sheet.background_name,
                    sheet.background_brief,
                    stat_line=_background_grants(sheet),
                )
            ],
        ),
        _hp_row(person),
        *score_block("Abilities", SHEET_HELP["Abilities"], _ability_scores(sheet)),
        *score_block("Defense", SHEET_HELP["Defense"], _defense_scores(sheet)),
        *score_block("Resources", SHEET_HELP["Resources"], _resource_scores(sheet)),
        *_slot_rows(sheet),
        *_lay_on_hands_rows(person, world),
        *_font_of_magic_rows(person),
        *_spell_rows(sheet),
        *_trait_rows(sheet),
    )


def kit_rows(sheet: Lite5eSheet) -> PanelRows:
    gear = [_gear_tag(gear_id, count) for gear_id, count in sheet.gear.items()]
    return (*tag_list("Gear", "", gear), _coins_row(sheet))


def pending_decision(world: Lite5eWorld) -> Decision | None:
    members = [member for member in world.members() if member.sheet is not None]
    for member in members:
        if (decision := _level_pick_decision(member)) is not None:
            return decision
    if world.hit_dice_due and (decision := _hit_dice_decision(members)) is not None:
        return decision
    if world.prepare_due:
        return _prepare_decision(members)
    return None


def level_pick_option(sheet: Lite5eSheet, kind: LevelPickKind, pick_id: Slug) -> Option:
    rule = level_pick_rules()[kind]
    spell = rule.vocabulary == "spell" and rule.replaces is None
    return Option(
        id=pick_id,
        name=sheet.level_pick_name(kind, pick_id),
        brief=srd().require_spell(pick_id).brief() if spell else "",
    )


def use_source(sheet: Lite5eSheet, use: FeatureUse) -> tuple[str, str]:
    options = srd().character_options
    source_id = options.feature_uses[use].source_id or f"{sheet.class_id}-{use}"
    traits = [trait for trait in sheet.traits() if use in trait.trait_id]
    source = options.features.get(source_id) or options.feats.get(source_id) or traits[0]
    return source.name, source.description


def _spell_tag(spell_id: Slug) -> Tag:
    spell = srd().require_spell(spell_id)
    return described_tag(spell.name, spell.description, stat_line=spell.brief())


def _gear_tag(gear_id: Slug, count: int = 1) -> Tag:
    return Tag(
        name=gear_name(gear_id) + (f" x{count}" if count > 1 else ""),
        help=_gear_summary(gear_id),
        detail=_gear_text(gear_id),
    )


def _gear_summary(gear_id: Slug) -> str:
    item = srd().require_gear(gear_id)
    match item:
        case Weapon() | Armor() | MagicItem(base_armor_id=str()):
            return _gear_stats(gear_id)
        case MagicItem():
            return first_sentence(item.description)
        case Gear() if item.description:
            return first_sentence(item.description)
        case Gear() if item.ability is not None:
            return f"A tool for {item.ability.title()} checks."
        case Gear():
            return f"{item.group.replace('-', ' ').capitalize()}."


def _gear_stats(gear_id: Slug) -> str:
    item = srd().require_gear(gear_id)
    match item:
        case Weapon():
            return _weapon_summary(item)
        case Armor():
            return _armor_summary(item)
        case MagicItem(base_armor_id=str(base_id)):
            return f"{_armor_summary(srd().gear.armor[base_id])}, +{item.bonus} AC"
        case MagicItem() | Gear():
            return ""


def _weapon_summary(weapon: Weapon) -> str:
    parts = [weapon.damage.text()]
    if weapon.versatile_damage is not None:
        parts.append(f"versatile {weapon.versatile_damage.dice}")
    parts.extend(found.replace("-", " ") for found in weapon.properties if found != "versatile")
    reach = weapon.thrown_range if weapon.kind == "melee" else weapon.range
    if reach is not None and reach.long is not None:
        parts.append(f"range {reach.normal}/{reach.long} ft")
    if weapon.magic_bonus:
        parts.append(f"+{weapon.magic_bonus} to attack and damage")
    return f"{weapon.category.title()} {weapon.kind} weapon: {', '.join(parts)}."


def _armor_summary(armor: Armor) -> str:
    if armor.category == "shield":
        return f"Shield: +{armor.base_ac} AC"
    dexterity = (
        " + Dex"
        if armor.dex_cap is None
        else f" + Dex (max {armor.dex_cap})"
        if armor.dex_cap
        else ""
    )
    stealth = ", Stealth disadvantage" if armor.stealth_disadvantage else ""
    return f"{armor.category.title()} armor: AC {armor.base_ac}{dexterity}{stealth}"


def _species_tag(sheet: Lite5eSheet) -> Tag:
    species = srd().character_options.species[sheet.species_id]
    name = species.name
    if sheet.subspecies_id is not None:
        name = f"{name} ({species.subspecies[sheet.subspecies_id].name})"
    return described_tag(
        name,
        f"Speed {species.speed} ft.",
        stat_line=", ".join(trait.name for trait in sheet.traits()),
    )


def _background_grants(sheet: Lite5eSheet) -> str:
    increases = " ".join(
        f"+{amount} {ability[:3].upper()}" for ability, amount in sheet.background_increases.items()
    )
    return " · ".join(
        (
            f"Skills {', '.join(skill_name(skill) for skill in sheet.background_skills)}",
            f"Tool {gear_name(sheet.background_tool_id)}",
            f"Feat {srd().character_options.feats[sheet.background_feat_id].name}",
            increases,
        )
    )


def _score_breakdown(sheet: Lite5eSheet, ability: Ability) -> str:
    parts = " + ".join(
        f"{amount} {label}" + (f" ({sheet.background_name})" if label == "background" else "")
        for label, amount in sheet.score_parts(ability)
    )
    return f"{sheet.score(ability)} = {parts} (max {MAX_SCORE})."


def _ability_scores(sheet: Lite5eSheet) -> tuple[Score, ...]:
    saves = sheet.srd_class().saving_throws
    scores: list[Score] = []
    for ability in ABILITIES:
        modifier = sheet.modifier(ability)
        save = sheet.save_bonus(ability)
        proficient = ability in saves
        breakdown = _score_breakdown(sheet, ability)
        scores.append(
            Score(
                name=ability[:3].upper(),
                value=str(sheet.score(ability)),
                note=f"{modifier:+d} · save {save:+d}" if proficient else f"{modifier:+d}",
                help=f"{breakdown} Modifier {modifier:+d}. "
                f"Saving throw {save:+d}{', proficient' if proficient else ''}.",
                detail=breakdown,
            )
        )
    return tuple(scores)


def _defense_scores(sheet: Lite5eSheet) -> tuple[Score, ...]:
    spell_ability = sheet.srd_class().spell_ability
    return (
        Score(
            name="AC",
            value=str(sheet.armor_class()),
            note="armor class",
            help="The number an attack roll must reach to hit.",
        ),
        Score(
            name="Prof",
            value=f"{sheet.proficiency_bonus():+d}",
            note="bonus",
            help="Added to the rolls this character is proficient in.",
        ),
        Score(
            name="Passive",
            value=str(sheet.passive_perception("bright")),
            note="perception",
            help="Perception without a roll, in bright light. A hidden creature must beat it.",
        ),
        *(
            ()
            if spell_ability is None
            else (
                Score(
                    name="Spell DC",
                    value=str(sheet.feature_dc(spell_ability)),
                    note=spell_ability[:3].upper(),
                    help="The DC a target's saving throw must reach against this caster's spells.",
                ),
            )
        ),
    )


def _resource_scores(sheet: Lite5eSheet) -> tuple[Score, ...]:
    notes: dict[FeatureUse, str] = {
        "bardic-inspiration": _bardic_die(sheet),
        "sorcery-points": _made_slots(sheet),
    }
    return (
        Score(
            name="Hit Dice",
            value=f"{sheet.hit_dice_left()}/{sheet.level}",
            note=f"d{sheet.srd_class().hit_die}",
            help=SHEET_HELP["Hit Dice"],
        ),
        Score(
            name="Heroic Inspiration",
            value=f"{int(sheet.inspiration)}/1",
            help=SHEET_HELP["Heroic Inspiration"],
        ),
        *(
            _use_score(sheet, use, notes.get(use, ""))
            for use in srd().character_options.feature_uses
            if use != "lay-on-hands" and sheet.use_limit(use)
        ),
    )


def _slot_rows(sheet: Lite5eSheet) -> PanelRows:
    slot_totals = sheet.class_level().slots
    if slot_totals is None:
        return ()
    meters = tuple(
        Meter(
            name=f"L{level}",
            current=sheet.slots_left(level),
            maximum=sheet.slot_maximum(level),
            look="pips",
        )
        for level, total in enumerate(slot_totals, 1)
        if total
    )
    if not meters:
        return ()
    return (PanelRow(name="Spell slots", brief="", help=SHEET_HELP["Spell slots"], meters=meters),)


def _use_score(sheet: Lite5eSheet, use: FeatureUse, note: str) -> Score:
    name, text = use_source(sheet, use)
    return Score(
        name=name,
        value=f"{sheet.uses_left(use)}/{sheet.use_limit(use)}",
        note=note,
        help=first_sentence(text),
        detail=text,
    )


def _spell_rows(sheet: Lite5eSheet) -> PanelRows:
    lists: tuple[tuple[str, Sequence[Slug]], ...] = (
        ("Cantrips", sheet.class_cantrip_ids()),
        ("Prepared", sheet.all_prepared_ids()),
        ("Spellbook", sheet.spellbook_ids()),
        ("Magic Initiate", sheet.initiate_spell_ids()),
        ("Lineage spells", sheet.lineage_spell_ids()),
    )
    return tuple(
        row
        for name, spell_ids in lists
        for row in tag_list(
            name, SHEET_HELP.get(name, ""), [_spell_tag(found) for found in spell_ids]
        )
    )


def _trait_rows(sheet: Lite5eSheet) -> PanelRows:
    metamagic = srd().character_options.metamagic
    return (
        *tag_list("Skills", SHEET_HELP["Skills"], _skill_tags(sheet)),
        *tag_list("Tools", "", [_gear_tag(tool_id) for tool_id in sheet.tool_ids()]),
        *tag_list(
            "Feats", "", [described_tag(feat.name, feat.description) for feat in sheet.feats()]
        ),
        *tag_list(
            "Features",
            "",
            [
                described_tag(boon.name, boon.description)
                for boon in (*sheet.features(), *sheet.class_options())
            ],
        ),
        *tag_list(
            "Species traits",
            "",
            [described_tag(trait.name, trait.description) for trait in sheet.traits()],
        ),
        *_invocation_rows(sheet),
        *tag_list(
            "Metamagic",
            SHEET_HELP["Metamagic"],
            [
                described_tag(
                    metamagic[found].name,
                    metamagic[found].description,
                    stat_line=f"{metamagic[found].cost} Sorcery Points",
                )
                for found in sheet.metamagic_ids()
            ],
        ),
    )


def _skill_tags(sheet: Lite5eSheet) -> list[Tag]:
    glossary = srd().character_options.skills
    expertise = sheet.pick_ids("expertise")
    tags: list[Tag] = []
    for skill in sheet.skills():
        ability = SKILL_ABILITY[skill]
        bonus = sheet.check_bonus(ability, skill, None)
        expert = ", expertise" if skill in expertise else ""
        tags.append(
            described_tag(
                f"{skill_name(skill)} {bonus:+d}",
                glossary[skill].description,
                stat_line=f"{ability.title()}{expert}",
            )
        )
    return tags


def _invocation_rows(sheet: Lite5eSheet) -> PanelRows:
    tags = [
        described_tag(invocation.name, invocation.description) for invocation in sheet.invocations()
    ]
    if not tags:
        return ()
    pact_weapon_id = sheet.find_pick("pact-weapon")
    brief = "" if pact_weapon_id is None else f"Pact weapon: {gear_name(pact_weapon_id)}"
    return (PanelRow(name="Invocations", brief=brief, tags=tuple(tags)),)


def _gear_text(gear_id: Slug) -> str:
    item = srd().require_gear(gear_id)
    return item.description if isinstance(item, Gear | MagicItem) else ""


def _hp_row(member: Lite5ePerson) -> PanelRow:
    gauge = member.require_vitals().hp
    temporary = 0 if member.sheet is None else member.sheet.temp_hp
    return PanelRow(
        name="HP",
        brief=f"+{temporary} temporary" if temporary else "",
        help=SHEET_HELP["HP"],
        meters=(Meter(name="", current=gauge.current, maximum=gauge.maximum),),
        tags=_condition_tags(member),
    )


def _condition_tags(member: Lite5ePerson) -> tuple[Tag, ...]:
    glossary = srd().character_options.conditions
    exhaustion = 0 if member.sheet is None else member.sheet.exhaustion
    held = [glossary[held.condition] for held in member.conditions]
    exhausted = (
        (described_tag(f"Exhaustion {exhaustion}", glossary["exhaustion"].description),)
        if exhaustion
        else ()
    )
    return (*(described_tag(entry.name, entry.description) for entry in held), *exhausted)


def _member_rows(world: Lite5eWorld, member: Lite5ePerson) -> PanelRows:
    return (*person_rows(member, world), _formation_row(member))


def _coins_row(sheet: Lite5eSheet) -> PanelRow:
    return PanelRow(name="Coins", brief=coins_text(sheet.coins_cp), help=SHEET_HELP["Coins"])


def _formation_row(member: Lite5ePerson) -> PanelRow:
    return PanelRow(
        name="Row",
        brief=f"{member.formation_row.title()} row",
        help=SHEET_HELP["Row"],
        options=tuple(
            ActionOption(
                id=f"row-{member.id}-{row}",
                name=f"{row.title()} row",
                action_name="set_formation_row",
                args={"actor_id": member.id, "row": row},
                refusal="" if row != member.formation_row else f"{member.name} is there now",
            )
            for row in FORMATION_ROWS
        ),
    )


def _lay_on_hands_rows(member: Lite5ePerson, world: Lite5eWorld | None) -> PanelRows:
    sheet = member.require_sheet()
    if LAY_ON_HANDS not in sheet.feature_ids():
        return ()
    pool = sheet.uses_left("lay-on-hands")
    options: list[ActionOption] = []
    for target in () if world is None else world.members():
        vitals = target.vitals
        if vitals is not None and vitals.hp.shortfall:
            refusal = "" if pool else "the pool is empty"
            options.append(_lay_on_hands_option(member, target, cure=False, refusal=refusal))
        if target.has_condition("poisoned"):
            short = f"the pool holds less than {LAY_ON_HANDS_CURE}"
            refusal = "" if pool >= LAY_ON_HANDS_CURE else short
            options.append(_lay_on_hands_option(member, target, cure=True, refusal=refusal))
    return (
        gauge_row(
            "Lay On Hands",
            _feature_help(LAY_ON_HANDS),
            pool,
            sheet.use_limit("lay-on-hands"),
            look="pips",
            options=options,
        ),
    )


def _lay_on_hands_option(
    member: Lite5ePerson, target: Lite5ePerson, *, cure: bool, refusal: str
) -> ActionOption:
    verb = "cure" if cure else "heal"
    name = f"End Poisoned on {target.name}" if cure else f"Heal {target.name}"
    return ActionOption(
        id=f"lay-on-hands-{member.id}-{verb}-{target.id}",
        name=name,
        action_name="lay_on_hands",
        args={"actor_id": member.id, "target_id": target.id, "cure": cure},
        refusal=refusal,
    )


def _font_of_magic_rows(member: Lite5ePerson) -> PanelRows:
    sheet = member.require_sheet()
    if FONT_OF_MAGIC not in sheet.feature_ids():
        return ()
    options = tuple(
        ActionOption(
            id=f"font-of-magic-{member.id}-{slot_level}",
            name=f"A level {slot_level} slot for {cost} points",
            action_name="font_of_magic",
            args={"actor_id": member.id, "slot_level": slot_level},
            refusal=sheet.font_of_magic_refusal(slot_level),
        )
        for slot_level, cost in MADE_SLOT_COST.items()
        if sheet.level >= MADE_SLOT_SORCERER_LEVEL[slot_level]
    )
    return (
        PanelRow(
            name="Font of Magic",
            brief="Sorcery Points into a spell slot",
            help=_feature_help(FONT_OF_MAGIC),
            options=options,
        ),
    )


def _gear_row(
    member: Lite5ePerson,
    sheet: Lite5eSheet,
    gear_id: Slug,
    count: int,
    others: Sequence[Lite5ePerson],
) -> PanelRow:
    equipped = gear_id in sheet.equipped_ids
    options: list[ActionOption] = []
    args: Args = {"actor_id": member.id, "gear_id": gear_id}
    if equipped:
        options.append(_use_option("unequip", member, gear_id, "Unequip", args))
    elif equip_slot(gear_id) is not None:
        untrained = "" if sheet.is_trained_to_wear(gear_id) else f"{member.name} lacks the training"
        options.append(_use_option("equip", member, gear_id, "Equip", args, refusal=untrained))
    if is_drinkable(gear_id):
        options.append(_use_option("drink", member, gear_id, "Drink", args))
    options.extend(
        ActionOption(
            id=f"give-{member.id}-{gear_id}-{other.id}",
            name=f"Give to {other.name}",
            action_name="give",
            args={**args, "to_id": other.id},
        )
        for other in others
    )
    options.append(_use_option("drop", member, gear_id, "Drop here", args))
    item = srd().require_gear(gear_id)
    bundle = f" per {item.bundle}" if isinstance(item, Gear) and item.bundle > 1 else ""
    price = PanelRow(
        name="Price", brief=coins_text(item.cost.copper()) + bundle, help=SHEET_HELP["Price"]
    )
    stats = _gear_stats(gear_id)
    return PanelRow(
        name=gear_name(gear_id),
        brief=f"{member.name} · x{count}" + (" · equipped" if equipped else ""),
        help=_gear_summary(gear_id),
        options=tuple(options),
        detail=(
            Panel(
                title=gear_name(gear_id),
                rows=(
                    *((PanelRow(name="Stats", brief=stats),) if stats else ()),
                    price,
                    *text_rows("About", "", _gear_text(gear_id)),
                ),
            ),
        ),
    )


def _use_option(
    kind: GearUseKind,
    member: Lite5ePerson,
    gear_id: Slug,
    name: str,
    args: Args,
    *,
    refusal: str = "",
) -> ActionOption:
    return ActionOption(
        id=f"{kind}-{member.id}-{gear_id}",
        name=name,
        action_name="use_gear",
        args={**args, "kind": kind},
        refusal=refusal,
    )


def _feature_help(feature_id: Slug) -> str:
    return first_sentence(srd().character_options.features[feature_id].description)


def _bardic_die(sheet: Lite5eSheet) -> str:
    die = sheet.class_level().class_specific.bardic_inspiration_die
    return "" if die is None else f"d{die}"


def _made_slots(sheet: Lite5eSheet) -> str:
    made = ", ".join(f"L{level} {count}" for level, count in sheet.made_slots.items() if count)
    return f"made slots {made}" if made else ""


def _level_pick_decision(member: Lite5ePerson) -> Decision | None:
    sheet = member.require_sheet()
    kind = sheet.find_level_pick_kind()
    if kind is None:
        return None
    picks = (level_pick_option(sheet, kind, pick_id) for pick_id in sheet.level_pick_options(kind))
    left = sheet.picks_left(kind)
    return Decision(
        kind=LEVEL_UP,
        prompt=f"{member.name}, {level_pick_rules()[kind].label()}: pick one"
        + (f" ({left} left)." if left > 1 else "."),
        options=tuple(
            ActionOption(
                id=f"level-pick-{member.id}-{kind}-{pick.id}",
                name=pick.name,
                brief=pick.brief,
                action_name="level_pick",
                args={"actor_id": member.id, "kind": kind, "pick_id": pick.id},
            )
            for pick in picks
        ),
        allows_text=False,
    )


def _hit_dice_decision(members: Sequence[Lite5ePerson]) -> Decision | None:
    options = tuple(
        ActionOption(
            id=f"spend-hit-die-{member.id}",
            name=f"{member.name}: spend a Hit Die",
            brief=f"d{sheet.srd_class().hit_die}, {sheet.hit_dice_left()} left, "
            f"HP {sheet.vitals.hp}",
            action_name="spend_hit_die",
            args={"actor_id": member.id},
        )
        for member in members
        if (sheet := member.require_sheet()).hit_dice_left() > 0
        and sheet.vitals.hp.current < sheet.vitals.hp.maximum
    )
    if not options:
        return None
    return Decision(
        kind="hit-dice",
        prompt="Short rest. Spend a Hit Die to heal, as often as you like, then finish.",
        options=(*options, _done()),
        allows_text=False,
    )


def _prepare_decision(members: Sequence[Lite5ePerson]) -> Decision | None:
    casters = [member for member in members if member.require_sheet().changes_all_prepared()]
    if not casters:
        return None
    return Decision(
        kind="prepare",
        prompt="Long rest. Drop a prepared spell to swap it, or finish.",
        options=(
            *(
                _unprepare_option(member, spell_id)
                for member in casters
                for spell_id in member.require_sheet().pick_ids("prepared")
            ),
            _done(),
        ),
        allows_text=False,
    )


def _unprepare_option(member: Lite5ePerson, spell_id: Slug) -> ActionOption:
    return ActionOption(
        id=f"unprepare-{member.id}-{spell_id}",
        name=f"{member.name}: drop {srd().require_spell(spell_id).name}",
        brief=srd().require_spell(spell_id).brief(),
        action_name="unprepare",
        args={"actor_id": member.id, "drop_id": spell_id},
    )


def _done() -> ActionOption:
    return ActionOption(id=DONE_ID, name="Done", action_name="finish_rest", args={})
