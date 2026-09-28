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

from rulehall.app.catalog import SavedGameKey
from rulehall.app.runtime import Runtime
from rulehall.core.creation import CreationStep, drop_stale, find_option
from rulehall.core.decisions import DecisionOption
from rulehall.core.documents import SOURCE_SUFFIXES
from rulehall.core.game import ScenarioDescription
from rulehall.core.validation import EngineId, Refusal, Slug, content_id
from rulehall.ui.panel_parts import labeled_value
from rulehall.ui.routes import assets_route, game_path, hall_path
from rulehall.ui.widgets import (
    action_bar,
    alert,
    attempt,
    done,
    entered_text,
    heading,
    help_tip,
    inform,
    page_body,
    page_header,
    page_intro,
    warn,
)

LOGGER = logging.getLogger(__name__)
SCENARIO_FAILED = "Something went wrong. The scenario was not written. Look in the server log."
PACK_FAILED = "Something went wrong. The pack was not written. Look in the server log."
NEW_CHARACTER_ICON = "sym_r_person_add"
NEW_ADVENTURE_ICON = "sym_r_auto_stories"
NEW_PACK_ICON = "sym_r_auto_fix_high"


class DocumentUpload:
    def __init__(self) -> None:
        self.document: Path | None = None
        self.uploads: Path | None = None
        ui.upload(on_upload=self.uploaded, max_files=1, auto_upload=True).props(
            f'accept="{",".join(SOURCE_SUFFIXES)}"'
        )
        # `on_disconnect` also fires on a reconnect, which would discard a live page's upload.
        ui.context.client.on_delete(self.discard)  # pyright: ignore[reportUnknownMemberType]

    async def uploaded(self, event: UploadEventArguments) -> None:
        if self.uploads is None:
            self.uploads = Path(mkdtemp())
        if self.document is not None:
            self.document.unlink(missing_ok=True)
        path = self.uploads / Path(event.file.name).name
        await event.file.save(path)
        self.document = path
        inform(f"Read {event.file.name}.")

    def discard(self) -> None:
        if self.uploads is not None:
            shutil.rmtree(self.uploads, ignore_errors=True)


