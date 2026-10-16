from collections.abc import Sequence
from random import Random
from typing import Literal, Self

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import DiceEvent, Fact, roll
from rulehall.core.game import Game
from rulehall.core.prompt import lines_of
from rulehall.core.validation import Frozen, Refusal, Slug, slug
from rulehall.core.views import Rows
from rulehall.engines.bases.maps.world import (
    OFF_MAP_ID,
    Item,
    MapProposal,
    MapWorld,
    Place,
    RegionProposal,
    Way,
)
from rulehall.engines.lite5e.args import (
    GEAR_ID,
    AbilityCheck,
    CastSpell,
    CertainDanger,
    CoinChange,
    DifficultyDc,
    FallDanger,
    FontOfMagic,
    GearGift,
    GearUse,
    GoalReward,
    Harm,
    HitDie,
    InspirationReward,
    KeyedWay,
    LayOnHands,
    LevelPick,
    MakeItem,
    SaveDanger,
    SaveThreat,
    Trade,
    TrapDanger,
    Unprepare,
)
from rulehall.engines.lite5e.battle.specs import DISCIPLE_OF_LIFE_BASE
from rulehall.engines.lite5e.battle.state import (
    Battle,
)
from rulehall.engines.lite5e.data import (
    Ability,
    Condition,
    DamageType,
    Gear,
    GearId,
    Skill,
    Spell,
    StoryBoon,
    Tier,
    TimedCondition,
    dice_parts,
    raised_dice,
    srd,
)
from rulehall.engines.lite5e.hire import SheetProposal, StatBlockHire
from rulehall.engines.lite5e.pack import Background
from rulehall.engines.lite5e.rules import (
    COIN_CAP_CP,
    DIFFICULTY_DC,
    ENCOUNTER_BUDGET,
    LAY_ON_HANDS_CURE,
    LIFE_DOMAIN,
    MAX_EXHAUSTION,
    MAX_LEVEL,
    SHORT_RESTS_PER_LONG_REST,
    SKILL_ABILITY,
    XP_FOR_LEVEL,
    Difficulty,
    Edge,
    GoalSize,
    Light,
    companion_cr_fits,
    damage_d6s,
    level_for_xp,
)
from rulehall.engines.lite5e.sheet import (
    PASSIVE_BASE,
    Lite5ePerson,
    Lite5eSheet,
    TestRoll,
    check_name,
    combined_edge,
    gear_name,
    roll_healing,
    roll_test,
)
from rulehall.engines.sheet import PLAYER_ID

type CheckRoute = Literal["word", "find", "lock", "disarm", "person"]

THIEVES_TOOLS: Slug = "thieves-tools"
SIGHT_SKILLS: frozenset[Skill] = frozenset({"perception", "investigation"})
INFLUENCE_SKILLS: frozenset[Skill] = frozenset(
    {"deception", "intimidation", "performance", "persuasion"}
)
CONCEAL_SKILLS: frozenset[Skill] = frozenset({"stealth", "sleight-of-hand"})
GRAB_SKILLS: frozenset[Skill] = frozenset({"athletics", "acrobatics"})
TAMED_TYPES = ("beast", "monstrosity")
INFLUENCE_DC = 15
UNABLE: frozenset[Condition] = frozenset(
    {"incapacitated", "paralyzed", "petrified", "stunned", "unconscious"}
)
CONDITION_TIER: dict[Condition, Tier] = {"poisoned": "place", "prone": "turn"}
FALL_FEET_PER_DIE = 10
FALL_DICE_MAX = 20


class Hazard(SaveThreat):
    disarm: Difficulty = Field(description="How hard it is to disarm.")


class Lite5eItem(Item):
    find: Difficulty | None = Field(
        default=None,
        description="How hard this hidden item is to notice. A hidden item needs it. The party "
        "notices it on arrival when its best passive Perception is at least the word's DC; a "
        "search finds it with a check against the same DC. Null for a known item.",
    )
    trap: Hazard | None = Field(
        default=None, description="The hazard when this hidden item is a trap. Null otherwise."
    )
    gear: GearId | None = Field(
        default=None,
        description=f"Loot: the SRD gear or magic item that this item is. {GEAR_ID} Null: a "
        "story item with no rules.",
    )
    opens: SkipJsonSchema[KeyedWay | None] = None

    def rows(self) -> Rows:
        return (
            *((("find", self.find),) if not self.known and self.find is not None else ()),
            *((("gear", gear_name(self.gear)),) if self.gear is not None else ()),
            *((("trap", _hazard_text(self.trap)),) if self.trap is not None else ()),
        )


class Lite5ePlace(Place):
    light: Light = Field(default="bright", description="The light of this place.")
    cover: bool = Field(
        default=False,
        description="True when it has cover to hide behind in a battle, such as crates, pillars "
        "or brush.",
    )
    shop: tuple[GearId, ...] | None = Field(
        default=None,
        description="The magic items its shop sells. A shop sells SRD gear at SRD prices and "
        f"the magic items listed here; an empty list sells no magic. Null: no shop. {GEAR_ID}",
    )

    def rows(self) -> Rows:
        if self.shop is None:
            shop = "none"
        else:
            shop = (
                ", ".join(("SRD gear", *map(gear_name, self.shop)))
                if self.shop
                else "SRD gear, no magic"
            )
        return (("light", self.light), ("cover", "yes" if self.cover else "no"), ("shop", shop))


class Lite5eWay(Way):
    """One way out, in one direction, from the place it is filed under."""

    lock: Difficulty | None = Field(
        default=None,
        description="How hard the lock of this locked way is to pick or force. Null: no lock "
        "to pick; only the story opens it.",
    )

    def lock_text(self) -> str:
        lock = f", lock: {self.lock}" if self.locked and self.lock is not None else ""
        return super().lock_text() + lock


class Goal(Frozen):
    brief: str = Field(min_length=1, description="What the party must do, in one line.")
    size: GoalSize = Field(description="How much XP it pays, for the party's level.")


class TurnBoon(Frozen):
    holder_id: Slug
    boon: StoryBoon


class SettledCheck(Frozen):
    actor_id: Slug
    label: str
    target: str
    what: str
    success: bool

    def repeats(self, earlier: Self) -> bool:
        return (self.actor_id, self.label, self.target) == (
            earlier.actor_id,
            earlier.label,
            earlier.target,
        )


