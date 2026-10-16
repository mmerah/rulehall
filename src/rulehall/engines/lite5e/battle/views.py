from collections.abc import Sequence
from typing import Literal

from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.core.views import Meter, Sprite, Tag
from rulehall.engines.lite5e.battle.actions import DONE, SLOT, TARGET, Aim, member_aims
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
from rulehall.engines.lite5e.battle.state import (
    Combatant,
    Fight,
    FoeCombatant,
    MemberCombatant,
    Phase,
    Side,
)
from rulehall.engines.lite5e.battle.turns import current_combatant, require_member_turn
from rulehall.engines.lite5e.data import (
    ActionVerb,
    srd,
    stat_block_sprite,
)
from rulehall.engines.lite5e.rules import HUNTER, HUNTERS_MARK, FormationRow
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

ACT: ActionVerb = "act"
BONUS: ActionVerb = "bonus"
PLAN = "plan"
MOVE = "move"
BACK = "back"
END = "end"
NEXT = "next"
AUTO = "auto"
SURRENDER = "surrender"
ACTION_GROUP = "Action"
BONUS_GROUP = "Bonus action"
TURN_GROUP = "Turn"
OVER = "The battle is over"


class BattleChoice(Frozen):
    command: str
    kind: BattleChoiceKind
    name: str
    brief: str = ""
    help: str = ""
    group: str = ""
    tags: tuple[Tag, ...] = ()
    sprite: Sprite | None = None


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


class TurnSlot(Frozen):
    combatant_id: Slug
    name: str
    current: bool


class Lite5eBattleView(Frozen):
    round: int
    phase: Phase
    thinking: bool
    foes: tuple[CombatantCard, ...]
    party: tuple[CombatantCard, ...]
    order: tuple[TurnSlot, ...]
    step: str
    choices: tuple[BattleChoice, ...]

    def offers(self, command: str) -> bool:
        autos = (f"{AUTO} {card.combatant_id}" for card in self.party if card.auto is not None)
        return command in (*(choice.command for choice in self.choices), *autos)


def battle_view(
    fight: Fight, *, live: bool, thinking: bool, aiming: str, picks: Sequence[str]
) -> Lite5eBattleView:
    battle = fight.battle
    current_id = battle.order[battle.turn_index] if live else None
    step, choices = _menu(fight, aiming, picks) if live else (OVER, ())
    autos = live and not (aiming and battle.phase == "member")
    return Lite5eBattleView(
        round=battle.round,
        phase=battle.phase,
        thinking=thinking,
        foes=tuple(_card(fight, foe, current_id, autos=False) for foe in battle.foes()),
        party=tuple(
            _card(fight, member, current_id, autos=autos) for member in battle.member_combatants()
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
    )


def require_aim(fight: Fight, command: str) -> Aim:
    member = require_member_turn(fight)
    found = next((aim for aim in member_aims(fight, member) if aim.command() == command), None)
    if found is None:
        raise Refusal(f"{command!r} is no pick of {fight.name_of(member)} now")
    return found


def _menu(fight: Fight, aiming: str, picks: Sequence[str]) -> tuple[str, tuple[BattleChoice, ...]]:
    battle = fight.battle
    current = current_combatant(fight)
    if battle.phase == "foes" or not isinstance(current, MemberCombatant):
        next_turn = BattleChoice(command=NEXT, kind="next", name="Next turn", group=TURN_GROUP)
        return f"{fight.name_of(current)}'s turn", (next_turn,)
    if aiming:
        return _aim_menu(fight, current, require_aim(fight, aiming), picks)
    name = fight.name_of(current)
    turn = (
        *(
            (BattleChoice(command=MOVE, kind="move", name="Change rows", group=TURN_GROUP),)
            if fight.battle.budget.move and not fight.battle.is_held(current.combatant_id)
            else ()
        ),
        BattleChoice(command=END, kind="end", name="End the turn", group=TURN_GROUP),
        BattleChoice(
            command=SURRENDER,
            kind="surrender",
            name="Surrender",
            help="The party yields: the battle ends as a defeat, and the members keep their HP.",
            group=TURN_GROUP,
        ),
    )
    aims = tuple(_aim_choice(aim) for aim in member_aims(fight, current))
    return f"{name}: pick an action", (*_plan_choices(fight, current), *aims, *turn)


def _aim_menu(
    fight: Fight, member: MemberCombatant, aim: Aim, picks: Sequence[str]
) -> tuple[str, tuple[BattleChoice, ...]]:
    back = BattleChoice(command=BACK, kind="back", name="Back", group=aim.name)
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
            (BattleChoice(command=DONE, kind="done", name="No more targets", group=aim.name),)
            if picked
            else ()
        )
        cap = aim.target_cap(picks)
        count = f" ({len(picked) + 1} of {cap})" if cap > 1 else ""
        return f"{aim.name}: pick a target{count}", (*targets, *done, back)
    slots = tuple(
        BattleChoice(
            command=f"{SLOT} {level}",
            kind="slot",
            name=f"Level {level}",
            brief=f"{fight.require_sheet(member).slots_left(level)} left",
            group=aim.name,
        )
        for level in aim.slot_levels
    )
    return f"{aim.name}: pick the spell slot", (*slots, back)


