from collections.abc import Collection
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import Fact
from rulehall.core.validation import Mutable, Refusal, Slug, check_unique, refuse
from rulehall.core.views import Rows
from rulehall.engines.bases.maps.world import Dweller
from rulehall.engines.pokemon.battle.models import LEVEL_MAX, MOVES_MAX, TEAM_MAX, BattleResult
from rulehall.engines.pokemon.dex import avatars, dex
from rulehall.engines.pokemon.journey.items import (
    ITEMS,
    TM_PREFIX,
    BagId,
    ItemId,
    TmId,
    bag_name,
    item_of,
)
from rulehall.engines.pokemon.journey.mon import Evolving, Learning, Mon
from rulehall.engines.pokemon.journey.rules import (
    BADGE_LEVELS,
    CATCH_UP,
    EXP_PER_LEVEL,
    NICKNAME_MARKS,
    NICKNAME_MAX,
    RANK_MAX,
    SKILLS,
    Challenge,
    RosterSlot,
    Skill,
    level_for,
)
from rulehall.engines.pokemon.rules import check_species, is_legendary
from rulehall.engines.pokemon.trainers import AVATAR_ID, LOSE_LINE, RIVAL, STYLE, WIN_LINE
from rulehall.engines.sheet import Sheeted

ROSTER = (
    "The Pokemon this person battles with, as species and level. Empty for a person who does "
    "not battle."
)
BADGE = "The badge this trainer gives when beaten, such as a gym leader's. Empty for most trainers."
KEY_TRAINER = "key trainer (a gym leader, the rival, an operation's leader or the team's boss)"
TRIAL = (
    "One sentence, only for a gym leader: the trial the challenger meets before the leader, such "
    "as a maze, a quiz or a puzzle a Pokemon solves. Empty for anyone else."
)
DOUBLE = (
    "True for a trainer who always battles two-on-two, such as twins, a pair or a gym that "
    "fights in doubles. Needs a `roster` of at least two."
)
LEGENDARY = (
    "A legendary species id from SPECIES, only for a legendary Pokemon that lives in this map, "
    "one of a kind: no roster, no badge; it battles alone as a wild Pokemon. Null for a person."
)


