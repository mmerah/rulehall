from collections import Counter
from collections.abc import Sequence
from typing import Literal

from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.core.views import Meter, Sprite, Tag
from rulehall.engines.lite5e.battle.actions import (
    DONE,
    SLOT,
    TARGET,
    Aim,
    member_aims,
    offered_rows,
)
from rulehall.engines.lite5e.battle.attack import advantage_of
from rulehall.engines.lite5e.battle.foes import (
    HOLD,
    MULTIATTACK,
    Plan,
    bonus_plans_of,
    health_band,
    plans_of,
)
from rulehall.engines.lite5e.battle.rows import row_of
from rulehall.engines.lite5e.battle.specs import ActionSpec, spell_action
from rulehall.engines.lite5e.battle.spells import QUICKENED, fitting_metamagic, split_variant
from rulehall.engines.lite5e.battle.state import (
    Combatant,
    Fight,
    FoeCombatant,
    MemberCombatant,
    Phase,
    Side,
)
from rulehall.engines.lite5e.battle.turns import current_combatant, require_member_turn
from rulehall.engines.lite5e.battle.variants import require_strike_variant
from rulehall.engines.lite5e.data import (
    ActionVerb,
    BattleActionRow,
    DamagePart,
    FeatureUse,
    MetamagicId,
    srd,
    stat_block_sprite,
)
from rulehall.engines.lite5e.panels import use_source
from rulehall.engines.lite5e.rules import (
    HUNTER,
    HUNTERS_MARK,
    MADE_SLOT_COST,
    Edge,
    FormationRow,
)
from rulehall.engines.lite5e.sheet import Lite5eSheet
from rulehall.engines.panels import first_sentence
from rulehall.engines.sheet import PLAYER_ID

type BattleChoiceKind = Literal[
    "action",
    "variant",
    "plan",
    "bonus",
    "target",
    "slot",
    "move",
    "back",
    "done",
    "end",
    "next",
    "surrender",
]
type AimKind = Literal["action", "variant", "bonus"]
type ChoiceCategory = Literal["spells", "attacks", "actions", "bonus", "items", "turn", "step"]

