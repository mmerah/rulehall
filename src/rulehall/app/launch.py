import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from rulehall.core.io import FileStore, Library, decode, routed
from rulehall.core.model import AnyGame, ScenarioMeta
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.core.views import Look
from rulehall.engines.engine import AnyEngine

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: Slug
    engine_id: EngineId
    name: str
    brief: str
    rules: str
    look: Look


@dataclass(frozen=True, slots=True)
class PackEntry:
    id: Slug
    engine_id: EngineId
    name: str
    rules: str
    written: bool


@dataclass(frozen=True, slots=True)
class LaunchTarget:
    scenario_id: Slug
    character_id: Slug

    @property
    def slug(self) -> str:
        return f"{self.scenario_id}--{self.character_id}"


@dataclass(frozen=True, slots=True)
class SaveOption:
    target: LaunchTarget
    scenario_label: str
    character_label: str
    turn: int
    where: str
    rules: str


@dataclass(frozen=True, slots=True)
class LauncherCatalog:
    scenarios: tuple[CatalogEntry, ...]
    characters: tuple[CatalogEntry, ...]
    packs: tuple[PackEntry, ...]
    saves: tuple[SaveOption, ...]
    unresumable: tuple[str, ...]

    def scenario(self, scenario_id: Slug) -> CatalogEntry:
        found = next((entry for entry in self.scenarios if entry.id == scenario_id), None)
        if found is None:
            raise Refusal(f"unknown scenario {scenario_id!r}")
        return found

    def characters_for(self, engine_id: EngineId) -> tuple[CatalogEntry, ...]:
        return tuple(entry for entry in self.characters if entry.engine_id == engine_id)

    def target(self, scenario_id: Slug, character_id: Slug) -> LaunchTarget:
        engine_id = self.scenario(scenario_id).engine_id
        if character_id not in {entry.id for entry in self.characters_for(engine_id)}:
            raise Refusal(f"no character {character_id!r} is written for the {engine_id!r} rules")
        return LaunchTarget(scenario_id=scenario_id, character_id=character_id)

    @classmethod
    def read(
        cls, library: Library, store: FileStore, engines: Mapping[EngineId, AnyEngine]
    ) -> Self:
        scenario_models = {engine_id: engine.scenario for engine_id, engine in engines.items()}
        on_disk = dict(library.read_scenarios(scenario_models))
        scenarios = tuple(
            CatalogEntry(
                id=name,
                engine_id=scenario.engine_id,
                name=scenario.meta.title,
                brief=scenario.meta.premise,
                rules=engines[scenario.engine_id].title,
                look=engines[scenario.engine_id].look,
            )
            for name, scenario in on_disk.items()
        )
        metas = {name: scenario.meta for name, scenario in on_disk.items()}
        characters = tuple(
            CatalogEntry(
                id=name,
                engine_id=engine_id,
                name=header.sheet.name,
                brief=header.sheet.brief,
                rules=engines[engine_id].title,
                look=engines[engine_id].look,
            )
            for name, engine_id, header in library.read_characters(engines)
        )
        packs = tuple(
            PackEntry(
                id=pack_id,
                engine_id=engine.id,
                name=pack.name,
                rules=engine.title,
                written=written,
            )
            for engine in engines.values()
            for written, shelf in ((False, engine.packs.shipped), (True, engine.packs.written))
            for pack_id, pack in shelf.items()
        )
        titles = {(entry.id, entry.engine_id): entry.name for entry in characters}
        played_by = {entry.id: entry.engine_id for entry in scenarios}
        saves: list[SaveOption] = []
        unresumable: list[str] = []
        for slug in store.slugs():
            try:
                option = _save_option(slug, store, engines, titles, played_by, metas)
            # Skipped, never deleted: one save that does not resume must not hide the rest.
            except Refusal as unreadable:
                LOGGER.warning("skipping save %r: %s", slug, unreadable)
                unresumable.append(slug)
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


def check_resumes(state: AnyGame, slug: str, meta: ScenarioMeta) -> None:
    actual = LaunchTarget(scenario_id=state.scenario_id, character_id=state.character_id).slug
    if actual != slug:
        raise Refusal(f"save is {actual!r}, filed as {slug!r}")
    state.scenario.check_drift(meta)


def _save_option(
    slug: str,
    store: FileStore,
    engines: Mapping[EngineId, AnyEngine],
    titles: Mapping[tuple[Slug, EngineId], str],
    played_by: Mapping[Slug, EngineId],
    metas: Mapping[Slug, ScenarioMeta],
) -> SaveOption | None:
    raw = store.read(slug)
    if raw is None:
        # Gone between `slugs()` and `read`: listing it would hide a Start that works.
        return None
    engine = routed(decode(raw), engines)
    state = engine.restore(raw)
    title = titles.get((state.character_id, state.engine_id))
    if played_by.get(state.scenario_id) != state.engine_id or title is None:
        raise Refusal("its scenario or character is gone")
    target = LaunchTarget(scenario_id=state.scenario_id, character_id=state.character_id)
    check_resumes(state, slug, metas[state.scenario_id])
    return SaveOption(
        target=target,
        scenario_label=state.scenario.title,
        character_label=title,
        turn=len(state.exchanges()),
        where=state.log[-1].title,
        rules=engine.title,
    )