class JourneySheet(Mutable):
    skills: dict[Skill, Annotated[int, Field(ge=0, le=RANK_MAX)]]
    money: int = Field(ge=0)
    bag: dict[BagId, Annotated[int, Field(ge=1)]]
    badges: list[str] = Field(default_factory=list)
    team: list[Mon] = Field(min_length=1, max_length=TEAM_MAX)
    box: list[Mon] = Field(default_factory=list)
    challenge: Challenge
    caught_species_ids: list[Slug] = Field(min_length=1)
    memorial: list[str] = Field(default_factory=list)
    learning: list[Learning] = Field(default_factory=list)
    evolving: list[Evolving] = Field(default_factory=list)
    ranks_due: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _unique_mons(self) -> Self:
        check_unique("mon ids over the team and the box", self.mon_ids())
        return self

    def require_mon(self, mon_id: Slug) -> Mon:
        return _require_in(self.team, mon_id, "on the team")

    def require_boxed(self, mon_id: Slug) -> Mon:
        return _require_in(self.box, mon_id, "in the box")

    def require_owned(self, mon_id: Slug) -> Mon:
        return _require_in(list(self.owned()), mon_id, "on the team or in the box")

    def table_level(self) -> int:
        return level_for(len(self.badges))

    def level_cap(self) -> int:
        if self.challenge == "relaxed" or len(self.badges) >= len(BADGE_LEVELS):
            return LEVEL_MAX
        return self.table_level()

    def challenge_line(self) -> str:
        cap = self.level_cap()
        return self.challenge if cap == LEVEL_MAX else f"{self.challenge}: level cap {cap}"

    def nickname_refusal(self, mon: Mon, name: str) -> str:
        shaped = name == name.strip() and 0 < len(name) <= NICKNAME_MAX
        if not shaped or not all(char.isalnum() or char in NICKNAME_MARKS for char in name):
            return f"a nickname is 1 to {NICKNAME_MAX} letters, digits, spaces, ' or -"
        folded = name.casefold()
        if any(other is not mon and other.name.casefold() == folded for other in self.owned()):
            return f"another Pokemon of the player is already called {name}"
        if any(species.name.casefold() == folded for species in dex().species.values()):
            return f"{name} is the name of a species"
        return ""

    def able(self) -> list[Mon]:
        return [mon for mon in self.team if not mon.fainted]

    def rankable(self) -> tuple[Skill, ...]:
        return tuple(skill for skill in SKILLS if self.skills.get(skill, 0) < RANK_MAX)

    def owned(self) -> tuple[Mon, ...]:
        return (*self.team, *self.box)

    def catch(self, mon: Mon) -> Literal["team", "box"]:
        self.caught_species_ids.append(mon.species_id)
        if len(self.team) < TEAM_MAX:
            self.team.append(mon)
            return "team"
        self.box.append(mon)
        return "box"

    def mon_ids(self) -> list[Slug]:
        return [mon.mon_id for mon in self.owned()]

    def exp_shares(self, result: BattleResult, *, trainer: bool) -> dict[Slug, int]:
        total = sum(EXP_PER_LEVEL * foe.level for foe in result.defeated_foes())
        if trainer:
            total = total * 3 // 2
        if total == 0:
            return {}
        caught_id = None if result.caught is None else result.caught.mon_id
        table_level = self.table_level()
        return {
            mon.mon_id: total * CATCH_UP if mon.level < table_level else total
            for mon in self.team
            if not mon.fainted and mon.mon_id != caught_id
        }

    def pay(self, cost: int) -> None:
        if cost > self.money:
            raise Refusal(f"that costs ₽{cost}, and the player has only ₽{self.money}")
        self.money -= cost

    def add(self, item_id: BagId, count: int) -> None:
        self.bag[item_id] = self.bag.get(item_id, 0) + count

    def take(self, item_id: BagId) -> None:
        count = self.bag.get(item_id, 0)
        if count == 0:
            raise Refusal(f"the bag holds no {bag_name(item_id)}")
        if count == 1:
            del self.bag[item_id]
        else:
            self.bag[item_id] = count - 1

    def heal_team(self) -> None:
        for mon in self.owned():
            mon.heal()

    def store_refusal(self, mon: Mon) -> str:
        if any(other is not mon for other in self.able()):
            return ""
        return "no other team Pokemon can fight"

    def withdraw_refusal(self, mon: Mon) -> str:
        if len(self.team) < TEAM_MAX:
            return ""
        return f"the team is full; swap {mon.name} in"

    def lead_refusal(self, mon: Mon) -> str:
        return f"{mon.name} leads the team already" if self.team[0] is mon else ""


