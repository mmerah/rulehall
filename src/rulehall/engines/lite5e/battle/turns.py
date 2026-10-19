from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from typing import Literal

from rulehall.core.facts import DiceEvent, Fact, roll
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.battle.attack import (
    blessing,
    find_bardic_die,
    holds_effect,
    spend_bardic_die,
)
from rulehall.engines.lite5e.battle.damage import (
    BEACON_OF_HOPE,
    change_row,
    end_of_turn_fire_aura,
    escape,
    regain,
    repeat_saves,
    resolve,
    roll_check,
    roll_parts,
    roll_save,
    save_facts,
    start_of_turn_regeneration,
    take_damage,
)
from rulehall.engines.lite5e.battle.foes import (
    CHARGE,
    Plan,
    instinct_plan,
    instinct_score,
    next_target_id,
    parse_plan,
    plans_of,
    scripted_pick,
    scripted_plan,
    standing_target,
)
from rulehall.engines.lite5e.battle.rows import hide_refusal, is_active, meets_requirements
from rulehall.engines.lite5e.battle.specs import (
    UNARMED_STRIKE,
    ActionSpec,
    SaveSpec,
    spell_part,
    stat_block_action,
    unarmed_action,
    weapon_action,
)
from rulehall.engines.lite5e.battle.spells import (
    FEAR,
    find_command,
    flee,
    obey_command,
)
from rulehall.engines.lite5e.battle.state import (
    SLOW,
    Combatant,
    Effect,
    Fight,
    FoeCombatant,
    MemberCombatant,
    TurnBudget,
    ended_facts,
    told,
)
from rulehall.engines.lite5e.data import (
    ActionBudget,
    EffectRule,
    StatBlock,
    Usage,
    modifier,
)
from rulehall.engines.lite5e.rules import DEATH_SAVE_DC, Edge
from rulehall.engines.lite5e.sheet import (
    combined_edge,
    roll_d20,
)
from rulehall.engines.sheet import PLAYER_ID

type Outcome = Literal["hero_dead", "victory", "escape", "defeat"]
type Planner = Callable[[Fight, Sequence[FoeCombatant]], Awaitable[Mapping[Slug, str]]]

HIDDEN = "hidden"
ROUND = "Round {round}"
HIDE_DC = 15
TURN_UNDEAD = "turn-undead"
INSTINCT_DIE = 10
RECHARGE_DIE = 6


class BattleEnd(Frozen):
    outcome: Outcome
    yielded: bool = False


def roll_initiative(fight: Fight, surprised_ids: Collection[Slug]) -> list[Fact]:
    battle = fight.battle
    groups: dict[Slug, list[Combatant]] = {}
    for combatant in battle.combatants:
        key = combatant.person_id if isinstance(combatant, FoeCombatant) else combatant.combatant_id
        groups.setdefault(key, []).append(combatant)
    ranks: dict[Slug, tuple[int, int, bool]] = {}
    numbers: list[str] = []
    dice: list[DiceEvent] = []
    for group in groups.values():
        first = group[0]
        sheet = fight.sheet_of(first)
        surprised = any(combatant.combatant_id in surprised_ids for combatant in group)
        unseen = any(battle.has_condition(c.combatant_id, "invisible") for c in group)
        edges: list[Edge] = [
            "disadvantage" if surprised else "none",
            "advantage" if unseen else "none",
        ]
        if sheet is None:
            block = fight.stat_block_of(first)
            assert block is not None
            dexterity = block.scores["dexterity"]
            bonus, lucky = modifier(dexterity), False
        else:
            dexterity = sheet.score("dexterity")
            bonus, lucky = sheet.initiative_bonus(), sheet.rerolls_ones()
            edges.append("advantage" if sheet.has_advantage("initiative") else "none")
        name = first.group_name if isinstance(first, FoeCombatant) else fight.name_of(first)
        face, events, _ = roll_d20(
            f"{name} initiative", combined_edge(*edges), fight.rng, lucky=lucky
        )
        for combatant in group:
            ranks[combatant.combatant_id] = (-(face + bonus), -dexterity, first.side == "foes")
        numbers.append(f"{name} {face + bonus}")
        dice.extend(events)
    battle.order = sorted(ranks, key=ranks.__getitem__)
    battle.turn_index = 0
    battle.round = 1
    names = ", ".join(fight.name_of(battle.require_combatant(c_id)) for c_id in battle.order)
    facts = [
        Fact(trace=f"initiative: {'; '.join(numbers)}"),
        told(f"Initiative: {names}", tuple(dice)),
        *(
            fact
            for member in battle.member_combatants()
            for fact in _uncanny_metabolism(fight, member)
        ),
        told(ROUND.format(round=battle.round)),
        *_settle_on_turn(fight),
    ]
    fight.battle.facts.extend(facts)
    return facts


