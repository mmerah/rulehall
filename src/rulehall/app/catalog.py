import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from rulehall.core.game import AnyGame, AnyScenario, ScenarioDescription
from rulehall.core.stores import Library, SaveStore
from rulehall.core.validation import EngineId, Refusal, Slug, for_engine_of
from rulehall.core.views import Look
from rulehall.engines.engine import AnyEngine

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: Slug
    engine_id: EngineId
    name: str
    brief: str
    engine_title: str
    look: Look


@dataclass(frozen=True, slots=True)
class PackEntry:
    id: Slug
    engine_id: EngineId
    name: str
    engine_title: str
    written: bool


@dataclass(frozen=True, slots=True)
class SavedGameKey:
    scenario_id: Slug
    character_id: Slug

    @property
    def save_id(self) -> str:
        return f"{self.scenario_id}--{self.character_id}"


@dataclass(frozen=True, slots=True)
class SaveOption:
    key: SavedGameKey
    scenario_label: str
    character_label: str
    turn: int
    where: str
    engine_title: str


@dataclass(frozen=True, slots=True)
class LauncherCatalog:
    scenarios: tuple[CatalogEntry, ...]
    characters: tuple[CatalogEntry, ...]
    packs: tuple[PackEntry, ...]
    saves: tuple[SaveOption, ...]
    unresumable: tuple[str, ...]

    def require_scenario(self, scenario_id: Slug) -> CatalogEntry:
        found = next((entry for entry in self.scenarios if entry.id == scenario_id), None)
        if found is None:
            raise Refusal(f"unknown scenario {scenario_id!r}")
        return found

    def characters_for(self, engine_id: EngineId) -> tuple[CatalogEntry, ...]:
        return tuple(entry for entry in self.characters if entry.engine_id == engine_id)

    def key_for(self, scenario_id: Slug, character_id: Slug) -> SavedGameKey:
        engine_id = self.require_scenario(scenario_id).engine_id
        if character_id not in {entry.id for entry in self.characters_for(engine_id)}:
            raise Refusal(f"no character {character_id!r} is written for the {engine_id!r} rules")
        return SavedGameKey(scenario_id=scenario_id, character_id=character_id)

    @classmethod
    def read(
        cls,
        library: Library,
        store: SaveStore,
        engines: Mapping[EngineId, AnyEngine],
        scenario_models: Mapping[EngineId, type[AnyScenario]],
    ) -> Self:
        on_disk = dict(library.read_scenarios(scenario_models))
        scenarios = tuple(
            CatalogEntry(
                id=scenario_id,
                engine_id=scenario.engine_id,
                name=scenario.description.title,
                brief=scenario.description.premise,
                engine_title=engines[scenario.engine_id].title,
                look=engines[scenario.engine_id].look,
            )
            for scenario_id, scenario in on_disk.items()
        )
        descriptions = {
            scenario_id: scenario.description for scenario_id, scenario in on_disk.items()
        }
        characters = tuple(
            CatalogEntry(
                id=character_id,
                engine_id=engine_id,
                name=header.person.name,
                brief=header.person.brief,
                engine_title=engines[engine_id].title,
                look=engines[engine_id].look,
            )
            for character_id, engine_id, header in library.read_characters(engines)
        )
        packs = tuple(
            PackEntry(
                id=pack_id,
                engine_id=engine.id,
                name=pack.name,
                engine_title=engine.title,
                written=pack_id in engine.packs.written_ids,
            )
            for engine in engines.values()
            for pack_id, pack in engine.packs.installed.items()
        )
        titles = {(entry.id, entry.engine_id): entry.name for entry in characters}
        played_by = {entry.id: entry.engine_id for entry in scenarios}
        saves: list[SaveOption] = []
        unresumable: list[str] = []
        for save_id in store.save_ids():
            try:
                option = _save_option(save_id, store, engines, titles, played_by, descriptions)
            except Refusal as unreadable:
                LOGGER.warning("skipping save %r: %s", save_id, unreadable)
                unresumable.append(save_id)
            else:
                if option is not None:
                    saves.append(option)
        return cls(
            scenarios=scenarios,
            characters=characters,
            packs=packs,
            saves=tuple(saves),
            unresumable=tuple(unresumable),
        )


def scenario_models(engines: Mapping[EngineId, AnyEngine]) -> dict[EngineId, type[AnyScenario]]:
    return {engine_id: engine.scenario_model for engine_id, engine in engines.items()}


def check_resumes(state: AnyGame, save_id: str, description: ScenarioDescription) -> SavedGameKey:
    key = SavedGameKey(scenario_id=state.scenario_id, character_id=state.character_id)
    if key.save_id != save_id:
        raise Refusal(f"save is {key.save_id!r}, filed as {save_id!r}")
    state.scenario_description.check_drift(description)
    return key


def _save_option(
    save_id: str,
    store: SaveStore,
    engines: Mapping[EngineId, AnyEngine],
    titles: Mapping[tuple[Slug, EngineId], str],
    played_by: Mapping[Slug, EngineId],
    descriptions: Mapping[Slug, ScenarioDescription],
) -> SaveOption | None:
    raw = store.read(save_id)
    if raw is None:
        # Gone between `save_ids()` and `read`: listing it would hide a Start that works.
        return None
    engine = for_engine_of(raw, engines)
    state = engine.restore(raw)
    title = titles.get((state.character_id, state.engine_id))
    if played_by.get(state.scenario_id) != state.engine_id or title is None:
        raise Refusal("its scenario or character is gone")
    return SaveOption(
        key=check_resumes(state, save_id, descriptions[state.scenario_id]),
        scenario_label=state.scenario_description.title,
        character_label=title,
        turn=len(state.log_entries()),
        where=state.chapters[-1].title,
        engine_title=engine.title,
    )
