import logging
import random
import shutil
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from tempfile import mkdtemp

from nicegui import ui
from nicegui.events import UploadEventArguments, ValueChangeEventArguments

from rulehall.app.launch import LauncherCatalog, LaunchTarget
from rulehall.app.runtime import Runtime
from rulehall.core.creation import CreationStep, drop_stale, picked
from rulehall.core.io import SOURCE_SUFFIXES
from rulehall.core.model import ScenarioMeta
from rulehall.core.play import DecisionOption
from rulehall.core.validation import EngineId, Refusal, Slug, content_id
from rulehall.ui import theme
from rulehall.ui.widgets import (
    action_bar,
    alert,
    assets_route,
    game_path,
    heading,
    labeled_value,
    note,
    page_body,
    page_header,
    page_intro,
    typed,
    warn,
)

LOGGER = logging.getLogger(__name__)


class DocumentUpload:
    def __init__(self) -> None:
        self.document: Path | None = None
        self.uploads: Path | None = None

    def build(self) -> None:
        ui.upload(on_upload=self.uploaded, max_files=1, auto_upload=True).props(
            f'accept="{",".join(SOURCE_SUFFIXES)}"'
        )
        # `on_disconnect` also fires on a reconnect, which would discard a live page's upload.
        ui.context.client.on_delete(self.discard)  # pyright: ignore[reportUnknownMemberType]

    async def uploaded(self, event: UploadEventArguments) -> None:
        # The source reader opens a path, and a PDF cannot be parsed from bytes.
        if self.uploads is None:
            self.uploads = Path(mkdtemp())
        if self.document is not None:
            self.document.unlink(missing_ok=True)
        path = self.uploads / Path(event.file.name).name
        await event.file.save(path)
        self.document = path
        note(f"Read {event.file.name}.")

    def discard(self) -> None:
        if self.uploads is not None:
            shutil.rmtree(self.uploads, ignore_errors=True)


class CharacterForm:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.use_engine(runtime.default_engine)
        self.picks: dict[Slug, str] = {}
        self.name: ui.input
        self.brief: ui.input
        self.create_button: ui.button

    @property
    def engine(self):
        return self.runtime.engine(self.engine_id)

    def build(self) -> None:
        with _form_page(
            self.runtime,
            self.engine_id,
            eyebrow="Character",
            title="New character",
            lead="Name them, pick their rules, and answer what the rules ask.",
        ):
            _engine_select(self.runtime, self.engine_id, self.choose_engine)
            self.name = ui.input(label="Name")
            self.brief = ui.input(label="Brief", placeholder="Who are they, in one sentence?")
            self.steps()
            heading("Preview")
            previewed = ui.column().classes("w-full game-gap-2xl")
            # Outside the preview refreshable: a rebuild on blur must not destroy button focus.
            with action_bar():
                self.create_button = ui.button(
                    "Create", icon="sym_r_person_add", on_click=self.create
                ).props("color=primary")
            with previewed:
                self.preview()

    def use_engine(self, engine_id: EngineId) -> None:
        self.engine_id = engine_id
        self.pack_id = self.engine.packs.options()[0].id

    def choose_engine(self, engine_id: EngineId) -> None:
        self.use_engine(engine_id)
        # The steps come from the engine and its pack, so an answer to the old ones means nothing.
        self.picks.clear()
        self.steps.refresh()
        self.preview.refresh()

    def write(self, step_id: Slug, event: ValueChangeEventArguments[str | None]) -> None:
        self.picks[step_id] = (event.value or "").strip()

    def choose(self, step_id: Slug, event: ValueChangeEventArguments[str]) -> None:
        self.pick(step_id, event.value)

    def choose_pack(self, event: ValueChangeEventArguments[str]) -> None:
        self.pack_id = content_id(event.value)
        self.answered()

    def answered(self) -> None:
        drop_stale(self.engine.creation_steps(self.pack_id, self.picks), self.picks)
        self.steps.refresh()
        self.preview.refresh()

    def field(self, step: CreationStep) -> None:
        given = picked(self.picks, step.id)
        if not step.options:
            box = ui.input(
                label=step.name,
                placeholder=step.hint or "In your own words",
                value=given,
                on_change=partial(self.write, step.id),
            )
            # Rebuilding the whole form on blur would destroy the field Tab just moved to.
            box.on("blur", self.preview.refresh)
            return
        if step.options[0].sprite:
            self.sprites(step, given)
            return
        # Quasar returns typed text as its own key, so a typed answer only lands on a keyed label.
        options = {
            (option.name if step.allows_text else option.id): (
                f"{option.name} — {option.brief}" if option.brief else option.name
            )
            for option in step.options
        }
        chosen = ui.select(
            options=options,
            value=given or None,
            label=step.name,
            on_change=partial(self.choose, step.id),
            with_input=step.allows_text,
            new_value_mode="add-unique" if step.allows_text else None,
        )
        if step.hint:
            chosen.props(f'hint="{step.hint}"')

    def sprites(self, step: CreationStep, given: str) -> None:
        ui.label(step.name).classes("game-eyebrow")
        with ui.element("div").classes("game-sprites w-full"):
            for option in step.options:
                with (
                    ui.button(on_click=partial(self.pick, step.id, option.id))
                    .props(f'flat aria-label="{option.name}"')
                    .classes("game-sprite" + (" game-sprite-on" if option.id == given else ""))
                ):
                    ui.element("img").props(
                        f'src="{assets_route(self.engine_id)}/{option.sprite}" alt=""'
                    )

    def pick(self, step_id: Slug, option_id: Slug) -> None:
        self.picks[step_id] = option_id
        self.answered()

    def create(self) -> None:
        title = typed(self.name)
        if not title:
            warn("Name the character.")
            return
        try:
            made = self.engine.create_character(title, typed(self.brief), self.pack_id, self.picks)
            self.runtime.library.write_character(made)
        except Refusal as refused:
            alert(str(refused))
            return
        LOGGER.info("character created: slug=%s engine=%s", made.id, made.engine_id)
        ui.navigate.to("/")

    @ui.refreshable_method
    def steps(self) -> None:
        _pack_select(self.engine.packs.options(), self.pack_id, self.choose_pack)
        for step in self.engine.creation_steps(self.pack_id, self.picks):
            self.field(step)

    @ui.refreshable_method
    def preview(self) -> None:
        engine = self.engine
        try:
            preview = engine.preview_character(
                engine.create_character(
                    typed(self.name) or "Unnamed",
                    typed(self.brief),
                    self.pack_id,
                    self.picks,
                )
            )
        except Refusal as refused:
            ui.label(f"Not ready yet: {refused}").classes("game-hint")
            self.create_button.set_visibility(False)
        else:
            for label, text in preview:
                labeled_value(label, text)
            self.create_button.set_visibility(True)