def battle_end(fight: Fight) -> BattleEnd | None:
    battle = fight.battle
    hero = _require_member(fight, PLAYER_ID)
    if fight.is_dead(hero):
        return BattleEnd(outcome="hero_dead")
    if not any(fight.is_standing(foe) for foe in battle.foes()):
        return BattleEnd(outcome="victory")
    staying = [member for member in battle.member_combatants() if member.withdrawal is None]
    if hero.withdrawal == "left" and not any(fight.is_standing(member) for member in staying):
        return BattleEnd(outcome="escape")
    if not any(is_active(fight, member) for member in staying):
        return BattleEnd(outcome="defeat")
    return None


def current_combatant(fight: Fight) -> Combatant:
    battle = fight.battle
    return battle.require_combatant(battle.order[battle.turn_index])


def require_member_turn(fight: Fight) -> MemberCombatant:
    current = current_combatant(fight)
    if fight.battle.phase != "member" or not isinstance(current, MemberCombatant):
        raise Refusal("no member's turn is open: play the next turn")
    return current


def player_picks(fight: Fight, combatant: Combatant) -> bool:
    return (
        isinstance(combatant, MemberCombatant)
        and not combatant.auto
        and is_active(fight, combatant)
    )


def hidden_effect(holder_id: Slug) -> Effect:
    return Effect(
        holder_id=holder_id,
        source_id=holder_id,
        effect_id=HIDDEN,
        condition="invisible",
        ends_on=("attack", "verbal-cast"),
    )


def block_foes(fight: Fight) -> list[FoeCombatant]:
    battle = fight.battle
    count = len(battle.order)
    found: list[FoeCombatant] = []
    for step in range(count):
        combatant = battle.require_combatant(battle.order[(battle.turn_index + step) % count])
        if not fight.in_battle(combatant):
            continue
        if player_picks(fight, combatant):
            break
        if isinstance(combatant, FoeCombatant):
            found.append(combatant)
    return found


async def plan_block(fight: Fight, planner: Planner) -> list[Fact]:
    battle = fight.battle
    facts: list[Fact] = []
    asked: list[FoeCombatant] = []
    for foe in block_foes(fight):
        score = instinct_score(foe.stat_block().scores["intelligence"])
        rolled = roll((INSTINCT_DIE,), f"{foe.name} instinct", fight.rng, label="Instinct")
        instinct = rolled.face <= score
        line = f"{foe.name}: instinct {rolled.face} vs {score}"
        facts.append(Fact(trace=line + (": acts on instinct" if instinct else "")))
        if instinct:
            battle.pending_plans[foe.combatant_id] = instinct_plan(fight, foe).text
        else:
            asked.append(foe)
    if asked:
        plans = await planner(fight, asked)
        if set(plans) != {foe.combatant_id for foe in asked}:
            raise ValueError("the planner must give one plan for each foe it was asked about")
        battle.pending_plans.update(plans)
    battle.facts.extend(facts)
    return facts


async def play_next(fight: Fight, planner: Planner) -> list[Fact]:
    battle = fight.battle
    if battle.phase != "foes":
        raise Refusal("a member's turn is open: play it or end it")
    current = current_combatant(fight)
    due = isinstance(current, FoeCombatant) and current.combatant_id not in battle.pending_plans
    planned = await plan_block(fight, planner) if due else []
    if player_picks(fight, current):
        played = _settle_on_turn(fight)
    else:
        played, acts = _start_turn(fight, current)
        if acts and battle_end(fight) is None:
            if isinstance(current, FoeCombatant):
                played.extend(_foe_turn(fight, current))
            else:
                played.extend(_code_member_turn(fight, current))
        if battle_end(fight) is None:
            played.extend(_finish_turn(fight, current))
    battle.facts.extend(played)
    return [*planned, *played]


def move(fight: Fight) -> list[Fact]:
    member = require_member_turn(fight)
    if fight.battle.is_held(member.combatant_id):
        raise Refusal(f"{fight.name_of(member)} cannot move: its Speed is 0")
    return after_member_action(fight, member, _spend_move(fight, member))


