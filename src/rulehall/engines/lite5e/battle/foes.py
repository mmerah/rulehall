import re
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from pydantic import Field

from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.battle.attack import advantage_of, has_special, holds_effect
from rulehall.engines.lite5e.battle.rows import (
    BANDS,
    area_cap,
    band_between,
    enemies_of,
    hide_refusal,
    in_reach,
    is_active,
    meets_requirements,
    reaches,
    row_of,
)
from rulehall.engines.lite5e.battle.specs import (
    MELEE_REACH_FEET,
    ActionSpec,
    stat_block_action,
    unarmed_action,
)
from rulehall.engines.lite5e.battle.state import (
    SLOW,
    Combatant,
    Fight,
    FoeCombatant,
    MemberCombatant,
)
from rulehall.engines.lite5e.data import (
    Area,
    Special,
    StatBlock,
    StatBlockAction,
    Usage,
    dice_parts,
)
from rulehall.engines.lite5e.rules import (
    INSTINCT_STEPS,
    INSTINCT_TOP_SCORE,
    Edge,
    FormationRow,
)
from rulehall.engines.sheet import Gauge

type HealthBand = Literal["unhurt", "hurt", "bloodied", "down"]
type PlanAction = Literal["attack", "escape", "disengage", "hide"]

MULTIATTACK: Slug = "multiattack"
CHARGE: Slug = "charge"
NIMBLE_ESCAPE = "nimble escape"
HEALTH_BANDS: tuple[HealthBand, ...] = ("down", "bloodied", "hurt", "unhurt")
PLAN_NOTE = re.compile(r"\s*\([^()]*\)$")


class Strike(Frozen):
    action_id: Slug
    target_ids: tuple[Slug, ...] = Field(min_length=1)


class Plan(Frozen):
    text: str
    move: FormationRow | None = None
    action: PlanAction | None = None
    bonus: bool = False
    entry_id: Slug | None = None
    strikes: tuple[Strike, ...] = ()
    edge: Edge = "none"
    charge: bool = False
    follow_up: Strike | None = None
    limited_use: bool = False
    expected_damage: float = 0


class PlanOption(Frozen):
    action: ActionSpec
    limited_use: bool
    strike_count: int


HOLD = Plan(text="hold")
ADVANCE = Plan(text="front", move="front")


def health_band(fight: Fight, combatant: Combatant) -> HealthBand:
    return gauge_band(fight.hp_of(combatant))


def gauge_band(hp: Gauge) -> HealthBand:
    if hp.current == 0:
        return "down"
    if hp.current * 2 <= hp.maximum:
        return "bloodied"
    return "hurt" if hp.current < hp.maximum else "unhurt"


def instinct_score(intelligence: int) -> int:
    return next((score for top, score in INSTINCT_STEPS if intelligence <= top), INSTINCT_TOP_SCORE)


def starting_row(stat_block: StatBlock) -> FormationRow:
    sources = {source.action_id: source for source in stat_block.actions}
    averages = {action_id: _average(stat_block_action(s)) for action_id, s in sources.items()}
    candidates = [(averages[action_id], [action_id]) for action_id in sources]
    if stat_block.multiattack is not None:
        composed = _compose(stat_block, averages, list(sources))
        candidates.append((sum(averages[action_id] for action_id in composed), list(composed)))
    best = max((average for average, _ in candidates), default=0)
    tied = [action_ids[0] for average, action_ids in candidates if average == best and action_ids]
    return "front" if not tied or any(_is_melee(sources[a]) for a in tied) else "back"


def parse_plan(fight: Fight, combatant: Combatant, text: str) -> Plan:
    wanted = bare_plan(text)
    for plan in (*plans_of(fight, combatant), *bonus_plans_of(fight, combatant)):
        if bare_plan(plan.text) == wanted:
            return plan
    raise Refusal(f"{text!r} is no legal plan for {fight.name_of(combatant)}")


def scripted_plan(fight: Fight, combatant: Combatant) -> Plan:
    return scripted_pick(fight, combatant, plans_of(fight, combatant))


