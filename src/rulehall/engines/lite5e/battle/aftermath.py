from collections import Counter
from collections.abc import Sequence
from random import Random
from typing import Literal

from rulehall.core.facts import DiceEvent, Fact, Resolution, roll
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.lite5e.args import StartBattle
from rulehall.engines.lite5e.battle.foes import starting_row
from rulehall.engines.lite5e.battle.morale import check_morale
from rulehall.engines.lite5e.battle.state import (
    Battle,
    Effect,
    Fight,
    FoeCombatant,
    MemberCombatant,
    foe_ids,
    told,
)
from rulehall.engines.lite5e.battle.turns import (
    BattleEnd,
    hidden_effect,
    roll_initiative,
)
from rulehall.engines.lite5e.data import Tier
from rulehall.engines.lite5e.rules import (
    FIENDISH_VIGOR,
    FIENDISH_VIGOR_HP,
    raised_light,
)
from rulehall.engines.lite5e.sheet import (
    ROUTED_NAME_SUFFIX,
    Lite5ePerson,
    SheetEffect,
    gear_name,
)
from rulehall.engines.lite5e.world import (
    Lite5ePlace,
    Lite5eWorld,
    lay_condition,
    magical_cunning_facts,
    stealth_test,
)
from rulehall.engines.sheet import Gauge

FOE_COUNT_MAX = 8
LASTING: Tier = "long-rest"
SEEDED_CONDITION: Slug = "sheet-condition"
CAPTIVES = "captives"
ROUTED = "routed"
BATTLE_OVER = (
    "The battle is over. Tell how it ended from WHAT HAPPENED, in a few sentences. The player "
    "watched every blow, so do not tell the fight again. Settle nothing else."
)
HERO_FALLS = "The hero died in the battle. Tell the death from WHAT HAPPENED, and end the story."
DEFEAT_NOTE = (
    "The party lost the battle{yielded}. The foes still standing here hold the party now and are "
    "no longer hostile: play what they do, such as a capture, a robbery, or leaving the party for "
    "dead. A defeat never kills by itself."
)
ESCAPE_NOTE = "The party escaped the battle."
GOT_AWAY = "The party escaped the battle and got away."
LEFT_BEHIND = (
    " Left behind at {place}, out of the party at 1 HP: {names}. Play their fate; join_party "
    "takes one back."
)
FOLLOWERS = " Followers: {names}. Play their fate: they leave the party, are captured, or stay."

type Fate = Literal["drops", "surrenders", "flees"]


def start_battle(world: Lite5eWorld, args: StartBattle, rng: Random) -> list[Fact]:
    if world.battle is not None:
        raise Refusal("a battle is already on")
    ambush = args.opening == "foe_ambush"
    groups = [_require_foe_here(world, foe_id, ambush=ambush) for foe_id in args.foe_ids]
    members = world.members()
    foes = _foes_of(world, groups)
    combatants: list[FoeCombatant | MemberCombatant] = [
        MemberCombatant(combatant_id=member.id, row=member.formation_row) for member in members
    ]
    combatants.extend(foes)
    world.battle = Battle(
        order=[combatant.combatant_id for combatant in combatants],
        combatants=combatants,
        effects=_seeded_effects(world, members, foes),
        phase="foes",
        light=raised_light(world.current.light, int(world.party_lit())),
        cover=world.current.cover,
    )
    fight = require_fight(world, rng)
    match args.opening:
        case "face_to_face":
            surprised: list[Slug] = []
            facts = [told("The battle begins face to face")]
        case "party_ambush":
            surprised, facts = _party_ambush(world, fight, groups, rng)
        case "foe_ambush":
            surprised, facts = _foe_ambush(world, groups, rng)
    for group in groups:
        if group.routed:
            facts.extend(check_morale(fight, group.id, "rout"))
    facts.extend(_fiendish_vigor_facts(members))
    world.battle.facts.extend(facts)
    world.long_rest_earned = True
    return [*facts, *roll_initiative(fight, surprised)]