ACT: ActionVerb = "act"
BONUS: ActionVerb = "bonus"
PLAN = "plan"
MOVE = "move"
BACK = "back"
END = "end"
NEXT = "next"
AUTO = "auto"
SURRENDER = "surrender"
OVER = "The battle is over"
ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}
ITEM_ROW_IDS = frozenset({"thrown", "potions", "healers-kit"})
FONT_OF_MAGIC = "font-of-magic"
SPELLS = "spells"
WILD_SHAPE = "wild-shape"
SORCERY_POINTS: FeatureUse = "sorcery-points"
EDGE_BRIEFS: dict[Edge, str] = {"none": "", "advantage": "Adv", "disadvantage": "Dis"}
SHOVE_HELP = (
    "In place of one attack, the target saves or falls Prone, or is pushed to its back row."
)
ROW_HELP: dict[str, str] = {
    "dodge": "Until your next turn, attacks against you have Disadvantage "
    "and you make Dexterity saves with Advantage.",
    "disengage": "Your row change this turn draws no opportunity attack.",
    "dash": "Leave the battle from your back row; the foes do not pursue.",
    "hide": "Back row with cover: Stealth vs DC 15 → Invisible until you attack or cast (V).",
    "escape": "Try to break free of a hold on you.",
    "douse": "Put out the flames burning on you.",
    "help": "Help an ally: it has Advantage on its next attack roll or ability check.",
    "shove-prone": SHOVE_HELP,
    "shove-push": SHOVE_HELP,
    "demand": "Intimidation vs a beaten group (one down or under half HP). Once per group.",
    "weapons": "Attack with a weapon you hold.",
    "off-hand": "After a Light melee attack, attack with your other Light weapon.",
    "thrown": "Throw a flask at a foe; it saves against its effect.",
    "potions": "Drink a potion, or give a healing potion to an ally beside you.",
    "healers-kit": "Stabilize a dying ally beside you.",
    "action-surge": "Take one more action this turn.",
    "sacred-weapon": "Add your Charisma modifier to your weapon attack rolls for a while.",
    "breath-weapon": "Exhale destructive energy: each creature in the area saves for half.",
    "divine-spark": "Deal radiant or necrotic damage to a foe, or heal an ally.",
    "turn-undead": "Undead near you save or flee, Frightened and Incapacitated.",
    "preserve-life": "Heal bloodied allies near you, up to half their HP.",
    "lands-aid": "Damage the foes in an area and heal the weakest ally.",
    "second-wind": "Regain HP: 1d10 plus your Fighter level.",
    "steady-aim": "Your next attack this turn has Advantage; you do not move.",
    "adrenaline-rush": "Dash and gain temporary HP.",
    "clouds-jaunt": "Teleport a short distance.",
    "large-form": "Grow to Large size for a while.",
    "rage": "Rage: extra melee damage and resistance to weapon damage.",
    "lay-on-hands": "Heal an ally beside you from your pool, or spend 5 to cure poison.",
    "bardic-inspiration": "Give an ally an Inspiration die to add to a roll.",
    "jeer": "Spend Bardic Inspiration to mock a foe.",
    "wild-shape": "Take a beast's form and gain temporary HP.",
    "flurry-of-blows": "Spend 1 Focus Point: two unarmed strikes.",
    "patient-defense": "Disengage; spend 1 Focus Point to also Dodge.",
    "step-of-the-wind": "Dash from your back row; spend 1 Focus Point to also Disengage.",
    "innate-sorcery": "Your spell save DC rises by 1 and your spell attacks have Advantage.",
    "pact-weapon": "Conjure your pact weapon into your hand.",
    "wild-shape-end": "Return to your own form.",
    "martial-arts": "Make one unarmed strike.",
    "font-of-magic": "Spend Sorcery Points to make a spell slot.",
    "attack": "Attack with one of the stat block's entries.",
}
ROW_GIST: dict[str, str] = {
    "dodge": "Foes have Dis",
    "disengage": "Safe row change",
    "dash": "Flee from back",
    "hide": "Stealth DC 15",
    "escape": "Break free",
    "douse": "Put out flames",
    "help": "Ally gets Adv",
    "shove-prone": "Prone or push",
    "shove-push": "Prone or push",
    "demand": "Force surrender",
    "healers-kit": "Stabilize",
    "potions": "Heal",
    "action-surge": "One more action",
    "sacred-weapon": "Charisma to hit",
    "breath-weapon": "Area damage",
    "divine-spark": "Harm or heal",
    "turn-undead": "Undead flee",
    "preserve-life": "Heal the bloodied",
    "lands-aid": "Harm and heal",
    "second-wind": "Heal yourself",
    "steady-aim": "Next attack Adv",
    "adrenaline-rush": "Dash, temp HP",
    "clouds-jaunt": "Teleport",
    "large-form": "Grow Large",
    "rage": "Enter a rage",
    "lay-on-hands": "Heal by touch",
    "pact-weapon": "Summon weapon",
    "bardic-inspiration": "Inspire an ally",
    "jeer": "Mock a foe",
    "wild-shape": "Beast form",
    "wild-shape-end": "Leave form",
    "patient-defense": "Disengage, dodge",
    "step-of-the-wind": "Dash away",
    "innate-sorcery": "Spells hit harder",
    "font-of-magic": "SP → slot",
    "attack": "Attack",
    MOVE: "Swap rows",
    SURRENDER: "Yield the battle",
}
FAMILY_ROWS: dict[str, str] = {"shove-push": "shove-prone"}
FAMILY_NAMES: dict[str, str] = {
    "shove-prone": "Shove",
    "wild-shape": "Wild Shape",
    "patient-defense": "Patient Defense",
    "step-of-the-wind": "Step of the Wind",
}
ROW_VARIANTS: dict[str, str] = {
    "shove-prone": "Knock prone",
    "shove-push": "Push",
    "lay-on-hands": "Heal",
    "patient-defense": "Disengage",
    "step-of-the-wind": "Dash",
}
MOVE_HELP = (
    "Swap rows. Leaving the front past a front-row foe provokes one attack, unless you Disengaged."
)
SURRENDER_HELP = "Ends the battle as a defeat. Everyone keeps their HP."


class FamilyWay(Frozen):
    variant: str
    commands: tuple[str | None, ...]


class BattleChoice(Frozen):
    command: str
    kind: BattleChoiceKind
    name: str
    variant: str = ""
    option: str = ""
    option_label: str = ""
    options: tuple[str, ...] = ()
    ways: tuple[FamilyWay, ...] = ()
    brief: str = ""
    stats: tuple[str, ...] = ()
    help: str = ""
    rules: str = ""
    category: ChoiceCategory
    level: int | None = None
    family: str = ""
    target_id: Slug | None = None