def plan(fight: Fight, text: str) -> list[Fact]:
    member = require_member_turn(fight)
    if fight.block_or_form_of(member) is None:
        raise Refusal("only a companion of a stat block or a member in Wild Shape plays plans")
    picked = parse_plan(fight, member, text)
    action_id = picked.entry_id or picked.action
    if action_id is not None:
        spend_budget(fight, member, "bonus" if picked.bonus else "action", action_id)
    return after_member_action(fight, member, _play_plan(fight, member, picked))


def end_turn(fight: Fight) -> list[Fact]:
    member = require_member_turn(fight)
    facts = _finish_turn(fight, member)
    fight.battle.facts.extend(facts)
    return facts


def surrender(fight: Fight) -> BattleEnd:
    _ = require_member_turn(fight)
    return BattleEnd(outcome="defeat", yielded=True)


def toggle_auto(fight: Fight, actor_id: Slug) -> list[Fact]:
    member = _require_member(fight, actor_id)
    if actor_id == PLAYER_ID:
        raise Refusal("the hero never plays on Auto")
    member.auto = not member.auto
    line = f"{fight.name_of(member)} plays {'on Auto' if member.auto else 'by your picks'}"
    facts = [Fact(trace=line, card=line)]
    battle = fight.battle
    battle.facts.extend(facts)
    if member.auto and battle.phase == "member" and current_combatant(fight) is member:
        facts.extend(after_member_action(fight, member, _code_member_turn(fight, member)))
    return facts


def strike_action(
    fight: Fight, combatant: Combatant, block: StatBlock | None, action_id: Slug
) -> ActionSpec:
    if block is not None:
        return stat_block_action(block.require_action(action_id))
    sheet = fight.sheet_of(combatant)
    assert sheet is not None
    if action_id == UNARMED_STRIKE:
        return unarmed_action(sheet)
    pact = action_id == fight.pact_weapon_id(combatant)
    return weapon_action(sheet, action_id, off_hand=False, pact=pact)


def spend_budget(
    fight: Fight, member: MemberCombatant, budget: ActionBudget, action_id: str
) -> None:
    spent = fight.battle.budget
    if budget == "bonus":
        if not spent.bonus_action:
            raise Refusal("the bonus action is spent this turn")
        spent.bonus_action = False
    elif budget == "attack" and spent.attacks_left:
        spent.attacks_left -= 1
    elif budget != "none":
        _take_action(fight, magic=budget == "magic")
        if budget == "attack":
            count = fight.attack_count(member, action_id)
            spent.attacks_left = count - 1
            spent.bound_weapon_id = action_id if fight.thirsts(member, action_id) else None


def after_member_action(fight: Fight, member: MemberCombatant, facts: list[Fact]) -> list[Fact]:
    if battle_end(fight) is None and not player_picks(fight, member):
        facts = [*facts, *_finish_turn(fight, member)]
    fight.battle.facts.extend(facts)
    return facts


def hide(fight: Fight, combatant: Combatant) -> list[Fact]:
    battle = fight.battle
    name = fight.name_of(combatant)
    if refusal := hide_refusal(fight, combatant):
        raise Refusal(refusal)
    test = roll_check(fight, combatant, "dexterity", "stealth", HIDE_DC, "none")
    facts = [
        Fact(trace=f"{name}: Stealth {test.total} vs DC {HIDE_DC}"),
        told(f"{name} hides → {'success' if test.success else 'failure'}", test.dice),
    ]
    if test.success:
        battle.replace_effect(hidden_effect(combatant.combatant_id))
    return facts


def _settle_on_turn(fight: Fight) -> list[Fact]:
    facts: list[Fact] = []
    battle = fight.battle
    while battle_end(fight) is None:
        combatant = current_combatant(fight)
        if fight.in_battle(combatant):
            if not player_picks(fight, combatant):
                battle.phase = "foes"
                return facts
            started, acts = _start_turn(fight, combatant)
            facts.extend(started)
            if acts:
                battle.phase = "member"
                return facts
            facts.extend(_end_turn_steps(fight, combatant))
        facts.extend(_step(fight))
    return facts


def _finish_turn(fight: Fight, combatant: Combatant) -> list[Fact]:
    facts = _end_turn_steps(fight, combatant)
    if battle_end(fight) is not None:
        return facts
    return [*facts, *_step(fight), *_settle_on_turn(fight)]


