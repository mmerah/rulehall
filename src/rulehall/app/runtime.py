import logging
from asyncio import to_thread
from pathlib import Path
from shutil import rmtree

from rulehall.app.illustration import ICON_DIR, Illustrator
from rulehall.app.launch import LauncherCatalog, LaunchTarget, check_resumes
from rulehall.app.providers import close_client
from rulehall.app.roles import role_answer
from rulehall.app.session import GameService, Gate
from rulehall.app.spawn import RoleRunner, Spawner
from rulehall.config import Settings
from rulehall.core.io import FileStore, Library, PackStore
from rulehall.core.model import AnyScenario, ScenarioMeta
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

    async def delete_save(self, slug: str) -> None:
        session = self._sessions.get(slug)
        if session is not None:
            if session.working_role is not None:
                raise Refusal(f"{slug} is taking a turn. Wait for that turn to end, then delete.")
            if session.battle_run is not None:
                raise Refusal(f"{slug} is in a battle. End that battle, then delete.")
            del self._sessions[slug]
            await session.close()
        self.store.discard(slug)
        rmtree(self.store.media_dir(slug), ignore_errors=True)

    def configure(self, settings: Settings) -> None:
        # The server is already bound: a CLI role must reach the port it listens on.
        settings = settings.model_copy(update={"server": self.settings.server})
        self.settings = settings
        if isinstance(self.spawner, RoleRunner):
            self.spawner.settings = settings
        for session in self._sessions.values():
            session.battle_config = settings.battle
            session.transcript_config = settings.transcript
            session.illustrator = session.illustrator.configured(settings)

    def catalog(self) -> LauncherCatalog:
        return LauncherCatalog.read(self.library, self.store, self.engines)

    def engine(self, engine_id: EngineId) -> AnyEngine:
        found = self.engines.get(engine_id)
        if found is None:
            raise Refusal(f"no rules {engine_id!r}")
        return found

    async def new_scenario(
        self,
        engine_id: EngineId,
        meta: ScenarioMeta,
        document: Path | None,
        pack_id: Slug,
        character_id: Slug,
    ) -> Slug:
        engine = self.engine(engine_id)
        character = self.library.read_character(character_id, engine.id, engine.character)
        engine.packs.require(pack_id)
        source = await to_thread(given_text, meta.premise, document)
        name = slug(meta.title, self.library.scenario_ids())

        def check(built: AnyScenario) -> None:
            engine.begin(name, built, character)

        with self.gate.creation():
            scenario = await engine.write_opening(
                meta, source, pack_id, role_answer(self.spawner, "worldsmith"), check
            )
        self.library.write_scenario(name, scenario)
        LOGGER.info("scenario written: slug=%s title=%r", name, meta.title)
        return name

    async def new_pack(
        self, engine_id: EngineId, name: str, premise: str, document: Path | None, license: str
    ) -> Slug:
        """Written and installed only after both answers land, so a failed pack leaves no file."""
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
        if target.slug not in self._sessions:
            self._sessions[target.slug] = self._open(target)
        return self._sessions[target.slug]

    def _open(self, target: LaunchTarget) -> GameService:
        models = {engine_id: engine.scenario for engine_id, engine in self.engines.items()}
        scenario = self.library.read_scenario(target.scenario_id, models)
        engine = self.engine(scenario.engine_id)
        character = self.library.read_character(target.character_id, engine.id, engine.character)
        saved = self.store.read(target.slug)
        if saved is None:
            state = engine.begin(target.scenario_id, scenario, character)
        else:
            state = engine.restore(saved)
            check_resumes(state, target.slug, scenario.meta)
        return GameService(
            target=target,
            scenario=scenario,
            character=character,
            engine=engine,
            spawner=self.spawner,
            store=self.store,
            state=state,
            gate=self.gate,
            battle_config=self.settings.battle,
            transcript_config=self.settings.transcript,
            illustrator=Illustrator.open(
                self.settings,
                self.store,
                target.slug,
                style=scenario.meta.art_style or engine.art_style,
                icon_dirs=(
                    self.library.scenario_folder(target.scenario_id) / ICON_DIR,
                    self.library.character_folder(target.character_id) / ICON_DIR,
                ),
                portraits=engine.portraits,
            ),
        )