class ScenarioForm:
    def __init__(self, runtime: Runtime, catalog: LauncherCatalog) -> None:
        self.runtime = runtime
        self.catalog = catalog
        self.use_engine(runtime.default_engine)
        self.upload = DocumentUpload()
        self.title: ui.input
        self.seed_button: ui.button
        self.backdrop_button: ui.button
        self.character: ui.select
        self.backdrop: ui.textarea
        self.premise: ui.textarea
        self.scope: ui.textarea
        self.style: ui.input
        self.button: ui.button

    @property
    def engine(self):
        return self.runtime.engine(self.engine_id)

    @property
    def pack(self):
        return self.engine.packs.require(self.pack_id)

    def build(self) -> None:
        with _form_page(
            self.runtime,
            self.engine_id,
            eyebrow="Scenario",
            title="New scenario",
            lead="Describe the adventure, or upload one, and the worldsmith writes its opening.",
        ):
            _engine_select(self.runtime, self.engine_id, self.choose_engine)
            self.title = ui.input(label="Title")
            self.character_fields()
            self.backdrop = ui.textarea(
                label="Backdrop",
                placeholder="What kind of world is this? Give the genre, the era, what "
                "technology or magic can do, and the mood.",
            )
            self.premise = ui.textarea(
                label="Premise",
                placeholder="What is this adventure about? Write the place and the "
                "trouble, never the character: any character can play it.",
            )
            self.scope = ui.textarea(
                label="Scope",
                placeholder="How far does this go, and does it tend toward an ending?",
            )
            self.style = ui.input(label="Art style")
            self._set_style_placeholder()
            heading("Or upload the adventure")
            self.upload.build()
            self.button_row()

    def use_engine(self, engine_id: EngineId) -> None:
        self.engine_id = engine_id
        self.pack_id = self.engine.packs.options()[0].id

    def choose_engine(self, engine_id: EngineId) -> None:
        self.use_engine(engine_id)
        self.character_fields.refresh()
        self._set_style_placeholder()
        self.button_row.refresh()

    def _set_style_placeholder(self) -> None:
        art_style = self.engine.art_style
        self.style.props(f'placeholder="Leave empty for: {art_style}"')

    @ui.refreshable_method
    def character_fields(self) -> None:
        characters = self.catalog.characters_for(self.engine_id)
        _pack_select(self.engine.packs.options(), self.pack_id, self.choose_pack)
        with ui.row().classes("items-center game-gap-lg"):
            self.seed_button = ui.button(
                "Roll a seed", icon="sym_r_casino", on_click=self.roll_seed
            ).props("outline dense")
            self.backdrop_button = ui.button(
                "Use the pack's backdrop", icon="sym_r_public", on_click=self.use_pack_backdrop
            ).props("outline dense")
        self.character = ui.select(
            options={entry.id: f"{entry.name} — {entry.brief}" for entry in characters},
            value=characters[0].id if characters else None,
            label="Character",
        )
        self._show_pack_buttons()

    def choose_pack(self, event: ValueChangeEventArguments[str]) -> None:
        self.pack_id = content_id(event.value)
        self._show_pack_buttons()

    def _show_pack_buttons(self) -> None:
        self.seed_button.set_visibility(bool(self.pack.seeds))
        self.backdrop_button.set_visibility(bool(self.pack.backdrop))

    def roll_seed(self) -> None:
        if seeds := self.pack.seeds:
            self.premise.value = random.choice(seeds)  # the page's own die: it rolls no game die

    def use_pack_backdrop(self) -> None:
        self.backdrop.value = self.pack.backdrop

    @ui.refreshable_method
    def button_row(self) -> None:
        characters = self.catalog.characters_for(self.engine_id)
        with action_bar():
            if not characters:
                ui.label("Make a character first.").classes("text-sm text-negative")
            ui.label("Writing takes several minutes.").classes("game-hint")
            self.button = ui.button(
                "Write the opening", icon="sym_r_auto_stories", on_click=self.write
            ).props("color=primary")
            if not characters:
                self.button.disable()

    async def write(self) -> None:
        title = typed(self.title)
        backdrop = typed(self.backdrop)
        premise = typed(self.premise)
        scope = typed(self.scope)
        character_id = self.character.value
        document = self.upload.document
        if not (title and backdrop and scope) or not (premise or document) or character_id is None:
            warn("A title, a backdrop, a scope, a character, and a premise or a document.")
            return
        self.button.props("loading")
        meta = ScenarioMeta(
            title=title,
            premise=premise,
            backdrop=backdrop,
            scope=scope,
            art_style=typed(self.style),
        )
        try:
            character_id = content_id(character_id)
            name = await self.runtime.new_scenario(
                self.engine_id, meta, document, self.pack_id, character_id
            )
            opened = LaunchTarget(scenario_id=name, character_id=character_id)
        except Refusal as refused:
            alert(str(refused))
            return
        finally:
            self.button.props(remove="loading")
        LOGGER.info("scenario created: slug=%s", name)
        ui.navigate.to(game_path(opened))