class Lite5eMapProposal(MapProposal[Lite5ePerson, Lite5eItem, Lite5ePlace, Lite5eWay]):
    goals: dict[Slug, Goal] = Field(
        default_factory=dict,
        description="Goals the party can complete, keyed by a new goal id. Each one pays XP "
        "once, by its size.",
    )


class Lite5eRegionProposal(
    Lite5eMapProposal, RegionProposal[Lite5ePerson, Lite5eItem, Lite5ePlace, Lite5eWay]
):
    pass


class Lite5eWorld(MapWorld[Lite5ePerson, Lite5eItem, Lite5ePlace, Lite5eWay]):
    goals: dict[Slug, Goal] = Field(default_factory=dict)
    paid_goal_ids: list[Slug] = Field(default_factory=list)
    settled: list[SettledCheck] = Field(default_factory=list)
    exhausted_place_ids: list[Slug] = Field(default_factory=list)
    long_rest_earned: bool = False
    short_rests_since_long_rest: int = Field(default=0, ge=0)
    hit_dice_due: bool = False
    prepare_due: bool = False
    grown_sheet: Lite5eSheet | None = None
    turn_boons: list[TurnBoon] = Field(default_factory=list)
    battle: Battle | None = None

    def apply_opening_extras(self, opening: Lite5eMapProposal, rng: Random) -> None:
        self.goals.update(opening.goals)
        _ = self._arrival_check(told=False)
        _ = self.notice_strangers(rng)

    def apply_next_extras(self, region: Lite5eRegionProposal) -> None:
        self.goals.update(region.goals)

    def members(self) -> list[Lite5ePerson]:
        return [self.player, *self.hired_party_members()]

    def party_level(self) -> int:
        return self.player.require_sheet().level

    def party_lit(self) -> bool:
        return any(
            member.sheet is not None and member.sheet.carries_light() for member in self.members()
        )

    def light_of(self, person: Lite5ePerson) -> Light:
        return person.light_seen(self.current.light, party_lit=self.party_lit())

    def passive_perception(self, person: Lite5ePerson) -> int:
        return person.passive_perception(self.light_of(person))

    def find_dc(self, entity: Lite5ePerson | Lite5eItem) -> int | None:
        if entity.find is not None:
            return DIFFICULTY_DC[entity.find]
        return entity.stealth_total if isinstance(entity, Lite5ePerson) else None

    def goal_lines(self) -> str:
        return "\n".join(
            f"- {goal_id} ({goal.size}): {goal.brief}"
            for goal_id, goal in self.goals.items()
            if goal_id not in self.paid_goal_ids
        )

    def check(self, args: AbilityCheck, rng: Random) -> list[Fact]:
        stranger = self._unrolled_stranger(args)
        if stranger is None:
            return self._roll_check(args, rng)
        noticed = self.notice_strangers(rng)
        return noticed if stranger.known else [*noticed, *self._roll_check(args, rng)]

    def _unrolled_stranger(self, args: AbilityCheck) -> Lite5ePerson | None:
        if args.target_id is None or args.skill not in SIGHT_SKILLS:
            return None
        stranger = self.npcs.get(args.target_id)
        return stranger if stranger is not None and self._is_stranger(stranger) else None

    def _is_stranger(self, npc: Lite5ePerson) -> bool:
        return self._is_hidden_here(npc) and self.find_dc(npc) is None

    def _is_unchecked_walk_in(self, npc: Lite5ePerson) -> bool:
        return self._is_hidden_here(npc) and npc.find is not None and not npc.missed

    def _is_hidden_here(self, npc: Lite5ePerson) -> bool:
        return npc.alive and not npc.known and npc.place_id == self.current.id

    def _best_watch(self) -> tuple[Lite5ePerson, int]:
        watcher = max(self.members(), key=self.passive_perception)
        return watcher, self.passive_perception(watcher)

    def _roll_check(self, args: AbilityCheck, rng: Random) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        ability = self._check_ability(actor, args)
        dc, route = self._route(args)
        failed = SettledCheck(
            actor_id=actor.id,
            label=args.skill or args.tool_id or ability,
            target=args.target_id or args.what.casefold(),
            what=args.what,
            success=False,
        )
        if any(failed.repeats(done) and not done.success for done in self.settled):
            raise Refusal(f"{actor.name} already failed this here. Move or rest first.")
        edges: list[Edge] = [args.edge]
        notes = [f"{args.edge}: {args.edge_reason}"] if args.edge != "none" else []
        if args.helper_id is not None:
            helper = self._require_helper(actor, args.helper_id, args.skill, args.tool_id)
            edges.append("advantage")
            notes.append(f"helped by {helper.name}")
        if (
            args.skill == "intimidation"
            and TurnBoon(holder_id=actor.id, boon="booming-voice") in self.turn_boons
        ):
            edges.append("advantage")
            notes.append("Booming Voice")
        sight = args.skill in SIGHT_SKILLS or route == "find"
        light = self.light_of(actor)
        if sight and light == "dark":
            self.settled.append(failed)
            return [_member_fact(actor, f"{args.what} — too dark to see → failure")]
        if sight and light == "dim":
            edges.append("disadvantage")
            notes.append("dim light")
        guidance = TurnBoon(holder_id=actor.id, boon="guidance")
        guided = guidance in self.turn_boons
        if guided:
            self.turn_boons.remove(guidance)
        test = actor.roll_check(
            ability,
            args.skill,
            args.tool_id,
            dc,
            combined_edge(*edges),
            rng,
            guided=guided,
            bardic_die=None,
            in_battle=False,
        )
        self.settled.append(failed.model_copy(update={"success": test.success}))
        shown = f"{args.what} — {check_name(ability, args.skill, args.tool_id)}"
        facts = _test_facts(actor, shown, test, notes, secret=route != "word")
        if test.success and args.target_id is not None:
            facts.extend(self._apply_success(route, args.target_id, args.skill))
        return facts

    def harm(self, args: Harm, rng: Random) -> list[Fact]:
        members = [self.require_actor(actor_id) for actor_id in args.actor_ids]
        match args.danger:
            case TrapDanger(hazard_id=hazard_id):
                return self._save(members, self._require_trap_here(hazard_id), rng, trap=True)
            case SaveDanger() as danger:
                return self._save(members, danger, rng, trap=False)
            case CertainDanger(damage=size, damage_type=damage_type, reason=reason):
                dice = damage_d6s(size, self.party_level())
                return [_harm_fact(member, dice, damage_type, reason, rng) for member in members]
            case FallDanger(falling_feet=feet):
                dice = min(feet // FALL_FEET_PER_DIE, FALL_DICE_MAX)
                reason = f"a {feet} ft fall"
                return [_harm_fact(member, dice, "bludgeoning", reason, rng) for member in members]

    def _save(
        self,
        members: Sequence[Lite5ePerson],
        danger: Hazard | SaveDanger,
        rng: Random,
        *,
        trap: bool,
    ) -> list[Fact]:
        ability, damage, damage_type = danger.ability, danger.damage, danger.damage_type
        here = self.current
        if danger.on_fail == "exhaustion" and here.id in self.exhausted_place_ids:
            raise Refusal(
                f"a save at {here.name} already added an Exhaustion level since the last rest"
            )
        dc = DIFFICULTY_DC[danger.difficulty]
        condition = danger.on_fail
        exhausted = False
        facts: list[Fact] = []
        for member in members:
            test = member.roll_save(
                ability,
                dc,
                "none",
                rng,
                against=condition,
                bardic_die=None,
            )
            dice = list(test.dice)
            numbers = f"{ability} save {test.total} vs DC {dc}"
            line = f"{ability} save → {_outcome(success=test.success)}"
            if damage != "none" and damage_type is not None:
                dice_count = damage_d6s(damage, self.party_level())
                harm, event = _roll_harm(
                    member, dice_count, damage_type, "damage", rng, halved=test.success
                )
                dice.append(event)
                line += f"; {harm}"
            if not test.success and condition is not None:
                line += self._afflict(member, condition)
                if condition == "exhaustion" and member.sheet is not None:
                    exhausted = True
            if trap:
                facts.append(Fact(trace=f"{member.ref}: {numbers}", dice=tuple(dice)))
                dice = []
            else:
                line = line.replace(f"{ability} save", numbers, 1)
            facts.append(_member_fact(member, line, tuple(dice)))
        if exhausted:
            self.exhausted_place_ids.append(here.id)
        return facts

    def cast(self, args: CastSpell, rng: Random) -> list[Fact]:
        caster = self.require_actor(args.actor_id)
        sheet = caster.require_sheet()
        spell = srd().require_spell(args.spell_id)
        ritual = _is_ritual_cast(spell, args.slot_level)
        known = (*sheet.castable_spell_ids(), *(sheet.class_spell_ids() if ritual else ()))
        if args.spell_id not in known:
            raise Refusal(f"{spell.name} is not in this caster's spells")
        if spell.battle is not None and spell.battle.healing_dice is None:
            raise Refusal(f"{spell.name} is a battle spell: wait for the battle")
        cast_level, from_slot = self._pay_for(sheet, args.spell_id, spell, args.slot_level)
        self._check_targets(spell, cast_level, args.target_ids)
        facts = [_member_fact(caster, f"casts {spell.name}")]
        if from_slot:
            facts.extend(magical_cunning_facts(caster))
        if spell.concentration:
            sheet.concentration_spell_id = args.spell_id
        if spell.battle is not None:
            bonus = sheet.modifier(sheet.spell_ability(args.spell_id))
            if from_slot and LIFE_DOMAIN in sheet.feature_ids():
                bonus += DISCIPLE_OF_LIFE_BASE + cast_level
            facts.extend(
                self._heal(target, spell, cast_level, bonus, rng)
                for target in self._member_targets(caster, args.target_ids)
            )
            return facts
        if spell.story_boon is not None:
            holders = (
                self._member_targets(caster, args.target_ids)
                if spell.range == "touch"
                else [caster]
            )
            self.turn_boons.extend(
                TurnBoon(holder_id=holder.id, boon=spell.story_boon) for holder in holders
            )
        dc = sheet.spell_save_dc(args.spell_id)
        return [*facts, *self._story_effect(spell, args.target_ids, dc, rng)]

    def rest(self, kind: Literal["short", "long"], rng: Random) -> list[Fact]:
        if near := self._foes_near():
            raise Refusal(f"no rest while a hostile person is near: {', '.join(near)}")
        if kind == "short":
            if self.short_rests_since_long_rest >= SHORT_RESTS_PER_LONG_REST:
                raise Refusal(f"{SHORT_RESTS_PER_LONG_REST} short rests at most between long rests")
            return self._short_rest()
        if not self.long_rest_earned:
            raise Refusal(
                "a long rest needs a battle or a first visit to a place since the last long rest"
            )
        group = self._nearest_hunter()
        if group is None:
            return self._long_rest()
        rolled = roll((6,), "long rest", rng)
        if rolled.face != 1:
            return [rolled.fact, *self._long_rest()]
        group.place_id = self.current.id
        line = f"The long rest is broken: {group.name} walks in"
        return [
            rolled.fact,
            *group.reveal(),
            group.fact(f"{group.mention} walks in and breaks the long rest", card=line),
        ]

    def inspire(self, args: InspirationReward) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        sheet = actor.require_sheet()
        if sheet.inspiration:
            raise Refusal(f"{actor.name} already holds Heroic Inspiration")
        if sheet.inspired_since_long_rest:
            raise Refusal(f"{actor.name} had Heroic Inspiration since the last long rest")
        sheet.inspiration = True
        sheet.inspired_since_long_rest = True
        return [_member_fact(actor, f"Heroic Inspiration — {args.reason}")]

    def complete_goal(self, args: GoalReward) -> list[Fact]:
        goal = self.goals.get(args.goal_id)
        if goal is None:
            raise Refusal(f"{args.goal_id!r} is no goal; goals: {sorted(self.goals)}")
        if args.goal_id in self.paid_goal_ids:
            raise Refusal(f"the goal {args.goal_id!r} is already paid")
        self.paid_goal_ids.append(args.goal_id)
        share = ENCOUNTER_BUDGET[self.party_level()][goal.size]
        self.player.require_sheet().gain_xp(share)
        line = f"Goal done: {goal.brief} — +{share} XP each"
        return [self.player.fact(line, card=line), *self.level_up()]

    def move_item(self, item_id: Slug, holder_id: Slug) -> list[Fact]:
        if not self.require_item_here(item_id).known:
            raise Refusal(f"{item_id!r} is hidden; the party must find it first")
        facts = super().move_item(item_id, holder_id)
        gear_id = self.items[item_id].gear
        sheets = {member.id: member.sheet for member in self.members() if member.sheet is not None}
        if gear_id is not None and holder_id in sheets:
            sheets[holder_id].add_gear(gear_id, 1)
            del self.items[item_id]
        return facts

    def trade(self, args: Trade) -> list[Fact]:
        stock = self._require_shop()
        actor = self.require_actor(args.actor_id)
        sheet = actor.require_sheet()
        coins = self.player.require_sheet()
        price = _price_cp(args.gear_id, args.count)
        name = gear_name(args.gear_id)
        match args.kind:
            case "sell":
                sheet.remove_gear(args.gear_id, args.count)
                coins.coins_cp += price // 2
                line = f"Sold {args.count} {name} for {coins_text(price // 2)}"
            case "buy":
                if srd().is_magic_gear(args.gear_id) and args.gear_id not in stock:
                    names = ", ".join(map(gear_name, stock)) or "no magic"
                    raise Refusal(f"this shop does not sell {name}; it sells {names}")
                if coins.coins_cp < price:
                    raise Refusal(
                        f"{name} costs {coins_text(price)}; the party holds "
                        f"{coins_text(coins.coins_cp)}"
                    )
                coins.coins_cp -= price
                sheet.add_gear(args.gear_id, args.count)
                line = f"Bought {args.count} {name} for {coins_text(price)}"
        return [_member_fact(actor, line)]

    def change_coins(self, args: CoinChange) -> list[Fact]:
        if abs(args.cp) > COIN_CAP_CP:
            raise Refusal(f"one change is {coins_text(COIN_CAP_CP)} at most")
        sheet = self.player.require_sheet()
        if sheet.coins_cp + args.cp < 0:
            raise Refusal(f"the party holds only {coins_text(sheet.coins_cp)}")
        sheet.coins_cp += args.cp
        sign = "+" if args.cp > 0 else "-"
        line = f"{sign}{coins_text(abs(args.cp))} — {args.reason}"
        return [self.player.fact(line, card=line)]

    def unlock_by_story(self, to_id: Slug) -> list[Fact]:
        here_id = self.current.id
        way = self.find_way(here_id, to_id)
        has_key = any(
            item.opens is not None and item.opens.joins(here_id, to_id)
            for member in self.members()
            for item in self.carried(member.id)
        )
        if way is not None and way.locked and way.lock is not None and not has_key:
            raise Refusal(
                "that way has a lock: pick or force it with `check`, or open it with its story "
                "key that a party member carries"
            )
        return self.unlock_way(to_id)

    def opens_offscreen(self, way: Lite5eWay) -> bool:
        return way.lock is None

    def make_item(self, args: MakeItem) -> list[Fact]:
        holder_id = args.holder_id
        if holder_id == self.current.id:
            holder_name = self.current.name
        elif holder_id == self.player.id:
            holder_name = self.player.name
        else:
            holder_name = self.require_person_here(holder_id).name
        names = {entry.name.casefold() for table in srd().gear.tables() for entry in table.values()}
        if args.name.casefold() in names:
            raise Refusal(f"{args.name} is SRD gear: only the world, shops and foes give it")
        if args.opens is not None:
            start = self.require_place(args.opens.from_id)
            end = self.require_place(args.opens.to_id)
            keyed = self.find_way(start.id, end.id)
            if keyed is None or not keyed.locked or keyed.lock is None:
                raise Refusal(f"no locked way with a lock leads from {start.name} to {end.name}")
        item = self.add_item(args.name, args.note, holder_id, None)
        item.opens = args.opens
        line = f"{args.name} → {holder_name}"
        return [item.fact(f"{item.mention} is made: {args.note}", card=line)]

    def move(self, to_id: Slug, with_ids: tuple[Slug, ...]) -> list[Fact]:
        if to_id not in self.visited_place_ids:
            self.long_rest_earned = True
        facts = super().move(to_id, with_ids)
        self.settled.clear()
        for npc in self.npcs.values():
            npc.stealth_total = None
        for member in self.members():
            member.conditions[:] = [kept for kept in member.conditions if kept.tier != "place"]
            if member.sheet is not None:
                member.sheet.end_effects("place")
        return [*facts, *self._arrival_check(told=True)]

    def walk(self, npc: Lite5ePerson, place: Lite5ePlace) -> Fact:
        fact = super().walk(npc, place)
        npc.stealth_total = None
        npc.missed = False
        return fact

    def notice_strangers(self, rng: Random) -> list[Fact]:
        here = list(self.at(self.current.id))
        walk_ins = [npc for npc in here if self._is_unchecked_walk_in(npc)]
        strangers = [npc for npc in here if self._is_stranger(npc)]
        if not walk_ins and not strangers:
            return []
        watcher, score = self._best_watch()
        watch = f"best passive Perception {score} ({watcher.ref})"
        facts: list[Fact] = []
        for npc in walk_ins:
            dc = self.find_dc(npc)
            facts.append(Fact(trace=f"{npc.ref}: find DC {dc} vs {watch}"))
            if dc is not None and score < dc:
                npc.missed = True
            else:
                facts.extend(self._noticed(watcher, npc))
        for stranger in strangers:
            test = stealth_test(stranger, rng)
            facts.append(
                Fact(trace=f"{stranger.ref}: Stealth {test.total} vs {watch}", dice=test.dice)
            )
            if score < test.total:
                stranger.stealth_total = test.total
            else:
                facts.extend(self._noticed(watcher, stranger))
        return facts

    def _noticed(self, watcher: Lite5ePerson, entity: Lite5ePerson | Lite5eItem) -> list[Fact]:
        return [
            *entity.reveal(),
            Fact(
                trace=f"{watcher.mention} notices {entity.mention}",
                told=True,
                card=watcher.card_line(f"Noticed {entity.name}"),
            ),
        ]

    def die(self, person: Lite5ePerson) -> str:
        card = super().die(person)
        return f"{person.name} are dead" if person.count > 1 else card

    def kill(self, entity_id: Slug) -> list[Fact]:
        if entity_id == self.player.id or entity_id in self.party_ids:
            raise Refusal("a party member never dies by this tool")
        person = self.require_person_here(entity_id)
        if not person.captive:
            raise Refusal(f"{person.name} stands free; only a captive dies by this tool")
        return super().kill(entity_id)

    def add_item(self, name: str, brief: str, holder_id: Slug, gear_id: Slug | None) -> Lite5eItem:
        item_id = self.new_id(name)
        item = Lite5eItem(
            id=item_id, name=name, brief=brief, holder_id=holder_id, known=True, gear=gear_id
        )
        self.items[item_id] = item
        return item

    def level_up(self) -> list[Fact]:
        target = level_for_xp(self.player.require_sheet().xp)
        facts: list[Fact] = []
        hero_grew = False
        for member in self.members():
            sheet = member.sheet
            if sheet is None or sheet.level >= target:
                continue
            sheet.level_to(target)
            hero_grew = hero_grew or member.id == self.player.id
            facts.append(member.card_fact(f"{member.name} reaches level {target}"))
        if hero_grew and not self.hero_picking():
            self.grown_sheet = self.player.require_sheet().written_back()
        return facts

    def hero_picking(self) -> bool:
        sheet = self.player.require_sheet()
        return sheet.find_level_pick_kind() is not None

    def level_pick(self, args: LevelPick) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        line = actor.require_sheet().level_pick(args.kind, args.pick_id)
        if actor.id == self.player.id and not self.hero_picking():
            self.grown_sheet = self.player.require_sheet().written_back()
        return [_member_fact(actor, line)]

    def finish_rest(self) -> None:
        self.hit_dice_due = False
        self.prepare_due = False

    def spend_hit_die(self, args: HitDie, rng: Random) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        sheet = actor.require_sheet()
        rolled = sheet.spend_hit_die(rng)
        return [_member_fact(actor, f"Hit Die → HP {sheet.vitals.hp}", (rolled.event,))]

    def unprepare(self, args: Unprepare) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        return [_member_fact(actor, actor.require_sheet().unprepare(args.drop_id))]

    def use_gear(self, args: GearUse, rng: Random) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        sheet = actor.require_sheet()
        match args.kind:
            case "equip":
                return [_member_fact(actor, sheet.equip(args.gear_id))]
            case "unequip":
                return [_member_fact(actor, sheet.unequip(args.gear_id))]
            case "drink":
                name = gear_name(args.gear_id)
                healing = sheet.spend_drink(args.gear_id)
                if healing is None:
                    return [_member_fact(actor, f"drinks {name}")]
                amount, event = roll_healing(healing, name, rng)
                healed = sheet.vitals.heal(amount)
                line = f"drinks {name}: +{healed} HP → {sheet.vitals.hp}"
                return [_member_fact(actor, line, (event,))]
            case "drop":
                sheet.remove_gear(args.gear_id, 1)
                name = gear_name(args.gear_id)
                _ = self.add_item(name, f"dropped by {actor.name}", self.current.id, args.gear_id)
                return [_member_fact(actor, f"drops {name} here")]

    def lay_on_hands(self, args: LayOnHands) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        target = self.require_actor(args.target_id)
        sheet = actor.require_sheet()
        if args.cure:
            held = target.conditions
            poisoned = next((kept for kept in held if kept.condition == "poisoned"), None)
            if poisoned is None:
                raise Refusal(f"{target.name} is not poisoned")
            sheet.spend_use("lay-on-hands", LAY_ON_HANDS_CURE)
            held.remove(poisoned)
            return [_member_fact(actor, f"Lay On Hands: {target.name} is no longer poisoned")]
        vitals = target.vitals
        if vitals is None or vitals.hp.shortfall == 0:
            raise Refusal(f"{target.name} has no HP to heal")
        amount = min(vitals.hp.shortfall, sheet.uses_left("lay-on-hands"))
        sheet.spend_use("lay-on-hands", amount)
        healed = vitals.heal(amount)
        return [_member_fact(actor, f"Lay On Hands: {target.name} +{healed} HP → {vitals.hp}")]

    def font_of_magic(self, args: FontOfMagic) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        return [_member_fact(actor, actor.require_sheet().make_slot(args.slot_level))]

    def give(self, args: GearGift) -> list[Fact]:
        actor = self.require_actor(args.actor_id)
        receiver = self.require_actor(args.to_id)
        if receiver.id == actor.id:
            raise Refusal(f"{actor.name} already holds it")
        actor.require_sheet().remove_gear(args.gear_id, 1)
        receiver.require_sheet().add_gear(args.gear_id, 1)
        return [_member_fact(actor, f"gives {gear_name(args.gear_id)} to {receiver.name}")]

    def end_turn(self) -> None:
        self.turn_boons.clear()
        for person in (self.player, *self.npcs.values()):
            person.conditions[:] = [kept for kept in person.conditions if kept.tier != "turn"]

    def new_id(self, name: str) -> Slug:
        return slug(name, (*self.places, *self.npcs, *self.items, PLAYER_ID, OFF_MAP_ID))

    def split_from_group(self, group: Lite5ePerson) -> Lite5ePerson:
        if group.count < 2:
            raise Refusal(f"{group.name} is no group")
        person_id = self.new_id(group.id)
        number = person_id.rsplit("-", 1)[1]
        person = group.model_copy(
            deep=True,
            update={"id": person_id, "name": f"{group.name} {number}", "count": 1},
        )
        group.count -= 1
        self.npcs[person.id] = person
        return person

    def sign_on(
        self,
        person: Lite5ePerson,
        hire: SheetProposal | StatBlockHire,
        backgrounds: Sequence[Background],
    ) -> str:
        level = self.party_level()
        match hire:
            case SheetProposal():
                sheet = hire.build_sheet(level, backgrounds)
                sheet.coins_cp = 0
                person.sheet = sheet
                summary = (
                    f"{sheet.srd_class().name} {level}, "
                    f"{srd().character_options.species[sheet.species_id].name}, "
                    f"{hire.require_background(backgrounds).name}"
                )
            case StatBlockHire():
                block = person.stat_block()
                if not companion_cr_fits(block.challenge_rating, level):
                    raise Refusal(
                        f"{person.name} is too strong to hire at level {level}: hire a class "
                        "companion, or someone weaker"
                    )
                person.fill_stat_block_hp()
                summary = f"fights as a {block.name}"
        person.hostile = False
        person.regroup()
        person.captive = False
        return summary

    def line(self, entity: Lite5ePerson | Lite5eItem) -> str:
        if isinstance(entity, Lite5eItem):
            return entity.line()
        rows = (*entity.master_rows(), *self._world_rows(entity))
        return "\n".join(
            (f"- {entity.headline}", *(f"  {label.lower()}: {value}" for label, value in rows))
        )

    def carrying_lines(self) -> str:
        return lines_of(
            item.line(detail=f"carried by {member.name}")
            for member in self.members()
            for item in self.carried(member.id)
        )

    def settled_lines(self) -> str:
        return lines_of(
            f"- {(self.find_person(done.actor_id) or self.player).name}: "
            f"{done.what} ({done.label}) → {_outcome(success=done.success)}"
            for done in self.settled
        )

    def group_difficulty(self, person: Lite5ePerson) -> str:
        members = len(self.members())
        budget = ENCOUNTER_BUDGET[self.party_level()]
        xp = person.stat_block().xp * person.count
        met = [size.title() for size, share in budget.items() if xp >= share * members]
        return met[-1] if met else "below Low"

    def _world_rows(self, person: Lite5ePerson) -> Rows:
        if person.id != self.player.id and person.id not in self.party_ids:
            return (("difficulty", f"{self.group_difficulty(person)} for the party"),)
        seen = (
            ("passive Perception", str(self.passive_perception(person))),
            ("light", self.light_of(person)),
        )
        if person.id != self.player.id:
            return seen
        sheet = person.require_sheet()
        upcoming = (
            f"next level at {XP_FOR_LEVEL[sheet.level + 1]}"
            if sheet.level < MAX_LEVEL
            else "top level"
        )
        return (
            *seen,
            ("coins", coins_text(sheet.coins_cp)),
            ("XP", f"{sheet.xp}, {upcoming}"),
            ("long rest", "ready" if self.long_rest_earned else "not yet"),
            ("short rests left", str(SHORT_RESTS_PER_LONG_REST - self.short_rests_since_long_rest)),
        )

    def _check_ability(self, actor: Lite5ePerson, args: AbilityCheck) -> Ability:
        if args.tool_id is not None:
            tool = srd().gear.gear.get(args.tool_id)
            if tool is None or tool.group != "tool":
                raise Refusal(f"{args.tool_id!r} is no SRD tool")
            if actor.sheet is None or not actor.sheet.gear.get(args.tool_id):
                raise Refusal(f"{actor.name} does not carry {tool.name}")
            if args.skill is None:
                assert tool.ability is not None
                return tool.ability
        if args.skill is not None:
            return SKILL_ABILITY[args.skill]
        assert args.ability is not None
        return args.ability

    def _route(self, args: AbilityCheck) -> tuple[int, CheckRoute]:
        if isinstance(args.dc, DifficultyDc):
            return DIFFICULTY_DC[args.dc.difficulty], "word"
        target_id = args.dc.target_id
        here = self.current
        skill, tool_id = args.skill, args.tool_id
        if (way := self.find_way(here.id, target_id)) is not None:
            if not way.locked or way.lock is None:
                raise Refusal("that way has no lock to open: give a difficulty instead")
            if tool_id != THIEVES_TOOLS and skill != "athletics":
                raise Refusal("pick a lock with thieves-tools, or force it with athletics")
            return DIFFICULTY_DC[way.lock], "lock"
        entity = self.require_entity(target_id)
        if (
            isinstance(entity, Place)
            or entity.id == self.player.id
            or (entity.id in self.party_ids)
        ):
            raise Refusal("a check targets a hidden thing, a trap, a person or a locked way")
        holder = entity.holder_id if isinstance(entity, Item) else self.npcs[entity.id].place_id
        if holder not in self.holders_here():
            raise Refusal(f"{entity.name} is not here")
        if not entity.known:
            if skill not in SIGHT_SKILLS:
                raise Refusal("search for a hidden thing with perception or investigation")
            find_dc = self.find_dc(entity)
            if find_dc is None:
                raise Refusal(f"{entity.name} has no find DC: reveal it when the story finds it")
            return find_dc, "find"
        if isinstance(entity, Lite5eItem) and (hazard := entity.trap) is not None:
            if tool_id != THIEVES_TOOLS and skill != "sleight-of-hand":
                raise Refusal("disarm a trap with thieves-tools or sleight-of-hand")
            return DIFFICULTY_DC[hazard.disarm], "disarm"
        if not isinstance(entity, Lite5ePerson):
            raise Refusal(f"{entity.name} sets no DC: give a difficulty instead")
        return self._person_dc(entity, skill), "person"

    def _person_dc(self, person: Lite5ePerson, skill: Skill | None) -> int:
        block = person.stat_block()
        if skill in INFLUENCE_SKILLS or (
            skill == "animal-handling" and block.creature_type in TAMED_TYPES
        ):
            return max(INFLUENCE_DC, block.scores["intelligence"])
        if skill in CONCEAL_SKILLS:
            return self.passive_perception(person)
        if skill == "insight":
            return PASSIVE_BASE + block.check_bonus("charisma", "deception")
        if skill in GRAB_SKILLS:
            raise Refusal(f"to grab or push {person.name} is a fight, not a check")
        raise Refusal(
            "against a person, check deception, intimidation, performance, persuasion, insight, "
            "stealth, sleight-of-hand, or animal-handling on a beast or monstrosity"
        )

    def _apply_success(self, route: CheckRoute, target_id: Slug, skill: Skill | None) -> list[Fact]:
        match route:
            case "find":
                entity = self.require_entity(target_id)
                found = "found" if isinstance(entity, Item) else "discovered"
                return entity.reveal(card=f"{entity.name} {found}")
            case "lock":
                return self.unlock_way(target_id)
            case "disarm":
                item = self.require_item(target_id)
                item.trap = None
                return [item.fact(f"{item.mention} is disarmed", card=f"{item.name} disarmed")]
            case "person":
                person = self.require_person_here(target_id)
                if skill != "intimidation" or not person.routed:
                    return []
                person.routed = False
                person.captive = True
                return [person.card_fact(f"{person.name} gives up and is held captive")]
            case "word":
                return []

    def _require_helper(
        self, actor: Lite5ePerson, helper_id: Slug, skill: Skill | None, tool_id: Slug | None
    ) -> Lite5ePerson:
        helper = self.require_actor(helper_id)
        if helper.id == actor.id:
            raise Refusal(f"{actor.name} cannot help themselves")
        if any(kept.condition in UNABLE for kept in helper.conditions):
            raise Refusal(f"{helper.name} is not able to help")
        if helper.sheet is not None:
            proficient = (skill is None or skill in helper.sheet.skills()) and (
                tool_id is None or tool_id in helper.sheet.tool_ids()
            )
        else:
            proficient = tool_id is None and (
                skill is None or skill in helper.stat_block().skill_bonuses
            )
        if not proficient:
            raise Refusal(f"{helper.name} lacks the proficiency to help")
        return helper

    def _require_trap_here(self, hazard_id: Slug) -> Hazard:
        item = self.items.get(hazard_id)
        if item is None or item.trap is None or item.holder_id not in self.holders_here():
            raise Refusal(f"{hazard_id!r} is no trap here")
        return item.trap

    def _afflict(self, member: Lite5ePerson, condition: Condition) -> str:
        if condition == "exhaustion":
            if member.sheet is None:
                return ""
            member.sheet.exhaustion = min(member.sheet.exhaustion + 1, MAX_EXHAUSTION)
            return f"; exhaustion {member.sheet.exhaustion}"
        lay_condition(member, condition, CONDITION_TIER[condition])
        return f"; {condition}"

    def _pay_for(
        self, sheet: Lite5eSheet, spell_id: Slug, spell: Spell, slot_level: int | None
    ) -> tuple[int, bool]:
        if _is_ritual_cast(spell, slot_level):
            return spell.level, False
        if slot_level is None:
            if spell.level == 0 or sheet.has_free_cast(spell_id):
                slot_level = spell.level
            else:
                open_levels = sheet.cast_slot_levels(spell_id, slot_open=True)
                slot_level = open_levels[0] if open_levels else spell.level
        return slot_level, sheet.pay_cast(spell_id, slot_level, slot_open=True)

    def _check_targets(self, spell: Spell, cast_level: int, target_ids: Sequence[Slug]) -> None:
        persons = [
            self.npcs[target_id]
            for target_id in target_ids
            if target_id in self.npcs and target_id not in self.party_ids
        ]
        count = len(target_ids) + sum(person.count - 1 for person in persons)
        limit = spell.target_limit(cast_level)
        if limit is not None and count > limit:
            raise Refusal(
                f"{spell.name} at level {cast_level} affects {limit} at most, not {count}: a "
                "group counts each of its members"
            )
        types = spell.targeting().creature_types
        if types and (
            strays := [
                person.name for person in persons if person.stat_block().creature_type not in types
            ]
        ):
            raise Refusal(f"{spell.name} affects only a {' or '.join(types)}, not {strays}")

    def _member_targets(
        self, caster: Lite5ePerson, target_ids: tuple[Slug, ...]
    ) -> list[Lite5ePerson]:
        return [self.require_actor(target_id) for target_id in target_ids] or [caster]

    def _heal(
        self, target: Lite5ePerson, spell: Spell, cast_level: int, bonus: int, rng: Random
    ) -> Fact:
        battle = spell.battle
        assert battle is not None and battle.healing_dice is not None
        dice = raised_dice(battle.healing_dice, battle.higher_level_dice, cast_level - spell.level)
        count, faces = dice_parts(dice)
        rolled = roll((faces,) * count, spell.name, rng)
        vitals = target.require_vitals()
        healed = vitals.heal(rolled.total + bonus)
        return _member_fact(target, f"+{healed} HP → {vitals.hp}", (rolled.event,))

    def _story_effect(
        self,
        spell: Spell,
        target_ids: tuple[Slug, ...],
        dc: int,
        rng: Random,
    ) -> list[Fact]:
        facts: list[Fact] = []
        for target_id in target_ids:
            if target_id == self.player.id or target_id in self.party_ids:
                continue
            if target_id not in self.npcs:
                _ = self.require_item_here(target_id)
                continue
            group = self.require_person_here(target_id)
            if spell.save_ability is not None:
                facts.extend(self._story_saves(spell, spell.save_ability, group, dc, rng))
        facts.append(Fact(trace=f"{spell.name}, as established: {spell.description}"))
        return facts

    def _story_saves(
        self, spell: Spell, ability: Ability, group: Lite5ePerson, dc: int, rng: Random
    ) -> list[Fact]:
        tests = [
            group.roll_save(ability, dc, "none", rng, against=None, bardic_die=None)
            for _ in range(group.count)
        ]
        totals = ", ".join(str(test.total) for test in tests)
        facts = [
            Fact(
                trace=f"{group.ref}: {ability} save {totals} vs DC {dc}",
                dice=tuple(event for test in tests for event in test.dice),
            )
        ]
        failures = sum(not test.success for test in tests)
        if failures in (0, group.count):
            return [*facts, _story_outcome(spell, group, affected=failures > 0)]
        affected = [self.split_from_group(group) for _ in range(failures)]
        return [
            *facts,
            _story_outcome(spell, group, affected=False),
            *(_story_outcome(spell, person, affected=True) for person in affected),
        ]

    def _foes_near(self) -> list[str]:
        here = self.current.id
        near = {here, *(way.to_id for way in self.ways.get(here, ()) if not way.locked)}
        return [npc.name for npc in self.npcs.values() if _threatens(npc) and npc.place_id in near]

    def _nearest_hunter(self) -> Lite5ePerson | None:
        region = set(self.current_region.place_ids)
        distance = {self.current.id: 0}
        pending = [self.current.id]
        while pending:
            place_id = pending.pop(0)
            for way in self.ways.get(place_id, ()):
                if not way.locked and way.to_id in region and way.to_id not in distance:
                    distance[way.to_id] = distance[place_id] + 1
                    pending.append(way.to_id)
        hunters = [
            npc for npc in self.npcs.values() if _threatens(npc) and npc.place_id in distance
        ]
        return min(hunters, key=lambda npc: distance[npc.place_id], default=None)

    def _short_rest(self) -> list[Fact]:
        self.short_rests_since_long_rest += 1
        self.settled.clear()
        self.exhausted_place_ids.clear()
        self.hit_dice_due = True
        return [
            self.player.card_fact("Short rest"),
            *(
                _member_fact(member, f"back: {', '.join(back)}")
                for member in self.members()
                if member.sheet is not None and (back := member.sheet.short_rest())
            ),
        ]

    def _long_rest(self) -> list[Fact]:
        self.long_rest_earned = False
        self.short_rests_since_long_rest = 0
        self.settled.clear()
        self.exhausted_place_ids.clear()
        self.hit_dice_due = False
        for member in self.members():
            member.conditions.clear()
            if member.sheet is not None:
                member.sheet.long_rest()
                self.prepare_due = self.prepare_due or member.sheet.changes_all_prepared()
            elif member.stat_block_vitals is not None:
                member.fill_stat_block_hp()
        for person in self.people():
            person.regroup()
        line = "Long rest: HP, Hit Dice, spell slots and uses come back"
        return [self.player.card_fact(line)]

    def _require_shop(self) -> tuple[Slug, ...]:
        stock = self.current.shop
        if stock is None:
            raise Refusal(f"{self.current.name} has no shop")
        return stock

    def _arrival_check(self, *, told: bool) -> list[Fact]:
        hidden = [
            (entity, dc)
            for entity in self.entities_at(self.current.id)
            if not entity.known and (dc := self.find_dc(entity)) is not None
        ]
        if not hidden:
            return []
        watcher, score = self._best_watch()
        facts = [Fact(trace=f"arrival check: best passive Perception {score} ({watcher.ref})")]
        for entity, dc in hidden:
            if score < dc:
                if isinstance(entity, Lite5ePerson):
                    entity.missed = True
                continue
            if not told:
                entity.known = True
                continue
            facts.extend(self._noticed(watcher, entity))
        return facts


Lite5eGame = Game[Lite5eWorld]


def coins_text(copper: int) -> str:
    gp, rest = divmod(copper, 100)
    sp, cp = divmod(rest, 10)
    parts = [f"{value} {unit}" for value, unit in ((gp, "gp"), (sp, "sp"), (cp, "cp")) if value]
    return " ".join(parts) or "0 gp"


def stealth_test(group: Lite5ePerson, rng: Random) -> TestRoll:
    bonus = group.stat_block().check_bonus("dexterity", "stealth")
    return roll_test("Stealth", bonus, 0, "none", rng)


def _test_facts(
    actor: Lite5ePerson, label: str, test: TestRoll, notes: Sequence[str], *, secret: bool
) -> list[Fact]:
    spends = [f"spent {spend}" for spend in test.spends]
    extra = "".join(f", {note}" for note in (*notes, *spends))
    outcome = _outcome(success=test.success)
    if secret:
        numbers = f"{actor.ref}: {label} {test.total} vs DC {test.dc}"
        line = f"{label}{extra} → {outcome}"
        return [
            Fact(trace=numbers, dice=test.dice),
            actor.fact(f"{actor.mention}: {line}", card=actor.card_line(line)),
        ]
    line = f"{label} {test.total} vs DC {test.dc}{extra} → {outcome}"
    return [actor.fact(f"{actor.mention}: {line}", card=actor.card_line(line), dice=test.dice)]


def _outcome(*, success: bool) -> str:
    return "success" if success else "failure"


def _hazard_text(hazard: Hazard) -> str:
    damage = "" if hazard.damage == "none" else f", {hazard.damage} {hazard.damage_type}"
    on_fail = "" if hazard.on_fail is None else f", {hazard.on_fail} on a failure"
    return (
        f"trap: {hazard.ability} save {hazard.difficulty}{damage}{on_fail}; disarm: {hazard.disarm}"
    )


def _price_cp(gear_id: Slug, count: int) -> int:
    item = srd().require_gear(gear_id)
    bundle = item.bundle if isinstance(item, Gear) else 1
    if count % bundle:
        raise Refusal(f"{item.name} comes in bundles of {bundle}")
    return item.cost.copper() * count // bundle


def lay_condition(person: Lite5ePerson, condition: Condition, tier: Tier) -> None:
    if all(kept.condition != condition for kept in person.conditions):
        person.conditions.append(TimedCondition(condition=condition, tier=tier))


def _is_ritual_cast(spell: Spell, slot_level: int | None) -> bool:
    return spell.level > 0 and spell.ritual and slot_level is None


def _threatens(npc: Lite5ePerson) -> bool:
    return npc.alive and npc.hostile and not npc.captive and not npc.routed


def _story_outcome(spell: Spell, person: Lite5ePerson, *, affected: bool) -> Fact:
    line = f"{person.name} {'is affected' if affected else 'resists'}"
    laid = spell.story_condition
    if affected and laid is not None:
        lay_condition(person, laid.condition, laid.tier)
        line += f": {laid.condition}"
    return person.fact(f"{person.mention}: {line}", card=line)


def magical_cunning_facts(member: Lite5ePerson) -> list[Fact]:
    back = member.require_sheet().recover_pact_slots()
    return [_member_fact(member, f"Pact slots: {back} back")] if back else []


def _roll_harm(
    member: Lite5ePerson,
    dice: int,
    damage_type: DamageType,
    label: str,
    rng: Random,
    *,
    halved: bool,
) -> tuple[str, DiceEvent]:
    rolled = roll((6,) * dice, label, rng)
    amount = rolled.total // 2 if halved else rolled.total
    return f"-{member.take_harm(amount, damage_type)} HP {damage_type}", rolled.event


def _harm_fact(
    member: Lite5ePerson, dice: int, damage_type: DamageType, reason: str, rng: Random
) -> Fact:
    harm, event = _roll_harm(member, dice, damage_type, reason, rng, halved=False)
    return _member_fact(member, f"{reason}: {harm}", (event,))


def _member_fact(member: Lite5ePerson, line: str, dice: tuple[DiceEvent, ...] = ()) -> Fact:
    return member.fact(f"{member.mention}: {line}", card=member.card_line(line), dice=dice)