class JourneyTrainer(Sheeted[JourneySheet], Dweller):
    roster: tuple[RosterSlot, ...] = Field(default=(), max_length=TEAM_MAX, description=ROSTER)
    badge: str = Field(default="", description=BADGE)
    style: str = Field(
        default="",
        description=STYLE.format(key_trainer=KEY_TRAINER, example="sets up rain, then sweeps"),
    )
    trial: str = Field(default="", description=TRIAL)
    win_line: str = Field(default="", description=WIN_LINE.format(key_trainer=KEY_TRAINER))
    lose_line: str = Field(default="", description=LOSE_LINE.format(key_trainer=KEY_TRAINER))
    rival: bool = Field(
        default=False,
        description=RIVAL.format(span="story")
        + " A rival has no `roster`: code builds their team at each battle.",
    )
    double: bool = Field(default=False, description=DOUBLE)
    legendary_id: Slug | None = Field(default=None, description=LEGENDARY)
    avatar_id: Slug = Field(description=AVATAR_ID)
    team: SkipJsonSchema[list[Mon]] = Field(default_factory=list)
    beaten: SkipJsonSchema[bool] = False
    last_battle_visit: SkipJsonSchema[int] = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _a_listed_avatar(self) -> Self:
        if self.sheet is not None and self.avatar_id not in avatars().player:
            raise ValueError(f"{self.avatar_id!r} is no player look")
        if self.sheet is None and self.avatar_id not in avatars().npc_ids():
            raise ValueError(f"{self.avatar_id!r} is no id from TRAINER LOOKS")
        return self

    @model_validator(mode="after")
    def _a_lone_legendary(self) -> Self:
        legendary_id = self.legendary_id
        if legendary_id is None:
            return self
        check_species(legendary_id)
        if not is_legendary(dex().species[legendary_id]):
            raise ValueError(f"`legendary_id` {legendary_id!r} is no legendary species")
        if self.roster or self.badge or self.rival or self.double:
            raise ValueError(
                f"{self.name} is a legendary Pokemon: no roster, no badge, not rival, not double"
            )
        return self

    def is_key(self, named_ids: Collection[Slug]) -> bool:
        return bool(self.badge) or self.rival or self.id in named_ids

    def rows(self) -> Rows:
        sheet = self.sheet
        if sheet is None:
            roster = ", ".join(slot.text() for slot in self.roster)
            legendary_id = self.legendary_id
            shown = (
                ("Legendary", "" if legendary_id is None else dex().species[legendary_id].name),
                ("Team", roster),
                ("Double", "battles two-on-two" if self.double else ""),
                ("Style", self.style),
                ("Trial", self.trial),
                ("Badge", self.badge),
                ("Beaten", "yes" if self.beaten else ""),
            )
            return tuple((label, value) for label, value in shown if value)
        skills = " · ".join(
            f"{skill.title()} {rank}" for skill in SKILLS if (rank := sheet.skills.get(skill, 0))
        )
        return (
            ("Skills", skills),
            ("Money", f"₽{sheet.money}"),
            ("Badges", ", ".join(sheet.badges) or "none"),
            ("Team", ", ".join(mon.summary() for mon in sheet.team)),
            *((("Memorial", "; ".join(sheet.memorial)),) if sheet.memorial else ()),
        )

    def nickname(self, mon_id: Slug, name: str) -> list[Fact]:
        sheet = self.require_sheet()
        mon = sheet.require_owned(mon_id)
        refuse(sheet.nickname_refusal(mon, name))
        before = mon.name
        mon.nickname = name
        return [self.card_fact(f"{before} is now called {name}")]

    def swap_mon(self, team_mon_id: Slug, box_mon_id: Slug) -> list[Fact]:
        sheet = self.require_sheet()
        leaving = sheet.require_mon(team_mon_id)
        joining = sheet.require_boxed(box_mon_id)
        sheet.team[sheet.team.index(leaving)] = joining
        sheet.box[sheet.box.index(joining)] = leaving
        return [self.card_fact(f"{leaving.name} to the box, {joining.name} to the team")]

    def store_mon(self, mon_id: Slug) -> list[Fact]:
        sheet = self.require_sheet()
        mon = sheet.require_mon(mon_id)
        refuse(sheet.store_refusal(mon))
        sheet.team.remove(mon)
        sheet.box.append(mon)
        return [self.card_fact(f"{mon.name} to the box")]

    def withdraw_mon(self, mon_id: Slug) -> list[Fact]:
        sheet = self.require_sheet()
        mon = sheet.require_boxed(mon_id)
        refuse(sheet.withdraw_refusal(mon))
        sheet.box.remove(mon)
        sheet.team.append(mon)
        return [self.card_fact(f"{mon.name} to the team")]

    def lead_mon(self, mon_id: Slug) -> list[Fact]:
        sheet = self.require_sheet()
        mon = sheet.require_mon(mon_id)
        refuse(sheet.lead_refusal(mon))
        sheet.team.remove(mon)
        sheet.team.insert(0, mon)
        return [self.card_fact(f"{mon.name} leads the team")]

    def hold_item(self, mon_id: Slug, item_id: ItemId | None) -> list[Fact]:
        sheet = self.require_sheet()
        mon = sheet.require_mon(mon_id)
        name = mon.name
        if item_id is None:
            if mon.item_id is None:
                raise Refusal(f"{name} holds nothing")
            line = f"Took the {dex().item_name(mon.item_id)} from {name}"
        else:
            item_name = dex().item_name(item_id)
            if ITEMS[item_id].kind != "held":
                raise Refusal(f"{item_name} is not an item to hold")
            refuse(mon.item_refusal(item_id, (), sheet.level_cap()))
            sheet.take(item_id)
            line = f"{name} holds the {item_name}"
        if mon.item_id is not None:
            sheet.add(mon.item_id, 1)
        mon.item_id = item_id
        return [self.card_fact(line)]

    def teach_move(self, mon_id: Slug, item_id: TmId) -> list[Fact]:
        sheet = self.require_sheet()
        if item_id not in sheet.bag:
            raise Refusal(f"the bag holds no {bag_name(item_id)}")
        mon = sheet.require_mon(mon_id)
        refuse(mon.item_refusal(item_id, (), sheet.level_cap()))
        return self._learn_or_ask(mon, item_id.removeprefix(TM_PREFIX))

    def relearn_move(self, mon_id: Slug, move_id: Slug) -> list[Fact]:
        sheet = self.require_sheet()
        mon = sheet.require_mon(mon_id)
        if move_id not in mon.relearnable():
            raise Refusal(f"{mon.name} cannot remember {move_id!r}")
        return self._learn_or_ask(mon, move_id)

    def learn_move(self, mon_id: Slug, move_id: Slug, forget_id: Slug | None) -> list[Fact]:
        sheet = self.require_sheet()
        if sheet.learning[:1] != [Learning(mon_id=mon_id, move_id=move_id)]:
            raise Refusal("no new move waits on this answer")
        mon = sheet.require_mon(mon_id)
        name = mon.name
        move = dex().moves[move_id].name
        if forget_id is None:
            line = f"{name} did not learn {move}"
        else:
            mon.learn(move_id, forget_id)
            line = f"{name} forgot {dex().moves[forget_id].name} and learned {move}"
        _ = sheet.learning.pop(0)
        return [self.card_fact(line)]

    def evolve(self, mon_id: Slug, species_id: Slug, species_ids: Collection[Slug]) -> list[Fact]:
        sheet = self.require_sheet()
        if not any(
            each.mon_id == mon_id and species_id in each.species_ids for each in sheet.evolving[:1]
        ):
            raise Refusal("no evolution waits on this answer")
        mon = sheet.require_mon(mon_id)
        name = mon.name
        mon.evolve(species_id)
        _ = sheet.evolving.pop(0)
        return [
            self.card_fact(f"{name} evolved into {mon.species_name}"),
            *self.evolve_chain(mon, species_ids),
        ]

    def raise_skill(self, skill: Skill) -> list[Fact]:
        sheet = self.require_sheet()
        if not sheet.ranks_due:
            raise Refusal("no skill rank waits")
        rank = sheet.skills.get(skill, 0)
        if rank >= RANK_MAX:
            raise Refusal(f"{skill.title()} is already at rank {RANK_MAX}")
        sheet.skills[skill] = rank + 1
        sheet.ranks_due -= 1
        return [self.card_fact(f"{skill.title()} rises to rank {rank + 1}")]

    def use_item(self, item_id: ItemId, mon_id: Slug, species_ids: Collection[Slug]) -> list[Fact]:
        sheet = self.require_sheet()
        mon = sheet.require_mon(mon_id)
        item, item_name = ITEMS[item_id], dex().item_name(item_id)
        if item.kind in ("ball", "held", "tm"):
            raise Refusal(f"{item_name} is given or taught on the Team page, not used")
        refuse(mon.item_refusal(item_id, species_ids, sheet.level_cap()))
        name = mon.name
        level = mon.level
        sheet.take(item_id)
        match item.kind:
            case "potion":
                healed = mon.hp.adjust(item.heal)
                line = f"{item_name} on {name}: HP +{healed} → {mon.hp}"
            case "full-heal":
                cured, mon.status = mon.status, ""
                line = f"{item_name} on {name}: {cured} cured"
            case "revive":
                mon.hp.current = mon.hp.maximum // 2
                line = f"{item_name} on {name}: HP {mon.hp}"
            case "candy":
                _ = mon.gain((mon.level + 1) ** 3 - mon.exp, sheet.level_cap())
                line = f"{item_name} on {name}: level {mon.level}"
            case "evolution":
                evolved_id = mon.evolution_by_item(species_ids, item_name)
                assert evolved_id is not None
                mon.evolve(evolved_id)
                line = f"{item_name} on {name}: it evolved into {mon.species_name}"
        reached = list(range(level + 1, mon.level + 1))
        return [self.card_fact(line), *self.grow(mon, reached, species_ids)]

    def grow(self, mon: Mon, reached: list[int], species_ids: Collection[Slug]) -> list[Fact]:
        facts: list[Fact] = []
        for level in reached:
            for move_id in mon.moves_at(level):
                if not mon.knows(move_id):
                    facts += self._learn_or_ask(mon, move_id)
        if reached and mon.item_id != "everstone":
            facts += self.evolve_chain(mon, species_ids)
        return facts

    def evolve_chain(self, mon: Mon, species_ids: Collection[Slug]) -> list[Fact]:
        sheet = self.require_sheet()
        facts: list[Fact] = []
        while len(found := mon.evolutions(species_ids)) == 1:
            name = mon.name
            mon.evolve(found[0])
            facts.append(self.card_fact(f"{name} evolved into {mon.species_name}"))
        if len(found) > 1:
            sheet.evolving.append(Evolving(mon_id=mon.mon_id, species_ids=found))
        return facts

    def buy(self, item_id: BagId, count: int) -> list[Fact]:
        sheet = self.require_sheet()
        item = item_of(item_id)
        if not item.price:
            raise Refusal(f"{bag_name(item_id)} is not sold; it is found or given")
        cost = item.price * count
        sheet.pay(cost)
        sheet.add(item_id, count)
        return [self.card_fact(f"Bought {count} {bag_name(item_id)} (₽{cost})")]

    def gain_item(self, item_id: BagId, count: int) -> list[Fact]:
        self.require_sheet().add(item_id, count)
        return [self.card_fact(f"Got {count} {bag_name(item_id)}")]

    def gain_money(self, amount: int) -> list[Fact]:
        self.require_sheet().money += amount
        return [self.card_fact(f"Got ₽{amount}")]

    def _learn_or_ask(self, mon: Mon, move_id: Slug) -> list[Fact]:
        sheet = self.require_sheet()
        if len(mon.moves) < MOVES_MAX:
            mon.learn(move_id)
            return [self.card_fact(f"{mon.name} learned {dex().moves[move_id].name}")]
        sheet.learning.append(Learning(mon_id=mon.mon_id, move_id=move_id))
        return []


def _require_in(mons: list[Mon], mon_id: Slug, where: str) -> Mon:
    found = next((mon for mon in mons if mon.mon_id == mon_id), None)
    if found is None:
        held = ", ".join(mon.mon_id for mon in mons) or "(none)"
        raise Refusal(f"{mon_id!r} is not {where}; {where}: {held}")
    return found