def _step(fight: Fight) -> list[Fact]:
    battle = fight.battle
    battle.turn_index += 1
    if battle.turn_index < len(battle.order):
        return []
    battle.turn_index = 0
    battle.round += 1
    return [told(ROUND.format(round=battle.round))]


def _start_turn(fight: Fight, combatant: Combatant) -> tuple[list[Fact], bool]:
    battle = fight.battle
    combatant_id = combatant.combatant_id
    name = fight.name_of(combatant)
    combatant.turns += 1
    battle.budget = TurnBudget(bonus_action=not holds_effect(fight, combatant_id, SLOW))
    facts = ended_facts(fight, battle.expire_effects(combatant_id, "start"))
    facts.extend(_turn_start_effects(fight, combatant))
    facts.extend(_recharge(fight, combatant))
    if isinstance(combatant, FoeCombatant):
        facts.extend(start_of_turn_regeneration(fight, combatant))
    if isinstance(combatant, MemberCombatant) and fight.hp_of(combatant).current == 0:
        facts.extend(_death_save(fight, combatant))
    if not fight.is_standing(combatant):
        return facts, False
    command = find_command(fight, combatant)
    if command is not None:
        return [*facts, *obey_command(fight, command)], False
    if battle.is_incapacitated(combatant_id):
        return [*facts, told(f"{name} cannot act")], False
    if holds_effect(fight, combatant_id, FEAR):
        return [*facts, *flee(fight, combatant)], False
    return facts, True


def _end_turn_steps(fight: Fight, combatant: Combatant) -> list[Fact]:
    facts = [*end_of_turn_fire_aura(fight, combatant), *repeat_saves(fight, combatant)]
    return [*facts, *ended_facts(fight, fight.battle.expire_effects(combatant.combatant_id, "end"))]


def _turn_start_effects(fight: Fight, combatant: Combatant) -> list[Fact]:
    battle = fight.battle
    return [
        fact
        for effect, rule in battle.effect_rules_on(combatant.combatant_id)
        if any(held is effect for held in battle.effects)
        for fact in _turn_start_effect(fight, combatant, effect, rule)
    ]


def _turn_start_effect(
    fight: Fight, combatant: Combatant, effect: Effect, rule: EffectRule
) -> list[Fact]:
    battle = fight.battle
    name = fight.name_of(combatant)
    source = next((c for c in battle.combatants if c.combatant_id == effect.source_id), combatant)
    facts: list[Fact] = []
    damage = rule.turn_damage
    if damage is not None:
        if damage == "spell":
            assert effect.slot_level is not None
            damage = spell_part(effect.effect_id, effect.slot_level)
        state = rule.state or effect.condition or effect.effect_id
        rolled = roll_parts(fight, [damage], state.capitalize())
        facts.append(told(f"{name} is {state}"))
        facts.extend(take_damage(fight, source, combatant, rolled)[1])
    if rule.turn_save is not None and fight.is_standing(combatant):
        dc = fight.require_sheet(source).spell_save_dc(effect.effect_id)
        save = SaveSpec(ability=rule.turn_save, dc=dc)
        test = roll_save(fight, combatant, save, against=None, spell=True)
        facts.extend(save_facts(fight, combatant, save, test))
        if test.success and any(held is effect for held in battle.effects):
            battle.effects.remove(effect)
            facts.extend(ended_facts(fight, [effect]))
    if rule.turn_temp_hp:
        assert effect.numbers is not None
        gain, sheet = effect.numbers.modifier, fight.sheet_of(combatant)
        if sheet is not None and sheet.gain_temp_hp(gain):
            facts.append(told(f"{name}: temporary HP {gain}"))
    return facts


def _recharge(fight: Fight, combatant: Combatant) -> list[Fact]:
    block = fight.stat_block_of(combatant)
    if block is None or not combatant.recharging_ids:
        return []
    facts: list[Fact] = []
    name = fight.name_of(combatant)
    for usage_id in list(combatant.recharging_ids):
        least = block.require_usage(usage_id).recharge_min
        if least is None:
            raise ValueError(f"{block.name}'s {usage_id} does not recharge")
        label = next((a.name for a in block.actions if a.action_id == usage_id), usage_id.title())
        rolled = roll((RECHARGE_DIE,), f"{label} recharge", fight.rng, label="Recharge")
        if rolled.face >= least:
            combatant.recharging_ids.remove(usage_id)
            facts.append(told(f"{name}: {label} is ready again", (rolled.event,)))
        else:
            facts.append(Fact(trace=f"{name}: {label} does not recharge", dice=(rolled.event,)))
    return facts