class PackForm:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.engine_id = runtime.default_engine
        self.upload = DocumentUpload()
        self.name: ui.input
        self.premise: ui.textarea
        self.license: ui.input
        self.button: ui.button

    def build(self) -> None:
        with _form_page(
            self.runtime,
            self.engine_id,
            eyebrow="Pack",
            title="New pack",
            lead="Name a genre, or upload a document, and the worldsmith writes the whole kit.",
        ):
            _engine_select(self.runtime, self.engine_id, self.choose_engine)
            self.name = ui.input(label="Name")
            self.premise = ui.textarea(
                label="Premise",
                placeholder="What genre is this, and what is a story in it about?",
            )
            heading("Or upload a document")
            self.upload.build()
            self.license = ui.input(
                label="Licence", placeholder="Optional: who wrote the source, under what terms"
            )
            with action_bar():
                ui.label("Writing takes several minutes.").classes("game-hint")
                self.button = ui.button(
                    "Write the pack", icon="sym_r_auto_fix_high", on_click=self.write
                ).props("color=primary")

    def choose_engine(self, engine_id: EngineId) -> None:
        self.engine_id = engine_id

    async def write(self) -> None:
        name = typed(self.name)
        premise = typed(self.premise)
        document = self.upload.document
        if not name or not (premise or document):
            warn("A name, and a premise or a document.")
            return
        self.button.props("loading")
        try:
            pack_id = await self.runtime.new_pack(
                self.engine_id, name, premise, document, typed(self.license)
            )
        except Refusal as refused:
            alert(str(refused))
            return
        finally:
            self.button.props(remove="loading")
        LOGGER.info("pack created: engine=%s slug=%s", self.engine_id, pack_id)
        note(
            f"Wrote {name}. Edit it in {self.runtime.packs.path(self.engine_id, pack_id)}.",
            good=True,
        )
        ui.navigate.to("/")


def character_page(runtime: Runtime) -> None:
    CharacterForm(runtime).build()


def scenario_page(runtime: Runtime) -> None:
    ScenarioForm(runtime, runtime.catalog()).build()


def new_pack_page(runtime: Runtime) -> None:
    PackForm(runtime).build()


@contextmanager
def _form_page(
    runtime: Runtime, engine_id: EngineId, *, eyebrow: str, title: str, lead: str
) -> Generator[None]:
    page_header(title, look=runtime.engine(engine_id).look)
    with page_body():
        page_intro(eyebrow, title, lead)
        with ui.card().classes("w-full game-gap-2xl"):
            yield


def _engine_select(
    runtime: Runtime,
    chosen_id: EngineId,
    on_change: Callable[[EngineId], None],
) -> None:
    def chosen(event: ValueChangeEventArguments[str]) -> None:
        engine_id = EngineId(event.value)
        theme.set_look(runtime.engine(engine_id).look)
        on_change(engine_id)

    ui.select(
        options={engine.id: engine.title for engine in runtime.engines.values()},
        value=chosen_id,
        label="Rules",
        on_change=chosen,
    )


def _pack_select(
    offered: tuple[DecisionOption, ...],
    chosen_id: Slug,
    on_change: Callable[[ValueChangeEventArguments[str]], None],
) -> None:
    if len(offered) == 1:
        return
    ui.select(
        options={option.id: option.name for option in offered},
        value=chosen_id,
        label="Pack",
        on_change=on_change,
    )
