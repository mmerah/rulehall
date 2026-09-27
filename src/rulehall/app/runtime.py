import logging
from asyncio import to_thread
from pathlib import Path
from shutil import rmtree

from rulehall.app.illustration import ICON_DIR, Illustrator
from rulehall.app.launch import LauncherCatalog, LaunchTarget, check_resumes, scenario_models
from rulehall.app.providers import close_client
from rulehall.app.roles import role_answer
from rulehall.app.session import GameService, Gate
from rulehall.app.spawn import RoleRunner, Spawner
from rulehall.config import Settings
from rulehall.core.io import FileStore, Library, PackStore
from rulehall.core.model import AnyScenario, ScenarioDescription
from rulehall.core.source import given_text
from rulehall.core.validation import EngineId, Refusal, Slug, slug
from rulehall.engines.engine import AnyEngine
from rulehall.engines.registry import build_engines

LOGGER = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings: Settings, spawner: Spawner | None = None) -> None:
        self.settings = settings
        self.spawner: Spawner = spawner or RoleRunner(settings)
        self.gate = Gate()
        self.engines = build_engines(settings.packs_dir)
        self.scenario_models = scenario_models(self.engines)
        self.library = Library(settings.scenarios_dir, settings.characters_dir)
        self.store = FileStore(settings.saves_dir)
        self.packs = PackStore(settings.packs_dir)
        self._sessions: dict[str, GameService] = {}

    @property
    def default_engine(self) -> EngineId:
        return next(iter(self.engines))

    async def close(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        await close_client()

    async def delete_save(self, save_id: str) -> None:
        session = self._sessions.get(save_id)
        if session is not None:
            if session.working_role is not None:
                raise Refusal(
                    f"{save_id} is taking a turn. Wait for that turn to end, then delete."
                )
            if session.battle_run is not None:
                raise Refusal(f"{save_id} is in a battle. End that battle, then delete.")
            del self._sessions[save_id]
            await session.close()
        self.store.discard(save_id)
        rmtree(self.store.media_dir(save_id), ignore_errors=True)

    def configure(self, settings: Settings) -> None:
        settings = settings.model_copy(update={"server": self.settings.server})
        self.settings = settings
        if isinstance(self.spawner, RoleRunner):
            self.spawner.settings = settings
        for session in self._sessions.values():
            session.settings = settings
            session.illustrator = session.illustrator.configured(settings)

    def catalog(self) -> LauncherCatalog:
        return LauncherCatalog.read(self.library, self.store, self.engines, self.scenario_models)

    def engine(self, engine_id: EngineId) -> AnyEngine:
        found = self.engines.get(engine_id)
        if found is None:
            raise Refusal(f"no rules {engine_id!r}")
        return found

    async def new_scenario(
        self,
        engine_id: EngineId,
        description: ScenarioDescription,
        document: Path | None,
        pack_id: Slug,
        character_id: Slug,
    ) -> Slug:
        engine = self.engine(engine_id)
        character = self.library.read_character(character_id, engine.id, engine.character)
        engine.packs.require(pack_id)
        source = await to_thread(given_text, description.premise, document)
        scenario_id = slug(description.title, self.library.scenario_ids())

        def check(built: AnyScenario) -> None:
            engine.begin(scenario_id, built, character)

        with self.gate.creation():
            scenario = await engine.write_opening(
                description, source, pack_id, role_answer(self.spawner, "worldsmith"), check
            )
        self.library.write_scenario(scenario_id, scenario)
        LOGGER.info("scenario written: scenario_id=%s title=%r", scenario_id, description.title)
        return scenario_id

    async def new_pack(
        self, engine_id: EngineId, name: str, premise: str, document: Path | None, license: str
    ) -> Slug:
        engine = self.engine(engine_id)
        source = await to_thread(given_text, premise, document)
        pack_id = slug(name, (*engine.packs.installed, *self.packs.ids(engine.id)))
        origin = f"written in this app from {'the premise' if document is None else document.name}"
        with self.gate.creation():
            pack = await engine.write_pack(
                name=name,
                source=source,
                origin=origin,
                license=license,
                worldsmith=role_answer(self.spawner, "worldsmith"),
            )
        self.packs.write(engine.id, pack_id, pack)
        engine.install_pack(pack_id, pack)
        LOGGER.info("pack written: engine=%s slug=%s name=%r", engine.id, pack_id, name)
        return pack_id

    def session(self, target: LaunchTarget) -> GameService:
        """Memoised: a page render must not rebuild the game and drop the running turn."""
        if target.save_id not in self._sessions:
            self._sessions[target.save_id] = self._open(target)
        return self._sessions[target.save_id]

    def _open(self, target: LaunchTarget) -> GameService:
        scenario = self.library.read_scenario(target.scenario_id, self.scenario_models)
        engine = self.engine(scenario.engine_id)
        character = self.library.read_character(target.character_id, engine.id, engine.character)
        saved = self.store.read(target.save_id)
        if saved is None:
            state = engine.begin(target.scenario_id, scenario, character)
        else:
            state = engine.restore(saved)
            check_resumes(state, target.save_id, scenario.description)
        return GameService(
            target=target,
            scenario=scenario,
            character=character,
            engine=engine,
            spawner=self.spawner,
            store=self.store,
            library=self.library,
            state=state,
            gate=self.gate,
            settings=self.settings,
            illustrator=Illustrator.open(
                self.settings,
                self.store,
                target.save_id,
                style=scenario.description.art_style or engine.art_style,
                icon_dirs=(
                    self.library.scenario_folder(target.scenario_id) / ICON_DIR,
                    self.library.character_folder(target.character_id) / ICON_DIR,
                ),
                portraits=engine.portraits,
            ),
        )