class CharacterForm:
    def __init__(self, runtime: Runtime, engine_id: EngineId) -> None:
        self.runtime = runtime
        self.engine = engine = runtime.require_engine(engine_id)
        self.pack_id = engine.packs.options()[0].id
        self.picks: dict[Slug, str] = {}
        with _form_page(
            runtime,
            engine_id,
            title="New character",
            lead="Name them, and answer what the rules ask.",
        ):
            self.name = ui.input(label="Name")
            self.brief = ui.input(label="Brief", placeholder="Who are they, in one sentence?")
            self.draw_steps()
            heading("Preview")
            previewed = ui.column().classes("w-full game-gap-2xl")
            # Outside the preview refreshable: a rebuild on blur must not destroy button focus.
            with action_bar():
                self.create_button = ui.button(
                    "Create", icon=NEW_CHARACTER_ICON, on_click=self.create
                ).props("color=primary")
            with previewed:
                self.draw_preview()

    def type_answer(self, step_id: Slug, event: ValueChangeEventArguments[str | None]) -> None:
        self.picks[step_id] = (event.value or "").strip()

    def choose_pack(self, event: ValueChangeEventArguments[str]) -> None:
        self.pack_id = content_id(event.value)
        self.answered()

    def answered(self) -> None:
        drop_stale(self.engine.creation_steps(self.pack_id, self.picks), self.picks)
        self.draw_steps.refresh()
        self.draw_preview.refresh()

    def field(self, step: CreationStep) -> None:
        given = self.picks.get(step.id, "")
        if not step.options:
            box = ui.input(
                label=step.name,
                placeholder=step.hint or "In your own words",
                value=given,
                on_change=partial(self.type_answer, step.id),
            )
            box.on("blur", self.draw_preview.refresh)
            _append_help(box, step.help)
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
        if step.allows_text and given:
            offered = find_option(step.options, given)
            given = given if offered is None else offered.name
            _ = options.setdefault(given, given)
        chosen = ui.select(
            options=options,
            value=given or None,
            label=step.name,
            on_change=lambda event: self.pick(step.id, event.value),
            with_input=step.allows_text,
            new_value_mode="add-unique" if step.allows_text else None,
        )
        if step.hint:
            chosen.props(f'hint="{step.hint}"')
        _append_help(chosen, step.help)

    def sprites(self, step: CreationStep, given: str) -> None:
        ui.label(step.name).classes("game-eyebrow")
        with ui.element("div").classes("game-sprites w-full"):
            for option in step.options:
                with (
                    ui.button(on_click=partial(self.pick, step.id, option.id))
                    .props(f'flat aria-label="{option.name}"')
                    .classes("game-sprite" + (" game-sprite-on" if option.id == given else ""))
                ):
                    sprite = ui.element("img").props('alt=""')
                    sprite.props["src"] = f"{assets_route(self.engine.id)}/{option.sprite}"

    def pick(self, step_id: Slug, option_id: Slug) -> None:
        self.picks[step_id] = option_id
        self.answered()

    def create(self) -> None:
        title = entered_text(self.name)
        if not title:
            warn("Name the character.")
            return
        try:
            made = self.engine.create_character(
                title, entered_text(self.brief), self.pack_id, self.picks
            )
            self.runtime.library.write_character(made)
        except Refusal as refused:
            alert(str(refused))
            return
        LOGGER.info("character created: slug=%s engine=%s", made.id, made.engine_id)
        ui.navigate.to(hall_path(self.engine.id, made.id))

    @ui.refreshable_method
    def draw_steps(self) -> None:
        _pack_select(self.engine.packs.options(), self.pack_id, self.choose_pack)
        for step in self.engine.creation_steps(self.pack_id, self.picks):
            self.field(step)

    @ui.refreshable_method
    def draw_preview(self) -> None:
        engine = self.engine
        try:
            preview = engine.preview_character(
                engine.create_character(
                    entered_text(self.name) or "Unnamed",
                    entered_text(self.brief),
                    self.pack_id,
                    self.picks,
                )
            )
        except Refusal as refused:
            ui.label(f"Not ready yet: {refused}").classes("game-hint")
            self.create_button.set_visibility(False)
        else:
            for label, text in preview:
                labeled_value(label, text, help=engine.sheet_help.get(label, ""))
            self.create_button.set_visibility(True)