def require_fight(world: Lite5eWorld, rng: Random) -> Fight:
    if world.battle is None:
        raise Refusal("no battle is on")
    return fight_over(world, world.battle, rng)


def fight_over(world: Lite5eWorld, battle: Battle, rng: Random) -> Fight:
    members: dict[Slug, Lite5ePerson] = {}
    for member in battle.member_combatants():
        found = (
            world.player
            if member.combatant_id == world.player.id
            else world.find_person(member.combatant_id)
        )
        if found is None:
            raise ValueError(f"{member.combatant_id} fought and is gone")
        members[member.combatant_id] = found
    return Fight(battle=battle, members=members, rng=rng)


def settle_battle(world: Lite5eWorld, end: BattleEnd, rng: Random) -> tuple[Resolution, list[str]]:
    fight = require_fight(world, rng)
    battle = fight.battle
    outcome = {
        "hero_dead": "The hero falls",
        "victory": "Victory",
        "escape": "The party escapes",
        "defeat": "The party yields" if end.yielded else "Defeat",
    }[end.outcome]
    facts = [told(outcome), *_fates(battle)]
    facts.extend(_battle_xp(world, fight))
    facts.extend(_settle_groups(world, battle, rng))
    facts.extend(_drop_gear(world, battle))
    if end.outcome == "defeat":
        for person in world.npcs.values():
            if person.alive and not person.routed and person.place_id == world.current.id:
                person.hostile = False
    members = [fight.require_member(member.combatant_id) for member in battle.member_combatants()]
    dead_ids = {m.combatant_id for m in battle.member_combatants() if fight.is_dead(m)}
    for member in members:
        vitals = member.require_vitals()
        if member.id not in dead_ids and vitals.hp.current == 0:
            _ = vitals.heal(1)
        _write_back(battle, member)
    behind = [
        fight.require_member(member.combatant_id)
        for member in battle.member_combatants()
        if member.withdrawal is None and member.combatant_id not in dead_ids
    ]
    if end.outcome == "escape":
        for member in behind:
            facts.extend(world.leave_party(member.id))
        facts.extend(_escape_move(world, rng))
    for member in members:
        if member.id in dead_ids:
            card = world.die(member)
            facts.append(member.fact(f"{member.mention} is dead", card=card))
    for member in members:
        if member.id not in dead_ids and member.sheet is not None:
            facts.extend(magical_cunning_facts(member))
    facts.extend(world.level_up())
    notes = _battle_notes(world, end, behind)
    cue = HERO_FALLS if end.outcome == "hero_dead" else " ".join((BATTLE_OVER, *notes))
    world.battle = None
    return Resolution(tuple(facts), cue), notes


def _require_foe_here(world: Lite5eWorld, foe_id: Slug, *, ambush: bool) -> Lite5ePerson:
    if foe_id == world.player.id or foe_id in world.party_ids:
        raise Refusal("a party member never fights the party")
    person = world.require_dweller(foe_id)
    if person.place_id != world.current.id:
        raise Refusal(f"{person.name} is not here with the player")
    _ = person.stat_block()
    if ambush and person.known:
        raise Refusal(f"{person.name} is not hidden: a foe ambush takes hidden foes only")
    if not ambush and not person.known:
        raise Refusal(f"{person.name} is hidden: open with a foe ambush, or reveal it first")
    return person


def _foes_of(world: Lite5eWorld, groups: Sequence[Lite5ePerson]) -> list[FoeCombatant]:
    taken: set[str] = {*world.npcs, world.player.id}
    foes: list[FoeCombatant] = []
    for group in groups:
        block = group.stat_block()
        made = foe_ids(group.id, group.count, taken)
        taken.update(made)
        foes.extend(
            FoeCombatant(
                combatant_id=combatant_id,
                person_id=group.id,
                name=group.name
                if group.count == 1
                else f"{group.name} {combatant_id.rsplit('-', 1)[1]}",
                group_name=group.name,
                stat_block_id=group.stat_block_id,
                row=starting_row(block),
                hp=Gauge(current=block.hit_points, maximum=block.hit_points),
            )
            for combatant_id in made
        )
    return foes


