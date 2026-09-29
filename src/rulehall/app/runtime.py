import logging
from asyncio import to_thread
from pathlib import Path
from shutil import rmtree

from rulehall.app.catalog import LauncherCatalog, SavedGameKey, check_resumes, scenario_models
from rulehall.app.game_session import GameSession, Gate
from rulehall.app.http_client import close_client
from rulehall.app.illustration import ICON_DIR, Illustrator
from rulehall.app.roles import ProviderRoleRunner, RoleRunner, role_answer
from rulehall.config import LiveSettings, Settings
from rulehall.core.documents import given_text
from rulehall.core.game import AnyScenario, ScenarioDescription
from rulehall.core.stores import Library, PackStore, SaveStore
from rulehall.core.validation import EngineId, Refusal, Slug, slug
from rulehall.engines.engine import AnyEngine
from rulehall.engines.registry import build_engines

LOGGER = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings: Settings, roles: RoleRunner | None = None) -> None:
        self.live_settings = LiveSettings(settings)
        self.roles: RoleRunner = roles or ProviderRoleRunner(self.live_settings)
        self.gate = Gate()
        self.engines = build_engines(settings.packs_dir)
        self.scenario_models = scenario_models(self.engines)
        self.library = Library(settings.scenarios_dir, settings.characters_dir)
        self.store = SaveStore(settings.saves_dir)
        self.packs = PackStore(settings.packs_dir)
        self._sessions: dict[str, GameSession] = {}

    async def close(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        await close_client()

    async def delete_save(self, save_id: str) -> None:
        session = self._sessions.get(save_id)
        if session is not None:
            session.require_idle()
            del self._sessions[save_id]
            await session.close()
        self.store.discard(save_id)
        rmtree(self.store.media_dir(save_id), ignore_errors=True)

    def configure(self, settings: Settings) -> None:
        self.live_settings.current = settings.model_copy(
            update={"server": self.live_settings.current.server}
        )

    def catalog(self) -> LauncherCatalog:
        return LauncherCatalog.read(self.library, self.store, self.engines, self.scenario_models)

    def require_engine(self, engine_id: EngineId) -> AnyEngine:
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
        engine = self.require_engine(engine_id)
        character = self.library.read_character(character_id, engine.id, engine.character_model)
        engine.packs.require_pack(pack_id)
        source = await to_thread(given_text, description.premise, document)
        scenario_id = slug(description.title, self.library.scenario_ids())

        def check(built: AnyScenario) -> None:
            engine.begin(scenario_id, built, character)

        with self.gate.creation():
            scenario = await engine.write_opening(
                description, source, pack_id, role_answer(self.roles, "worldsmith"), check
            )
        self.library.write_scenario(scenario_id, scenario)
        LOGGER.info("scenario written: scenario_id=%s title=%r", scenario_id, description.title)
        return scenario_id

    async def new_pack(
        self, engine_id: EngineId, name: str, premise: str, document: Path | None, license: str
    ) -> Slug:
        engine = self.require_engine(engine_id)
        source = await to_thread(given_text, premise, document)
        pack_id = slug(name, (*engine.packs.installed, *self.packs.ids(engine.id)))
        origin = f"written in this app from {'the premise' if document is None else document.name}"
        with self.gate.creation():
            pack = await engine.write_pack(
                name=name,
                source=source,
                origin=origin,
                license=license,
                worldsmith=role_answer(self.roles, "worldsmith"),
            )
        self.packs.write(engine.id, pack_id, pack)
        engine.install_pack(pack_id, pack)
        LOGGER.info("pack written: engine=%s slug=%s name=%r", engine.id, pack_id, name)
        return pack_id

    def session_for(self, key: SavedGameKey) -> GameSession:
        """Memoised: a page render must not rebuild the game and drop the running turn."""
        if key.save_id not in self._sessions:
            self._sessions[key.save_id] = self._open(key)
        return self._sessions[key.save_id]

    def _open(self, key: SavedGameKey) -> GameSession:
        scenario = self.library.read_scenario(key.scenario_id, self.scenario_models)
        engine = self.require_engine(scenario.engine_id)
        character = self.library.read_character(key.character_id, engine.id, engine.character_model)
        saved = self.store.read(key.save_id)
        if saved is None:
            state = engine.begin(key.scenario_id, scenario, character)
        else:
            state = engine.restore(saved)
            check_resumes(state, key.save_id, scenario.description)
        return GameSession(
            key=key,
            scenario=scenario,
            character=character,
            engine=engine,
            roles=self.roles,
            store=self.store,
            library=self.library,
            state=state,
            gate=self.gate,
            live_settings=self.live_settings,
            illustrator=Illustrator(
                live_settings=self.live_settings,
                saves=self.store.media_dir(key.save_id),
                style=scenario.description.art_style or engine.art_style,
                icon_dirs=(
                    self.library.scenario_folder(key.scenario_id) / ICON_DIR,
                    self.library.character_folder(key.character_id) / ICON_DIR,
                ),
                portraits=engine.portraits,
            ),
        )
