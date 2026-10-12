from collections.abc import Awaitable, Callable
from functools import partial

from nicegui import ui

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.champions.views import ImportPreview, PickField
from rulehall.screens.pokemon.catalog_picker import FindSprite, slot_sprite
from rulehall.ui.panel_parts import avatar, tag_row
from rulehall.ui.widgets import alert, done, entered_text


class TeamDialogs:
    def __init__(
        self,
        find_sprite: FindSprite,
        import_preview: Callable[[str], ImportPreview],
        replace_team: Callable[[str], Awaitable[bool]],
    ) -> None:
        self.find_sprite = find_sprite
        self.import_preview = import_preview
        self.replace_team = replace_team
        self.previewed = ""
        with (
            ui.dialog() as self.import_dialog,
            ui.card().classes(
                "game-row-dialog game-builder-dialog game-builder-import game-gap-md"
            ),
        ):
            ui.label("Import a team").classes("game-title game-builder-dialog-title")
            with ui.column().classes("w-full game-builder-dialog-body game-gap-md"):
                ui.label(
                    "Paste a team exported from a team builder, then check it before it replaces "
                    "yours."
                ).classes("game-hint")
                self.paste = (
                    ui.textarea("Team paste", on_change=self.paste_changed)
                    .props(remove="autogrow")
                    .props("rows=8 input-class=game-builder-mono")
                    .classes("w-full")
                )
                self.preview_box = ui.column().classes("w-full game-gap-0")
            with ui.row().classes("w-full justify-end game-builder-dock game-gap-md"):
                ui.button("Cancel", on_click=self.import_dialog.close).props("flat no-caps")
                ui.button("Check", on_click=self.preview).props("outline no-caps")
                self.replace_button = ui.button("Replace team", on_click=self.replace)
                self.replace_button.props("color=primary no-caps").set_enabled(False)
        with (
            ui.dialog() as self.export_dialog,
            ui.card().classes("game-row-dialog game-builder-dialog game-gap-md"),
        ):
            ui.label("Export the team").classes("game-title game-builder-dialog-title")
            self.export_box = (
                ui.textarea("Team paste")
                .props(remove="autogrow")
                .props("readonly rows=12 input-class=game-builder-mono")
                .classes("w-full")
            )
            with ui.row().classes("w-full justify-end game-builder-dock game-gap-md"):
                ui.button("Close", on_click=self.export_dialog.close).props("flat no-caps")
                ui.button("Copy", icon="sym_r_content_copy", on_click=self.copy_export).props(
                    "color=primary no-caps"
                )
        with (
            ui.dialog() as self.replace_dialog,
            ui.card().classes("game-row-dialog game-gap-md"),
        ):
            self.replace_title = ui.label().classes("game-title game-builder-dialog-title")
            ui.label("A set holds four moves. Pick the one to drop.").classes("game-hint")
            self.replace_box = ui.element("div").classes("game-builder-replace")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=self.replace_dialog.close).props("flat no-caps")

    def open_import(self) -> None:
        self.paste.value = ""
        self.paste_changed()
        self.import_dialog.open()

    def paste_changed(self) -> None:
        self.preview_box.clear()
        self.replace_button.set_enabled(False)

    def preview(self) -> None:
        text = entered_text(self.paste)
        self.paste_changed()
        if not text:
            return
        try:
            preview = self.import_preview(text)
        except Refusal as refused:
            alert(str(refused))
            return
        self.previewed = text
        with self.preview_box:
            self.draw_preview(preview)
        self.replace_button.set_enabled(preview.importable)

    def draw_preview(self, preview: ImportPreview) -> None:
        for row in preview.rows:
            with ui.element("div").classes("w-full game-builder-preview"):
                avatar(slot_sprite(self.find_sprite, row), row.name)
                with ui.column().classes("game-gap-0 game-builder-card-body"):
                    with ui.row().classes("items-center no-wrap game-gap-sm"):
                        ui.label(row.name).classes("game-builder-card-name")
                        if row.tags:
                            tag_row(row.tags)
                    ui.label(row.error or row.brief).classes(
                        "game-builder-field-error" if row.error else "game-builder-card-brief"
                    )
                ui.label("⚠ fix" if row.error else "✓ ok").classes(
                    "game-builder-status "
                    + ("game-builder-status-invalid" if row.error else "game-builder-status-ready")
                )
        for note in preview.notes:
            ui.label(note).classes("game-hint game-builder-preview-note")

    async def replace(self) -> None:
        if await self.replace_team(self.previewed):
            self.import_dialog.close()

    def open_export(self, text: str) -> None:
        self.export_box.value = text
        self.export_dialog.open()

    def copy_export(self) -> None:
        ui.clipboard.write(self.export_box.value or "")
        done("Copied.")

    async def ask_replaced(self, pick: PickField) -> int | None:
        self.replace_title.set_text(f"Replace which {pick.label.lower().removesuffix('s')}?")
        self.replace_box.clear()
        with self.replace_box:
            for index, choice in enumerate(pick.picked):
                ui.button(choice.name, on_click=partial(self.replace_dialog.submit, index)).props(
                    "outline no-caps"
                ).classes("game-builder-pick")
        chosen: object = await self.replace_dialog
        return chosen if isinstance(chosen, int) else None