def _death_save(fight: Fight, member: MemberCombatant) -> list[Fact]:
    if fight.require_member(member.combatant_id).require_vitals().stable or fight.is_dead(member):
        return []
    name = fight.name_of(member)
    hopeful = holds_effect(fight, member.combatant_id, BEACON_OF_HOPE)
    edge: Edge = "advantage" if hopeful else "none"
    blessed, blessing_dice = blessing(fight, member)
    saved, test = fight.require_member(member.combatant_id).roll_death_save(
        edge,
        fight.rng,
        dc=DEATH_SAVE_DC - blessed,
        bardic_die=find_bardic_die(fight, member),
    )
    if test.bardic_die_spent:
        spend_bardic_die(fight, member)
    spends = "".join(f", spent {spend}" for spend in test.spends)
    facts = [told(f"{name}: death save{spends} → {saved.outcome}", (*blessing_dice, *saved.dice))]
    if saved.outcome == "dead":
        facts.append(told(f"{name} dies"))
        facts.extend(ended_facts(fight, fight.battle.stop_turns(member.combatant_id)))
    elif saved.outcome == "revived":
        facts.append(told(f"{name} is back at 1 HP"))
    return facts


def _foe_turn(fight: Fight, foe: FoeCombatant) -> list[Fact]:
    battle = fight.battle
    text = battle.pending_plans.pop(foe.combatant_id, "")
    main, _, bonus_text = text.partition(";")
    facts: list[Fact] = []
    picked = _fitting_plan(fight, foe, main, bonus=False) if text else None
    if text and picked is None:
        facts.append(_stale_plan(foe, main, bonus=False))
    picked = picked or scripted_plan(fight, foe)
    facts.extend([*_stand_if_prone(fight, foe, picked), *_play_plan(fight, foe, picked)])
    if bonus_text.strip() and battle_end(fight) is None and is_active(fight, foe):
        extra = _fitting_plan(fight, foe, bonus_text, bonus=True)
        if extra is None:
            facts.append(_stale_plan(foe, bonus_text, bonus=True))
        else:
            facts.extend(_play_plan(fight, foe, extra))
    return facts


def _fitting_plan(fight: Fight, foe: FoeCombatant, text: str, *, bonus: bool) -> Plan | None:
    try:
        picked = parse_plan(fight, foe, text)
    except Refusal:
        return None
    if picked.bonus != bonus or (picked.move is not None and not fight.battle.budget.move):
        return None
    return picked


def _stale_plan(foe: FoeCombatant, text: str, *, bonus: bool) -> Fact:
    what = "bonus plan" if bonus else "plan"
    fallback = "drops it" if bonus else "takes the scripted pick"
    line = f"{foe.name}'s {what} {text.strip()!r} no longer works: it {fallback}"
    return Fact(trace=line, card=line)


def _code_member_turn(fight: Fight, member: MemberCombatant) -> list[Fact]:
    budget = fight.battle.budget
    plans = [plan for plan in plans_of(fight, member) if plan.move is None or budget.move]
    if not budget.action or not plans:
        return []
    picked = scripted_pick(fight, member, plans)
    stood = _stand_if_prone(fight, member, picked) if budget.move else []
    return [*stood, *_play_plan(fight, member, picked)]


def _play_plan(fight: Fight, combatant: Combatant, picked: Plan) -> list[Fact]:
    facts: list[Fact] = []
    if picked.move is not None:
        if picked.action == "disengage":
            fight.battle.budget.disengaged = True
        facts.extend(_spend_move(fight, combatant))
        if not fight.is_standing(combatant):
            return facts
    match picked.action:
        case "attack":
            facts.extend(_strikes(fight, combatant, picked))
        case "escape" if holds := fight.battle.escape_holds(combatant.combatant_id):
            facts.extend(escape(fight, combatant, combatant, holds[0].source_id))
        case "escape":
            facts.append(told(f"{fight.name_of(combatant)} struggles in vain"))
        case "hide":
            facts.extend(hide(fight, combatant))
        case "disengage" | None:
            pass
    return facts