def _seeded_effects(
    world: Lite5eWorld, members: Sequence[Lite5ePerson], foes: Sequence[FoeCombatant]
) -> list[Effect]:
    effects: list[Effect] = []
    holders = [(member.id, member) for member in members]
    holders.extend((foe.combatant_id, world.npcs[foe.person_id]) for foe in foes)
    for holder_id, person in holders:
        effects.extend(
            Effect(
                holder_id=holder_id,
                source_id=holder_id,
                effect_id=SEEDED_CONDITION,
                condition=held.condition,
                tier=held.tier,
            )
            for held in person.conditions
        )
        if person.sheet is not None:
            effects.extend(
                Effect(
                    holder_id=holder_id,
                    source_id=held.source_id,
                    effect_id=held.effect_id,
                    tier=held.tier,
                )
                for held in person.sheet.effects
            )
    for _, person in holders:
        person.conditions.clear()
        if person.sheet is not None:
            person.sheet.effects.clear()
    return effects


def _party_ambush(
    world: Lite5eWorld, fight: Fight, groups: Sequence[Lite5ePerson], rng: Random
) -> tuple[list[Slug], list[Fact]]:
    watch = max(world.passive_perception(group) for group in groups)
    tests = [
        (
            member,
            member.roll_check(
                "dexterity",
                "stealth",
                None,
                watch,
                "none",
                rng,
                guided=False,
                bardic_die=None,
                in_battle=False,
            ),
        )
        for member in world.members()
    ]
    numbers = "; ".join(f"{member.name} {test.total}" for member, test in tests)
    dice = tuple(event for _, test in tests for event in test.dice)
    facts = [Fact(trace=f"party ambush: Stealth {numbers} vs passive Perception {watch}")]
    names = " and ".join(group.name for group in groups)
    if not all(test.success for _, test in tests):
        return [], [*facts, told(f"The party's ambush is spotted by {names}", dice)]
    battle = fight.battle
    for member in world.members():
        battle.effects.append(hidden_effect(member.id))
    line = f"The party strikes from hiding; {names} are surprised"
    return [foe.combatant_id for foe in battle.foes()], [*facts, told(line, dice)]


def _foe_ambush(
    world: Lite5eWorld, groups: Sequence[Lite5ePerson], rng: Random
) -> tuple[list[Slug], list[Fact]]:
    totals: list[int] = []
    dice: list[DiceEvent] = []
    for group in groups:
        total = group.stealth_total
        if total is None:
            test = stealth_test(group, rng)
            total = test.total
            dice.extend(test.dice)
        totals.append(total)
    stealth = min(totals)
    watches = [(member, world.passive_perception(member)) for member in world.members()]
    surprised = [member for member, watch in watches if watch <= stealth]
    numbers = "; ".join(f"{member.name} {watch}" for member, watch in watches)
    facts: list[Fact] = [
        Fact(trace=f"foe ambush: Stealth {stealth} vs passive Perception {numbers}")
    ]
    for group in groups:
        facts.extend(group.reveal())
    names = " and ".join(group.name for group in groups)
    caught = ", ".join(member.name for member in surprised)
    line = f"{names} strike from hiding; " + (
        f"surprised: {caught}" if caught else "nobody is surprised"
    )
    facts.append(told(line, tuple(dice)))
    return [member.id for member in surprised], facts


def _battle_groups(world: Lite5eWorld, battle: Battle) -> list[Lite5ePerson]:
    group_ids = dict.fromkeys(foe.person_id for foe in battle.foes())
    return [world.npcs[group_id] for group_id in group_ids if world.npcs[group_id].alive]