def scripted_pick(fight: Fight, combatant: Combatant, plans: Sequence[Plan]) -> Plan:
    attacks = [plan for plan in plans if plan.action == "attack"]
    escape = next((plan for plan in plans if plan.action == "escape"), None)
    standing = [plan for plan in attacks if plan.move is None]
    restrained = fight.battle.has_condition(combatant.combatant_id, "restrained")
    if escape is not None and (
        not standing or (restrained and not any(plan.edge == "advantage" for plan in standing))
    ):
        return escape
    for move in (None, "front"):
        found = [plan for plan in attacks if plan.move == move]
        if found:
            return _aimed(fight, _first_entry(found))
    return plans[0]


def next_target_id(fight: Fight, combatant: Combatant, action_id: Slug) -> Slug | None:
    plans = [
        plan
        for plan in plans_of(fight, combatant)
        if plan.move is None and plan.entry_id == action_id
    ]
    return _aimed(fight, plans).strikes[0].target_ids[0] if plans else None


def nearest_key(fight: Fight, user: Combatant, target: Combatant) -> tuple[int, int, int]:
    return BANDS.index(band_between(fight, user, target)), *_aim_key(fight, target)


def instinct_plan(fight: Fight, foe: FoeCombatant) -> Plan:
    plans = [plan for plan in plans_of(fight, foe) if plan.action == "attack" and plan.move is None]
    if not plans:
        return scripted_plan(fight, foe)
    first = _first_entry(plans)
    struck = [plan for plan in first if foe.last_damager_id in plan.strikes[0].target_ids]
    if struck:
        return struck[0]
    return min(
        first, key=lambda plan: nearest_key(fight, foe, _first_target(fight, plan.strikes[0]))
    )


def plans_of(fight: Fight, combatant: Combatant) -> list[Plan]:
    if not is_active(fight, combatant):
        return [HOLD]
    plans = _attack_plans(fight, combatant, _up(fight, combatant)) or _attack_plans(
        fight, combatant, _downed(fight, combatant)
    )
    by_block = fight.block_or_form_of(combatant) is not None
    if by_block and fight.battle.is_held(combatant.combatant_id):
        plans.append(Plan(text="escape", action="escape"))
    if plans:
        return plans
    row = combatant.row if by_block else row_of(fight, combatant)
    if row == "back" and _can_move(fight, combatant):
        return [ADVANCE]
    return [HOLD]


def bonus_plans_of(fight: Fight, combatant: Combatant) -> list[Plan]:
    if (
        not is_active(fight, combatant)
        or not has_special(fight, combatant, "nimble-escape")
        or holds_effect(fight, combatant.combatant_id, SLOW)
    ):
        return []
    plans: list[Plan] = []
    if combatant.row == "front" and _can_move(fight, combatant):
        plans.append(
            Plan(text=f"{NIMBLE_ESCAPE}: back", move="back", action="disengage", bonus=True)
        )
    if not hide_refusal(fight, combatant):
        plans.append(Plan(text=f"{NIMBLE_ESCAPE}: hide", action="hide", bonus=True))
    return plans


def bare_plan(text: str) -> str:
    return PLAN_NOTE.sub("", text.strip())


def _attack_plans(fight: Fight, combatant: Combatant, targets: Sequence[Combatant]) -> list[Plan]:
    moves: list[FormationRow | None] = [None]
    if _can_move(fight, combatant):
        moves.append("back" if combatant.row == "front" else "front")
    plans: list[Plan] = []
    for move in moves:
        view = fight if move is None else _moved(fight, combatant, move)
        user = view.battle.require_combatant(combatant.combatant_id)
        seen = [view.battle.require_combatant(target.combatant_id) for target in targets]
        options = _options(view, user)
        found = [
            *_multiattack_plans(view, user, options, seen, move),
            *(
                _option_plan(view, user, option, group, move)
                for option in options
                for group in _target_groups(view, user, option.action, seen)
            ),
        ]
        plans.extend(sorted(found, key=lambda plan: (not plan.limited_use, -plan.expected_damage)))
    return plans