class CombatantCard(Frozen):
    combatant_id: Slug
    name: str
    sprite: Sprite
    side: Side
    row: FormationRow
    hp: Meter | None = None
    band: Tag | None = None
    tags: tuple[Tag, ...] = ()
    current: bool = False
    auto: bool | None = None
    picked: int = 0


class TurnSlot(Frozen):
    combatant_id: Slug
    name: str
    current: bool


class BudgetView(Frozen):
    action: bool
    bonus: bool
    move: bool
    attacks_left: int


class PoolPips(Frozen):
    name: str
    left: int
    maximum: int
    slot_level: int | None = None
    categories: tuple[ChoiceCategory, ...] = ()


class Lite5eBattleView(Frozen):
    round: int
    phase: Phase
    thinking: bool
    foes: tuple[CombatantCard, ...]
    party: tuple[CombatantCard, ...]
    order: tuple[TurnSlot, ...]
    step: str
    choices: tuple[BattleChoice, ...]
    aiming: str
    repeats: bool
    budget: BudgetView | None
    pools: tuple[PoolPips, ...]

    def offers(self, command: str) -> bool:
        autos = (f"{AUTO} {card.combatant_id}" for card in self.party if card.auto is not None)
        return command in (*(choice.command for choice in self.choices), *autos)


def battle_view(
    fight: Fight, *, live: bool, thinking: bool, aiming: str, picks: Sequence[str]
) -> Lite5eBattleView:
    battle = fight.battle
    current_id = battle.order[battle.turn_index] if live else None
    member = _member_turn(fight) if live else None
    aim = None if member is None or not aiming else require_aim(fight, aiming)
    step, choices = _menu(fight, member, aim, picks) if live else (OVER, ())
    autos = live and aim is None
    picked = Counter(() if aim is None else aim.picked_target_ids(picks))
    sheet = None if member is None else fight.sheet_of(member)
    return Lite5eBattleView(
        round=battle.round,
        phase=battle.phase,
        thinking=thinking,
        foes=tuple(_card(fight, foe, current_id, picked, autos=False) for foe in battle.foes()),
        party=tuple(
            _card(fight, ally, current_id, picked, autos=autos)
            for ally in battle.member_combatants()
        ),
        order=tuple(
            TurnSlot(
                combatant_id=combatant_id,
                name=fight.name_of(combatant),
                current=combatant_id == current_id,
            )
            for combatant_id in battle.order
            if fight.in_battle(combatant := battle.require_combatant(combatant_id))
        ),
        step=step,
        choices=choices,
        aiming="" if aim is None else aiming,
        repeats=aim is not None and aim.repeats,
        budget=None if member is None else _budget(fight, member),
        pools=() if member is None or sheet is None else _pools(fight, member, sheet),
    )


def require_aim(fight: Fight, command: str) -> Aim:
    member = require_member_turn(fight)
    found = next((aim for aim in member_aims(fight, member) if aim.command() == command), None)
    if found is None:
        raise Refusal(f"{command!r} is no pick of {fight.name_of(member)} now")
    return found


def ordinal(number: int) -> str:
    return f"{number}{ORDINAL_SUFFIXES.get(number, 'th')}"


def _member_turn(fight: Fight) -> MemberCombatant | None:
    current = current_combatant(fight)
    if fight.battle.phase == "foes" or not isinstance(current, MemberCombatant):
        return None
    return current


def _can_move(fight: Fight, member: MemberCombatant) -> bool:
    return fight.battle.budget.move and not fight.battle.is_held(member.combatant_id)


def _menu(
    fight: Fight,
    member: MemberCombatant | None,
    aim: Aim | None,
    picks: Sequence[str],
) -> tuple[str, tuple[BattleChoice, ...]]:
    if member is None:
        next_turn = BattleChoice(command=NEXT, kind="next", name="Next turn", category="step")
        return f"{fight.name_of(current_combatant(fight))}'s turn", (next_turn,)
    if aim is not None:
        return _aim_menu(fight, member, aim, picks)
    turn = (
        *(
            (
                BattleChoice(
                    command=MOVE,
                    kind="move",
                    name="Change rows",
                    brief=ROW_GIST[MOVE],
                    help=MOVE_HELP,
                    category="turn",
                ),
            )
            if _can_move(fight, member)
            else ()
        ),
        BattleChoice(command=END, kind="end", name="End the turn", category="turn"),
        BattleChoice(
            command=SURRENDER,
            kind="surrender",
            name="Surrender",
            brief=ROW_GIST[SURRENDER],
            help=SURRENDER_HELP,
            category="turn",
        ),
    )
    offered = member_aims(fight, member)
    families = _families(offered)
    choices = {
        aim.command(): _aim_choice(fight, member, aim, families[aim.command()]) for aim in offered
    }
    aims = tuple(
        choice
        if choice.family
        else _family_grid(
            fight, member, families[command][0], [choices[a.command()] for a in families[command]]
        )
        for command, choice in choices.items()
    )
    return f"{fight.name_of(member)}'s turn", (*aims, *_plan_choices(fight, member), *turn)