def _fates(battle: Battle) -> list[Fact]:
    # The battle facts already showed each fate as a card; the narrator still reads it here.
    return [
        Fact(trace=f"{foe.name} {fate}", told=True)
        for foe in battle.foes()
        if (fate := _fate(foe)) is not None
    ]


def _battle_xp(world: Lite5eWorld, fight: Fight) -> list[Fact]:
    battle = fight.battle
    earned = sum(
        foe.stat_block().xp
        for foe in battle.foes()
        if _fate(foe) is not None and not world.npcs[foe.person_id].xp_paid
    )
    alive = [m for m in battle.member_combatants() if not fight.is_dead(m)]
    share = earned // len(alive) if alive else 0
    if not share or all(member.combatant_id != world.player.id for member in alive):
        return []
    world.player.require_sheet().gain_xp(share)
    return [Fact(trace="The party earns XP from the battle", told=True, card=f"+{share} XP each")]


def _settle_groups(world: Lite5eWorld, battle: Battle, rng: Random) -> list[Fact]:
    facts: list[Fact] = []
    for group in _battle_groups(world, battle):
        foes = [foe for foe in battle.foes() if foe.person_id == group.id]
        fates = [_fate(foe) for foe in foes]
        surrendered = fates.count("surrenders")
        fled = fates.count("flees")
        gone = fates.count("drops")
        gone += surrendered if _kind_id(group, CAPTIVES) != group.id else 0
        gone += fled if _kind_id(group, ROUTED) != group.id else 0
        if surrendered:
            facts.extend(_gather(world, group, CAPTIVES, surrendered)[1])
        if fled:
            routed, gathered = _gather(world, group, ROUTED, fled)
            way, rolled = _way_out(world, rng)
            facts.extend((*gathered, *rolled))
            if way is not None:
                facts.append(world.walk(routed, way))
        _lay_lasting(group, [e for foe in foes for e in battle.effects_on(foe.combatant_id)])
        if gone < group.count:
            group.count -= gone
        elif fates.count("drops") >= group.count:
            facts.append(group.fact(f"{group.mention} is no more", card=world.die(group)))
        else:
            facts.extend(_disband(world, group))
    return facts


def _disband(world: Lite5eWorld, group: Lite5ePerson) -> list[Fact]:
    facts = [Fact(trace=f"{group.ref} is gone: its last members surrendered or fled")]
    for item in list(world.carried(group.id)):
        item.holder_id = world.current.id
        facts.append(item.fact(f"{item.mention} fell loose here"))
    del world.npcs[group.id]
    return facts


def _gather(
    world: Lite5eWorld, group: Lite5ePerson, kind: str, count: int
) -> tuple[Lite5ePerson, list[Fact]]:
    kind_id = _kind_id(group, kind)
    found = world.npcs.get(kind_id)
    if found is group:
        if kind == ROUTED and not group.routed:
            group.routed = True
            group.name += ROUTED_NAME_SUFFIX
        return group, []
    if found is not None and found.alive:
        scattered = found.count + count - FOE_COUNT_MAX
        found.count = min(found.count + count, FOE_COUNT_MAX)
        found.place_id = world.current.id
        if scattered <= 0:
            return found, []
        line = f"{scattered} more scatter"
        return found, [found.fact(f"{scattered} more of {found.mention} scatter", card=line)]
    made = group.model_copy(
        deep=True,
        update={
            "id": kind_id,
            "name": group.name + (ROUTED_NAME_SUFFIX if kind == ROUTED else f", {kind}"),
            "count": count,
            "place_id": world.current.id,
            "known": True,
            "hostile": kind == ROUTED,
            "captive": kind == CAPTIVES,
            "routed": kind == ROUTED,
            "xp_paid": True,
            "conditions": [],
        },
    )
    world.npcs[kind_id] = made
    return made, made.reveal()