class ScenarioForm:
    def __init__(self, runtime: Runtime, engine_id: EngineId) -> None:
        self.runtime = runtime
        self.engine = engine = runtime.require_engine(engine_id)
        self.characters = runtime.catalog().characters_for(engine_id)
        self.pack_id = engine.packs.options()[0].id
        self.seed_button: ui.button
        self.backdrop_button: ui.button
        self.character: ui.select
        self.button: ui.button
        with _form_page(
            runtime,
            engine_id,
            title="New adventure",
            lead="Describe the adventure, or upload one, and the worldsmith writes its opening.",
        ):
            self.title = ui.input(label="Title")
            self.draw_character_fields()
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
            self.style = ui.input(
                label="Art style", placeholder=f"Leave empty for: {engine.art_style}"
            )
            heading("Or upload the adventure")
            self.upload = DocumentUpload()
            self.draw_button_row()

    @property
    def pack(self):
        return self.engine.packs.require(self.pack_id)

    def draw_character_fields(self) -> None:
        _pack_select(self.engine.packs.options(), self.pack_id, self.choose_pack)
        with ui.row().classes("items-center game-gap-lg"):
            self.seed_button = ui.button(
                "Roll a seed", icon="sym_r_casino", on_click=self.roll_seed
            ).props("outline dense")
            self.backdrop_button = ui.button(
                "Use the pack's backdrop", icon="sym_r_public", on_click=self.use_pack_backdrop
            ).props("outline dense")
        self.character = ui.select(
            options={entry.id: f"{entry.name} — {entry.brief}" for entry in self.characters},
            value=self.characters[0].id if self.characters else None,
            label="Character",
        )
        self._show_pack_buttons()

    def choose_pack(self, event: ValueChangeEventArguments[str]) -> None:
        self.pack_id = content_id(event.value)
        self._show_pack_buttons()

    def roll_seed(self) -> None:
        if seeds := self.pack.seeds:
            self.premise.value = random.choice(seeds)  # the page's own die: it rolls no game die

    def use_pack_backdrop(self) -> None:
        self.backdrop.value = self.pack.backdrop

    def draw_button_row(self) -> None:
        with action_bar():
            if not self.characters:
                ui.label("Make a character first.").classes("text-sm text-negative")
            ui.label("Writing takes several minutes.").classes("game-hint")
            self.button = ui.button(
                "Write the opening", icon=NEW_ADVENTURE_ICON, on_click=self.write_opening
            ).props("color=primary")
            if not self.characters:
                self.button.disable()

    async def write_opening(self) -> None:
        title = entered_text(self.title)
        backdrop = entered_text(self.backdrop)
        premise = entered_text(self.premise)
        scope = entered_text(self.scope)
        character_id = self.character.value
        document = self.upload.document
        if not (title and backdrop and scope) or not (premise or document) or character_id is None:
            warn("A title, a backdrop, a scope, a character, and a premise or a document.")
            return
        description = ScenarioDescription(
            title=title,
            premise=premise,
            backdrop=backdrop,
            scope=scope,
            art_style=entered_text(self.style),
        )

        async def writing() -> None:
            played_id = content_id(character_id)
            scenario_id = await self.runtime.new_scenario(
                self.engine.id, description, document, self.pack_id, played_id
            )
            LOGGER.info("scenario created: scenario_id=%s", scenario_id)
            ui.navigate.to(game_path(SavedGameKey(scenario_id=scenario_id, character_id=played_id)))

        _ = await attempt(writing, failed=SCENARIO_FAILED, loading=self.button)

    def _show_pack_buttons(self) -> None:
        self.seed_button.set_visibility(bool(self.pack.seeds))
        self.backdrop_button.set_visibility(bool(self.pack.backdrop))


class PackForm:
    def __init__(self, runtime: Runtime, engine_id: EngineId) -> None:
        self.runtime = runtime
        self.engine_id = engine_id
        with _form_page(
            runtime,
            engine_id,
            title="New pack",
            lead="Name a genre, or upload a document, and the worldsmith writes the whole kit.",
        ):
            self.name = ui.input(label="Name")
            self.premise = ui.textarea(
                label="Premise",
                placeholder="What genre is this, and what is a story in it about?",
            )
            heading("Or upload a document")
            self.upload = DocumentUpload()
            self.license = ui.input(
                label="Licence", placeholder="Optional: who wrote the source, under what terms"
            )
            with action_bar():
                ui.label("Writing takes several minutes.").classes("game-hint")
                self.button = ui.button(
                    "Write the pack", icon=NEW_PACK_ICON, on_click=self.write_pack
                ).props("color=primary")

    async def write_pack(self) -> None:
        name = entered_text(self.name)
        premise = entered_text(self.premise)
        document = self.upload.document
        if not name or not (premise or document):
            warn("A name, and a premise or a document.")
            return

        async def writing() -> None:
            pack_id = await self.runtime.new_pack(
                self.engine_id, name, premise, document, entered_text(self.license)
            )
            LOGGER.info("pack created: engine=%s slug=%s", self.engine_id, pack_id)
            done(f"Wrote {name}. Edit it in {self.runtime.packs.path(self.engine_id, pack_id)}.")
            ui.navigate.to(hall_path(self.engine_id))

        _ = await attempt(writing, failed=PACK_FAILED, loading=self.button)


@contextmanager
def _form_page(runtime: Runtime, engine_id: EngineId, *, title: str, lead: str) -> Generator[None]:
    engine = runtime.require_engine(engine_id)
    page_header(title, look=engine.look, back=hall_path(engine_id))
    with page_body():
        page_intro(engine.title, title, lead)
        with ui.card().classes("w-full game-gap-2xl"):
            yield


def _append_help(field: ui.input | ui.select, text: str) -> None:
    if text:
        with field.add_slot("append"):
            help_tip(text)


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
