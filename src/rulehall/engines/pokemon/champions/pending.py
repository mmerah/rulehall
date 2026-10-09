from collections.abc import Collection, Iterable, Sequence
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.validation import Mutable, Refusal, Slug, check_unique, refuse
from rulehall.engines.pokemon.battle.models import Nature
from rulehall.engines.pokemon.champions.data import CompetitiveSet, champions_data
from rulehall.engines.pokemon.dex import NATURES, dex, species_name
from rulehall.engines.pokemon.rules import STAT_NAMES

SPECIES = "species"
ABILITY = "ability"
ITEM = "item"
NATURE = "nature"
MOVES = "moves"
SP = "sp"


class PendingSet(Mutable):
    species_id: Slug
    ability_id: Slug | None = None
    item_id: Slug | None = None
    move_ids: list[Slug] = Field(default_factory=list)
    nature: Nature = "Serious"
    sp: list[int] = Field(
        default_factory=lambda: [0] * len(STAT_NAMES),
        min_length=len(STAT_NAMES),
        max_length=len(STAT_NAMES),
    )

    @model_validator(mode="after")
    def _known_ids(self) -> Self:
        legal = champions_data().legal
        pokedex = dex()
        _ = legal.require_species(self.species_id)
        if self.ability_id is not None and self.ability_id not in pokedex.ability_names:
            raise ValueError(f"{self.ability_id!r} is no ability of the dex")
        if self.item_id is not None and self.item_id not in pokedex.item_names:
            raise ValueError(f"{self.item_id!r} is no item of the dex")
        if unknown := sorted(set(self.move_ids) - set(pokedex.moves)):
            raise ValueError(f"moves the dex lacks: {unknown}")
        check_unique(f"moves of {self.species_id}", self.move_ids)
        if len(self.move_ids) > legal.moves_max:
            raise ValueError(f"a set has at most {legal.moves_max} moves")
        if not all(0 <= points <= legal.sp_max for points in self.sp):
            raise ValueError(f"a stat outside 0 to {legal.sp_max} stat points")
        return self

    @classmethod
    def of_set(cls, competitive_set: CompetitiveSet) -> Self:
        return cls(
            species_id=competitive_set.species_id,
            ability_id=competitive_set.ability_id,
            item_id=competitive_set.item_id,
            move_ids=list(competitive_set.move_ids),
            nature=competitive_set.nature,
            sp=list(competitive_set.sp),
        )

    def competitive(self) -> CompetitiveSet | None:
        if self.ability_id is None or self.item_id is None:
            return None
        return CompetitiveSet(
            species_id=self.species_id,
            ability_id=self.ability_id,
            item_id=self.item_id,
            move_ids=tuple(self.move_ids),
            nature=self.nature,
            sp=tuple(self.sp),
        )

    def errors(self) -> dict[Slug, str]:
        found = {
            ABILITY: self._ability_error(),
            ITEM: self._item_error(),
            MOVES: self._moves_error(),
            SP: self._sp_error(),
        }
        return {field_id: error for field_id, error in found.items() if error}

    def _ability_error(self) -> str:
        if self.ability_id is None:
            return "pick an ability"
        if self.ability_id not in champions_data().legal.species[self.species_id].ability_ids:
            return f"{species_name(self.species_id)} cannot have {_ability_name(self.ability_id)}"
        return ""

    def _item_error(self) -> str:
        if self.item_id is None:
            return "pick an item"
        return item_refusal(self.species_id, self.item_id)

    def _moves_error(self) -> str:
        if not self.move_ids:
            return "pick at least one move"
        learnable = champions_data().legal.species[self.species_id].move_ids
        if unknown := [move_id for move_id in self.move_ids if move_id not in learnable]:
            return f"{species_name(self.species_id)} cannot learn {_move_names(unknown)}"
        return ""

    def _sp_error(self) -> str:
        budget = champions_data().legal.sp_total
        used = sum(self.sp)
        return f"{used} stat points spent, above {budget}" if used > budget else ""