def _options(fight: Fight, user: Combatant) -> list[PlanOption]:
    block = fight.block_or_form_of(user)
    if block is None:
        assert isinstance(user, MemberCombatant)
        actions = (*fight.weapon_actions(user), unarmed_action(fight.require_sheet(user)))
        return [
            PlanOption(
                action=action,
                limited_use=False,
                strike_count=fight.attack_count(user, action.action_id),
            )
            for action in actions
        ]
    return [
        PlanOption(
            action=stat_block_action(source), limited_use=source.usage != Usage(), strike_count=1
        )
        for source in block.actions
        if _is_ready(user, source.action_id, source.usage)
    ]


def _target_groups(
    fight: Fight, user: Combatant, action: ActionSpec, targets: Sequence[Combatant]
) -> list[list[Combatant]]:
    reached = [target for target in targets if reaches(fight, user, target, action)]
    if action.area is None:
        return [[target] for target in reached]
    return _area_groups(fight, reached, action.area)


def _option_plan(
    fight: Fight,
    user: Combatant,
    option: PlanOption,
    group: Sequence[Combatant],
    move: FormationRow | None,
) -> Plan:
    action = option.action
    return _attack_plan(
        fight,
        user,
        action,
        action.action_id,
        (_strike(action.action_id, group),) * option.strike_count,
        move,
        limited_use=option.limited_use,
        expected_damage=_average(action) * len(group),
    )


def _multiattack_plans(
    fight: Fight,
    user: Combatant,
    options: Sequence[PlanOption],
    targets: Sequence[Combatant],
    move: FormationRow | None,
) -> list[Plan]:
    block = fight.block_or_form_of(user)
    if block is None or block.multiattack is None or holds_effect(fight, user.combatant_id, SLOW):
        return []
    plans: list[Plan] = []
    for target in targets:
        reached = [o.action for o in options if in_reach(fight, user, target, o.action)]
        usable = {action.action_id: _average(action) for action in reached}
        held = [a.action_id for a in reached if meets_requirements(fight, user, target, a)]
        action_ids = _compose(block, usable, held)
        if action_ids:
            plans.append(
                _attack_plan(
                    fight,
                    user,
                    next(action for action in reached if action.action_id == action_ids[0]),
                    MULTIATTACK,
                    tuple(_strike(action_id, [target]) for action_id in action_ids),
                    move,
                    limited_use=False,
                    expected_damage=sum(usable[action_id] for action_id in action_ids),
                )
            )
    return plans


def _attack_plan(
    view: Fight,
    user: Combatant,
    action: ActionSpec,
    entry_id: Slug,
    strikes: tuple[Strike, ...],
    move: FormationRow | None,
    *,
    limited_use: bool,
    expected_damage: float,
) -> Plan:
    target = _first_target(view, strikes[0])
    charge = None if move is None else _charge_in(view, user, strikes)
    follow_up = None
    if charge is not None and charge.follow_up_action_id is not None:
        follow_up = _strike(charge.follow_up_action_id, [target])
    edge: Edge = "none" if action.to_hit is None else advantage_of(view, user, target, action)[0]
    notes = [
        *([] if charge is None else ["charge"]),
        *([] if follow_up is None else [f"then {follow_up.action_id}"]),
        *([] if edge == "none" else [edge]),
    ]
    text = ("" if move is None else f"{move}, ") + f"{entry_id} {target.combatant_id}"
    if notes:
        text += f" ({', '.join(notes)})"
    return Plan(
        text=text,
        move=move,
        action="attack",
        entry_id=entry_id,
        strikes=strikes,
        edge=edge,
        charge=charge is not None,
        follow_up=follow_up,
        limited_use=limited_use,
        expected_damage=expected_damage,
    )