def _aim_menu(
    fight: Fight, member: MemberCombatant, aim: Aim, picks: Sequence[str]
) -> tuple[str, tuple[BattleChoice, ...]]:
    back = BattleChoice(command=BACK, kind="back", name="Back", category="step")
    name = _family_name(aim)
    if aim.awaits_target(picks):
        picked = aim.picked_target_ids(picks)
        row = (
            row_of(fight, fight.battle.require_combatant(picked[0]))
            if picked and aim.one_row
            else None
        )
        targets = tuple(
            _target_choice(fight, member, aim, fight.battle.require_combatant(target_id))
            for target_id in aim.target_ids
            if (aim.repeats or target_id not in picked)
            and (row is None or row_of(fight, fight.battle.require_combatant(target_id)) == row)
        )
        done = (
            (BattleChoice(command=DONE, kind="done", name="No more targets", category="step"),)
            if picked
            else ()
        )
        cap = aim.target_cap(picks)
        count = f" {len(picked) + 1}/{cap}" if cap > 1 else ""
        return f"{name} · target{count}", (*targets, *done, back)
    sheet = fight.require_sheet(member)
    slots = tuple(
        BattleChoice(
            command=f"{SLOT} {level}",
            kind="slot",
            name=ordinal(level),
            brief=" · ".join(
                part
                for part in (f"{sheet.slots_left(level)} left", _slot_gain(sheet, aim, level))
                if part
            ),
            category="step",
        )
        for level in aim.slot_levels
    )
    return f"{name} · slot", (*slots, back)


def _slot_gain(sheet: Lite5eSheet, aim: Aim, level: int) -> str:
    cap = aim.slot_caps.get(level)
    if cap is not None:
        return f"{cap} {'strikes' if aim.repeats else 'targets'}"
    battle = srd().require_spell(aim.action_id).battle
    if battle is None or battle.higher_level_dice is None:
        return ""
    return " + ".join(_amounts(spell_action(sheet, aim.action_id, level)))


def _target_choice(
    fight: Fight, member: MemberCombatant, aim: Aim, target: Combatant
) -> BattleChoice:
    brief, help = "", ""
    action = aim.action
    if action is not None and action.to_hit is not None and target.side == "foes":
        mode, reasons = advantage_of(fight, member, target, action)
        brief = EDGE_BRIEFS[mode]
        help = "; ".join(reasons)
    return BattleChoice(
        command=f"{TARGET} {target.combatant_id}",
        kind="target",
        name=fight.name_of(target),
        brief=brief,
        help=help,
        category="step",
        target_id=target.combatant_id,
    )


def _plan_choices(fight: Fight, member: MemberCombatant) -> tuple[BattleChoice, ...]:
    if fight.block_or_form_of(member) is None:
        return ()
    budget = fight.battle.budget
    plans = (
        [
            plan
            for plan in plans_of(fight, member)
            if plan != HOLD and (budget.move or plan.move is None)
        ]
        if budget.action
        else []
    )
    extra = bonus_plans_of(fight, member) if budget.bonus_action else []
    return (
        *(_plan_choice(fight, member, plan, "plan") for plan in plans),
        *(_plan_choice(fight, member, plan, "bonus") for plan in extra),
    )