def _strikes(fight: Fight, combatant: Combatant, picked: Plan) -> list[Fact]:
    block = fight.block_or_form_of(combatant)
    charge = None if block is None or not picked.charge else block.find_special("charge")
    facts: list[Fact] = []
    charged = False
    strikes = [*picked.strikes, *([] if picked.follow_up is None else [picked.follow_up])]
    for strike in strikes:
        if battle_end(fight) is not None or not fight.is_standing(combatant):
            break
        action = strike_action(fight, combatant, block, strike.action_id)
        targets = [
            target
            for target_id in strike.target_ids
            if fight.in_battle(target := fight.battle.require_combatant(target_id))
        ]
        if not targets and block is None:
            found_id = next_target_id(fight, combatant, strike.action_id)
            targets = [] if found_id is None else [fight.battle.require_combatant(found_id)]
        if targets and not any(fight.is_standing(target) for target in targets):
            standing = standing_target(fight, combatant, action)
            targets = targets if standing is None else [standing]
        unheld = [t for t in targets if not meets_requirements(fight, combatant, t, action)]
        facts.extend(
            told(f"{fight.name_of(combatant)} cannot use {action.name} on {fight.name_of(t)}")
            for t in unheld
        )
        targets = [target for target in targets if target not in unheld]
        if not targets:
            continue
        if charge is not None and not charged and strike.action_id == charge.action_id:
            charged = True
            action = action.model_copy(
                update={
                    "damage": (*action.damage, *charge.damage),
                    "riders": (*action.riders, *charge.riders),
                }
            )
            _spend_usage(combatant, CHARGE, charge.usage)
        facts.extend(resolve(fight, combatant, action, targets))
        if block is not None:
            entry = block.require_action(strike.action_id)
            _spend_usage(combatant, strike.action_id, entry.usage)
    return facts


def _spend_usage(combatant: Combatant, usage_id: Slug, usage: Usage) -> None:
    if usage.recharge_min is not None and usage_id not in combatant.recharging_ids:
        combatant.recharging_ids.append(usage_id)
    if usage.uses_per_day is not None:
        combatant.uses_spent[usage_id] = combatant.uses_spent.get(usage_id, 0) + 1


def _stand_if_prone(fight: Fight, combatant: Combatant, picked: Plan) -> list[Fact]:
    battle = fight.battle
    if (
        picked.move is not None
        or not battle.has_condition(combatant.combatant_id, "prone")
        or battle.is_held(combatant.combatant_id)
    ):
        return []
    return _spend_move(fight, combatant)


def _spend_move(fight: Fight, combatant: Combatant) -> list[Fact]:
    battle = fight.battle
    if not battle.budget.move:
        raise Refusal("the move is spent this turn")
    battle.budget.move = False
    if battle.has_condition(combatant.combatant_id, "prone"):
        _ = battle.remove_effects(
            lambda effect: (
                effect.holder_id == combatant.combatant_id and effect.condition == "prone"
            )
        )
        return [told(f"{fight.name_of(combatant)} stands up")]
    battle.budget.moved = True
    return change_row(fight, combatant, provoking=not battle.budget.disengaged, teleport=False)


def _take_action(fight: Fight, *, magic: bool) -> None:
    budget = fight.battle.budget
    if budget.extra_actions and not magic:
        budget.extra_actions -= 1
    elif budget.action:
        budget.action = False
    elif budget.extra_actions:
        raise Refusal("the action of Action Surge is not for a Magic action")
    else:
        raise Refusal("the action is spent this turn")


def _uncanny_metabolism(fight: Fight, member: MemberCombatant) -> list[Fact]:
    sheet = fight.sheet_of(member)
    if (
        sheet is None
        or sheet.uses_left("uncanny-metabolism") <= 0
        or (
            sheet.uses_left("focus") == sheet.use_limit("focus")
            and not fight.hp_of(member).shortfall
        )
    ):
        return []
    die = sheet.class_level().class_specific.martial_arts_die
    if die is None:
        raise ValueError(f"{member.combatant_id} has Uncanny Metabolism with no Martial Arts die")
    sheet.spend_use("uncanny-metabolism")
    _ = sheet.uses_spent.pop("focus", None)
    rolled = roll((die,), "Uncanny Metabolism", fight.rng, label="Uncanny Metabolism")
    line = told(f"{fight.name_of(member)}: Uncanny Metabolism restores the Focus Points")
    return [line, *regain(fight, member, rolled.total + sheet.level, (rolled.event,))[1]]


def _require_member(fight: Fight, actor_id: Slug) -> MemberCombatant:
    found = fight.battle.require_combatant(actor_id)
    if not isinstance(found, MemberCombatant):
        raise Refusal(f"{actor_id!r} is no member of the party")
    return found