class PendingTeam(Mutable):
    slots: list[PendingSet | None]

    @model_validator(mode="after")
    def _a_team_of_slots(self) -> Self:
        size = champions_data().legal.team_size
        if len(self.slots) != size:
            raise ValueError(f"a pending team has {size} slots, not {len(self.slots)}")
        return self

    @classmethod
    def of_team(cls, sets: Sequence[CompetitiveSet]) -> Self:
        size = champions_data().legal.team_size
        slots: list[PendingSet | None] = [PendingSet.of_set(each) for each in sets]
        return cls(slots=slots + [None] * (size - len(slots)))

    def find_set(self, slot: int) -> PendingSet | None:
        return self.slots[self._index(slot)]

    def require_set(self, slot: int) -> PendingSet:
        found = self.find_set(slot)
        if found is None:
            raise Refusal(f"slot {slot} is empty")
        return found

    def pick(
        self,
        slot: int,
        field_id: Slug,
        choice_ids: Sequence[Slug],
        allowed_species_ids: Collection[Slug] | None,
    ) -> None:
        if field_id == MOVES:
            self._pick_moves(slot, choice_ids)
            return
        if len(choice_ids) != 1:
            raise Refusal(f"pick one {field_id}")
        chosen = choice_ids[0]
        if field_id == SPECIES:
            self._pick_species(slot, chosen, allowed_species_ids)
            return
        pending_set = self.require_set(slot)
        if field_id == ABILITY:
            if chosen not in champions_data().legal.species[pending_set.species_id].ability_ids:
                raise Refusal(
                    f"{species_name(pending_set.species_id)} cannot have {_ability_name(chosen)}"
                )
            pending_set.ability_id = chosen
        elif field_id == ITEM:
            self._refuse_item(slot, pending_set.species_id, chosen)
            pending_set.item_id = chosen
        elif field_id == NATURE:
            pending_set.nature = nature_of(chosen)
        else:
            raise Refusal(f"{field_id!r} is no field of a set")

    def place(
        self,
        slot: int,
        competitive_set: CompetitiveSet,
        allowed_species_ids: Collection[Slug] | None,
    ) -> None:
        refuse(self.species_refusal(slot, competitive_set.species_id, allowed_species_ids))
        self.slots[self._index(slot)] = PendingSet.of_set(competitive_set)

    def set_points(self, slot: int, row: int, points: int) -> None:
        pending_set = self.require_set(slot)
        if row >= len(STAT_NAMES):
            raise Refusal(f"a set has {len(STAT_NAMES)} stats, not row {row}")
        legal = champions_data().legal
        others = sum(pending_set.sp) - pending_set.sp[row]
        pending_set.sp[row] = max(0, min(points, legal.sp_max, legal.sp_total - others))

    def apply_spread(self, slot: int, nature: Nature, sp: Sequence[int]) -> None:
        pending_set = self.require_set(slot)
        pending_set.nature = nature
        pending_set.sp = list(sp)

    def move_slot(self, slot: int, to_slot: int) -> None:
        index, to_index = self._index(slot), self._index(to_slot)
        self.slots.insert(to_index, self.slots.pop(index))

    def clear_slot(self, slot: int) -> None:
        self.slots[self._index(slot)] = None

    def team_errors(self) -> tuple[str, ...]:
        legal = champions_data().legal
        filled = [(number, each) for number, each in enumerate(self.slots, 1) if each is not None]
        bases: dict[Slug, list[int]] = {}
        items: dict[Slug, list[int]] = {}
        for number, each in filled:
            bases.setdefault(legal.species[each.species_id].base_species_id, []).append(number)
            if each.item_id is not None:
                items.setdefault(each.item_id, []).append(number)
        species = (
            f"{species_name(base_id)} is on slots {_numbers(numbers)}"
            for base_id, numbers in bases.items()
            if len(numbers) > 1
        )
        held = (
            f"{dex().item_names[item_id]} is held by slots {_numbers(numbers)}"
            for item_id, numbers in items.items()
            if len(numbers) > 1
        )
        return (*species, *held)

    def field_errors(self, slot: int) -> dict[Slug, str]:
        pending_set = self.find_set(slot)
        if pending_set is None:
            return {}
        clashes = {
            SPECIES: self.species_clash(slot, pending_set.species_id),
            ITEM: "" if pending_set.item_id is None else self.item_clash(slot, pending_set.item_id),
        }
        found = pending_set.errors()
        return found | {
            field_id: clash
            for field_id, clash in clashes.items()
            if clash and field_id not in found
        }

    def completed(self) -> tuple[CompetitiveSet, ...]:
        sets: list[CompetitiveSet] = []
        for number, pending_set in enumerate(self.slots, 1):
            if pending_set is None:
                raise Refusal(f"slot {number} is empty")
            if errors := self.field_errors(number):
                field_id, error = next(iter(errors.items()))
                raise Refusal(f"slot {number}, {field_id}: {error}")
            competitive_set = pending_set.competitive()
            if competitive_set is None:
                raise Refusal(f"slot {number} is incomplete")
            sets.append(competitive_set)
        return tuple(sets)

    def free_preset_index(self, slot: int, species_id: Slug) -> int | None:
        presets = champions_data().presets.get(species_id, ())
        return next(
            (
                index
                for index, preset in enumerate(presets)
                if not self.item_clash(slot, preset.item_id)
            ),
            None,
        )

    def species_clash(self, slot: int, species_id: Slug) -> str:
        species = champions_data().legal.species
        base_id = species[species_id].base_species_id
        numbers = (
            number
            for number, each in enumerate(self.slots, 1)
            if each is not None
            and number != slot
            and species[each.species_id].base_species_id == base_id
        )
        number = next(numbers, None)
        return "" if number is None else f"{species_name(species_id)} is on slot {number}"

    def item_clash(self, slot: int, item_id: Slug) -> str:
        numbers = (
            number
            for number, each in enumerate(self.slots, 1)
            if each is not None and number != slot and each.item_id == item_id
        )
        number = next(numbers, None)
        return "" if number is None else f"{dex().item_names[item_id]} is held by slot {number}"

    def species_refusal(
        self, slot: int, species_id: Slug, allowed_species_ids: Collection[Slug] | None
    ) -> str:
        if allowed_species_ids is not None and species_id not in allowed_species_ids:
            return f"{species_name(species_id)} is not recruited"
        return self.species_clash(slot, species_id)

    def _pick_species(
        self, slot: int, species_id: Slug, allowed_species_ids: Collection[Slug] | None
    ) -> None:
        legal = champions_data().legal
        _ = legal.require_species(species_id)
        refuse(self.species_refusal(slot, species_id, allowed_species_ids))
        index = self._index(slot)
        old = self.slots[index]
        if old is not None and old.species_id == species_id:
            return
        kept = old.ability_id if old is not None else None
        ability_id = kept if kept in legal.species[species_id].ability_ids else None
        self.slots[index] = PendingSet(species_id=species_id, ability_id=ability_id)

    def _pick_moves(self, slot: int, move_ids: Sequence[Slug]) -> None:
        pending_set = self.require_set(slot)
        moves_max = champions_data().legal.moves_max
        if len(move_ids) > moves_max:
            raise Refusal(f"a set has at most {moves_max} moves")
        if len(set(move_ids)) != len(move_ids):
            raise Refusal("a set knows each move once")
        learnable = champions_data().legal.species[pending_set.species_id].move_ids
        if unknown := [move_id for move_id in move_ids if move_id not in learnable]:
            raise Refusal(
                f"{species_name(pending_set.species_id)} cannot learn {_move_names(unknown)}"
            )
        pending_set.move_ids = list(move_ids)

    def _refuse_item(self, slot: int, species_id: Slug, item_id: Slug) -> None:
        if item_id not in dex().item_names:
            raise Refusal(f"{item_id!r} is no item of the dex")
        refuse(item_refusal(species_id, item_id) or self.item_clash(slot, item_id))

    def _index(self, slot: int) -> int:
        if not 1 <= slot <= len(self.slots):
            raise Refusal(f"a team has slots 1 to {len(self.slots)}, not {slot}")
        return slot - 1