def _way_out(world: Lite5eWorld, rng: Random) -> tuple[Lite5ePlace | None, list[Fact]]:
    ways = [way for way in world.ways.get(world.current.id, ()) if not way.locked]
    if not ways:
        return None, []
    rolled = roll((len(ways),), "way out", rng)
    return world.require_place(ways[rolled.total - 1].to_id), [rolled.fact]


def _drop_gear(world: Lite5eWorld, battle: Battle) -> list[Fact]:
    names: Counter[str] = Counter()
    for foe in battle.foes():
        dropped_on_surrender = _is_kind(foe.person_id, CAPTIVES)
        if dropped_on_surrender or _fate(foe) not in ("drops", "surrenders"):
            continue
        for gear_id in foe.stat_block().gear_drops:
            name = gear_name(gear_id)
            names[
                world.add_item(name, f"dropped by {foe.name}", world.current.id, gear_id).name
            ] += 1
    counted = [name + (f" x{count}" if count > 1 else "") for name, count in names.items()]
    return [told(f"Left on the ground: {', '.join(counted)}")] if counted else []


def _write_back(battle: Battle, member: Lite5ePerson) -> None:
    held = battle.effects_on(member.id)
    _lay_lasting(member, held)
    sheet = member.sheet
    if sheet is None:
        return
    sheet.concentration_spell_id = None
    kept = {
        effect.effect_id: effect.source_id
        for effect in held
        if effect.tier == LASTING and effect.condition is None
    }
    sheet.effects[:] = [
        SheetEffect(effect_id=effect_id, source_id=source_id, tier=LASTING)
        for effect_id, source_id in kept.items()
    ]


def _escape_move(world: Lite5eWorld, rng: Random) -> list[Fact]:
    way, facts = _way_out(world, rng)
    if way is None:
        return facts
    return [*facts, *world.move(way.id, ()), *world.notice_strangers(rng)]


def _battle_notes(world: Lite5eWorld, end: BattleEnd, behind: Sequence[Lite5ePerson]) -> list[str]:
    followers = [member.name for member in world.party_members() if not member.has_sheet]
    tail = FOLLOWERS.format(names=", ".join(followers)) if followers else ""
    match end.outcome:
        case "defeat":
            yielded = " and yields" if end.yielded else ""
            return [DEFEAT_NOTE.format(yielded=yielded) + tail]
        case "escape":
            if not behind and not followers:
                return [GOT_AWAY]
            names = ", ".join(member.name for member in behind)
            left = LEFT_BEHIND.format(place=world.current.name, names=names) if behind else ""
            return [ESCAPE_NOTE + left + tail]
        case "victory" | "hero_dead":
            return []


def _fate(foe: FoeCombatant) -> Fate | None:
    if foe.withdrawal == "surrendered":
        return "surrenders"
    if foe.withdrawal == "fled":
        return "flees"
    return "drops" if foe.hp.current == 0 else None


def _kind_id(group: Lite5ePerson, kind: str) -> Slug:
    return group.id if _is_kind(group.id, kind) else f"{group.id}-{kind}"


def _is_kind(person_id: Slug, kind: str) -> bool:
    return person_id.endswith(f"-{kind}")


def _lay_lasting(person: Lite5ePerson, effects: Sequence[Effect]) -> None:
    person.conditions.clear()
    for effect in effects:
        if effect.tier == LASTING and effect.condition is not None:
            lay_condition(person, effect.condition, LASTING)


def _fiendish_vigor_facts(members: Sequence[Lite5ePerson]) -> list[Fact]:
    facts: list[Fact] = []
    for member in members:
        sheet = member.sheet
        if (
            sheet is None
            or FIENDISH_VIGOR not in sheet.pick_ids("invocation")
            or not sheet.gain_temp_hp(FIENDISH_VIGOR_HP)
        ):
            continue
        line = f"Fiendish Vigor: temporary HP {sheet.temp_hp}"
        facts.append(member.fact(f"{member.mention}: Fiendish Vigor", card=member.card_line(line)))
    return facts