def _plan_choice(
    fight: Fight, member: MemberCombatant, plan: Plan, kind: BattleChoiceKind
) -> BattleChoice:
    block = fight.block_or_form_of(member)
    bonus = kind == "bonus"
    if plan.entry_id is None or block is None:
        name = plan.text.capitalize() if plan.action else f"Move to the {plan.move} row"
        return BattleChoice(
            command=f"{PLAN} {plan.text}",
            kind=kind,
            name=name,
            brief=ROW_GIST[MOVE if plan.action is None else plan.action],
            help=MOVE_HELP if plan.action is None else ROW_HELP[plan.action],
            category="bonus" if bonus else "actions",
        )
    strike_names = [block.require_action(strike.action_id).name for strike in plan.strikes]
    name = (
        f"Multiattack: {', '.join(strike_names)}"
        if plan.entry_id == MULTIATTACK
        else strike_names[0]
    )
    target_ids = dict.fromkeys(t_id for strike in plan.strikes for t_id in strike.target_ids)
    targets = (fight.battle.require_combatant(target_id) for target_id in target_ids)
    follow_up = plan.follow_up
    notes = [
        ", ".join(fight.name_of(target) for target in targets),
        *([] if plan.move is None else [f"→ {plan.move}"]),
        *([] if follow_up is None else [f"then {block.require_action(follow_up.action_id).name}"]),
        *([] if plan.edge == "none" else [EDGE_BRIEFS[plan.edge]]),
    ]
    return BattleChoice(
        command=f"{PLAN} {plan.text}",
        kind=kind,
        name=name,
        stats=tuple(notes),
        help=ROW_HELP["attack"],
        category="bonus" if bonus else "attacks",
    )


def _aim_choice(
    fight: Fight, member: MemberCombatant, aim: Aim, family: Sequence[Aim]
) -> BattleChoice:
    kind: AimKind = (
        "bonus" if aim.verb == BONUS else "action" if aim.variant_id is None else "variant"
    )
    action = aim.action
    level: int | None = None
    if action is not None and action.origin == "spell":
        spell = srd().require_spell(aim.action_id)
        help, rules = _described(spell.description)
        level = spell.level
    else:
        help, rules = _row_help(fight, member, aim)
    folded = len(family) > 1
    variant, option = _variant_and_option(aim) if folded else ("", "")
    head = family[0]
    return BattleChoice(
        command=aim.command(),
        kind=kind,
        name=_family_name(aim) if folded else aim.name,
        variant=variant,
        option=option,
        brief=ROW_GIST[aim.row.action_id] if action is None else _stat_line(action),
        stats=() if action is None else tuple(action.summary_parts()),
        help=help,
        rules=rules,
        category=_aim_category(aim),
        level=level,
        family="" if aim is head else head.command(),
    )


def _family_grid(
    fight: Fight, member: MemberCombatant, head: Aim, members: Sequence[BattleChoice]
) -> BattleChoice:
    action = head.action
    spell = action is not None and action.origin == "spell"
    if spell:
        known = fitting_metamagic(fight.require_sheet(member), srd().require_spell(head.action_id))
        dependent = {choice.variant for choice in members}
        axis = ("", *(_metamagic_label(metamagic) for metamagic in known))
    else:
        dependent = {choice.variant for choice in members if choice.option}
        axis = ()
    options = tuple(dict.fromkeys((*axis, *(c.option for c in members if c.variant in dependent))))
    ways = tuple(
        FamilyWay(
            variant=variant,
            commands=tuple(
                next(
                    (
                        choice.command
                        for choice in members
                        if choice.variant == variant
                        and (choice.option == option or variant not in dependent)
                    ),
                    None,
                )
                for option in options or ("",)
            ),
        )
        for variant in dict.fromkeys(choice.variant for choice in members)
    )
    if len(ways) < 2 and len(options) < 2:
        return members[0]
    return members[0].model_copy(
        update={
            "option_label": "Metamagic" if spell else "Slot",
            "options": options if len(options) > 1 else (),
            "ways": ways,
        }
    )


def _families(aims: Sequence[Aim]) -> dict[str, list[Aim]]:
    families: dict[tuple[ActionVerb, str], list[Aim]] = {}
    for aim in sorted(aims, key=lambda aim: (aim.variant_id is not None, aim.verb != ACT)):
        families.setdefault(_family_key(aim), []).append(aim)
    return {aim.command(): family for family in families.values() for aim in family}


def _family_key(aim: Aim) -> tuple[ActionVerb, str]:
    # A Quickened cast stays with the action cast it speeds up.
    quickened = split_variant(aim.variant_id)[1] == QUICKENED
    return ACT if quickened else aim.verb, _family_id(aim)


def _family_id(aim: Aim) -> str:
    return FAMILY_ROWS.get(aim.action_id, aim.action_id)


