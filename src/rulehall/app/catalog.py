import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Self

from rulehall.app.illustration import ICON_DIR, find_cover, find_image
from rulehall.core.game import AnyGame, AnyScenario, ScenarioDescription
from rulehall.core.stores import Library, SaveStore
from rulehall.core.validation import EngineId, Refusal, Slug, for_engine_of
from rulehall.engines.engine import AnyEngine
from rulehall.engines.sheet import PLAYER_ID

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: Slug
    engine_id: EngineId
    name: str
    brief: str
    portrait: Path | None = None


@dataclass(frozen=True, slots=True)
class PackEntry:
    id: Slug
    engine_id: EngineId
    name: str
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
    engine_id: EngineId
    saved_at: datetime
    cover: Path | None


@dataclass(frozen=True, slots=True)
class LauncherCatalog:
    scenarios: tuple[CatalogEntry, ...]
    characters: tuple[CatalogEntry, ...]
    packs: tuple[PackEntry, ...]
    saves: tuple[SaveOption, ...]
    unresumable: tuple[str, ...]

    def scenarios_for(self, engine_id: EngineId) -> tuple[CatalogEntry, ...]:
        return tuple(entry for entry in self.scenarios if entry.engine_id == engine_id)

    def characters_for(self, engine_id: EngineId) -> tuple[CatalogEntry, ...]:
        return tuple(entry for entry in self.characters if entry.engine_id == engine_id)

    def packs_for(self, engine_id: EngineId) -> tuple[PackEntry, ...]:
        return tuple(entry for entry in self.packs if entry.engine_id == engine_id)

    def saves_for(self, engine_id: EngineId) -> tuple[SaveOption, ...]:
        return tuple(save for save in self.saves if save.engine_id == engine_id)

    def find_save(self, key: SavedGameKey) -> SaveOption | None:
        return next((save for save in self.saves if save.key == key), None)

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
            )
            for scenario_id, scenario in on_disk.items()
        )
        characters = tuple(
            CatalogEntry(
                id=character_id,
                engine_id=engine_id,
                name=header.person.name,
                brief=header.person.brief,
                portrait=find_image(library.character_folder(character_id) / ICON_DIR, PLAYER_ID),
            )
            for character_id, engine_id, header in library.read_characters(engines)
        )
        packs = tuple(
            PackEntry(
                id=pack_id,
                engine_id=engine.id,
                name=pack.name,
                written=pack_id in engine.packs.written_ids,
            )
            for engine in engines.values()
            for pack_id, pack in engine.packs.installed.items()
        )
        titles = {(entry.id, entry.engine_id): entry.name for entry in characters}
        saves: list[SaveOption] = []
        unresumable: list[str] = []
        for save_id in store.save_ids():
            try:
                option = _save_option(save_id, store, engines, titles, on_disk)
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
            saves=tuple(sorted(saves, key=lambda save: save.saved_at, reverse=True)),
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
    on_disk: Mapping[Slug, AnyScenario],
) -> SaveOption | None:
    raw = store.read(save_id)
    saved_at = store.find_saved_at(save_id)
    if raw is None or saved_at is None:
        # Deleted since `save_ids()`: listing it would hide a Start that works.
        return None
    engine = for_engine_of(raw, engines)
    state = engine.restore(raw)
    title = titles.get((state.character_id, state.engine_id))
    scenario = on_disk.get(state.scenario_id)
    if scenario is None or scenario.engine_id != state.engine_id or title is None:
        raise Refusal("its scenario or character is gone")
    return SaveOption(
        key=check_resumes(state, save_id, scenario.description),
        scenario_label=state.scenario_description.title,
        character_label=title,
        turn=len(state.log_entries()),
        engine_id=engine.id,
        saved_at=saved_at,
        cover=find_cover(store.media_dir(save_id)),
    )