def _compose(
    block: StatBlock, usable: Mapping[Slug, float], held: Collection[Slug]
) -> tuple[Slug, ...]:
    multiattack = block.multiattack
    if multiattack is None:
        raise ValueError(f"{block.name} has no Multiattack")
    once = {special.action_id for special in block.specials if special.special_id == "life-drain"}
    picked = [
        part.action_id
        for part in multiattack.fixed
        if part.action_id in usable
        for _ in range(part.count)
    ]
    ranked = sorted(
        (option for option in multiattack.options if option in usable),
        key=lambda option: -usable[option],
    )
    for _ in range(multiattack.choose):
        pick = next((o for o in ranked if o not in once or o not in picked), None)
        if pick is None:
            break
        picked.append(pick)
    grapples = {
        entry.action_id
        for entry in block.actions
        if any(rider.rider_id == "grapple" for rider in entry.riders)
    }
    kept: list[Slug] = []
    for action_id in picked:
        if action_id in held or not grapples.isdisjoint(kept):
            kept.append(action_id)
    return tuple(kept)


def _is_ready(combatant: Combatant, usage_id: Slug, usage: Usage) -> bool:
    if usage.recharge_min is not None and usage_id in combatant.recharging_ids:
        return False
    limit = usage.uses_per_day
    return limit is None or combatant.uses_spent.get(usage_id, 0) < limit


def _area_groups(fight: Fight, reached: Sequence[Combatant], area: Area) -> list[list[Combatant]]:
    cap = area_cap(area)
    groups: list[list[Combatant]] = []
    for row in ("front", "back"):
        in_row = sorted(
            (target for target in reached if row_of(fight, target) == row),
            key=lambda target: _aim_key(fight, target),
        )
        if in_row:
            groups.append(in_row if cap is None else in_row[:cap])
    return groups


def _is_melee(source: StatBlockAction) -> bool:
    if source.kind == "save":
        return source.area is None and (source.range_feet or 0) <= MELEE_REACH_FEET
    return source.kind == "melee"


def _average(action: ActionSpec) -> float:
    total = 0.0
    for part in action.damage:
        if part.dice is not None:
            count, faces = dice_parts(part.dice)
            total += count * (faces + 1) / 2
        total += part.bonus
    return total


def _charge_in(fight: Fight, combatant: Combatant, strikes: Sequence[Strike]) -> Special | None:
    block = fight.block_or_form_of(combatant)
    special = None if block is None else block.find_special("charge")
    if special is None or all(strike.action_id != special.action_id for strike in strikes):
        return None
    if not _is_ready(combatant, CHARGE, special.usage):
        return None
    return special


def _up(fight: Fight, combatant: Combatant) -> list[Combatant]:
    return [enemy for enemy in enemies_of(fight, combatant) if fight.is_standing(enemy)]


def _downed(fight: Fight, combatant: Combatant) -> list[Combatant]:
    return [
        enemy
        for enemy in enemies_of(fight, combatant)
        if isinstance(enemy, MemberCombatant)
        and enemy.withdrawal is None
        and fight.hp_of(enemy).current == 0
        and not fight.is_dead(enemy)
    ]


def _can_move(fight: Fight, combatant: Combatant) -> bool:
    battle = fight.battle
    return not battle.is_held(combatant.combatant_id) and not battle.has_condition(
        combatant.combatant_id, "prone"
    )


def _moved(fight: Fight, combatant: Combatant, row: FormationRow) -> Fight:
    battle = fight.battle.model_copy(deep=True)
    battle.require_combatant(combatant.combatant_id).row = row
    return Fight(battle=battle, members=fight.members, rng=fight.rng)


def _aimed(fight: Fight, plans: Sequence[Plan]) -> Plan:
    return min(
        plans,
        key=lambda plan: (
            -len(plan.strikes[0].target_ids),
            _aim_key(fight, _first_target(fight, plan.strikes[0])),
        ),
    )


def _first_entry(plans: Sequence[Plan]) -> list[Plan]:
    return [plan for plan in plans if plan.entry_id == plans[0].entry_id]


def _aim_key(fight: Fight, target: Combatant) -> tuple[int, int]:
    ids = [combatant.combatant_id for combatant in fight.battle.combatants]
    return HEALTH_BANDS.index(health_band(fight, target)), ids.index(target.combatant_id)


def _first_target(fight: Fight, strike: Strike) -> Combatant:
    return fight.battle.require_combatant(strike.target_ids[0])


def _strike(action_id: Slug, targets: Sequence[Combatant]) -> Strike:
    return Strike(action_id=action_id, target_ids=tuple(target.combatant_id for target in targets))