def _family_name(aim: Aim) -> str:
    action = aim.action
    if action is not None and action.action_id == aim.action_id:
        return action.name
    return FAMILY_NAMES.get(_family_id(aim), aim.row.name or aim.name)


def _variant_and_option(aim: Aim) -> tuple[str, str]:
    action, variant_id = aim.action, aim.variant_id
    if action is None:
        return _row_variant(aim), ""
    if variant_id is None:
        return "", ""
    if action.origin == "spell":
        base, metamagic = split_variant(variant_id)
        variant = "" if base is None else base.capitalize()
        return variant, "" if metamagic is None else _metamagic_label(metamagic)
    picked = require_strike_variant(variant_id)
    slot = "" if picked.slot_level is None else ordinal(picked.slot_level)
    return picked.variant.name, slot


def _metamagic_label(metamagic: MetamagicId) -> str:
    cost = srd().character_options.metamagic[metamagic].cost
    return f"{metamagic.title()} · {cost} SP"


def _row_variant(aim: Aim) -> str:
    row, variant_id = aim.row, aim.variant_id
    if variant_id is None:
        return ROW_VARIANTS.get(row.action_id, row.name)
    if row.action_id == FONT_OF_MAGIC:
        level = int(variant_id)
        return f"{ordinal(level)} · {MADE_SLOT_COST[level]} SP"
    if row.action_id == WILD_SHAPE:
        return srd().require_stat_block(variant_id).name
    return variant_id.replace("-", " ").capitalize()


def _stat_line(action: ActionSpec) -> str:
    parts = [
        *(() if action.to_hit is None else (f"{action.to_hit:+d}",)),
        *(() if action.save is None else (f"DC {action.save.dc}",)),
    ]
    if action.area is not None:
        parts.append(action.area.text())
    elif action.range_feet is not None:
        parts.append(f"{action.range_feet} ft")
    amounts = _amounts(action)
    if amounts:
        parts.append(" + ".join(amounts))
    return " · ".join(parts)


def _amounts(action: ActionSpec) -> list[str]:
    healing = action.healing
    parts = (
        *action.damage,
        *(() if healing is None else (DamagePart(dice=healing.dice, bonus=healing.bonus),)),
    )
    return [part.model_copy(update={"damage_type": None}).text() for part in parts]


def _described(text: str) -> tuple[str, str]:
    first = first_sentence(text)
    return first, "" if first == text.strip() else text


def _row_help(fight: Fight, member: MemberCombatant, aim: Aim) -> tuple[str, str]:
    row = aim.row
    feature = (
        None if row.feature_id is None else srd().character_options.features.get(row.feature_id)
    )
    if feature is not None and feature.name == row.name:
        return _described(feature.description)
    sheet = fight.sheet_of(member)
    if row.use is not None and sheet is not None:
        name, description = use_source(sheet, row.use)
        if name == row.name:
            return _described(description)
    return ROW_HELP[row.action_id], ""


def _aim_category(aim: Aim) -> ChoiceCategory:
    action = aim.action
    if action is not None and action.origin == "spell":
        return "spells"
    if aim.row.action_id not in ITEM_ROW_IDS and action is not None and action.kind == "attack":
        return "attacks"
    return _row_category(aim.row)


def _row_category(row: BattleActionRow) -> ChoiceCategory:
    if row.action_id in ITEM_ROW_IDS:
        return "items"
    if row.budget == "attack":
        return "attacks"
    if row.action_id == SPELLS:
        return "spells"
    return "bonus" if row.verb == BONUS else "actions"


def _pool_categories(
    fight: Fight, member: MemberCombatant, sheet: Lite5eSheet
) -> dict[FeatureUse, tuple[ChoiceCategory, ...]]:
    spenders: dict[FeatureUse, dict[ChoiceCategory, None]] = {}
    for verb in (ACT, BONUS):
        for row in offered_rows(fight, member, verb):
            spent: tuple[FeatureUse, ...] = (
                *(() if row.use is None else (row.use,)),
                *((SORCERY_POINTS,) if row.action_id == FONT_OF_MAGIC else ()),
                *((SORCERY_POINTS,) if row.action_id == SPELLS and sheet.metamagic_ids() else ()),
            )
            for use in spent:
                spenders.setdefault(use, {})[_row_category(row)] = None
    for variant in srd().strike_variants:
        use = variant.spent_use
        if use is not None and (variant.source_id is None or sheet.owns(variant.source_id)):
            spenders.setdefault(use, {})["attacks"] = None
    return {use: tuple(categories) for use, categories in spenders.items()}