def _target_choice(
    fight: Fight, member: MemberCombatant, aim: Aim, target: Combatant
) -> BattleChoice:
    brief, help = "", ""
    action = aim.action
    if action is not None and action.to_hit is not None and target.side == "foes":
        mode, reasons = advantage_of(fight, member, target, action)
        brief = "" if mode == "none" else mode.title()
        help = "; ".join(reasons)
    return BattleChoice(
        command=f"{TARGET} {target.combatant_id}",
        kind="target",
        name=fight.name_of(target),
        brief=brief,
        help=help,
        group=aim.name,
        sprite=_sprite(fight, target),
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
        *(_plan_choice(fight, member, plan, "plan", ACTION_GROUP) for plan in plans),
        *(_plan_choice(fight, member, plan, "bonus", BONUS_GROUP) for plan in extra),
    )


def _plan_choice(
    fight: Fight, member: MemberCombatant, plan: Plan, kind: BattleChoiceKind, group: str
) -> BattleChoice:
    block = fight.block_or_form_of(member)
    if plan.entry_id is None or block is None:
        name = plan.text.capitalize() if plan.action else f"Move to the {plan.move} row"
        return BattleChoice(command=f"{PLAN} {plan.text}", kind=kind, name=name, group=group)
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
        *([] if plan.move is None else [f"after moving to the {plan.move} row"]),
        *(["charge"] if plan.charge else []),
        *([] if follow_up is None else [f"then {block.require_action(follow_up.action_id).name}"]),
        *([] if plan.edge == "none" else [plan.edge]),
    ]
    return BattleChoice(
        command=f"{PLAN} {plan.text}", kind=kind, name=name, brief="; ".join(notes), group=group
    )


def _aim_choice(aim: Aim) -> BattleChoice:
    kind: AimKind = (
        "bonus" if aim.verb == BONUS else "action" if aim.variant_id is None else "variant"
    )
    group = BONUS_GROUP if aim.verb == BONUS else ACTION_GROUP
    return BattleChoice(command=aim.command(), kind=kind, name=aim.name, group=group)


def _card(
    fight: Fight, combatant: Combatant, current_id: Slug | None, *, autos: bool
) -> CombatantCard:
    combatant_id = combatant.combatant_id
    tags = [
        *(Tag(name=condition.title()) for condition in fight.battle.conditions_on(combatant_id)),
        *_effect_tags(fight, combatant),
    ]
    hp = band = auto = None
    if isinstance(combatant, FoeCombatant):
        tags.extend(_lore_tags(fight, combatant))
        band = Tag(name=health_band(fight, combatant).title())
    else:
        gauge = fight.hp_of(combatant)
        hp = Meter(name="HP", current=gauge.current, maximum=gauge.maximum)
        offered = autos and combatant_id != PLAYER_ID and fight.in_battle(combatant)
        auto = combatant.auto if offered else None
        sheet = fight.sheet_of(combatant)
        if combatant.auto:
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
        row=combatant.row,
        hp=hp,
        band=band,
        tags=tuple(tags),
        current=combatant_id == current_id,
        auto=auto,
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