def item_refusal(species_id: Slug, item_id: Slug) -> str:
    legal = champions_data().legal
    if item_id not in legal.item_ids:
        return f"{dex().item_names[item_id]} is not legal in the format"
    holders = legal.mega_formes.get(item_id, {})
    if holders and species_id not in holders:
        return "only " + " or ".join(species_name(holder_id) for holder_id in holders)
    return ""


def unowned_refusal(
    species_ids: Iterable[Slug], allowed_species_ids: Collection[Slug] | None
) -> str:
    if allowed_species_ids is None:
        return ""
    missing = dict.fromkeys(each for each in species_ids if each not in allowed_species_ids)
    return "needs: " + ", ".join(map(species_name, missing)) if missing else ""


def nature_of(choice_id: Slug) -> Nature:
    found = next((nature for nature in NATURES if nature.lower() == choice_id), None)
    if found is None:
        raise Refusal(f"{choice_id!r} is no nature")
    return found


def _ability_name(ability_id: Slug) -> str:
    return dex().ability_names.get(ability_id, ability_id)


def _move_names(move_ids: Iterable[Slug]) -> str:
    moves = dex().moves
    return ", ".join(moves[each].name if each in moves else each for each in move_ids)


def _numbers(numbers: Sequence[int]) -> str:
    return " and ".join(str(number) for number in numbers)