def _budget(fight: Fight, member: MemberCombatant) -> BudgetView:
    budget = fight.battle.budget
    return BudgetView(
        action=budget.action or budget.extra_actions > 0,
        bonus=budget.bonus_action,
        move=_can_move(fight, member),
        attacks_left=budget.attacks_left,
    )


def _pools(fight: Fight, member: MemberCombatant, sheet: Lite5eSheet) -> tuple[PoolPips, ...]:
    slots = (
        PoolPips(
            name=ordinal(level),
            left=sheet.slots_left(level),
            maximum=maximum,
            slot_level=level,
        )
        for level in range(1, len(sheet.class_level().slots or ()) + 1)
        if (maximum := sheet.slot_maximum(level))
    )
    categories = _pool_categories(fight, member, sheet)
    uses = (
        PoolPips(
            name=use_source(sheet, use)[0],
            left=sheet.uses_left(use),
            maximum=maximum,
            categories=categories.get(use, ()),
        )
        for use in srd().character_options.feature_uses
        if (maximum := sheet.use_limit(use))
    )
    return (*slots, *uses)


def _card(
    fight: Fight,
    combatant: Combatant,
    current_id: Slug | None,
    picked: Counter[Slug],
    *,
    autos: bool,
) -> CombatantCard:
    combatant_id = combatant.combatant_id
    tags = [
        *(Tag(name=condition.title()) for condition in fight.battle.conditions_on(combatant_id)),
        *_effect_tags(fight, combatant),
    ]
    hp = band = auto = None
    if isinstance(combatant, FoeCombatant):
        tags.extend(_lore_tags(fight, combatant))
        shape = health_band(fight, combatant)
        band = None if shape == "unhurt" else Tag(name=shape.title())
    else:
        gauge = fight.hp_of(combatant)
        hp = Meter(name="", current=gauge.current, maximum=gauge.maximum)
        offered = autos and combatant_id != PLAYER_ID and fight.in_battle(combatant)
        auto = combatant.auto if offered else None
        sheet = fight.sheet_of(combatant)
        if combatant.auto and auto is None:
            tags.append(Tag(name="Auto"))
        if fight.is_dead(combatant):
            tags.append(Tag(name="Dead"))
        if sheet is not None and sheet.temp_hp:
            tags.append(Tag(name=f"Temporary HP {sheet.temp_hp}"))
    if combatant.withdrawal is not None:
        tags.append(Tag(name=combatant.withdrawal.title(), help="Left the battle"))
    return CombatantCard(
        combatant_id=combatant_id,
        name=fight.name_of(combatant),
        sprite=_sprite(fight, combatant),
        side=combatant.side,
        row=row_of(fight, combatant),
        hp=hp,
        band=band,
        tags=tuple(tags),
        current=combatant_id == current_id,
        auto=auto,
        picked=picked[combatant_id],
    )


def _lore_tags(fight: Fight, foe: FoeCombatant) -> tuple[Tag, ...]:
    lored = any(
        mark.effect_id == HUNTERS_MARK
        and (sheet := fight.sheet_of(fight.battle.require_combatant(mark.source_id))) is not None
        and HUNTER in sheet.feature_ids()
        for mark in fight.battle.effects_on(foe.combatant_id)
    )
    if not lored:
        return ()
    block = foe.stat_block()
    lore = (
        ("Immune", (*block.damage_immunities, *block.condition_immunities)),
        ("Resists", block.damage_resistances),
        ("Vulnerable", block.damage_vulnerabilities),
    )
    return tuple(
        Tag(name=f"{label}: {', '.join(kinds)}", help="Hunter's Lore")
        for label, kinds in lore
        if kinds
    )


def _effect_tags(fight: Fight, combatant: Combatant) -> tuple[Tag, ...]:
    rules = srd().battle_effects.effects
    names = dict.fromkeys(
        tag
        for effect in fight.battle.effects_on(combatant.combatant_id)
        if (rule := rules.get(effect.effect_id)) is not None and (tag := rule.tag) is not None
    )
    return tuple(Tag(name=name) for name in names)


def _sprite(fight: Fight, combatant: Combatant) -> Sprite:
    if isinstance(combatant, FoeCombatant):
        return stat_block_sprite(combatant.stat_block_id)
    return fight.require_member(combatant.combatant_id).sprite()
